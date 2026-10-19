"""Idempotent backfill for the FX reference series in the ``akshare_data`` warehouse.

The registered ``currency_boc_safe`` script stamps ``data_date`` with the import day and
leaves ``symbol`` NULL, so its ``(symbol, data_date)`` unique key never matches and every
run appends a full copy of the series. This script inserts only the trading dates that are
missing from ``CURRENCY_BOC_SAFE``.

Usage (from ``src/backend``)::

    python scripts/backfill_fx_history.py                     # dry run, prints the plan
    python scripts/backfill_fx_history.py --apply             # writes the missing rows
    python scripts/backfill_fx_history.py --step boc-sina --currencies 美元 --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from time import sleep
from typing import Any

import mysql.connector
import pandas as pd

from app.data_fetch.configs.db_config import DB_CONFIG

BOC_SAFE_TABLE = "CURRENCY_BOC_SAFE"
BOC_SINA_TABLE = "CURRENCY_BOC_SINA"

# Rows in CURRENCY_BOC_SINA were written without a symbol, so they cannot be attributed to
# a currency at all. This backfill always stamps the ISO code.
BOC_SINA_PRICE_COLUMNS = [
    "中行汇买价",
    "中行钞买价",
    "中行钞卖价/汇卖价",
    "央行中间价",
    "中行折算价",
]

# Measured from the live Sina option list on 2026-10-19; used when the map endpoint is down.
BOC_SINA_NAME_TO_CODE = {
    "美元": "USD",
    "英镑": "GBP",
    "欧元": "EUR",
    "澳门元": "MOP",
    "泰国铢": "THP",
    "菲律宾比索": "PHP",
    "港币": "HKD",
    "瑞士法郎": "CHF",
    "新加坡元": "SGD",
    "瑞典克朗": "SEK",
    "丹麦克朗": "DKK",
    "挪威克朗": "NOK",
    "日元": "JPY",
    "加拿大元": "CAD",
    "澳大利亚元": "AUD",
    "新西兰元": "NZD",
    "韩国元": "KRW",
}

# Currencies that SAFE quotes as CNY per 100 foreign units. Listed here only to document
# the column convention; values are stored verbatim, exactly as akshare returns them.
CURRENCY_COLUMNS = [
    "美元",
    "欧元",
    "日元",
    "港元",
    "英镑",
    "澳元",
    "新西兰元",
    "新加坡元",
    "瑞士法郎",
    "加元",
    "澳门元",
    "林吉特",
    "卢布",
    "兰特",
    "韩元",
    "迪拉姆",
    "里亚尔",
    "福林",
    "兹罗提",
    "丹麦克朗",
    "瑞典克朗",
    "挪威克朗",
    "里拉",
    "比索",
    "泰铢",
]


def _connect() -> mysql.connector.MySQLConnection:
    return mysql.connector.connect(**DB_CONFIG)


def _census(conn: mysql.connector.MySQLConnection, table: str) -> dict[str, Any]:
    """Measure the current population of a table by its real date column."""
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT `日期`), MIN(`日期`), MAX(`日期`)
            FROM `{table}`
            """
        )
        rows, distinct_dates, min_date, max_date = cursor.fetchone()
    return {
        "rows": int(rows),
        "distinct_dates": int(distinct_dates),
        "min_date": str(min_date),
        "max_date": str(max_date),
    }


