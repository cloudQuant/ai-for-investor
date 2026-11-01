"""Tests for DirectOrderService - managed-paper execution bridge.

Live AI order submission is unavailable until an authorized service-v2 scope is
configured; AI paper orders are submitted through ``ManagedPaperOrderAdapter``.
These tests pin that boundary and the safe success/error mapping around it.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.ai_trading import OrderType, TradeAction, TradingIntent
from app.services.direct_order_service import DirectOrderService
from app.services.managed_paper_adapter import ManagedPaperOrderError


def _intent(**overrides):
    values = {
        "action": TradeAction.BUY,
        "symbol": "rb2501",
        "quantity": 10,
        "order_type": OrderType.MARKET,
        "confidence": 0.9,
    }
    values.update(overrides)
    return TradingIntent(**values)


def _adapter(*, result=None, error=None):
    """Return a patched-capable adapter double with one recorded submit call."""

    adapter = MagicMock()
    if error is not None:
        adapter.submit_ai = AsyncMock(side_effect=error)
    else:
        adapter.submit_ai = AsyncMock(return_value=result or {})
    return adapter


async def _execute(adapter, intent, *, operation_id="trade-1", account_id="acct-1"):
    with patch(
        "app.services.managed_paper_adapter.ManagedPaperOrderAdapter",
        return_value=adapter,
    ):
        return await DirectOrderService().execute_paper_trade(
            intent,
            user_id="user1",
            account_id=account_id,
            operation_id=operation_id,
        )


class TestDirectOrderServicePaperTrade:
    """Test managed paper trade execution."""

    @pytest.mark.asyncio
    async def test_query_action(self):
        """QUERY is not supported by managed execution and fails closed."""
        adapter = _adapter(
            error=ManagedPaperOrderError("UNSUPPORTED_PAPER_ACTION", status_code=422)
        )

        result = await _execute(adapter, _intent(action=TradeAction.QUERY))

        assert result["success"] is False
        assert result["error"] == "UNSUPPORTED_PAPER_ACTION"
        assert "暂不支持该交易动作" in result["message"]

    @pytest.mark.asyncio
    async def test_query_action_uses_paper_service_limit_offset_signature(self):
        """QUERY never falls back to the retired legacy PaperTradingService."""
        adapter = _adapter(
            error=ManagedPaperOrderError("UNSUPPORTED_PAPER_ACTION", status_code=422)
        )

        with patch("app.services.paper_trading_service.PaperTradingService") as legacy:
            result = await _execute(adapter, _intent(action=TradeAction.QUERY))

        assert result["success"] is False
        legacy.assert_not_called()
        adapter.submit_ai.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_query_action_reports_paper_position_query_error(self):
        """Unexpected adapter failures are reported without provider text."""
        adapter = _adapter(error=RuntimeError("paper db unavailable"))

        result = await _execute(adapter, _intent(action=TradeAction.QUERY))

        assert result["success"] is False
        assert result["error"] == "RuntimeError"
        assert "paper db unavailable" not in result["message"]
        assert "paper db unavailable" not in str(result)

    @pytest.mark.asyncio
    async def test_unsupported_action(self):
        """Unsupported actions return the stable managed error code."""
        adapter = _adapter(
            error=ManagedPaperOrderError("UNSUPPORTED_PAPER_ACTION", status_code=422)
        )

        result = await _execute(adapter, _intent(action=TradeAction.CANCEL))

        assert result["success"] is False
        assert result["error"] == "UNSUPPORTED_PAPER_ACTION"
        adapter.submit_ai.assert_awaited_once_with(
            subject="user1",
            legacy_account_id="acct-1",
            intent=_intent(action=TradeAction.CANCEL),
            trade_id="trade-1",
        )

    @pytest.mark.asyncio
    async def test_buy_order_success(self):
        """An acknowledged managed buy is a successful dispatch."""
        adapter = _adapter(result={"intent_id": "intent-buy", "state": "ACKED"})

        result = await _execute(adapter, _intent())

        assert result["success"] is True
        assert result["type"] == "managed_paper_trade"
        assert (
            result["message"] == "managed paper order accepted and awaiting completion: intent-buy"
        )

    @pytest.mark.asyncio
    async def test_fractional_paper_quantity_is_preserved(self):
        """Managed paper trades must not truncate fractional crypto quantities."""
        intent = _intent(symbol="BTC/USDT", quantity=0.25)
        adapter = _adapter(result={"intent_id": "intent-frac", "state": "FILLED"})

        result = await _execute(adapter, intent)

        assert result["success"] is True
        submitted = adapter.submit_ai.await_args.kwargs["intent"]
        assert submitted.quantity == pytest.approx(0.25)
        assert submitted.symbol == "BTC/USDT"

    @pytest.mark.asyncio
    async def test_sell_order_success(self):
        """A filled managed sell is a successful dispatch."""
        adapter = _adapter(result={"intent_id": "intent-sell", "state": "FILLED"})

        result = await _execute(adapter, _intent(action=TradeAction.SELL, symbol="BTCUSDT"))

        assert result["success"] is True
        assert result["message"] == "managed paper order filled: intent-sell"

    @pytest.mark.asyncio
    async def test_value_error_handled(self):
        """A cutover denial is mapped to its operator-facing message."""
        adapter = _adapter(
            error=ManagedPaperOrderError("LEGACY_PAPER_CUTOVER_NOT_READY", status_code=409)
        )

        result = await _execute(adapter, _intent())

        assert result["success"] is False
        assert result["error"] == "LEGACY_PAPER_CUTOVER_NOT_READY"
        assert "未迁移状态" in result["message"]

    @pytest.mark.asyncio
    async def test_generic_exception_handled(self):
        """Generic adapter exceptions are contained and reconciled, not retried."""
        adapter = _adapter(error=RuntimeError("DB connection failed"))

        result = await _execute(adapter, _intent())

        assert result["success"] is False
        assert result["error"] == "RuntimeError"
        assert "结果未确认" in result["message"]

    @pytest.mark.asyncio
    async def test_creates_account_when_none_exists(self):
        """A missing account is denied; managed execution never creates one."""
        adapter = _adapter(error=ManagedPaperOrderError("PAPER_ACCOUNT_REQUIRED", status_code=422))

        result = await _execute(adapter, _intent(), account_id=None)

        assert result["success"] is False
        assert result["error"] == "PAPER_ACCOUNT_REQUIRED"
        assert "未创建默认账户" in result["message"]
        assert adapter.submit_ai.await_args.kwargs["legacy_account_id"] is None

    @pytest.mark.asyncio
    async def test_operation_id_is_required(self):
        """Without a stable operation id nothing is dispatched."""
        adapter = _adapter(result={"intent_id": "unused", "state": "FILLED"})

        result = await _execute(adapter, _intent(), operation_id=None)

        assert result["success"] is False
        assert result["error"] == "stable_operation_id_required"
        adapter.submit_ai.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_position_success(self):
        """A managed close is dispatched through the typed intent."""
        adapter = _adapter(result={"intent_id": "intent-close", "state": "FILLED"})

        result = await _execute(adapter, _intent(action=TradeAction.CLOSE, symbol="rb2501"))

        assert result["success"] is True
        assert result["type"] == "managed_paper_trade"
        assert result["message"] == "managed paper order filled: intent-close"

    @pytest.mark.asyncio
    async def test_close_position_uses_paper_service_limit_offset_signature(self):
        """Close passes the original intent and stable trade id to the adapter."""
        intent = _intent(action=TradeAction.CLOSE, symbol="BTCUSDT")
        adapter = _adapter(result={"intent_id": "intent-close", "state": "FILLED"})

        await _execute(adapter, intent)

        adapter.submit_ai.assert_awaited_once_with(
            subject="user1",
            legacy_account_id="acct-1",
            intent=intent,
            trade_id="trade-1",
        )

    @pytest.mark.asyncio
    async def test_close_position_respects_explicit_quantity(self):
        """An explicit close quantity is preserved in the submitted intent."""
        intent = _intent(action=TradeAction.CLOSE, symbol="rb2501", quantity=3)
        adapter = _adapter(result={"intent_id": "intent-close", "state": "FILLED"})

        result = await _execute(adapter, intent)

        assert result["success"] is True
        assert adapter.submit_ai.await_args.kwargs["intent"].quantity == 3

    @pytest.mark.asyncio
    async def test_close_position_rejects_quantity_above_position(self):
        """An over-sized close is denied by the managed owner, not retried."""
        adapter = _adapter(
            error=ManagedPaperOrderError("POSITION_QUANTITY_EXCEEDED", status_code=422)
        )

        result = await _execute(adapter, _intent(action=TradeAction.CLOSE, quantity=11))

        assert result["success"] is False
        assert result["error"] == "POSITION_QUANTITY_EXCEEDED"
        adapter.submit_ai.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_position_matches_compact_exchange_symbol(self):
        """The symbol is forwarded unchanged; normalization belongs to the owner."""
        intent = _intent(action=TradeAction.CLOSE, symbol="BTC/USDT")
        adapter = _adapter(result={"intent_id": "intent-close", "state": "FILLED"})

        result = await _execute(adapter, intent)

        assert result["success"] is True
        assert adapter.submit_ai.await_args.kwargs["intent"].symbol == "BTC/USDT"

    @pytest.mark.asyncio
    async def test_close_position_rejects_hedged_symbol_without_requested_side(self):
        """Hedged-leg ambiguity is reported by the managed owner."""
        adapter = _adapter(error=ManagedPaperOrderError("AMBIGUOUS_POSITION", status_code=409))

        result = await _execute(adapter, _intent(action=TradeAction.CLOSE, symbol="BTCUSDT"))

        assert result["success"] is False
        assert result["error"] == "AMBIGUOUS_POSITION"

    @pytest.mark.asyncio
    async def test_close_position_uses_explicit_position_side_for_hedged_symbol(self):
        """The requested hedge leg remains part of the forwarded intent."""
        intent = _intent(
            action=TradeAction.CLOSE,
            symbol="BTCUSDT",
            quantity=0.1,
            additional_params={"position_side": "short"},
        )
        adapter = _adapter(result={"intent_id": "intent-short", "state": "FILLED"})

        result = await _execute(adapter, intent)

        assert result["success"] is True
        submitted = adapter.submit_ai.await_args.kwargs["intent"]
        assert submitted.additional_params == {"position_side": "short"}
        assert submitted.quantity == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_close_position_not_found(self):
        """A missing position is a stable denial, not a local precheck."""
        adapter = _adapter(error=ManagedPaperOrderError("NO_POSITION", status_code=404))

        result = await _execute(adapter, _intent(action=TradeAction.CLOSE, symbol="i2501"))

        assert result["success"] is False
        assert result["error"] == "NO_POSITION"
        assert result["message"] == "托管纸面执行不可用（NO_POSITION），未使用旧撮合回退。"
