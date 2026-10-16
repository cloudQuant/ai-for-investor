"""Executable AFI10 checks for retiring the AI live raw-ZMQ order path."""

import asyncio
from pathlib import Path

import pytest

from app.schemas.ai_trading import AITradingRequest, TradeAction, TradingIntent
from app.services.ai_trading_service import AITradingService
from app.services.direct_order_service import DirectOrderService


@pytest.mark.parametrize(
    "action",
    [TradeAction.BUY, TradeAction.SELL, TradeAction.CLOSE, TradeAction.QUERY],
)
@pytest.mark.parametrize("gateway_id", [None, "manual:CTP:legacy-account"])
def test_ai_live_actions_fail_closed_without_service_v2_scope(action, gateway_id):
    service = AITradingService()
    intent = TradingIntent(
        action=action,
        symbol="rb2610",
        quantity=1,
        confidence=0.9,
    )
    request = AITradingRequest(
        message="买入一手螺纹钢",
        dry_run=False,
        gateway_id=gateway_id,
    )

    result = asyncio.run(
        service._execute_trade(
            "user-1",
            intent,
            request,
        )
    )

    assert result["success"] is False
    assert result["error"] == "service_v2_unavailable"
    assert result["reason"] == "service_v2_scope_not_configured"
    assert result["submitted"] is False
    assert "service-v2" in result["message"]
    assert "未提交" in result["message"]


def test_direct_order_service_has_no_legacy_live_transport_or_order_domain():
    backend = Path(__file__).resolve().parents[1]
    direct_source = (backend / "app/services/direct_order_service.py").read_text(
        encoding="utf-8"
    )
    ai_source = (backend / "app/services/ai_trading_service.py").read_text(encoding="utf-8")

    assert not hasattr(DirectOrderService, "execute_live_trade")
    for retired_name in (
        "_get_gateway_command_endpoint",
        "_send_gateway_command",
        "_query_live_positions",
        "_close_live_position",
        "_build_order_payload",
    ):
        assert not hasattr(DirectOrderService, retired_name)

    for retired_token in (
        "import zmq",
        "place_order",
        "get_positions",
        "_send_gateway_command",
        "_get_gateway_command_endpoint",
    ):
        assert retired_token not in direct_source

    assert "execute_live_trade(" not in ai_source