def _sina_census(conn: mysql.connector.MySQLConnection) -> dict[str, Any]:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT symbol), SUM(symbol IS NULL),
                   MIN(`日期`), MAX(`日期`)
            FROM `{BOC_SINA_TABLE}`
            """
        )
        rows, symbols, unattributed, min_date, max_date = cursor.fetchone()
    return {
        "rows": int(rows),
        "attributable_symbols": int(symbols or 0),
        "unattributed_rows": int(unattributed or 0),
        "min_date": str(min_date),
        "max_date": str(max_date),
    }


def _existing_dates(conn: mysql.connector.MySQLConnection, table: str) -> set[str]:
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT DISTINCT `日期` FROM `{table}`")
        return {str(row[0]) for row in cursor.fetchall() if row[0] is not None}


def _fetch_source() -> pd.DataFrame:
    import akshare as ak

    frame = ak.currency_boc_safe()
    if frame is None or frame.empty:
        raise RuntimeError("ak.currency_boc_safe() returned no rows")
    return frame


def _missing_rows(frame: pd.DataFrame, existing: set[str]) -> pd.DataFrame:
    candidate = frame.copy()
    candidate["日期"] = pd.to_datetime(candidate["日期"], errors="coerce").dt.strftime("%Y-%m-%d")
    candidate = candidate.dropna(subset=["日期"])
    candidate = candidate[~candidate["日期"].isin(existing)]
    return candidate.sort_values("日期").reset_index(drop=True)


def _insert_boc_safe(conn: mysql.connector.MySQLConnection, missing: pd.DataFrame) -> int:
    columns = ["日期", *CURRENCY_COLUMNS, "data_date"]
    placeholders = ", ".join(["%s"] * len(columns))
    quoted = ", ".join(f"`{name}`" for name in columns)
    sql = f"INSERT INTO `{BOC_SAFE_TABLE}` ({quoted}) VALUES ({placeholders})"

    payload: list[tuple[Any, ...]] = []
    for _, row in missing.iterrows():
        values: list[Any] = [row["日期"]]
        for column in CURRENCY_COLUMNS:
            raw = row.get(column)
            values.append(None if pd.isna(raw) else float(raw))
        values.append(date.fromisoformat(row["日期"]))
        payload.append(tuple(values))

    with conn.cursor() as cursor:
        cursor.executemany(sql, payload)
    conn.commit()
    return len(payload)


def _run_boc_safe(
    conn: mysql.connector.MySQLConnection,
    *,
    apply: bool,
    end: date,
) -> int:
    before = _census(conn, BOC_SAFE_TABLE)
    existing = _existing_dates(conn, BOC_SAFE_TABLE)
    print(
        f"[{BOC_SAFE_TABLE}] before: rows={before['rows']} "
        f"distinct_dates={before['distinct_dates']} "
        f"range={before['min_date']}..{before['max_date']}"
    )

    frame = _fetch_source()
    missing = _missing_rows(frame, existing)
    source_max = str(pd.to_datetime(frame["日期"], errors="coerce").max().date())
    print(f"[{BOC_SAFE_TABLE}] source: rows={len(frame)} latest_date={source_max}")
    print(f"[{BOC_SAFE_TABLE}] missing_dates={len(missing)}")

    if missing.empty:
        print(f"[{BOC_SAFE_TABLE}] already covers the source")
        return 0

    print(f"[{BOC_SAFE_TABLE}] will_insert {missing['日期'].iloc[0]}..{missing['日期'].iloc[-1]}")
    if not apply:
        print("[BOC_SAFE] DRY RUN - no rows written (pass --apply to write)")
        return 0

    inserted = _insert_boc_safe(conn, missing)
    after = _census(conn, BOC_SAFE_TABLE)
    print(
        f"[{BOC_SAFE_TABLE}] after: rows={after['rows']} "
        f"distinct_dates={after['distinct_dates']} range={after['min_date']}..{after['max_date']}"
    )
    print(
        f"[{BOC_SAFE_TABLE}] delta: rows=+{after['rows'] - before['rows']} "
        f"distinct_dates=+{after['distinct_dates'] - before['distinct_dates']} "
        f"inserted={inserted}"
    )
    if after["rows"] - before["rows"] != inserted:
        print("WARNING: inserted count != measured row growth", file=sys.stderr)
        return 1
    return 0


def _sina_currency_map() -> dict[str, str]:
    try:
        from akshare.currency.currency_china_bank_sina import _currency_boc_sina_map

        mapping = _currency_boc_sina_map()
        if mapping:
            return dict(mapping)
    except Exception as exc:
        print(f"live currency map unavailable ({exc}), using measured fallback", file=sys.stderr)
    return dict(BOC_SINA_NAME_TO_CODE)


def _insert_boc_sina(
    conn: mysql.connector.MySQLConnection,
    frame: pd.DataFrame,
    *,
    code: str,
    name_cn: str,
) -> int:
    columns = ["symbol", "name", "日期", *BOC_SINA_PRICE_COLUMNS, "data_date"]
    placeholders = ", ".join(["%s"] * len(columns))
    quoted = ", ".join(f"`{c}`" for c in columns)
    sql = f"INSERT IGNORE INTO `{BOC_SINA_TABLE}` ({quoted}) VALUES ({placeholders})"

    payload: list[tuple[Any, ...]] = []
    for _, row in frame.iterrows():
        if pd.isna(row["日期"]):
            continue
        values: list[Any] = [code, name_cn, str(row["日期"])]
        for column in BOC_SINA_PRICE_COLUMNS:
            raw = row.get(column)
            values.append(None if pd.isna(raw) else float(raw))
        values.append(row["日期"])
        payload.append(tuple(values))

    if not payload:
        return 0
    with conn.cursor() as cursor:
        cursor.executemany(sql, payload)
        inserted = cursor.rowcount
    conn.commit()
    return int(inserted)


def _fetch_boc_sina(
    ak,
    *,
    name_cn: str,
    start_text: str,
    end_text: str,
    attempts: int = 3,
) -> pd.DataFrame:
    """Fetch one currency, retrying transient failures against the Sina endpoint.

    ``biz.finance.sina.com.cn`` answers a direct probe in <1s but intermittently drops the
    connection mid-backfill, so a single timeout must not abandon the whole currency loop.
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return ak.currency_boc_sina(symbol=name_cn, start_date=start_text, end_date=end_text)
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                delay = 2 * attempt
                print(
                    f"  {name_cn}: attempt {attempt}/{attempts} failed "
                    f"({type(exc).__name__}), retrying in {delay}s",
                    file=sys.stderr,
                )
                sleep(delay)
    raise RuntimeError(f"{name_cn}: {attempts} attempts failed") from last_error


