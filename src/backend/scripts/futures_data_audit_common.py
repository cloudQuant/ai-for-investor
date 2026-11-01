"""Shared helpers for the futures daily-data completeness audits.

The audits reuse the existing AkShare warehouse tables and scripts:

* ``TRADING_DAYS``                      -- China trading calendar (Sina)
* ``FUTURES_DAILY_MARKET``              -- futures daily bars
* ``FUTURES_CONTRACT_INFO_{EXCHANGE}``  -- exchange contract references

Run the scripts from ``src/backend`` (or use ``run_futures_data_audit.sh``)
so the usual ``.env`` configuration is picked up.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# These CLI scripts are warehouse maintenance tools. They never use the web
# server's production secrets, so force a non-production settings mode in this
# process to avoid unrelated runtime-security validation blocking the audit.
os.environ["DEBUG"] = "true"
if not os.environ.get("AKSHARE_DATA_DATABASE_URL"):
    try:
        from dotenv import load_dotenv

        load_dotenv(_BACKEND_ROOT / ".env", override=False)
    except ImportError:
        pass

import mysql.connector  # noqa: E402

from app.data_fetch.configs.db_config import DB_CONFIG  # noqa: E402
from app.data_fetch.scripts.futures.weekly.daily_market_data import (  # noqa: E402
    FuturesDailyMarket,
)

DAILY_MARKET_TABLE = "FUTURES_DAILY_MARKET"
CALENDAR_TABLE = "TRADING_DAYS"
UNAVAILABLE_TABLE = "FUTURES_DATA_AUDIT_UNAVAILABLE"
MARKET_UNAVAILABLE_SYMBOL = "*"
AUDIT_DATA_SOURCE = "期货日线完整性审计"
SINA_FALLBACK_SOURCE = "新浪期货兜底"

EXCHANGES = ("CFFEX", "CZCE", "DCE", "GFEX", "INE", "SHFE")
CONTRACT_INFO_TABLES = {
    "CFFEX": "FUTURES_CONTRACT_INFO_CFFEX",
    "CZCE": "FUTURES_CONTRACT_INFO_CZCE",
    "DCE": "FUTURES_CONTRACT_INFO_DCE",
    "GFEX": "FUTURES_CONTRACT_INFO_GFEX",
    "INE": "FUTURES_CONTRACT_INFO_INE",
    "SHFE": "FUTURES_CONTRACT_INFO_SHFE",
}
CONTRACT_START_COLUMNS = {
    "CFFEX": "LISTING_DATE",
    "CZCE": "FIRST_TRADE_DATE",
    "DCE": "START_TRADE_DATE",
    "GFEX": "START_TRADE_DATE",
    "INE": "LISTING_DATE",
    "SHFE": "LISTING_DATE",
}
DEFAULT_MARKET_START = {
    "CFFEX": date(2010, 4, 16),
    "CZCE": date(2010, 1, 4),
    "DCE": date(2001, 1, 4),
    "GFEX": date(2022, 12, 22),
    "INE": date(2018, 3, 26),
    "SHFE": date(2002, 1, 7),
}
# SHFE contract snapshots also contain the international energy contracts that
# the daily table stores under INE.
INE_PRODUCTS = frozenset({"BC", "EC", "LU", "NR", "SC"})
CONTRACT_CODE_PATTERN = r"^[A-Za-z]{1,3}[0-9]{3,4}$"

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
LOGGER = logging.getLogger("futures_data_audit")

_DAILY_UPDATER: FuturesDailyMarket | None = None


@dataclass(slots=True)
class ContractRef:
    market: str
    code: str
    source_market: str
    listing_date: date | None
    expiry_date: date | None


@dataclass(slots=True)
class FetchOutcome:
    market: str
    start: date
    end: date
    rows: int = 0
    saved: bool = False
    error: str | None = None
    covered_ranges: list[tuple[date, date]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "rows": self.rows,
            "saved": self.saved,
            "error": self.error,
            "covered_ranges": [
                [range_start.isoformat(), range_end.isoformat()]
                for range_start, range_end in self.covered_ranges
            ],
        }


def iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def resolve_as_of(value: date | None) -> date:
    """Return the latest date whose daily bars should exist.

    Before 18:00 Asia/Shanghai the current day's exchange files are usually not
    published yet, so the audit stops at the previous day.
    """
    if value is not None:
        return value
    now = datetime.now(SHANGHAI_TZ)
    if now.hour < 18:
        return now.date() - timedelta(days=1)
    return now.date()


def parse_markets(value: str | None) -> list[str]:
    if not value:
        return list(EXCHANGES)
    markets = [item.strip().upper() for item in value.split(",") if item.strip()]
    unknown = sorted(set(markets) - set(EXCHANGES))
    if unknown:
        raise ValueError(f"unknown market(s): {', '.join(unknown)}")
    return markets


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def connect() -> Any:
    return mysql.connector.connect(**DB_CONFIG)


def load_calendar(conn: Any, as_of: date, start: date | None = None) -> list[date]:
    query = f"SELECT TRADE_DATE FROM `{CALENDAR_TABLE}` WHERE TRADE_DATE <= %s"
    params: list[Any] = [as_of]
    if start is not None:
        query += " AND TRADE_DATE >= %s"
        params.append(start)
    query += " ORDER BY TRADE_DATE"
    cursor = conn.cursor()
    try:
        cursor.execute(query, tuple(params))
        return [row[0] for row in cursor.fetchall() if row[0] is not None]
    finally:
        cursor.close()


def load_market_first_dates(conn: Any) -> dict[str, date]:
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"SELECT MARKET, MIN(TRADE_DATE) FROM `{DAILY_MARKET_TABLE}` GROUP BY MARKET"
        )
        return {str(row[0]).upper(): row[1] for row in cursor.fetchall() if row[1] is not None}
    finally:
        cursor.close()


def load_daily_dates_by_market(conn: Any, as_of: date) -> dict[str, set[date]]:
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            SELECT MARKET, TRADE_DATE
            FROM `{DAILY_MARKET_TABLE}`
            WHERE TRADE_DATE <= %s
            GROUP BY MARKET, TRADE_DATE
            """,
            (as_of,),
        )
        dates: dict[str, set[date]] = {}
        for market, trade_date in cursor.fetchall():
            dates.setdefault(str(market).upper(), set()).add(trade_date)
        return dates
    finally:
        cursor.close()


