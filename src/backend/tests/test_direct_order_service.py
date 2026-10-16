"""Tests for DirectOrderService - trade execution bridge."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.ai_trading import OrderType, TradeAction, TradingIntent
from app.services.direct_order_service import DirectOrderService


class TestDirectOrderServiceMapOrderType:
    """Test order type mapping."""

    def test_market(self):
        assert DirectOrderService._map_order_type(OrderType.MARKET) == "market"

    def test_limit(self):
        assert DirectOrderService._map_order_type(OrderType.LIMIT) == "limit"

    def test_stop(self):
        assert DirectOrderService._map_order_type(OrderType.STOP) == "stop"

    def test_stop_limit(self):
        assert DirectOrderService._map_order_type(OrderType.STOP_LIMIT) == "stop_limit"






class TestDirectOrderServiceNumericBoundaries:
    @pytest.mark.parametrize("value", [None, "", "invalid", float("nan"), float("inf")])
    def test_invalid_order_sizes_are_rejected(self, value):
        with pytest.raises(ValueError, match="quantity"):
            DirectOrderService._normalise_order_size(value, default=None)

    def test_overflowing_order_size_is_rejected(self):
        with pytest.raises(ValueError, match="quantity"):
            DirectOrderService._normalise_order_size(10**400, default=None)



class TestDirectOrderServicePaperTrade:
    """Test paper trade execution."""

    @pytest.mark.asyncio
    async def test_query_action(self):
        """QUERY action should query positions."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.QUERY,
            confidence=0.9,
        )

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))
        mock_paper_service.list_positions = AsyncMock(return_value=([], 0))

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")
            assert result["success"] is True
            assert result["type"] == "query"

    @pytest.mark.asyncio
    async def test_query_action_uses_paper_service_limit_offset_signature(self):
        """Direct paper queries must call the real PaperTradingService signature."""
        service = DirectOrderService()
        intent = TradingIntent(action=TradeAction.QUERY, confidence=0.9)

        class StrictPaperService:
            async def list_accounts(self, user_id, limit=20, offset=0):
                assert user_id == "user1"
                assert limit == 1
                assert offset == 0
                return [SimpleNamespace(id="acc1")], 1

            async def list_positions(self, filters, limit=20, offset=0):
                assert filters == {"account_id": "acc1"}
                assert limit == 50
                assert offset == 0
                return [
                    SimpleNamespace(
                        symbol="BTCUSDT",
                        size=0.25,
                        avg_price=50000.0,
                        unrealized_pnl=125.0,
                    )
                ], 1

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=StrictPaperService(),
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")

        assert result["success"] is True
        assert result["positions"] == [
            {
                "symbol": "BTCUSDT",
                "size": 0.25,
                "avg_price": 50000.0,
                "unrealized_pnl": 125.0,
            }
        ]

    @pytest.mark.asyncio
    async def test_query_action_reports_paper_position_query_error(self):
        service = DirectOrderService()
        intent = TradingIntent(action=TradeAction.QUERY, confidence=0.9)

        class FailingPaperService:
            async def list_accounts(self, user_id, limit=20, offset=0):
                return [SimpleNamespace(id="acc1")], 1

            async def list_positions(self, filters, limit=20, offset=0):
                raise RuntimeError("paper db unavailable")

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=FailingPaperService(),
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")

        assert result["success"] is False
        assert result["error"] == "paper db unavailable"
        assert result["positions"] == []

    @pytest.mark.asyncio
    async def test_unsupported_action(self):
        """Unsupported actions return error."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.CANCEL,
            confidence=0.9,
        )

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")
            assert result["success"] is False
            assert "Unsupported action" in result["error"]

    @pytest.mark.asyncio
    async def test_buy_order_success(self):
        """Successful buy order execution."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=10,
            price=3500.0,
            order_type=OrderType.LIMIT,
            confidence=0.9,
        )

        mock_order = MagicMock()
        mock_order.id = "order123"
        mock_order.status = "submitted"

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))
        mock_paper_service.submit_order = AsyncMock(return_value=mock_order)

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")
            assert result["success"] is True
            assert result["type"] == "paper_trade"
            assert result["order_id"] == "order123"
            assert result["symbol"] == "rb2501"
            assert result["quantity"] == 10
            assert result["side"] == "buy"

    @pytest.mark.asyncio
    async def test_fractional_paper_quantity_is_preserved(self):
        """Paper trades must not truncate fractional crypto quantities."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTC/USDT",
            quantity=0.25,
            price=50000.0,
            order_type=OrderType.LIMIT,
            confidence=0.9,
        )

        mock_order = MagicMock()
        mock_order.id = "order123"
        mock_order.status = "submitted"

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))
        mock_paper_service.submit_order = AsyncMock(return_value=mock_order)

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")

        assert result["success"] is True
        assert result["quantity"] == pytest.approx(0.25)
        assert mock_paper_service.submit_order.await_args.kwargs["size"] == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_sell_order_success(self):
        """Successful sell order execution."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.SELL,
            symbol="BTCUSDT",
            quantity=1,
            price=50000.0,
            order_type=OrderType.LIMIT,
            confidence=0.9,
        )

        mock_order = MagicMock()
        mock_order.id = "order456"
        mock_order.status = "submitted"

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))
        mock_paper_service.submit_order = AsyncMock(return_value=mock_order)

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")
            assert result["success"] is True
            assert result["side"] == "sell"

    @pytest.mark.asyncio
    async def test_value_error_handled(self):
        """ValueError from paper trading service is handled gracefully."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=10,
            confidence=0.9,
        )

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))
        mock_paper_service.submit_order = AsyncMock(side_effect=ValueError("Insufficient balance"))

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")
            assert result["success"] is False
            assert "Insufficient balance" in result["error"]

    @pytest.mark.asyncio
    async def test_generic_exception_handled(self):
        """Generic exceptions are handled gracefully."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=10,
            confidence=0.9,
        )

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(
            side_effect=RuntimeError("DB connection failed")
        )

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")
            assert result["success"] is False
            assert "DB connection failed" in result["error"]

    @pytest.mark.asyncio
    async def test_creates_account_when_none_exists(self):
        """Creates a new account when user has no active accounts."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.QUERY,
            confidence=0.9,
        )

        mock_account = MagicMock()
        mock_account.id = "new_acc"

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([], 0))
        mock_paper_service.create_account = AsyncMock(return_value=mock_account)
        mock_paper_service.list_positions = AsyncMock(return_value=([], 0))

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")
            assert result["success"] is True
            mock_paper_service.create_account.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_position_success(self):
        """Close position submits counter-order."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.CLOSE,
            symbol="rb2501",
            confidence=0.9,
        )

        mock_position = MagicMock()
        mock_position.symbol = "RB2501"
        mock_position.size = 10

        mock_order = MagicMock()
        mock_order.id = "close_order"

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))
        mock_paper_service.list_positions = AsyncMock(return_value=([mock_position], 1))
        mock_paper_service.submit_order = AsyncMock(return_value=mock_order)

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")
            assert result["success"] is True
            assert result["type"] == "close_position"
            assert result["side"] == "sell"
            assert result["size"] == 10

    @pytest.mark.asyncio
    async def test_close_position_uses_paper_service_limit_offset_signature(self):
        """Direct paper closes must use the real list_positions arguments."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.CLOSE,
            symbol="BTC/USDT",
            quantity=0.1,
            confidence=0.9,
        )
        submitted: dict[str, object] = {}

        class StrictPaperService:
            async def list_accounts(self, user_id, limit=20, offset=0):
                assert user_id == "user1"
                assert limit == 1
                assert offset == 0
                return [SimpleNamespace(id="acc1")], 1

            async def list_positions(self, filters, limit=20, offset=0):
                assert filters == {"account_id": "acc1"}
                assert limit == 50
                assert offset == 0
                return [SimpleNamespace(symbol="BTCUSDT", size=0.25)], 1

            async def submit_order(self, **kwargs):
                submitted.update(kwargs)
                return SimpleNamespace(id="close_order")

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=StrictPaperService(),
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")

        assert result["success"] is True
        assert result["side"] == "sell"
        assert result["size"] == pytest.approx(0.1)
        assert submitted == {
            "account_id": "acc1",
            "symbol": "BTCUSDT",
            "order_type": "market",
            "side": "sell",
            "size": 0.1,
        }

    @pytest.mark.asyncio
    async def test_close_position_respects_explicit_quantity(self):
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.CLOSE,
            symbol="rb2501",
            quantity=3,
            confidence=0.9,
        )

        mock_position = MagicMock()
        mock_position.symbol = "RB2501"
        mock_position.size = 10
        mock_order = MagicMock()
        mock_order.id = "close_order"

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))
        mock_paper_service.list_positions = AsyncMock(return_value=([mock_position], 1))
        mock_paper_service.submit_order = AsyncMock(return_value=mock_order)

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")

        assert result["success"] is True
        assert result["size"] == 3
        assert mock_paper_service.submit_order.await_args.kwargs["size"] == 3

    @pytest.mark.asyncio
    async def test_close_position_rejects_quantity_above_position(self):
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.CLOSE,
            symbol="rb2501",
            quantity=11,
            confidence=0.9,
        )

        mock_position = MagicMock()
        mock_position.symbol = "RB2501"
        mock_position.size = 10

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))
        mock_paper_service.list_positions = AsyncMock(return_value=([mock_position], 1))
        mock_paper_service.submit_order = AsyncMock()

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")

        assert result["success"] is False
        assert result["error"] == "invalid_order"
        assert "exceeds available" in result["message"]
        mock_paper_service.submit_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_position_matches_compact_exchange_symbol(self):
        """Paper close should use the same symbol aliases as live portfolio risk."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.CLOSE,
            symbol="BTC/USDT",
            confidence=0.9,
        )

        mock_position = MagicMock()
        mock_position.symbol = "BTCUSDT"
        mock_position.size = 0.25

        mock_order = MagicMock()
        mock_order.id = "close_order"

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))
        mock_paper_service.list_positions = AsyncMock(return_value=([mock_position], 1))
        mock_paper_service.submit_order = AsyncMock(return_value=mock_order)

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")

        assert result["success"] is True
        assert result["symbol"] == "BTCUSDT"
        mock_paper_service.submit_order.assert_awaited_once()
        assert mock_paper_service.submit_order.await_args.kwargs["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_close_position_rejects_hedged_symbol_without_requested_side(self):
        """Paper close should match live close ambiguity checks for hedged symbols."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.CLOSE,
            symbol="BTCUSDT",
            confidence=0.9,
        )

        long_position = SimpleNamespace(symbol="BTCUSDT", size=0.25, position_side="long")
        short_position = SimpleNamespace(symbol="BTCUSDT", size=-0.2, position_side="short")

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))
        mock_paper_service.list_positions = AsyncMock(
            return_value=([long_position, short_position], 2)
        )
        mock_paper_service.submit_order = AsyncMock()

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")

        assert result["success"] is False
        assert result["error"] == "ambiguous_position"
        assert "请指定合约或方向" in result["message"]
        mock_paper_service.submit_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_position_uses_explicit_position_side_for_hedged_symbol(self):
        """Paper close-short intents should close only the short leg."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.CLOSE,
            symbol="BTCUSDT",
            quantity=0.1,
            confidence=0.9,
            additional_params={"position_side": "short"},
        )

        long_position = SimpleNamespace(symbol="BTCUSDT", size=0.25, position_side="long")
        short_position = SimpleNamespace(symbol="BTCUSDT", size=-0.2, position_side="short")
        mock_order = SimpleNamespace(id="close_short")

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))
        mock_paper_service.list_positions = AsyncMock(
            return_value=([long_position, short_position], 2)
        )
        mock_paper_service.submit_order = AsyncMock(return_value=mock_order)

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")

        assert result["success"] is True
        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "buy"
        assert result["size"] == pytest.approx(0.1)
        assert mock_paper_service.submit_order.await_args.kwargs == {
            "account_id": "acc1",
            "symbol": "BTCUSDT",
            "order_type": "market",
            "side": "buy",
            "size": 0.1,
        }

    @pytest.mark.asyncio
    async def test_close_position_not_found(self):
        """Close position fails when no matching position exists."""
        service = DirectOrderService()
        intent = TradingIntent(
            action=TradeAction.CLOSE,
            symbol="i2501",
            confidence=0.9,
        )

        mock_paper_service = AsyncMock()
        mock_paper_service.list_accounts = AsyncMock(return_value=([MagicMock(id="acc1")], 1))
        mock_paper_service.list_positions = AsyncMock(return_value=([], 0))

        with patch(
            "app.services.paper_trading_service.PaperTradingService",
            return_value=mock_paper_service,
        ):
            result = await service.execute_paper_trade(intent, user_id="user1")
            assert result["success"] is False
            assert "no_position" in result["error"]




