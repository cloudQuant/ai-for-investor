# ruff: noqa: E402
"""把 THS 历史数据导出为 bt_api_py 的 ``stock_data`` 目录（一标一份 Parquet）。

来源分工（dump 只覆盖日线与除权因子）：
- 日线 OHLCV：``market-dumps/daily-k`` Parquet 切分（本地缓存可复用）
- 除权因子：``market-dumps/adjustment-factors`` Parquet 切分
- 财务三表：本地 MySQL（``market.stock_financials_*``）
- 交易日历：本地 MySQL（``md_calendar_events``）

用法：
    python scripts/export_ths_to_stock_data.py \
        --target-dir /Users/yunjinqi/Documents/new_projects/bt_api_py/stock_data \
        --dump-file "$TMPDIR/ths_daily_k_full.parquet" --datasets daily adjustment financials calendar
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.market_data.ths_dump_importer import (
    ThsDumpDownloader,
    parse_adjustment_factors_parquet,
    parse_daily_k_parquet,
    thscode_for_canonical_id,
)

_UTC = timezone.utc
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FINANCIALS = {
    "income": "market.stock_financials_income",
    "balance": "market.stock_financials_balance",
    "cashflow": "market.stock_financials_cashflow",
}


def load_env_file() -> None:
    """仅注入所需环境变量（不覆盖已存在值）。"""
    env_path = BACKEND_ROOT.parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in {"THS_API_KEY", "THS_API_BASE_URL", "DATABASE_URL"}:
            os.environ.setdefault(key.strip(), value.strip())


def _write_parquet(path: Path, rows: list[dict], schema: pa.Schema) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, path)


# ---------------------------------------------------------------- daily


_DAILY_SCHEMA = pa.schema(
    [
        ("thscode", pa.string()),
        ("date", pa.date32()),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("volume", pa.float64()),
        ("turnover", pa.float64()),
    ]
)


def export_daily(*, target_dir: Path, dump_file: str | None, limit: int | None) -> int:
    downloader = _downloader()
    content = downloader.fetch_dump("daily-k", cache_path=dump_file)
    bars = parse_daily_k_parquet(content)
    grouped: dict[str, list] = {}
    for bar in bars:
        grouped.setdefault(bar.thscode, []).append(bar)
    written = 0
    for symbol in sorted(grouped):
        if limit is not None and written >= limit:
            break
        rows = [
            {
                "thscode": bar.thscode,
                "date": bar.event_at.date(),  # event_at 已是交易日 UTC midnight
                "open": bar.open_price,
                "high": bar.high_price,
                "low": bar.low_price,
                "close": bar.close_price,
                "volume": bar.volume,
                "turnover": bar.turnover,
            }
            for bar in sorted(grouped[symbol], key=lambda b: b.event_at)
        ]
        _write_parquet(target_dir / "daily" / f"{symbol}.parquet", rows, _DAILY_SCHEMA)
        written += 1
    return written


# ------------------------------------------------------- adjustment factors


_ADJUSTMENT_SCHEMA = pa.schema(
    [
        ("thscode", pa.string()),
        ("ex_date", pa.date32()),
        ("dividend_per_share", pa.float64()),
        ("per_share_bonus", pa.float64()),
    ]
)


def export_adjustment(*, target_dir: Path, limit: int | None) -> int:
    downloader = _downloader()
    content = downloader.fetch_dump("adjustment-factors")
    factors = parse_adjustment_factors_parquet(content)
    grouped: dict[str, list] = {}
    for factor in factors:
        grouped.setdefault(factor.thscode, []).append(factor)
    written = 0
    for symbol in sorted(grouped):
        if limit is not None and written >= limit:
            break
        rows = [
            {
                "thscode": factor.thscode,
                "ex_date": factor.event_at.date(),
                "dividend_per_share": factor.dividend_per_share,
                "per_share_bonus": factor.per_share_bonus,
            }
            for factor in sorted(grouped[symbol], key=lambda f: f.event_at)
        ]
        _write_parquet(
            target_dir / "adjustment_factors" / f"{symbol}.parquet", rows, _ADJUSTMENT_SCHEMA
        )
        written += 1
    return written


def _downloader() -> ThsDumpDownloader:
    api_key = os.environ.get("THS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("THS_AUTH_UNAVAILABLE")
    base_url = os.environ.get("THS_API_BASE_URL", "https://fuyao.aicubes.cn").strip()
    return ThsDumpDownloader(api_key=api_key, base_url=base_url, timeout_seconds=600.0)


# ------------------------------------------------------------- financials


async def export_financials(*, target_dir: Path, limit: int | None) -> dict[str, int]:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL_UNAVAILABLE")
    engine = create_async_engine(database_url, future=True)
    result_counts: dict[str, int] = {}
    try:
        async with engine.connect() as conn:
            for statement, dataset_code in _FINANCIALS.items():
                rows = (
                    await conn.execute(
                        text(
                            """
                            SELECT s.canonical_id, o.event_time, o.fields_json
                            FROM md_data_series s
                            JOIN dg_datasets d ON d.id = s.dataset_id
                            JOIN md_observation_revisions o ON o.series_id = s.id
                            WHERE d.dataset_code = :code
                            ORDER BY s.canonical_id, o.event_time
                            """
                        ),
                        {"code": dataset_code},
                    )
                ).all()
                by_symbol: dict[str, list[dict]] = {}
                for canonical_id, event_time, fields_json in rows:
                    symbol = thscode_for_canonical_id(canonical_id)
                    if symbol is None:
                        continue
                    fields = (
                        fields_json if isinstance(fields_json, dict) else json.loads(fields_json)
                    )
                    record = {
                        "period_end": event_time.date()
                        if hasattr(event_time, "date")
                        else event_time
                    }
                    record.update(fields)
                    by_symbol.setdefault(symbol, []).append(record)
                written = 0
                for symbol in sorted(by_symbol):
                    if limit is not None and written >= limit:
                        break
                    _write_financials_parquet(
                        target_dir / "financials" / statement / f"{symbol}.parquet",
                        by_symbol[symbol],
                    )
                    written += 1
                result_counts[statement] = written
    finally:
        await engine.dispose()
    return result_counts


def _write_financials_parquet(path: Path, records: list[dict]) -> None:
    """财务字段异构，统一按字符串/数值列写出（避免缺失列报错）。"""
    normalized: dict[str, list] = {}
    for record in records:
        for key, value in record.items():
            normalized.setdefault(key, []).append(value)
    arrays = {}
    for key, values in normalized.items():
        if key == "period_end":
            arrays[key] = pa.array(values, type=pa.date32())
        elif all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in values if v is not None
        ):
            arrays[key] = pa.array(values, type=pa.float64())
        else:
            arrays[key] = pa.array(
                [None if v is None else str(v) for v in values], type=pa.string()
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(arrays), path)


# ---------------------------------------------------------------- calendar


async def export_calendar(*, target_dir: Path) -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT DISTINCT trading_date, event_start
                        FROM md_calendar_events
                        WHERE event_type = 'session' AND is_trading_day = 1
                        ORDER BY trading_date
                        """
                    )
                )
            ).all()
    finally:
        await engine.dispose()
    records = []
    for trading_date, _event_start in rows:
        day = trading_date.date() if isinstance(trading_date, datetime) else trading_date
        millis = int(datetime.combine(day, time.min, tzinfo=_SHANGHAI).timestamp() * 1000)
        records.append({"date": day, "date_ms": millis})
    schema = pa.schema([("date", pa.date32()), ("date_ms", pa.int64())])
    _write_parquet(target_dir / "trading_calendar.parquet", records, schema)
    return len(records)


# ------------------------------------------------------------------- main


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-dir", required=True, help="stock_data 目录")
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=["daily", "adjustment", "financials", "calendar"],
        default=["daily", "adjustment", "financials", "calendar"],
    )
    parser.add_argument("--limit", type=int, default=None, help="每个数据集最多写多少标的")
    parser.add_argument("--dump-file", default=None, help="日线 Parquet 本地缓存")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    args = _arguments(argv)
    target = Path(args.target_dir).expanduser()
    report: dict[str, object] = {"target_dir": str(target)}
    if "daily" in args.datasets:
        report["daily_symbols"] = export_daily(
            target_dir=target, dump_file=args.dump_file, limit=args.limit
        )
    if "adjustment" in args.datasets:
        report["adjustment_symbols"] = export_adjustment(target_dir=target, limit=args.limit)
    if "financials" in args.datasets:
        report["financials"] = asyncio.run(export_financials(target_dir=target, limit=args.limit))
    if "calendar" in args.datasets:
        report["calendar_days"] = asyncio.run(export_calendar(target_dir=target))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
