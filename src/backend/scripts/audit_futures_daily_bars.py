#!/usr/bin/env python3
"""Audit per-contract futures daily bars and fill contract-date gaps.

Step 3 of the futures daily-data audit. For every referenced contract it
compares the trading days between listing and expiry with the dates present in
``FUTURES_DAILY_MARKET``. Missing contract-date rows are backfilled by fetching
the affected exchange dates; the source returns all contracts for a date.

Exit codes: 0 = no missing rows remain, 1 = gaps remain, 2 = fatal error.
"""

from __future__ import annotations

import argparse
import sys
import time
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from futures_data_audit_common import (
    DEFAULT_MARKET_START,
    LOGGER,
    ContractRef,
    add_common_arguments,
    connect,
    fetch_daily_range,
    group_dates,
    load_actual_counts,
    load_actual_dates,
    load_calendar,
    load_market_dates,
    load_reference_contracts,
    load_unavailable_dates,
    parse_markets,
    record_unavailable_dates,
    resolve_as_of,
    setup_logging,
    write_report,
)


@dataclass(slots=True)
class ContractGap:
    ref: ContractRef
    missing_dates: list[date]
    expected_days: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check per-contract futures daily bars and backfill missing dates."
    )
    add_common_arguments(parser, chunk_days=30, max_repair_days=500)
    parser.add_argument(
        "--symbols",
        type=str,
        help="comma-separated contract codes to audit (default: all referenced contracts)",
    )
    parser.add_argument(
        "--min-missing-days",
        type=int,
        default=1,
        help="only report/repair contracts missing at least this many days (default: 1)",
    )
    parser.add_argument(
        "--retry-unavailable",
        action="store_true",
        help="retry contract-dates previously recorded as unavailable from the source",
    )
    return parser


def _selected_references(
    references: dict[tuple[str, str], ContractRef],
    markets: set[str],
    symbols: set[str] | None,
) -> list[ContractRef]:
    selected = [
        ref
        for ref in references.values()
        if ref.market in markets and (symbols is None or ref.code in symbols)
    ]
    return sorted(selected, key=lambda ref: (ref.market, ref.code))


def _expected_windows(
    references: list[ContractRef],
    calendar: list[date],
    as_of: date,
) -> dict[tuple[str, str], tuple[int, int]]:
    windows: dict[tuple[str, str], tuple[int, int]] = {}
    calendar_start = calendar[0]
    for ref in references:
        if ref.listing_date is None or ref.expiry_date is None:
            continue
        window_start = max(ref.listing_date, calendar_start, DEFAULT_MARKET_START[ref.market])
        window_end = min(ref.expiry_date, as_of)
        if window_start > window_end:
            continue
        lower = bisect_left(calendar, window_start)
        upper = bisect_right(calendar, window_end)
        if upper > lower:
            windows[(ref.market, ref.code)] = (lower, upper)
    return windows


def _load_dates_for_markets(
    suspicious: list[ContractRef],
    windows: dict[tuple[str, str], tuple[int, int]],
    calendar: list[date],
) -> dict[tuple[str, str], set[date]]:
    by_market: dict[str, list[ContractRef]] = {}
    for ref in suspicious:
        by_market.setdefault(ref.market, []).append(ref)

    dates: dict[tuple[str, str], set[date]] = {}
    try:
        conn = connect()
        try:
            for market, refs in by_market.items():
                lower = min(windows[(market, ref.code)][0] for ref in refs)
                upper = max(windows[(market, ref.code)][1] for ref in refs)
                loaded = load_actual_dates(
                    conn,
                    market,
                    (ref.code for ref in refs),
                    calendar[lower],
                    calendar[upper - 1],
                )
                for ref in refs:
                    dates[(market, ref.code)] = loaded.get(ref.code, set())
        finally:
            conn.close()
    except Exception as exc:
        LOGGER.error("读取逐合约行情日期失败: %s", exc, exc_info=True)
        raise
    return dates