def load_daily_codes(conn: Any) -> set[str]:
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT DISTINCT UPPER(TRIM(SYMBOL)) FROM `{DAILY_MARKET_TABLE}`")
        return {str(row[0]).strip().upper() for row in cursor.fetchall() if row[0]}
    finally:
        cursor.close()


def load_reference_contracts(conn: Any) -> dict[tuple[str, str], ContractRef]:
    """Load the exchange contract universe aggregated across snapshots."""
    refs: dict[tuple[str, str], ContractRef] = {}
    cursor = conn.cursor()
    try:
        for source_market, table in CONTRACT_INFO_TABLES.items():
            start_column = CONTRACT_START_COLUMNS[source_market]
            option_filter = ""
            if source_market == "CFFEX":
                option_filter = "AND (OPTION_TYPE IS NULL OR OPTION_TYPE = '')"
            query = (
                f"SELECT UPPER(TRIM(CONTRACT_CODE)), MIN({start_column}), MAX(EXPIRY_DATE) "
                f"FROM `{table}` "
                f"WHERE TRIM(CONTRACT_CODE) REGEXP %s {option_filter} "
                f"GROUP BY UPPER(TRIM(CONTRACT_CODE))"
            )
            try:
                cursor.execute(query, (CONTRACT_CODE_PATTERN,))
            except mysql.connector.Error as exc:
                LOGGER.warning("读取 %s 合约基准失败: %s", table, exc)
                continue

            for code, listing_date, expiry_date in cursor.fetchall():
                if not code:
                    continue
                market = map_contract_market(source_market, code)
                key = (market, code)
                existing = refs.get(key)
                if existing is None:
                    refs[key] = ContractRef(
                        market=market,
                        code=code,
                        source_market=source_market,
                        listing_date=listing_date,
                        expiry_date=expiry_date,
                    )
                    continue
                if listing_date and (
                    existing.listing_date is None or listing_date < existing.listing_date
                ):
                    existing.listing_date = listing_date
                if expiry_date and (
                    existing.expiry_date is None or expiry_date > existing.expiry_date
                ):
                    existing.expiry_date = expiry_date
    finally:
        cursor.close()
    return refs


