"""Forward-only market-outcome evaluation for stored predictions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal


BenchmarkStatus = Literal["available", "unknown"]
BENCHMARK_UNKNOWN_REASON = "benchmark_20d_return_not_recorded"


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) and numeric > 0 else None


def normalize_benchmark_20d_return(value: Any) -> float | None:
    """Return a finite 20-day benchmark value suitable for JSON output."""
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def benchmark_status_for_20d_return(value: Any) -> tuple[BenchmarkStatus, str | None]:
    """Describe stored 20-day value presence without asserting provider provenance."""
    if normalize_benchmark_20d_return(value) is None:
        return "unknown", BENCHMARK_UNKNOWN_REASON
    return "available", None


@dataclass(frozen=True)
class OutcomeEvaluation:
    """A non-destructive outcome update prepared from future market data."""

    status: str
    reason: str | None
    entry_date: date | None
    entry_price: float | None
    horizon_returns: dict[int, float | None]
    benchmark_returns: dict[int, float | None]
    excess_returns: dict[int, float | None]
    buy_is_correct_20d: bool | None
    sell_is_correct_20d: bool | None
    benchmark_status: BenchmarkStatus = "unknown"
    benchmark_status_reason: str | None = BENCHMARK_UNKNOWN_REASON


def _row_index(rows: list[dict[str, Any]], target: date) -> int | None:
    for index, row in enumerate(rows):
        if _parse_date(row.get("date")) == target:
            return index
    return None


def _return_at(
    *,
    rows: list[dict[str, Any]],
    entry_index: int,
    entry_price: float,
    horizon: int,
    cost: float,
) -> float | None:
    target_index = entry_index + horizon - 1
    if target_index >= len(rows):
        return None
    close = _number(rows[target_index].get("close"))
    if close is None:
        return None
    result = close / entry_price - 1.0 - cost
    return result if math.isfinite(result) else None


def _benchmark_return_at(
    *,
    benchmark_rows: list[dict[str, Any]],
    entry_date: date,
    horizon_date: date,
) -> float | None:
    entry_index = _row_index(benchmark_rows, entry_date)
    target_index = _row_index(benchmark_rows, horizon_date)
    if entry_index is None or target_index is None:
        return None
    entry_open = _number(benchmark_rows[entry_index].get("open"))
    target_close = _number(benchmark_rows[target_index].get("close"))
    if entry_open is None or target_close is None:
        return None
    result = target_close / entry_open - 1.0
    return result if math.isfinite(result) else None


def evaluate_outcome(
    *,
    prediction_action: str,
    next_trading_date: date | None,
    price_rows: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]],
    policy_snapshot: dict[str, Any],
) -> OutcomeEvaluation:
    """Evaluate only post-prediction rows; missing data remains unscorable or pending."""
    normalized_rows = sorted(
        [row for row in price_rows if isinstance(row, dict) and _parse_date(row.get("date"))],
        key=lambda row: str(row.get("date")),
    )
    if next_trading_date is None:
        return OutcomeEvaluation(
            "pending", "next_trading_date_unavailable", None, None, {}, {}, {}, None, None
        )
    entry_index = _row_index(normalized_rows, next_trading_date)
    if entry_index is None:
        return OutcomeEvaluation(
            "pending", "entry_session_not_available", None, None, {}, {}, {}, None, None
        )
    entry_price = _number(normalized_rows[entry_index].get("open"))
    if entry_price is None:
        return OutcomeEvaluation(
            "unscorable", "entry_open_unavailable", next_trading_date, None, {}, {}, {}, None, None
        )

    try:
        cost = max(0.0, float(policy_snapshot.get("round_trip_cost_bps", 0.0))) / 10000.0
    except (TypeError, ValueError):
        cost = 0.0
    horizon_returns: dict[int, float | None] = {}
    benchmark_returns: dict[int, float | None] = {}
    excess_returns: dict[int, float | None] = {}
    for horizon in (1, 5, 20):
        result = _return_at(
            rows=normalized_rows,
            entry_index=entry_index,
            entry_price=entry_price,
            horizon=horizon,
            cost=cost,
        )
        horizon_returns[horizon] = result
        target_index = entry_index + horizon - 1
        target_date = (
            _parse_date(normalized_rows[target_index].get("date"))
            if target_index < len(normalized_rows)
            else None
        )
        benchmark = (
            _benchmark_return_at(
                benchmark_rows=benchmark_rows,
                entry_date=next_trading_date,
                horizon_date=target_date,
            )
            if target_date is not None
            else None
        )
        benchmark_returns[horizon] = benchmark
        excess_returns[horizon] = (
            result - benchmark if result is not None and benchmark is not None else None
        )

    benchmark_status, benchmark_status_reason = benchmark_status_for_20d_return(
        benchmark_returns[20]
    )

    if all(value is None for value in horizon_returns.values()):
        return OutcomeEvaluation(
            "unscorable",
            "exit_close_unavailable",
            next_trading_date,
            entry_price,
            horizon_returns,
            benchmark_returns,
            excess_returns,
            None,
            None,
            benchmark_status,
            benchmark_status_reason,
        )
    status = "scored" if horizon_returns[20] is not None else "partial"
    buy_correct: bool | None = None
    sell_correct: bool | None = None
    if horizon_returns[20] is not None:
        try:
            buy_threshold = float(policy_snapshot.get("buy_success_threshold_bps", 0.0)) / 10000.0
        except (TypeError, ValueError):
            buy_threshold = 0.0
        try:
            sell_threshold = float(policy_snapshot.get("sell_success_threshold_bps", 0.0)) / 10000.0
        except (TypeError, ValueError):
            sell_threshold = 0.0
        if prediction_action == "BUY":
            buy_correct = horizon_returns[20] > buy_threshold
        elif prediction_action == "SELL":
            sell_correct = horizon_returns[20] < -sell_threshold
    return OutcomeEvaluation(
        status,
        None,
        next_trading_date,
        entry_price,
        horizon_returns,
        benchmark_returns,
        excess_returns,
        buy_correct,
        sell_correct,
        benchmark_status,
        benchmark_status_reason,
    )
