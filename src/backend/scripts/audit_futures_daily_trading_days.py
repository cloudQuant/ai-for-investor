#!/usr/bin/env python3
"""Audit futures trading days and fill dates missing for a whole exchange.

Step 1 of the futures daily-data audit. It refreshes the shared
``TRADING_DAYS`` calendar, compares it with the dates present in
``FUTURES_DAILY_MARKET`` for each exchange, and fetches missing market dates
from AkShare.

Exit codes: 0 = no missing dates remain, 1 = gaps remain, 2 = fatal error.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta
from typing import Any

from futures_data_audit_common import (
    DEFAULT_MARKET_START,
    LOGGER,
    MARKET_UNAVAILABLE_SYMBOL,
    add_common_arguments,
    connect,
    fetch_daily_range,
    group_dates,
    load_calendar,
    load_daily_dates_by_market,
    load_market_dates,
    load_market_first_dates,
    load_unavailable_market_dates,
    parse_markets,
    record_unavailable_dates,
    resolve_as_of,
    setup_logging,
    write_report,
)

from app.data_fetch.scripts.common.monthly.trading_days import TradingDaysUpdater


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check futures trading-day coverage and backfill missing dates."
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--no-refresh-calendar",
        action="store_true",
        help="use the existing TRADING_DAYS table without refreshing it from Sina",
    )
    parser.add_argument(
        "--retry-unavailable",
        action="store_true",
        help="retry market dates previously recorded as unavailable from the source",
    )
    return parser


def _calendar_refresh(args: argparse.Namespace, report: dict[str, Any]) -> None:
    if args.no_refresh_calendar:
        report["calendar_refresh"] = "skipped"
        return
    try:
        refreshed = TradingDaysUpdater(
            logger=logging.getLogger("futures_data_audit.trading_days")
        ).run()
        report["calendar_refresh"] = bool(refreshed)
        LOGGER.info("交易日历刷新%s", "成功" if refreshed else "未获得新数据")
    except Exception as exc:
        report["calendar_refresh"] = False
        report["calendar_refresh_error"] = f"{type(exc).__name__}: {exc}"
        LOGGER.warning("交易日历刷新失败，继续使用现有日历: %s", exc)


def _market_floor(market: str, first_dates: dict[str, date], start_date: date | None) -> date:
    floor = first_dates.get(market) or DEFAULT_MARKET_START[market]
    if start_date is not None and start_date > floor:
        floor = start_date
    return floor


def _verify_attempted(market: str, attempted: list[date], missing: list[date]) -> list[date]:
    try:
        conn = connect()
        try:
            fetched = load_market_dates(conn, market, min(attempted), max(attempted))
        finally:
            conn.close()
    except Exception as exc:
        LOGGER.warning("%s 补齐结果复核失败: %s", market, exc)
        return missing
    return [trade_date for trade_date in missing if trade_date not in fetched]


def main() -> int:
    args = build_parser().parse_args()
    setup_logging(args.verbose)
    as_of = resolve_as_of(args.as_of)
    try:
        markets = parse_markets(args.markets)
    except ValueError as exc:
        LOGGER.error("%s", exc)
        return 2

    LOGGER.info("期货交易日审计开始: as_of=%s markets=%s", as_of, ",".join(markets))
    report: dict[str, Any] = {
        "script": "audit_futures_daily_trading_days",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "markets": markets,
        "repair_enabled": not args.no_repair,
        "results": [],
    }
    _calendar_refresh(args, report)

    try:
        conn = connect()
        try:
            calendar = load_calendar(conn, as_of)
            first_dates = load_market_first_dates(conn)
            daily_dates = load_daily_dates_by_market(conn, as_of)
            unavailable: set[tuple[str, date]] = set()
            if not args.retry_unavailable:
                unavailable = load_unavailable_market_dates(conn)
        finally:
            conn.close()
    except Exception as exc:
        LOGGER.error("读取交易日历或行情日期失败: %s", exc, exc_info=True)
        return 2

    if not calendar:
        LOGGER.error("TRADING_DAYS 中没有 <= %s 的交易日，无法审计", as_of)
        return 2

    stale_cutoff = date.today() - timedelta(days=30)
    perpetual_error_markers = (
        "JSONDecodeError",
        "ValueError",
        "KeyError",
        "ParserError",
        "IndexError",
    )
    total_missing = 0
    total_remaining = 0
    total_unavailable = 0
    for market in markets:
        floor = _market_floor(market, first_dates, args.start_date)
        expected = [trade_date for trade_date in calendar if trade_date >= floor]
        actual = daily_dates.get(market, set())
        raw_missing = [trade_date for trade_date in expected if trade_date not in actual]
        known_unavailable = [
            trade_date for trade_date in raw_missing if (market, trade_date) in unavailable
        ]
        missing = [
            trade_date for trade_date in raw_missing if (market, trade_date) not in unavailable
        ]

        outcomes: list[dict[str, Any]] = []
        attempted: list[date] = []
        planned: list[date] = []
        if missing and not args.no_repair and args.max_repair_days > 0:
            planned = missing[: args.max_repair_days]
            for chunk_start, chunk_end in group_dates(planned, max_span_days=args.chunk_days):
                outcome = fetch_daily_range(market, chunk_start, chunk_end)
                outcomes.append(outcome.as_dict())
                attempted.extend(
                    trade_date for trade_date in planned if chunk_start <= trade_date <= chunk_end
                )
                LOGGER.info(
                    "%s 抓取 %s ~ %s: rows=%s saved=%s error=%s",
                    market,
                    chunk_start,
                    chunk_end,
                    outcome.rows,
                    outcome.saved,
                    outcome.error,
                )
                time.sleep(max(0.0, args.sleep_seconds))

        remaining = _verify_attempted(market, attempted, missing) if attempted else missing

        covered_dates: set[date] = set()
        parse_failed_dates: set[date] = set()
        for outcome in outcomes:
            range_start = date.fromisoformat(str(outcome["start"]))
            range_end = date.fromisoformat(str(outcome["end"]))
            covered_ranges = outcome.get("covered_ranges") or []
            for covered_start, covered_end in covered_ranges:
                start = date.fromisoformat(str(covered_start))
                end = date.fromisoformat(str(covered_end))
                covered_dates.update(
                    trade_date for trade_date in planned if start <= trade_date <= end
                )
            error = outcome.get("error") or ""
            if any(marker in str(error) for marker in perpetual_error_markers):
                parse_failed_dates.update(
                    trade_date for trade_date in planned if range_start <= trade_date <= range_end
                )

        newly_unavailable = [
            trade_date
            for trade_date in remaining
            if trade_date <= stale_cutoff
            and (trade_date in covered_dates or trade_date in parse_failed_dates)
        ]
        if newly_unavailable:
            newly_unavailable_set = set(newly_unavailable)
            try:
                conn = connect()
                try:
                    recorded = record_unavailable_dates(
                        conn,
                        (
                            (market, MARKET_UNAVAILABLE_SYMBOL, trade_date)
                            for trade_date in newly_unavailable
                        ),
                        "source_fetch_unavailable",
                    )
                finally:
                    conn.close()
                LOGGER.info("%s 记录源端不可得交易日 %s 条", market, recorded)
            except Exception as exc:
                LOGGER.warning("%s 写入源端不可得记录失败: %s", market, exc)
            remaining = [
                trade_date for trade_date in remaining if trade_date not in newly_unavailable_set
            ]

        result = {
            "market": market,
            "floor": floor.isoformat(),
            "expected_days": len(expected),
            "missing_days": len(missing),
            "missing_sample": [trade_date.isoformat() for trade_date in missing[:20]],
            "previously_unavailable_days": len(known_unavailable),
            "newly_unavailable_days": len(newly_unavailable),
            "unavailable_sample": [trade_date.isoformat() for trade_date in newly_unavailable[:20]],
            "attempted_days": len(attempted),
            "fetch_outcomes": outcomes,
            "remaining_days": len(remaining),
            "remaining_sample": [trade_date.isoformat() for trade_date in remaining[:20]],
        }
        report["results"].append(result)
        total_missing += len(missing)
        total_remaining += len(remaining)
        total_unavailable += len(known_unavailable) + len(newly_unavailable)
        LOGGER.info(
            "%s: expected=%s missing=%s unavailable=%s attempted=%s remaining=%s",
            market,
            len(expected),
            len(missing),
            len(known_unavailable) + len(newly_unavailable),
            len(attempted),
            len(remaining),
        )

    report["summary"] = {
        "missing_days": total_missing,
        "unavailable_days": total_unavailable,
        "remaining_days": total_remaining,
        "complete": total_remaining == 0,
    }
    report_path = write_report(report, args.report_dir, "audit_futures_daily_trading_days")
    LOGGER.info(
        "交易日审计完成: missing=%s unavailable=%s remaining=%s report=%s",
        total_missing,
        total_unavailable,
        total_remaining,
        report_path,
    )
    return 0 if total_remaining == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