def map_contract_market(source_market: str, code: str) -> str:
    prefix_match = re.match(r"^[A-Z]+", code)
    prefix = prefix_match.group(0) if prefix_match else ""
    if source_market == "SHFE" and prefix in INE_PRODUCTS:
        return "INE"
    return source_market


def load_actual_counts(conn: Any, market: str, as_of: date) -> dict[str, int]:
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            SELECT UPPER(TRIM(SYMBOL)), COUNT(DISTINCT TRADE_DATE)
            FROM `{DAILY_MARKET_TABLE}`
            WHERE MARKET = %s AND TRADE_DATE <= %s
            GROUP BY UPPER(TRIM(SYMBOL))
            """,
            (market, as_of),
        )
        return {str(row[0]).strip().upper(): int(row[1]) for row in cursor.fetchall() if row[0]}
    finally:
        cursor.close()


def load_actual_dates(
    conn: Any,
    market: str,
    codes: Iterable[str],
    start: date,
    end: date,
) -> dict[str, set[date]]:
    """Load traded dates for a set of contracts, batched to keep SQL small."""
    ordered = sorted({str(code).strip().upper() for code in codes})
    result: dict[str, set[date]] = {code: set() for code in ordered}
    if not ordered:
        return result

    cursor = conn.cursor()
    try:
        for offset in range(0, len(ordered), 200):
            batch = ordered[offset : offset + 200]
            placeholders = ", ".join(["%s"] * len(batch))
            cursor.execute(
                f"""
                SELECT UPPER(TRIM(SYMBOL)), TRADE_DATE
                FROM `{DAILY_MARKET_TABLE}`
                WHERE MARKET = %s
                  AND TRADE_DATE BETWEEN %s AND %s
                  AND UPPER(TRIM(SYMBOL)) IN ({placeholders})
                GROUP BY UPPER(TRIM(SYMBOL)), TRADE_DATE
                """,
                (market, start, end, *batch),
            )
            for code, trade_date in cursor.fetchall():
                result.setdefault(str(code).strip().upper(), set()).add(trade_date)
    finally:
        cursor.close()
    return result


def load_market_dates(conn: Any, market: str, start: date, end: date) -> set[date]:
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            SELECT DISTINCT TRADE_DATE
            FROM `{DAILY_MARKET_TABLE}`
            WHERE MARKET = %s AND TRADE_DATE BETWEEN %s AND %s
            """,
            (market, start, end),
        )
        return {row[0] for row in cursor.fetchall() if row[0] is not None}
    finally:
        cursor.close()


def _daily_updater() -> FuturesDailyMarket:
    global _DAILY_UPDATER
    if _DAILY_UPDATER is None:
        _DAILY_UPDATER = FuturesDailyMarket(logger=logging.getLogger("futures_data_audit.akshare"))
    return _DAILY_UPDATER


_SPLITTABLE_ERROR_MARKERS = (
    "JSONDecodeError",
    "ValueError",
    "KeyError",
    "ParserError",
    "IndexError",
    "TimeoutError",
)
_MAX_SPLIT_DEPTH = 4