def _collect_gaps(
    refs: list[ContractRef],
    windows: dict[tuple[str, str], tuple[int, int]],
    calendar: list[date],
    actual_counts: dict[str, dict[str, int]],
    min_missing_days: int,
    unavailable: set[tuple[str, str, date]],
) -> tuple[list[ContractGap], dict[str, int]]:
    suspicious: list[ContractRef] = []
    for ref in refs:
        window = windows.get((ref.market, ref.code))
        if window is None:
            continue
        expected_days = window[1] - window[0]
        actual_days = actual_counts.get(ref.market, {}).get(ref.code, 0)
        if actual_days != expected_days:
            suspicious.append(ref)

    LOGGER.info(
        "逐合约检查: windows=%s suspicious=%s",
        len(windows),
        len(suspicious),
    )
    actual_dates = _load_dates_for_markets(suspicious, windows, calendar)

    gaps: list[ContractGap] = []
    below_threshold = 0
    out_of_window_only = 0
    previously_unavailable_days = 0
    for ref in suspicious:
        lower, upper = windows[(ref.market, ref.code)]
        present = actual_dates.get((ref.market, ref.code), set())
        missing = [trade_date for trade_date in calendar[lower:upper] if trade_date not in present]
        known_unavailable: list[date] = []
        if unavailable:
            known_unavailable = [
                trade_date
                for trade_date in missing
                if (ref.market, ref.code, trade_date) in unavailable
            ]
            previously_unavailable_days += len(known_unavailable)
            missing = [trade_date for trade_date in missing if trade_date not in known_unavailable]
        if not missing:
            if not known_unavailable:
                out_of_window_only += 1
            continue
        if len(missing) < max(1, min_missing_days):
            below_threshold += 1
            continue
        gaps.append(
            ContractGap(
                ref=ref,
                missing_dates=missing,
                expected_days=upper - lower,
            )
        )

    gaps.sort(key=lambda item: (-len(item.missing_dates), item.ref.market, item.ref.code))
    stats = {
        "suspicious_contracts": len(suspicious),
        "out_of_window_only": out_of_window_only,
        "below_threshold": below_threshold,
        "previously_unavailable_days": previously_unavailable_days,
    }
    return gaps, stats


def _repair_gaps(
    gaps: list[ContractGap],
    args: argparse.Namespace,
    report: dict[str, Any],
) -> tuple[set[tuple[str, date]], list[dict[str, Any]]]:
    repair_plan: dict[str, set[date]] = {}
    for gap in gaps:
        repair_plan.setdefault(gap.ref.market, set()).update(gap.missing_dates)

    pairs = sorted(
        (trade_date, market) for market, dates in repair_plan.items() for trade_date in dates
    )
    budget = max(0, args.max_repair_days)
    selected = pairs[:budget]
    attempted = {(market, trade_date) for trade_date, market in selected}
    report["repair_budget_exhausted"] = len(selected) < len(pairs)

    selected_by_market: dict[str, list[date]] = {}
    for trade_date, market in selected:
        selected_by_market.setdefault(market, []).append(trade_date)

    outcomes: list[dict[str, Any]] = []
    for market, dates in sorted(selected_by_market.items()):
        for chunk_start, chunk_end in group_dates(dates, max_span_days=args.chunk_days):
            outcome = fetch_daily_range(market, chunk_start, chunk_end)
            outcomes.append(outcome.as_dict())
            LOGGER.info(
                "%s 行情补齐 %s ~ %s: rows=%s saved=%s error=%s",
                market,
                chunk_start,
                chunk_end,
                outcome.rows,
                outcome.saved,
                outcome.error,
            )
            time.sleep(max(0.0, args.sleep_seconds))
    return attempted, outcomes


