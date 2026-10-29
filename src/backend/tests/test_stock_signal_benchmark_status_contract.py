"""Benchmark visibility stays separate from each stock's realized outcome."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse

from app.schemas.stock_signal import StockSignalRecordResponse
from app.services.stock_signal.outcomes import (
    BENCHMARK_UNKNOWN_REASON,
    benchmark_status_for_20d_return,
    evaluate_outcome,
)
from app.services.stock_signal.service import StockSignalService


def _rows(*, base: float, step: float, count: int = 25) -> list[dict[str, float | str]]:
    first_day = date(2026, 7, 1)
    return [
        {
            "date": (first_day + timedelta(days=index)).isoformat(),
            "open": base + step * index,
            "close": base + step * index + step / 2,
        }
        for index in range(count)
    ]


def _record(*, benchmark_20d_return: float | None) -> SimpleNamespace:
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return SimpleNamespace(
        id="prediction-id",
        source="nightly_sse50",
        universe_code="SSE50",
        symbol="600000.SH",
        symbol_name="测试股份",
        market_type="A股",
        as_of_date=date(2026, 6, 30),
        available_at=now,
        next_trading_date=date(2026, 7, 1),
        signal_action="BUY",
        confidence_score=0.75,
        risk_score=0.25,
        expected_excess_return=0.01,
        eligibility_status="eligible",
        quality_reasons_json=[],
        feature_version="ohlcv-v1",
        decision_policy_version="baseline-v1",
        model_version="deterministic-shadow-v1",
        outcome_status="scored",
        outcome_reason=None,
        entry_date=date(2026, 7, 1),
        entry_price=10.0,
        horizon_1d_return=0.01,
        horizon_5d_return=0.02,
        horizon_20d_return=0.03,
        benchmark_20d_return=benchmark_20d_return,
        excess_20d_return=(
            0.01 if benchmark_20d_return is not None else None
        ),
        buy_is_correct_20d=True,
        sell_is_correct_20d=None,
    )


def test_missing_benchmark_does_not_replace_a_scored_stock_outcome() -> None:
    evaluation = evaluate_outcome(
        prediction_action="BUY",
        next_trading_date=date(2026, 7, 1),
        price_rows=_rows(base=10.0, step=0.1),
        benchmark_rows=[],
        policy_snapshot={"round_trip_cost_bps": 20, "buy_success_threshold_bps": 0},
    )

    assert evaluation.status == "scored"
    assert evaluation.horizon_returns[20] is not None
    assert evaluation.benchmark_returns[20] is None
    assert evaluation.excess_returns[20] is None
    assert evaluation.benchmark_status == "unknown"
    assert evaluation.benchmark_status_reason == BENCHMARK_UNKNOWN_REASON


def test_available_twenty_day_benchmark_is_classified_independently() -> None:
    evaluation = evaluate_outcome(
        prediction_action="BUY",
        next_trading_date=date(2026, 7, 1),
        price_rows=_rows(base=10.0, step=0.1),
        benchmark_rows=_rows(base=100.0, step=1.0),
        policy_snapshot={},
    )

    assert evaluation.status == "scored"
    assert evaluation.benchmark_returns[20] is not None
    assert evaluation.benchmark_status == "available"
    assert evaluation.benchmark_status_reason is None


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True, "invalid"])
def test_missing_or_invalid_twenty_day_value_remains_unknown(value: object) -> None:
    assert benchmark_status_for_20d_return(value) == (
        "unknown",
        BENCHMARK_UNKNOWN_REASON,
    )


def test_history_response_classifies_legacy_null_as_unknown_without_losing_stock_status() -> None:
    payload = StockSignalService.record_payload(_record(benchmark_20d_return=None))
    response = StockSignalRecordResponse(**payload)

    assert response.outcome_status == "scored"
    assert response.horizon_20d_return == 0.03
    assert response.benchmark_20d_return is None
    assert response.benchmark_status == "unknown"
    assert response.benchmark_status_reason == BENCHMARK_UNKNOWN_REASON

    legacy_payload = dict(payload)
    legacy_payload.pop("benchmark_status")
    legacy_payload.pop("benchmark_status_reason")
    legacy_response = StockSignalRecordResponse(**legacy_payload)
    assert legacy_response.benchmark_status == "unknown"
    assert legacy_response.benchmark_status_reason == BENCHMARK_UNKNOWN_REASON


def test_history_response_classifies_a_valid_persisted_twenty_day_value_as_available() -> None:
    payload = StockSignalService.record_payload(_record(benchmark_20d_return=0.015))
    response = StockSignalRecordResponse(**payload)

    assert response.outcome_status == "scored"
    assert response.benchmark_status == "available"
    assert response.benchmark_status_reason is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_legacy_benchmark_value_serializes_as_json_null(value: float) -> None:
    payload = StockSignalService.record_payload(_record(benchmark_20d_return=value))
    response = StockSignalRecordResponse(**payload)
    serialized = JSONResponse(content=response.model_dump(mode="json")).body
    decoded = json.loads(serialized)

    assert decoded["benchmark_20d_return"] is None
    assert decoded["benchmark_status"] == "unknown"
    assert decoded["benchmark_status_reason"] == "benchmark_20d_return_not_recorded"