def _fetch_daily_range_once(
    market: str,
    start: date,
    end: date,
    *,
    target_codes: set[str] | None,
    retries: int,
    retry_delay: float,
    timeout_seconds: int,
) -> FetchOutcome:
    outcome = FetchOutcome(market=market, start=start, end=end)
    updater = _daily_updater()
    frame: Any = None
    for attempt in range(retries + 1):
        try:
            frame = updater.fetch_ak_data(
                "get_futures_daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                market=market,
                _call_timeout=timeout_seconds,
            )
            outcome.error = None
            break
        except TimeoutError as exc:
            outcome.error = f"TimeoutError: {exc}"
            break
        except Exception as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(retry_delay * (attempt + 1))

    if frame is None or getattr(frame, "empty", True):
        outcome.error = outcome.error or "数据源返回空数据"
        return outcome

    prepared = updater._prepare_daily_market_frame(
        frame,
        market=market,
        data_source=AUDIT_DATA_SOURCE,
    )
    if prepared.empty:
        outcome.error = "标准化后无有效数据"
        return outcome

    if target_codes:
        normalized = prepared["SYMBOL"].astype(str).str.strip().str.upper()
        prepared = prepared[normalized.isin(target_codes)]
        if prepared.empty:
            outcome.error = "返回数据中不含目标合约"
            return outcome

    outcome.rows = len(prepared)
    outcome.saved = bool(updater._save_daily_market_frame(prepared, table_name=DAILY_MARKET_TABLE))
    if outcome.saved:
        outcome.covered_ranges = [(start, end)]
    else:
        outcome.error = outcome.error or "写入数据库失败"
    return outcome


