#!/usr/bin/env python3
"""Audit the futures contract universe and backfill contracts with no bars.

Step 2 of the futures daily-data audit. It refreshes the existing
``FUTURES_CONTRACT_INFO_*`` reference tables, compares their contracts with
``FUTURES_DAILY_MARKET``, and fetches date windows for contracts that have no
daily rows at all.

Exit codes: 0 = no missing contracts remain, 1 = gaps remain, 2 = fatal error.
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
    ContractRef,
    add_common_arguments,
    connect,
    fetch_daily_range,
    load_daily_codes,
    load_reference_contracts,
    parse_markets,
    resolve_as_of,
    setup_logging,
    write_report,
)

from app.data_fetch.scripts.futures.weekly.dce_contract_info import FuturesContractInfoDce
from app.data_fetch.scripts.futures.weekly.futures_contract_info_cffex import (
    FuturesContractInfoCffex,
)
from app.data_fetch.scripts.futures.weekly.futures_contract_info_czce import (
    FuturesContractInfoCzce,
)
from app.data_fetch.scripts.futures.weekly.futures_contract_info_ine import (
    FuturesContractInfoIne,
)
from app.data_fetch.scripts.futures.weekly.futures_contract_info_shfe import (
    FuturesContractInfoShfe,
)
from app.data_fetch.scripts.futures.weekly.gfex_contract_info import FuturesContractInfoGfex

DATE_ITERATING_UPDATERS = {
    "CFFEX": FuturesContractInfoCffex,
    "CZCE": FuturesContractInfoCzce,
    "INE": FuturesContractInfoIne,
    "SHFE": FuturesContractInfoShfe,
}
SNAPSHOT_UPDATERS = {
    "DCE": FuturesContractInfoDce,
    "GFEX": FuturesContractInfoGfex,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check futures contract coverage and backfill missing contracts."
    )
    add_common_arguments(parser, chunk_days=30, max_repair_days=500)
    parser.add_argument(
        "--no-refresh-reference",
        action="store_true",
        help="use existing FUTURES_CONTRACT_INFO_* tables without refreshing them",
    )
    parser.add_argument(
        "--refresh-reference-days",
        type=int,
        default=3,
        help="recent trading days to refresh per date-iterating exchange (default: 3)",
    )
    parser.add_argument(
        "--max-repair-contracts",
        type=int,
        default=10,
        help="maximum missing contracts to fetch in this run (default: 10)",
    )
    return parser


def _refresh_reference(
    markets: list[str],
    refresh_days: int,
    sleep_seconds: float,
    report: dict[str, Any],
) -> None:
    refresh_results: dict[str, Any] = {}
    for market in markets:
        started = time.monotonic()
        try:
            if market in DATE_ITERATING_UPDATERS:
                updater = DATE_ITERATING_UPDATERS[market](
                    logger=logging.getLogger(f"futures_data_audit.contract_info.{market}")
                )
                updater.run(
                    lookback_days=max(1, refresh_days),
                    max_days=max(1, refresh_days),
                    sleep_seconds=max(0.0, min(sleep_seconds, 1.0)),
                )
            else:
                updater = SNAPSHOT_UPDATERS[market](
                    logger=logging.getLogger(f"futures_data_audit.contract_info.{market}")
                )
                updater.run()
            refresh_results[market] = {
                "status": "ok",
                "seconds": round(time.monotonic() - started, 1),
            }
            LOGGER.info("%s 合约基准刷新完成", market)
        except Exception as exc:
            refresh_results[market] = {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "seconds": round(time.monotonic() - started, 1),
            }
            LOGGER.warning("%s 合约基准刷新失败，继续使用现有数据: %s", market, exc)
    report["reference_refresh"] = refresh_results


def _contract_window(
    ref: ContractRef, as_of: date, start_date: date | None
) -> tuple[date, date] | None:
    if ref.listing_date is None or ref.expiry_date is None:
        return None
    window_start = max(ref.listing_date, DEFAULT_MARKET_START[ref.market])
    if start_date is not None:
        window_start = max(window_start, start_date)
    window_end = min(ref.expiry_date, as_of)
    if window_start > window_end:
        return None
    return window_start, window_end


def _merge_windows(
    entries: list[tuple[date, date, str]],
) -> list[tuple[date, date, set[str]]]:
    merged: list[list[Any]] = []
    for window_start, window_end, code in sorted(entries, key=lambda item: item[0]):
        if not merged or window_start > merged[-1][1] + timedelta(days=1):
            merged.append([window_start, window_end, {code}])
            continue
        merged[-1][1] = max(merged[-1][1], window_end)
        merged[-1][2].add(code)
    return [(item[0], item[1], item[2]) for item in merged]


def _repair_missing(
    opportunities: list[tuple[ContractRef, date, date]],
    args: argparse.Namespace,
    report: dict[str, Any],
) -> None:
    by_market: dict[str, list[tuple[date, date, str]]] = {}
    for ref, window_start, window_end in opportunities:
        by_market.setdefault(ref.market, []).append((window_start, window_end, ref.code))

    outcomes: list[dict[str, Any]] = []
    budget = max(0, args.max_repair_days)
    budget_exhausted = False
    for market, entries in sorted(by_market.items()):
        for merged_start, merged_end, _codes in _merge_windows(entries):
            cursor = merged_start
            while cursor <= merged_end and budget > 0:
                chunk_end = min(
                    cursor + timedelta(days=max(1, args.chunk_days) - 1),
                    merged_end,
                )
                span = (chunk_end - cursor).days + 1
                if span > budget:
                    chunk_end = cursor + timedelta(days=budget - 1)
                    span = budget
                targets = {
                    entry_code
                    for entry_start, entry_end, entry_code in entries
                    if entry_start <= chunk_end and entry_end >= cursor
                }
                if targets:
                    outcome = fetch_daily_range(market, cursor, chunk_end, target_codes=targets)
                    outcomes.append(outcome.as_dict())
                    LOGGER.info(
                        "%s 合约补齐 %s ~ %s: targets=%s rows=%s saved=%s error=%s",
                        market,
                        cursor,
                        chunk_end,
                        len(targets),
                        outcome.rows,
                        outcome.saved,
                        outcome.error,
                    )
                    time.sleep(max(0.0, args.sleep_seconds))
                budget -= span
                cursor = chunk_end + timedelta(days=1)
            if cursor <= merged_end and budget <= 0:
                budget_exhausted = True

    report["contract_fetch_outcomes"] = outcomes
    report["repair_budget_exhausted"] = budget_exhausted
    if budget_exhausted:
        LOGGER.warning(
            "补齐预算已用尽（max_repair_days=%s），剩余合约将在下次运行继续检查",
            args.max_repair_days,
        )


def main() -> int:
    args = build_parser().parse_args()
    setup_logging(args.verbose)
    as_of = resolve_as_of(args.as_of)
    try:
        markets = parse_markets(args.markets)
    except ValueError as exc:
        LOGGER.error("%s", exc)
        return 2

    LOGGER.info("期货合约审计开始: as_of=%s markets=%s", as_of, ",".join(markets))
    report: dict[str, Any] = {
        "script": "audit_futures_daily_contracts",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "markets": markets,
        "repair_enabled": not args.no_repair,
    }

    if not args.no_refresh_reference:
        _refresh_reference(
            markets,
            max(1, args.refresh_reference_days),
            args.sleep_seconds,
            report,
        )
    else:
        report["reference_refresh"] = "skipped"

    try:
        conn = connect()
        try:
            references = load_reference_contracts(conn)
            daily_codes = load_daily_codes(conn)
        finally:
            conn.close()
    except Exception as exc:
        LOGGER.error("读取合约基准或行情合约失败: %s", exc, exc_info=True)
        return 2

    market_set = set(markets)
    references = {key: ref for key, ref in references.items() if ref.market in market_set}
    missing = sorted(
        (ref for ref in references.values() if ref.code not in daily_codes),
        key=lambda ref: (ref.market, ref.listing_date or date.max, ref.code),
    )

    report["reference_contracts"] = len(references)
    report["missing_contracts"] = len(missing)
    report["missing_sample"] = [
        {
            "market": ref.market,
            "code": ref.code,
            "listing_date": ref.listing_date.isoformat() if ref.listing_date else None,
            "expiry_date": ref.expiry_date.isoformat() if ref.expiry_date else None,
        }
        for ref in missing[:50]
    ]

    opportunities: list[tuple[ContractRef, date, date]] = []
    unrepairable: list[dict[str, Any]] = []
    for ref in missing:
        window = _contract_window(ref, as_of, args.start_date)
        if window is None:
            unrepairable.append(
                {
                    "market": ref.market,
                    "code": ref.code,
                    "reason": "missing or invalid listing/expiry window",
                }
            )
            continue
        opportunities.append((ref, window[0], window[1]))

    report["repairable_contracts"] = len(opportunities)
    report["unrepairable_contracts"] = unrepairable[:50]
    limited = opportunities[: max(0, args.max_repair_contracts)]
    if len(opportunities) > len(limited):
        report["repair_contract_limit"] = len(limited)
        LOGGER.warning(
            "本次只补齐 %s/%s 个缺失合约，可用 --max-repair-contracts 调整",
            len(limited),
            len(opportunities),
        )

    if limited and not args.no_repair:
        _repair_missing(limited, args, report)
    elif limited:
        report["contract_fetch_outcomes"] = []

    try:
        conn = connect()
        try:
            daily_codes_after = load_daily_codes(conn)
        finally:
            conn.close()
    except Exception as exc:
        LOGGER.warning("补齐后复核失败: %s", exc)
        daily_codes_after = daily_codes

    remaining = [ref for ref in missing if ref.code not in daily_codes_after]
    report["remaining_contracts"] = len(remaining)
    report["remaining_sample"] = [
        {"market": ref.market, "code": ref.code} for ref in remaining[:50]
    ]
    report["summary"] = {
        "missing_contracts": len(missing),
        "remaining_contracts": len(remaining),
        "complete": len(remaining) == 0,
    }

    report_path = write_report(report, args.report_dir, "audit_futures_daily_contracts")
    LOGGER.info(
        "合约审计完成: reference=%s missing=%s remaining=%s report=%s",
        len(references),
        len(missing),
        len(remaining),
        report_path,
    )
    return 0 if not remaining else 1


if __name__ == "__main__":
    sys.exit(main())
