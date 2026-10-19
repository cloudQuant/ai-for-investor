"""Backfill Binance crypto klines into the ``akshare_data`` warehouse.

三种模式（与期货日线审计脚本一致）::

    report  只读：统计仓库里每个交易对已有多少根 K 线、最新到哪天
    plan    只读：列出将要抓取的窗口、预期行数与 REST 请求/权重数，不写数据
    run     执行：REST 分页（默认，1000 根/请求）或归档 CSV 包写入仓库，可断点续跑

用法（本地 .env 的 SECRET_KEY 仍是示例值，需要与后端进程一致的 DEBUG=true）::

    cd src/backend
    DEBUG=true python scripts/crypto_history_backfill.py report
    DEBUG=true python scripts/crypto_history_backfill.py plan --symbols BTCUSDT
    DEBUG=true python scripts/crypto_history_backfill.py run --symbols BTCUSDT,ETHUSDT
    DEBUG=true python scripts/crypto_history_backfill.py run --intervals 1d,1h --source archive

进度落在 ``--resume-file``（默认 logs/crypto_history_backfill/progress.jsonl），
每完成一个 (symbol, interval) 追加一行；重跑默认跳过已完成项，``--force`` 强制重取。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.data_fetch.configs.db_config import DB_CONFIG  # noqa: E402
from app.data_fetch.providers.binance_to_mysql import (  # noqa: E402
    DEFAULT_CRYPTO_SYMBOLS,
    daily_table_ddl,
    hourly_table_ddl,
)
from app.data_fetch.providers.binance_vision import (  # noqa: E402
    BinanceClientError,
    BinanceRequestError,
    date_to_ms,
    iter_month_windows,
    validate_symbol,
)
from app.data_fetch.scripts.cryptos.daily.crypto_daily_market import (  # noqa: E402
    CryptoDailyMarket,
)
from app.data_fetch.scripts.cryptos.hourly.crypto_hourly_market import (  # noqa: E402
    CryptoHourlyMarket,
)

INTERVAL_TABLES = {
    "1d": ("CRYPTO_DAILY_MARKET", "TRADE_DATE"),
    "1h": ("CRYPTO_HOURLY_MARKET", "TRADE_DATETIME"),
}

DEFAULT_REPORT_DIR = _BACKEND_ROOT / "logs" / "crypto_history_backfill"
DEFAULT_START = {"1d": date(2017, 8, 1), "1h": date(2020, 1, 1)}


def iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for noisy in ("akshare_to_mysql", "BinanceToMySql", "binance_vision"):
        logging.getLogger(noisy).setLevel(logging.INFO if verbose else logging.WARNING)


@dataclass
class SymbolCoverage:
    symbol: str
    interval: str
    table: str
    rows: int = 0
    first_date: str | None = None
    last_date: str | None = None
    age_days: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "table": self.table,
            "rows": self.rows,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "age_days": self.age_days,
        }


@dataclass
class RunOutcome:
    symbol: str
    interval: str
    archive_rows: int = 0
    tail_rows: int = 0
    error: str | None = None
    seconds: float = 0.0

    @property
    def written(self) -> int:
        return self.archive_rows + self.tail_rows

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "archive_rows": self.archive_rows,
            "tail_rows": self.tail_rows,
            "written": self.written,
            "error": self.error,
            "seconds": round(self.seconds, 2),
        }


@dataclass
class Progress:
    path: Path
    done: set[tuple[str, str]] = field(default_factory=set)
    rows_by_key: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Progress:
        state = cls(path=path)
        if not path.exists():
            return state
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = (record.get("symbol", ""), record.get("interval", ""))
                if record.get("error"):
                    continue
                state.done.add(key)
                state.rows_by_key[f"{key[0]}|{key[1]}"] = int(record.get("written", 0))
        return state

    def mark(self, outcome: RunOutcome) -> None:
        self.done.add((outcome.symbol, outcome.interval))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Append in place: an atomic rename would strand this file's inode for
        # any reader that already opened it.
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(outcome.as_dict(), ensure_ascii=False) + "\n")


def connect_warehouse() -> Any:
    import mysql.connector

    return mysql.connector.connect(**DB_CONFIG)


def table_exists(conn: Any, table: str) -> bool:
    cursor = conn.cursor()
    try:
        cursor.execute("SHOW TABLES LIKE %s", (table,))
        return cursor.fetchone() is not None
    finally:
        cursor.close()


def ensure_tables(conn: Any) -> list[str]:
    created: list[str] = []
    cursor = conn.cursor()
    try:
        for table, ddl in (
            ("CRYPTO_DAILY_MARKET", daily_table_ddl("CRYPTO_DAILY_MARKET")),
            ("CRYPTO_HOURLY_MARKET", hourly_table_ddl("CRYPTO_HOURLY_MARKET")),
        ):
            cursor.execute(ddl)
            created.append(table)
        conn.commit()
    finally:
        cursor.close()
    return created


def measure_coverage(conn: Any, symbols: list[str], intervals: list[str]) -> list[SymbolCoverage]:
    """Per-symbol census. Reports 0 only for symbols actually queried."""
    coverage: list[SymbolCoverage] = []
    today = datetime.now(timezone.utc).date()
    for interval in intervals:
        table, time_column = INTERVAL_TABLES[interval]
        if not table_exists(conn, table):
            for symbol in symbols:
                coverage.append(SymbolCoverage(symbol=symbol, interval=interval, table=table))
            continue
        cursor = conn.cursor()
        try:
            for symbol in symbols:
                cursor.execute(
                    f"SELECT COUNT(*), MIN(`{time_column}`), MAX(`{time_column}`) "  # nosec B608
                    f"FROM `{table}` WHERE MARKET = %s AND SYMBOL = %s",
                    ("BINANCE", symbol),
                )
                row = cursor.fetchone() or (0, None, None)
                rows = int(row[0] or 0)
                last = row[2]
                last_date = last.date() if isinstance(last, datetime) else last
                coverage.append(
                    SymbolCoverage(
                        symbol=symbol,
                        interval=interval,
                        table=table,
                        rows=rows,
                        first_date=str(row[1] or ""),
                        last_date=str(last_date or ""),
                        age_days=(today - last_date).days if last_date else None,
                    )
                )
        finally:
            cursor.close()
    return coverage


def build_plan(
    symbols: list[str], intervals: list[str], start: date, until: date
) -> list[dict[str, Any]]:
    """What a run would touch: expected bars, REST pages, archive months."""
    plan: list[dict[str, Any]] = []
    for interval in intervals:
        table, _ = INTERVAL_TABLES[interval]
        floor = DEFAULT_START[interval]
        window_start = max(start, floor)
        span_days = max(0, (until - window_start).days + 1)
        bars_per_day = 1 if interval == "1d" else 24
        expected = span_days * bars_per_day
        months = list(iter_month_windows(window_start, until))
        for symbol in symbols:
            plan.append(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "table": table,
                    "window": f"{window_start}..{until}",
                    "expected_bars": expected,
                    "rest_requests": -(-expected // 1000) or 1,
                    "rest_weight": (-(-expected // 1000) or 1) * 5,
                    "archive_months": len(months),
                }
            )
    return plan


def run_backfill(
    providers: dict[str, Any],
    symbols: list[str],
    intervals: list[str],
    *,
    start: date,
    until: date,
    tail_days: int,
    source: str,
    force: bool,
    progress: Progress,
    limit: int | None,
) -> list[RunOutcome]:
    outcomes: list[RunOutcome] = []
    jobs = [(symbol, interval) for symbol in symbols for interval in intervals]
    if not force:
        jobs = [job for job in jobs if job not in progress.done]
    if limit is not None:
        jobs = jobs[:limit]
    total = len(jobs)
    print(f"RUN population: {total} (symbol, interval) jobs to fetch")
    for index, (symbol, interval) in enumerate(jobs, start=1):
        provider = providers[interval]
        started = datetime.now(timezone.utc)
        outcome = RunOutcome(symbol=symbol, interval=interval)
        try:
            outcome.archive_rows = provider.backfill_history(
                symbol, start=max(start, DEFAULT_START[interval]), end=until, source=source
            )
            tail = list(
                provider.client.iter_klines(
                    symbol, interval, since_ms=date_to_ms(
                        datetime.now(timezone.utc).date() - timedelta(days=tail_days)
                    )
                )
            )
            outcome.tail_rows = int(provider.store(tail, symbol) or 0) if tail else 0
        except (BinanceClientError, BinanceRequestError, ValueError) as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # a single bad symbol must not kill the batch
            outcome.error = f"{type(exc).__name__}: {exc}"
        outcome.seconds = (datetime.now(timezone.utc) - started).total_seconds()
        outcomes.append(outcome)
        progress.mark(outcome)
        print(
            f"[{index}/{total}] {symbol} {interval}: written={outcome.written} "
            f"(archive={outcome.archive_rows} tail={outcome.tail_rows}) "
            f"{outcome.seconds:.1f}s"
            + (f" ERROR {outcome.error[:90]}" if outcome.error else "")
        )
    return outcomes


def write_report(payload: dict[str, Any], report_dir: Path, prefix: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = report_dir / f"{prefix}_{stamp}.json"
    path.write_text(text, encoding="utf-8")
    (report_dir / f"{prefix}_latest.json").write_text(text, encoding="utf-8")
    return path


def resolve_symbols(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_CRYPTO_SYMBOLS)
    return sorted({validate_symbol(item) for item in raw.split(",") if item.strip()})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("report", "plan", "run"), help="what to do")
    parser.add_argument("--symbols", help=f"comma-separated, default: the {len(DEFAULT_CRYPTO_SYMBOLS)} core pairs")
    parser.add_argument("--intervals", default="1d", help="comma-separated of 1d/1h (default: 1d)")
    parser.add_argument("--since", type=iso_date, default=None, help="archive start (default per interval)")
    parser.add_argument("--until", type=iso_date, default=None, help="archive end (default: today)")
    parser.add_argument("--tail-days", type=int, default=5, help="recent days re-pulled over REST")
    parser.add_argument(
        "--source",
        choices=("rest", "archive"),
        default="rest",
        help="rest = 1000 bars/request (fast); archive = monthly CSV zips (no request weight)",
    )
    parser.add_argument("--limit", type=int, default=None, help="cap number of jobs this invocation runs")
    parser.add_argument("--force", action="store_true", help="re-fetch even if already in the resume log")
    parser.add_argument("--resume-file", type=Path, default=None, help="JSONL progress file")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--json", action="store_true", help="dump the machine-readable report to stdout")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    setup_logging(args.verbose)
    symbols = resolve_symbols(args.symbols)
    intervals = [item.strip().lower() for item in args.intervals.split(",") if item.strip()]
    unknown = [item for item in intervals if item not in INTERVAL_TABLES]
    if unknown:
        print(f"unsupported intervals: {unknown}; supported = {sorted(INTERVAL_TABLES)}")
        return 2
    until = args.until or datetime.now(timezone.utc).date()
    resume_path = args.resume_file or (args.report_dir / "progress.jsonl")
    progress = Progress.load(resume_path)

    conn = connect_warehouse()
    try:
        coverage = measure_coverage(conn, symbols, intervals)
        if args.mode == "report":
            payload = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "db": DB_CONFIG["database"],
                "symbols_requested": len(symbols),
                "intervals": intervals,
                "resume_completed": len(progress.done),
                "tables_present": {
                    INTERVAL_TABLES[i][0]: table_exists(conn, INTERVAL_TABLES[i][0]) for i in intervals
                },
                "total_rows": sum(item.rows for item in coverage),
                "symbols_with_data": sum(1 for item in coverage if item.rows),
                "coverage": [item.as_dict() for item in coverage],
            }
            report_path = write_report(payload, args.report_dir, "crypto_coverage")
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str) if args.json else "")
            for item in coverage:
                print(
                    f"  {item.interval} {item.symbol:10s} rows={item.rows:>7} "
                    f"first={item.first_date or '-':10s} last={item.last_date or '-':10s} "
                    f"age={item.age_days if item.age_days is not None else '-'}d"
                )
            print(
                f"\nREPORT tables_present={payload['tables_present']} "
                f"total_rows={payload['total_rows']} symbols_with_data="
                f"{payload['symbols_with_data']}/{len(symbols) * len(intervals)}"
            )
            print(f"report_written={report_path}")
            return 0

        if args.mode == "plan":
            start = args.since or min(DEFAULT_START.values())
            plan = build_plan(symbols, intervals, start, until)
            payload = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "mode": "plan",
                "symbols": len(symbols),
                "intervals": intervals,
                "since": str(start),
                "until": str(until),
                "total_rest_requests": sum(item["rest_requests"] for item in plan),
                "total_rest_weight": sum(item["rest_weight"] for item in plan),
                "total_archive_months": sum(item["archive_months"] for item in plan),
                "expected_bars": sum(item["expected_bars"] for item in plan),
                "jobs_skipped_as_done": len(
                    [(s, i) for s in symbols for i in intervals if (s, i) in progress.done]
                ),
                "plan": plan,
            }
            report_path = write_report(payload, args.report_dir, "crypto_plan")
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str) if args.json else "")
            if not args.json:
                for item in plan[:12]:
                    print(
                        f"  {item['interval']} {item['symbol']:10s} window={item['window']} "
                        f"expected_bars={item['expected_bars']:>6} rest_req={item['rest_requests']:>3} "
                        f"archive_months={item['archive_months']:>4}"
                    )
                if len(plan) > 12:
                    print(f"  ... {len(plan) - 12} more")
            print(
                f"\nPLAN jobs={len(plan)} expected_bars={payload['expected_bars']} "
                f"rest_requests={payload['total_rest_requests']} "
                f"rest_weight={payload['total_rest_weight']} "
                f"archive_months={payload['total_archive_months']} "
                f"skipped_done={payload['jobs_skipped_as_done']}"
            )
            print(f"report_written={report_path}")
            return 0

        # run
        created = ensure_tables(conn)
        print(f"ENSURED tables={created}")
        provider_classes = {"1d": CryptoDailyMarket, "1h": CryptoHourlyMarket}
        providers = {interval: provider_classes[interval]() for interval in intervals}
        start = args.since or min(DEFAULT_START.values())
        print(f"RUN source={args.source} start={start} until={until} tail_days={args.tail_days}")
        outcomes = run_backfill(
            providers,
            symbols,
            intervals,
            start=start,
            until=until,
            tail_days=args.tail_days,
            source=args.source,
            force=args.force,
            progress=progress,
            limit=args.limit,
        )
        failed = [o for o in outcomes if o.error]
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "run",
            "jobs": len(outcomes),
            "total_written": sum(o.written for o in outcomes),
            "failed": len(failed),
            "outcomes": [o.as_dict() for o in outcomes],
        }
        report_path = write_report(payload, args.report_dir, "crypto_run")
        print(
            f"\nRUN jobs={len(outcomes)} total_written={payload['total_written']} "
            f"failed={len(failed)} resume_file={resume_path}"
        )
        for outcome in failed:
            print(f"  FAILED {outcome.symbol} {outcome.interval}: {outcome.error[:140]}")
        print(f"report_written={report_path}")
        return 1 if failed and len(failed) == len(outcomes) else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