def fetch_daily_range(
    market: str,
    start: date,
    end: date,
    *,
    target_codes: set[str] | None = None,
    retries: int = 1,
    retry_delay: float = 3.0,
    timeout_seconds: int = 45,
    split_on_failure: bool = True,
    _split_depth: int = 0,
) -> FetchOutcome:
    """Fetch one exchange date range and upsert it into FUTURES_DAILY_MARKET.

    AkShare's exchange-day parser sometimes rejects a whole range when a single
    day inside it is unavailable. Parse-level failures are split in half down
    to individual days so the remaining dates can still be backfilled.
    """
    outcome = _fetch_daily_range_once(
        market,
        start,
        end,
        target_codes=target_codes,
        retries=retries,
        retry_delay=retry_delay,
        timeout_seconds=timeout_seconds,
    )
    splittable = bool(
        outcome.error and any(marker in outcome.error for marker in _SPLITTABLE_ERROR_MARKERS)
    )
    if (
        outcome.saved
        or start >= end
        or not split_on_failure
        or not splittable
        or _split_depth >= _MAX_SPLIT_DEPTH
    ):
        return outcome

    midpoint = start + timedelta(days=(end - start).days // 2)
    left = fetch_daily_range(
        market,
        start,
        midpoint,
        target_codes=target_codes,
        retries=0,
        retry_delay=retry_delay,
        timeout_seconds=timeout_seconds,
        split_on_failure=True,
        _split_depth=_split_depth + 1,
    )
    right = fetch_daily_range(
        market,
        midpoint + timedelta(days=1),
        end,
        target_codes=target_codes,
        retries=0,
        retry_delay=retry_delay,
        timeout_seconds=timeout_seconds,
        split_on_failure=True,
        _split_depth=_split_depth + 1,
    )

    combined = FetchOutcome(market=market, start=start, end=end)
    combined.rows = left.rows + right.rows
    combined.saved = left.saved or right.saved
    combined.covered_ranges = left.covered_ranges + right.covered_ranges
    errors = [item.error for item in (left, right) if item.error]
    combined.error = "; ".join(errors) if errors else None
    return combined


def group_dates(
    dates: Iterable[date],
    *,
    max_span_days: int = 7,
    max_gap_days: int = 7,
) -> list[tuple[date, date]]:
    """Group missing dates into bounded, mostly-contiguous fetch windows."""
    ordered = sorted(set(dates))
    if not ordered:
        return []

    groups: list[tuple[date, date]] = []
    group_start = previous = ordered[0]
    for current in ordered[1:]:
        if (current - group_start).days > max_span_days or (current - previous).days > max_gap_days:
            groups.append((group_start, previous))
            group_start = current
        previous = current
    groups.append((group_start, previous))
    return groups


def write_report(report: Mapping[str, Any], report_dir: Path, prefix: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    timestamp = datetime.now(SHANGHAI_TZ).strftime("%Y%m%d_%H%M%S")
    path = report_dir / f"{prefix}_{timestamp}.json"
    path.write_text(payload, encoding="utf-8")
    (report_dir / f"{prefix}_latest.json").write_text(payload, encoding="utf-8")
    return path


def ensure_unavailable_table(conn: Any) -> None:
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{UNAVAILABLE_TABLE}` (
              `MARKET` VARCHAR(16) NOT NULL COMMENT '交易所',
              `SYMBOL` VARCHAR(32) NOT NULL COMMENT '合约代码',
              `TRADE_DATE` DATE NOT NULL COMMENT '缺失交易日',
              `REASON` VARCHAR(128) NOT NULL COMMENT '归类原因',
              `CREATEDATE` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              `UPDATEDATE` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (`MARKET`, `SYMBOL`, `TRADE_DATE`),
              KEY `IDX_FUTURES_AUDIT_UNAVAILABLE_DATE` (`TRADE_DATE`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='期货日线审计源端不可得记录'
            """
        )
        conn.commit()
    finally:
        cursor.close()


def load_unavailable_dates(conn: Any) -> set[tuple[str, str, date]]:
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT MARKET, UPPER(TRIM(SYMBOL)), TRADE_DATE FROM `{UNAVAILABLE_TABLE}`")
        return {
            (str(market).upper(), str(symbol).strip().upper(), trade_date)
            for market, symbol, trade_date in cursor.fetchall()
            if trade_date is not None
        }
    except mysql.connector.Error as exc:
        if getattr(exc, "errno", None) == 1146:
            return set()
        raise
    finally:
        cursor.close()


def load_unavailable_market_dates(conn: Any) -> set[tuple[str, date]]:
    return {
        (market, trade_date)
        for market, symbol, trade_date in load_unavailable_dates(conn)
        if symbol == MARKET_UNAVAILABLE_SYMBOL
    }


def record_unavailable_dates(
    conn: Any,
    entries: Iterable[tuple[str, str, date]],
    reason: str,
) -> int:
    unique_entries = sorted(set(entries))
    if not unique_entries:
        return 0
    ensure_unavailable_table(conn)
    cursor = conn.cursor()
    try:
        cursor.executemany(
            f"""
            INSERT INTO `{UNAVAILABLE_TABLE}` (MARKET, SYMBOL, TRADE_DATE, REASON)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE REASON = VALUES(REASON)
            """,
            [(market, symbol, trade_date, reason) for market, symbol, trade_date in unique_entries],
        )
        conn.commit()
        return len(unique_entries)
    finally:
        cursor.close()


def add_common_arguments(
    parser: argparse.ArgumentParser,
    *,
    chunk_days: int = 7,
    max_repair_days: int = 200,
) -> None:
    parser.add_argument("--as-of", type=iso_date, help="audit through this date (YYYY-MM-DD)")
    parser.add_argument(
        "--markets",
        type=str,
        default=",".join(EXCHANGES),
        help=f"comma-separated exchanges, default: {','.join(EXCHANGES)}",
    )
    parser.add_argument(
        "--start-date",
        type=iso_date,
        help="ignore expected dates before this floor (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--no-repair",
        action="store_true",
        help="only report gaps; do not fetch missing data",
    )
    parser.add_argument(
        "--max-repair-days",
        type=int,
        default=max_repair_days,
        help=f"maximum missing dates to fetch in this run (default: {max_repair_days})",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=chunk_days,
        help=f"maximum calendar span per data-source request (default: {chunk_days})",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=2.0,
        help="pause between data-source requests (default: 2.0)",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=_BACKEND_ROOT / "logs" / "futures_data_audit",
        help="directory for JSON audit reports",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
