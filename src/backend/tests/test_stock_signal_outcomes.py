"""Forward-return and performance denominator regression coverage."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.stock_signal import StockSignalPrediction
from app.services.stock_signal.outcomes import evaluate_outcome
from app.services.stock_signal.performance import build_performance_summary


def _rows(*, base: float, step: float, count: int = 25) -> list[dict[str, float | str]]:
    first_day = date(2026, 4, 1)
    return [
        {
            "date": (first_day + timedelta(days=index)).isoformat(),
            "open": base + step * index,
            "high": base + step * index + 0.2,
            "low": base + step * index - 0.2,
            "close": base + step * index + 0.05,
            "volume": 1000,
        }
        for index in range(count)
    ]


def _record(action: str, evaluation: object | None = None) -> StockSignalPrediction:
    record = StockSignalPrediction(
        prediction_key=f"key-{action}-{id(evaluation)}",
        owner_scope="system",
        source="nightly_sse50",
        universe_code="SSE50",
        symbol="600000.SH",
        market_type="A股",
        as_of_date=date(2026, 3, 31),
        as_of_at=datetime.now(timezone.utc),
        available_at=datetime.now(timezone.utc),
        next_trading_date=date(2026, 4, 1),
        signal_action=action,
        confidence_score=0.75,
        risk_score=0.3,
        eligibility_status="eligible",
        quality_reasons_json=[],
        data_freshness_json={},
        feature_version="ohlcv-v1",
        decision_policy_version="baseline-v1",
        model_version="deterministic-shadow-v1",
        feature_snapshot_json={},
        policy_snapshot_json={
            "round_trip_cost_bps": 20,
            "buy_success_threshold_bps": 30,
            "sell_success_threshold_bps": 30,
        },
        source_snapshot_hash="a" * 64,
        outcome_status="pending",
    )
    return record


def test_outcome_uses_next_open_and_marks_buy_success_only_after_20_sessions() -> None:
    evaluation = evaluate_outcome(
        prediction_action="BUY",
        next_trading_date=date(2026, 4, 1),
        price_rows=_rows(base=10.0, step=0.1),
        benchmark_rows=_rows(base=100.0, step=0.01),
        policy_snapshot={
            "round_trip_cost_bps": 20,
            "buy_success_threshold_bps": 30,
            "sell_success_threshold_bps": 30,
        },
    )

    assert evaluation.status == "scored"
    assert evaluation.entry_price == 10.0
    assert evaluation.horizon_returns[20] is not None and evaluation.horizon_returns[20] > 0
    assert evaluation.buy_is_correct_20d is True
    assert evaluation.sell_is_correct_20d is None


def test_watch_is_never_part_of_actioned_success_rate() -> None:
    buy = _record("BUY")
    buy.outcome_status = "scored"
    buy.horizon_20d_return = 0.08
    buy.buy_is_correct_20d = True
    sell = _record("SELL")
    sell.outcome_status = "scored"
    sell.horizon_20d_return = 0.06
    sell.sell_is_correct_20d = False
    watch = _record("WATCH")
    watch.outcome_status = "scored"
    watch.horizon_20d_return = 0.2

    summary = build_performance_summary([buy, sell, watch], symbol="600000.SH")

    assert summary["actioned_generated_count"] == 2
    assert summary["actioned_scorable_count"] == 2
    assert summary["actioned_success_count"] == 1
    assert summary["actioned_success_rate"] == 0.5


@pytest.mark.parametrize("threshold", [-100.0, float("-inf"), "-inf", 10**400])
def test_non_finite_or_invalid_success_thresholds_do_not_create_profit(threshold: object) -> None:
    buy = _record("BUY")
    buy.horizon_20d_return = -0.001
    buy.policy_snapshot_json["buy_success_threshold_bps"] = threshold
    sell = _record("SELL")
    sell.horizon_20d_return = 0.001
    sell.policy_snapshot_json["sell_success_threshold_bps"] = threshold

    summary = build_performance_summary([buy, sell], symbol="600000.SH")
    actions = {action["action"]: action for action in summary["actions"]}

    assert actions["BUY"]["scorable_count"] == 1
    assert actions["BUY"]["success_count"] == 0
    assert actions["SELL"]["scorable_count"] == 1
    assert actions["SELL"]["success_count"] == 0