def _remaining_gaps(
    gaps: list[ContractGap],
    attempted: set[tuple[str, date]],
) -> tuple[
    int,
    list[tuple[ContractGap, list[date]]],
    list[dict[str, Any]],
]:
    if not attempted:
        entries = [(gap, list(gap.missing_dates)) for gap in gaps]
        return sum(len(dates) for _, dates in entries), entries, []

    affected: list[ContractGap] = [
        gap
        for gap in gaps
        if any((gap.ref.market, trade_date) in attempted for trade_date in gap.missing_dates)
    ]
    by_market: dict[str, list[ContractGap]] = {}
    for gap in affected:
        by_market.setdefault(gap.ref.market, []).append(gap)

    refreshed: dict[tuple[str, str], set[date]] = {}
    try:
        conn = connect()
        try:
            for market, market_gaps in by_market.items():
                attempted_dates = sorted(trade_date for m, trade_date in attempted if m == market)
                loaded = load_actual_dates(
                    conn,
                    market,
                    (gap.ref.code for gap in market_gaps),
                    attempted_dates[0],
                    attempted_dates[-1],
                )
                for gap in market_gaps:
                    refreshed[(market, gap.ref.code)] = loaded.get(gap.ref.code, set())
        finally:
            conn.close()
    except Exception as exc:
        LOGGER.warning("补齐后复核失败，按原始缺口报告: %s", exc)
        entries = [(gap, list(gap.missing_dates)) for gap in gaps]
        return sum(len(dates) for _, dates in entries), entries, []

    total_remaining = 0
    entries: list[tuple[ContractGap, list[date]]] = []
    sample: list[dict[str, Any]] = []
    for gap in gaps:
        present = refreshed.get((gap.ref.market, gap.ref.code))
        if present is None:
            remaining = list(gap.missing_dates)
        else:
            remaining = [
                trade_date
                for trade_date in gap.missing_dates
                if (gap.ref.market, trade_date) not in attempted or trade_date not in present
            ]
        total_remaining += len(remaining)
        if remaining:
            entries.append((gap, remaining))
            sample.append(
                {
                    "market": gap.ref.market,
                    "code": gap.ref.code,
                    "remaining_days": len(remaining),
                    "remaining_sample": [trade_date.isoformat() for trade_date in remaining[:10]],
                }
            )
    sample.sort(key=lambda item: -int(item["remaining_days"]))
    return total_remaining, entries, sample[:50]


def _confirmed_unavailable_dates(
    remaining_entries: list[tuple[ContractGap, list[date]]],
    fetch_outcomes: list[dict[str, Any]],
) -> list[tuple[str, str, date]]:
    """Return gaps covered by successful fetches where the market itself has bars."""
    successful_ranges: dict[str, list[tuple[date, date]]] = {}
    for outcome in fetch_outcomes:
        if not outcome.get("saved") or int(outcome.get("rows") or 0) <= 0:
            continue
        market = str(outcome["market"])
        covered = outcome.get("covered_ranges") or [[outcome["start"], outcome["end"]]]
        for range_start, range_end in covered:
            successful_ranges.setdefault(market, []).append(
                (date.fromisoformat(str(range_start)), date.fromisoformat(str(range_end)))
            )
    if not successful_ranges:
        return []

    market_dates: dict[str, set[date]] = {}
    conn = connect()
    try:
        for market, ranges in successful_ranges.items():
            observed: set[date] = set()
            for range_start, range_end in ranges:
                observed.update(load_market_dates(conn, market, range_start, range_end))
            market_dates[market] = observed
    finally:
        conn.close()

    confirmed: list[tuple[str, str, date]] = []
    for gap, dates in remaining_entries:
        observed = market_dates.get(gap.ref.market, set())
        confirmed.extend(
            (gap.ref.market, gap.ref.code, trade_date)
            for trade_date in dates
            if trade_date in observed
        )
    return confirmed