def _run_boc_sina(
    conn: mysql.connector.MySQLConnection,
    *,
    apply: bool,
    currencies: list[str] | None,
    start: date,
    end: date,
) -> int:
    import akshare as ak

    currency_map = _sina_currency_map()
    selected = currencies or list(currency_map)
    unknown = [name for name in selected if name not in currency_map]
    if unknown:
        print(f"ABORT: currencies not offered by the source: {unknown}", file=sys.stderr)
        print(f"available: {sorted(currency_map)}", file=sys.stderr)
        return 1

    before = _sina_census(conn)
    print(
        f"[{BOC_SINA_TABLE}] before: rows={before['rows']} "
        f"attributable_symbols={before['attributable_symbols']} "
        f"unattributed_rows={before['unattributed_rows']} "
        f"range={before['min_date']}..{before['max_date']}"
    )

    start_text = start.strftime("%Y%m%d")
    end_text = end.strftime("%Y%m%d")
    print(
        f"[{BOC_SINA_TABLE}] window={start.isoformat()}..{end.isoformat()} currencies={len(selected)}"
    )

    failures: list[str] = []
    for name_cn in selected:
        code = currency_map[name_cn]
        try:
            frame = _fetch_boc_sina(ak, name_cn=name_cn, start_text=start_text, end_text=end_text)
        except Exception as exc:
            failures.append(f"{name_cn}({code}): {type(exc).__name__}")
            print(f"  {name_cn}({code}): FETCH_FAILED {type(exc).__name__}", file=sys.stderr)
            continue

        if frame is None or frame.empty:
            failures.append(f"{name_cn}({code}): empty")
            print(f"  {name_cn}({code}): source returned 0 rows", file=sys.stderr)
            continue

        dates = pd.to_datetime(frame["日期"], errors="coerce")
        observed = f"{dates.min().date()}..{dates.max().date()}"
        if not apply:
            print(f"  {name_cn}({code}): source_rows={len(frame)} range={observed} [dry]")
            continue

        inserted = _insert_boc_sina(conn, frame, code=code, name_cn=name_cn)
        print(f"  {name_cn}({code}): source_rows={len(frame)} range={observed} inserted={inserted}")
        sleep(0.6)

    after = _sina_census(conn)
    print(
        f"[{BOC_SINA_TABLE}] after: rows={after['rows']} "
        f"attributable_symbols={after['attributable_symbols']} "
        f"unattributed_rows={after['unattributed_rows']} "
        f"range={after['min_date']}..{after['max_date']}"
    )
    print(
        f"[{BOC_SINA_TABLE}] delta: rows=+{after['rows'] - before['rows']} "
        f"attributable_symbols=+{after['attributable_symbols'] - before['attributable_symbols']}"
    )
    if failures:
        print(
            f"[{BOC_SINA_TABLE}] FAILED_CURRENCIES={len(failures)}: {failures[:6]}", file=sys.stderr
        )
        return 1
    return 0


CROSS_TABLE = "CURRENCY_TIME_SERIES"

CROSS_COLUMNS = [
    "symbol",
    "name",
    "currency",
    "date",
    "base",
    "rates",
    "source",
    "data_date",
]


