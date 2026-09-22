"""Fail-closed tests for alert-evaluation input type boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.alert_evaluation import (
    _check_cross_trigger,
    check_trigger,
    get_current_metric_value,
)


@pytest.mark.asyncio
async def test_non_mapping_trigger_config_skips_metric_lookup() -> None:
    rule = SimpleNamespace(trigger_type="threshold", trigger_config=["invalid"])
    get_metric = AsyncMock(return_value=10.0)

    assert await check_trigger(rule, {}, get_metric) is False
    get_metric.assert_not_awaited()


@pytest.mark.asyncio
async def test_cross_with_none_value_fails_closed_without_state_change() -> None:
    rule = SimpleNamespace(id="rule-1")
    state: dict[str, object] = {}

    assert await _check_cross_trigger(rule, {"value1": None, "value2": 5.0}, state) is False
    assert state == {}


@pytest.mark.asyncio
async def test_current_value_none_fails_closed() -> None:
    rule = SimpleNamespace(alert_type="account")

    result = await get_current_metric_value(
        rule,
        {"current_value": None},
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
    )

    assert result is None


@pytest.mark.asyncio
async def test_invalid_alert_type_fails_closed_before_fallback_or_service_calls() -> None:
    rule = SimpleNamespace(alert_type="not-an-alert-type")
    paper_service = AsyncMock()
    live_service = AsyncMock()
    backtest_service = AsyncMock()

    result = await get_current_metric_value(
        rule,
        {"current_value": 42.0},
        paper_service,
        live_service,
        backtest_service,
    )

    assert result is None
    paper_service.assert_not_awaited()
    live_service.assert_not_awaited()
    backtest_service.assert_not_awaited()