def main() -> int:
    args = build_parser().parse_args()
    setup_logging(args.verbose)
    as_of = resolve_as_of(args.as_of)
    try:
        markets = parse_markets(args.markets)
    except ValueError as exc:
        LOGGER.error("%s", exc)
        return 2
    symbols = None
    if args.symbols:
        symbols = {item.strip().upper() for item in args.symbols.split(",") if item.strip()}

    LOGGER.info("期货逐合约行情审计开始: as_of=%s markets=%s", as_of, ",".join(markets))
    report: dict[str, Any] = {
        "script": "audit_futures_daily_bars",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "markets": markets,
        "symbol_filter": sorted(symbols) if symbols else None,
        "repair_enabled": not args.no_repair,
    }

    try:
        conn = connect()
        try:
            calendar = load_calendar(conn, as_of)
            references = load_reference_contracts(conn)
            actual_counts = {market: load_actual_counts(conn, market, as_of) for market in markets}
        finally:
            conn.close()
    except Exception as exc:
        LOGGER.error("读取交易日历、合约基准或行情计数失败: %s", exc, exc_info=True)
        return 2

    if not calendar:
        LOGGER.error("TRADING_DAYS 中没有 <= %s 的交易日，无法审计", as_of)
        return 2

    refs = _selected_references(references, set(markets), symbols)
    windows = _expected_windows(refs, calendar, as_of)

    unavailable: set[tuple[str, str, date]] = set()
    if not args.retry_unavailable:
        try:
            conn = connect()
            try:
                unavailable = load_unavailable_dates(conn)
            finally:
                conn.close()
        except Exception as exc:
            LOGGER.warning("读取源端不可得记录失败: %s", exc)

    gaps, stats = _collect_gaps(
        refs,
        windows,
        calendar,
        actual_counts,
        args.min_missing_days,
        unavailable,
    )

    missing_contract_days = sum(len(gap.missing_dates) for gap in gaps)
    missing_market_days = len(
        {(gap.ref.market, trade_date) for gap in gaps for trade_date in gap.missing_dates}
    )
    market_summary: dict[str, dict[str, int]] = {}
    for gap in gaps:
        summary = market_summary.setdefault(gap.ref.market, {"contracts": 0, "missing_days": 0})
        summary["contracts"] += 1
        summary["missing_days"] += len(gap.missing_dates)

    report["checked_contracts"] = len(windows)
    report["contracts_with_gaps"] = len(gaps)
    report["missing_contract_days"] = missing_contract_days
    report["missing_market_days"] = missing_market_days
    report["market_summary"] = market_summary
    report.update(stats)
    report["gap_sample"] = [
        {
            "market": gap.ref.market,
            "code": gap.ref.code,
            "expected_days": gap.expected_days,
            "missing_days": len(gap.missing_dates),
            "missing_sample": [trade_date.isoformat() for trade_date in gap.missing_dates[:10]],
        }
        for gap in gaps[:50]
    ]

    attempted: set[tuple[str, date]] = set()
    if gaps and not args.no_repair:
        attempted, outcomes = _repair_gaps(gaps, args, report)
        report["fetch_outcomes"] = outcomes
    else:
        report["fetch_outcomes"] = []

    remaining_days, remaining_entries, remaining_sample = _remaining_gaps(gaps, attempted)
    newly_unavailable: list[tuple[str, str, date]] = []
    if remaining_entries and report["fetch_outcomes"]:
        try:
            newly_unavailable = _confirmed_unavailable_dates(
                remaining_entries,
                report["fetch_outcomes"],
            )
        except Exception as exc:
            LOGGER.warning("归类源端不可得日期失败: %s", exc)
        if newly_unavailable:
            try:
                conn = connect()
                try:
                    recorded = record_unavailable_dates(
                        conn,
                        newly_unavailable,
                        "source_no_contract_rows",
                    )
                finally:
                    conn.close()
                LOGGER.info("记录源端不可得合约日期 %s 条", recorded)
            except Exception as exc:
                LOGGER.warning("写入源端不可得记录失败: %s", exc)

    remaining_days = max(0, remaining_days - len(newly_unavailable))
    previously_unavailable = int(stats.get("previously_unavailable_days", 0))
    report["attempted_market_days"] = len(attempted)
    report["previously_unavailable_contract_days"] = previously_unavailable
    report["newly_unavailable_contract_days"] = len(newly_unavailable)
    report["unavailable_contract_days"] = previously_unavailable + len(newly_unavailable)
    report["remaining_contract_days"] = remaining_days
    report["remaining_sample"] = remaining_sample
    report["summary"] = {
        "missing_contract_days": missing_contract_days,
        "remaining_contract_days": remaining_days,
        "unavailable_contract_days": previously_unavailable + len(newly_unavailable),
        "complete": remaining_days == 0,
    }

    report_path = write_report(report, args.report_dir, "audit_futures_daily_bars")
    LOGGER.info(
        "逐合约行情审计完成: checked=%s gaps=%s missing=%s unavailable=%s remaining=%s report=%s",
        len(windows),
        len(gaps),
        missing_contract_days,
        previously_unavailable + len(newly_unavailable),
        remaining_days,
        report_path,
    )
    return 0 if remaining_days == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