def _run_crosses(
    conn: mysql.connector.MySQLConnection,
    *,
    apply: bool,
    end: date,
) -> int:
    """Extend CURRENCY_TIME_SERIES with the repo's own cross-rate derivation.

    ``build_currency_time_series_fallback`` divides two CNY-per-unit mid rates, so the new
    rows use exactly the same convention as the 78k rows already in the table. Its output
    only needs the dates the table is missing; ``(symbol, data_date)`` is a real unique key
    here, so INSERT IGNORE makes the step idempotent.
    """
    from datetime import timedelta

    from app.data_fetch.scripts.common.currency_fallback import (
        build_currency_time_series_fallback,
    )

    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT `date`), MIN(`date`), MAX(`date`),
                   COUNT(DISTINCT `currency`)
            FROM `{CROSS_TABLE}`
            """
        )
        rows, distinct_dates, min_date, max_date, currencies = cursor.fetchone()
    print(
        f"[{CROSS_TABLE}] before: rows={rows} distinct_dates={distinct_dates} "
        f"currencies={currencies} range={min_date}..{max_date}"
    )

    # A one-day overlap is harmless under INSERT IGNORE and avoids a boundary gap if the
    # table's newest date was itself written from a partial BOC_SAFE import.
    start = (date.fromisoformat(str(max_date)) - timedelta(days=1)) if max_date else end
    frame = build_currency_time_series_fallback(
        base="USD", start_date=start.isoformat(), end_date=end.isoformat()
    )
    if frame is None or frame.empty:
        print(f"[{CROSS_TABLE}] builder returned no rows for {start}..{end}", file=sys.stderr)
        return 1

    frame = frame[[column for column in CROSS_COLUMNS if column in frame.columns]]
    print(
        f"[{CROSS_TABLE}] built: rows={len(frame)} dates={frame['date'].nunique()} "
        f"currencies={frame['currency'].nunique()} range={frame['date'].min()}..{frame['date'].max()}"
    )

    payload = [
        tuple(None if pd.isna(value) else value for value in row)
        for row in frame.itertuples(index=False, name=None)
    ]
    quoted = ", ".join(f"`{name}`" for name in frame.columns)
    placeholders = ", ".join(["%s"] * len(frame.columns))
    sql = f"INSERT IGNORE INTO `{CROSS_TABLE}` ({quoted}) VALUES ({placeholders})"

    if not apply:
        print(f"[{CROSS_TABLE}] DRY RUN - {len(payload)} rows staged (pass --apply to write)")
        return 0

    with conn.cursor() as cursor:
        cursor.executemany(sql, payload)
        inserted = cursor.rowcount
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT `date`), MAX(`date`)
            FROM `{CROSS_TABLE}`
            """
        )
        after_rows, after_dates, after_max = cursor.fetchone()
    print(
        f"[{CROSS_TABLE}] after: rows={after_rows} distinct_dates={after_dates} max_date={after_max}"
    )
    print(
        f"[{CROSS_TABLE}] staged={len(payload)} inserted={inserted} "
        f"skipped_as_duplicate={len(payload) - inserted} "
        f"row_growth=+{int(after_rows) - int(rows)}"
    )
    return 0


def _run_purge_bad_cache(
    conn: mysql.connector.MySQLConnection,
    *,
    apply: bool,
    backup_path: str,
) -> int:
    """Delete FX cache rows whose symbol cannot be derived from the mid-rate table.

    ``_fx_history_column`` matched only one leg of a pair and fell back to 美元, so symbols
    such as CZKUSD, USDARS and USDCNH were all stored with the same 人民币-per-100-USD value.
    Re-running the corrected cache backfill overwrites every symbol it can resolve; these
    leftovers are the residue it structurally cannot, and they are the only rows removed here.
    """
    from app.data_fetch.scripts.common.currency_fallback import CODE_TO_NAME
    from app.services.market_instrument_asset_adapter import (
        _FX_OFFSHORE_LEG_MAP,
        _fx_pair_legs,
    )

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT UPPER(`代码`) FROM FOREX_SPOT_EM WHERE data_date="
            "(SELECT MAX(data_date) FROM FOREX_SPOT_EM)"
        )
        spot_codes = {str(row[0]) for row in cursor.fetchall() if row[0]}

    derivable: set[str] = set()
    for code in spot_codes:
        legs = _fx_pair_legs(code)
        if not legs:
            continue
        resolved = [_FX_OFFSHORE_LEG_MAP.get(leg, leg) for leg in legs]
        if all(leg == "CNY" or leg in CODE_TO_NAME for leg in resolved):
            derivable.add(code)

    with conn.cursor(dictionary=True) as cursor:
        cursor.execute(
            """
            SELECT symbol, COUNT(*) AS rows_, MIN(`date`) AS mn, MAX(`date`) AS mx,
                   AVG(close) AS avg_close
            FROM MARKET_INSTRUMENT_HISTORY_CACHE
            WHERE asset_type = 'fx'
            GROUP BY symbol
            """
        )
        per_symbol = {row["symbol"]: row for row in cursor.fetchall()}

    leftovers = sorted(set(per_symbol) - derivable)
    total = sum(int(per_symbol[s]["rows_"]) for s in leftovers)
    print(
        f"[cache] fx symbols={len(per_symbol)} derivable={len(set(per_symbol) & derivable)} "
        f"leftover={len(leftovers)} rows={total}"
    )
    for symbol in leftovers:
        row = per_symbol[symbol]
        avg = row["avg_close"]
        print(
            f"  LEFTOVER {symbol:9} rows={int(row['rows_']):5} "
            f"range={row['mn']}..{row['mx']} avg_close={round(float(avg), 4) if avg else None}"
        )

    if not leftovers:
        print("[cache] no non-derivable fx symbols remain")
        return 0

    if not apply:
        print(f"[cache] DRY RUN - {total} rows would be deleted (pass --apply)")
        return 0

    placeholders = ", ".join(["%s"] * len(leftovers))
    select_sql = (
        "SELECT * FROM MARKET_INSTRUMENT_HISTORY_CACHE"
        f" WHERE asset_type = 'fx' AND symbol IN ({placeholders})"
    )
    delete_sql = (
        "DELETE FROM MARKET_INSTRUMENT_HISTORY_CACHE"
        f" WHERE asset_type = 'fx' AND symbol IN ({placeholders})"
    )
    symbols_param = tuple(leftovers)

    with conn.cursor(dictionary=True) as cursor:
        cursor.execute(select_sql, symbols_param)
        dumped = 0
        with open(backup_path, "w", encoding="utf-8") as handle:
            for record in cursor.fetchall():
                handle.write(
                    json.dumps(
                        {key: str(value) for key, value in record.items()}, ensure_ascii=False
                    )
                    + "\n"
                )
                dumped += 1
        print(f"[cache] backup: wrote {dumped} rows to {backup_path}")
        if dumped != total:
            print("WARNING: backup rows != measured leftover rows", file=sys.stderr)
            return 1

        with conn.cursor() as cursor:
            cursor.execute(delete_sql, symbols_param)
            deleted = cursor.rowcount
        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*), COUNT(DISTINCT symbol) FROM MARKET_INSTRUMENT_HISTORY_CACHE"
                " WHERE asset_type = 'fx'"
            )
            remaining_rows, remaining_symbols = cursor.fetchone()
    print(
        f"[cache] deleted={deleted} expected={total} remaining_fx_rows={remaining_rows} "
        f"remaining_fx_symbols={remaining_symbols}"
    )
    return 0 if deleted == total else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--step",
        choices=["boc-safe", "boc-sina", "crosses", "purge-bad-cache", "all"],
        default="boc-safe",
        help="which FX reference series to refresh (default: boc-safe)",
    )
    parser.add_argument(
        "--backup",
        default="/tmp/fx_cache_backup.jsonl",
        help="where purge-bad-cache writes the rows it is about to delete",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the missing rows (default is a dry run that only prints the plan)",
    )
    parser.add_argument(
        "--currencies",
        help="comma separated Chinese currency names for boc-sina (default: all offered)",
    )
    parser.add_argument("--start-date", help="boc-sina window start, YYYY-MM-DD")
    parser.add_argument("--end-date", help="window end, YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    end = date.fromisoformat(args.end_date) if args.end_date else pd.Timestamp.now().date()
    start = (
        date.fromisoformat(args.start_date)
        if args.start_date
        else date.fromordinal(date.toordinal(end) - 730)
    )
    currencies = (
        [item.strip() for item in args.currencies.split(",") if item.strip()]
        if args.currencies
        else None
    )

    conn = _connect()
    try:
        rc = 0
        if args.step in ("boc-safe", "all"):
            rc |= _run_boc_safe(conn, apply=args.apply, end=end)
        if args.step in ("boc-sina", "all"):
            rc |= _run_boc_sina(conn, apply=args.apply, currencies=currencies, start=start, end=end)
        # Derives from CURRENCY_BOC_SAFE, so it must follow the boc-safe step.
        if args.step in ("crosses", "all"):
            rc |= _run_crosses(conn, apply=args.apply, end=end)
        # Deliberately excluded from "all": it deletes rows, so it is only ever explicit.
        if args.step == "purge-bad-cache":
            rc |= _run_purge_bad_cache(conn, apply=args.apply, backup_path=args.backup)
        return 1 if rc else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
