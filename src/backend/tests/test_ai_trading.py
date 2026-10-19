"""Tests for AI Trading service and API.

Tests the natural language trading pipeline including:
- Intent parsing (mocked LLM)
- Risk guard assessment
- API endpoints
- Trade confirmation flow
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.ai_trading import (
    AITradingRequest,
    OrderType,
    RiskLevel,
    TradeAction,
    TradeStatus,
    TradingIntent,
)
from app.services.ai_trading_service import AITradingService
from app.services.service_read.access import ReadAccess, ServiceReadAccessDirectory
from app.services.service_read.contracts import AccountReadView, ReadQuality
from app.services.trading_risk_guard import TradingRiskConfig, TradingRiskGuard


def _service_account_view(
    account_ref: str,
    *,
    value: str = "100000",
    quality: ReadQuality = ReadQuality.FRESH,
    positions: tuple[dict, ...] = (),
    balances_complete: bool = True,
    positions_complete: bool = True,
) -> AccountReadView:
    observed_at = "2026-10-17T00:00:00Z"
    resource = {"product_type": "SWAP", "margin_pool": "default"}
    account_key = {
        "provider": "okx",
        "venue": "OKX",
        "environment": "live",
        "account_id": "test-account",
        "subaccount_id": None,
    }
    observation = {
        "observation_id": "observation-test-1",
        "coverage": (resource,),
        "balances": (
            {
                "resource": resource,
                "currency": "USDT",
                "total": value,
                "available": value,
                "locked": "0",
                "observed_at_utc": observed_at,
            },
        ),
        "positions": positions,
        "valuation": {
            "currency": "USDT",
            "available_cash": value,
            "equity": value,
            "observed_at_utc": observed_at,
        },
        "started_at_utc": observed_at,
        "completed_at_utc": observed_at,
        "consistency": "multi_query",
        "balances_complete": balances_complete,
        "positions_complete": positions_complete,
    }
    return AccountReadView(
        account_ref=account_ref,
        execution_domain_ref="live:OKX",
        currency="USDT",
        quality=quality,
        session_generation="session-generation-test",
        cash=value,
        value=value,
        observed_at_utc=observed_at,
        received_age_seconds=0.0,
        fresh_for_seconds=10.0 if quality is ReadQuality.FRESH else 0.0,
        positions_count=len(positions),
        open_orders_count=0,
        account_key=account_key,
        account_key_id="account-" + "0" * 64,
        provider_observation=observation,
    )


class _StaticServiceReadWorker:
    def __init__(self, view_or_error):
        self.view_or_error = view_or_error
        self.reads = []

    async def read_account(self, account_ref):
        self.reads.append(account_ref)
        if isinstance(self.view_or_error, Exception):
            raise self.view_or_error
        return self.view_or_error

    async def read_order(self, *_args, **_kwargs):
        raise AssertionError("not used")

    async def read_strategy_health(self, *_args, **_kwargs):
        raise AssertionError("not used")


class TestTradingRiskGuard:
    """Test the risk guard assessment logic."""

    def setup_method(self):
        self.guard = TradingRiskGuard(
            TradingRiskConfig(
                max_single_trade_amount=10000,
                max_daily_trades=50,
                max_position_ratio=0.3,
                require_confirmation_above=5000,
                min_confidence_threshold=0.3,
                blocked_symbols=["FORBIDDEN"],
            )
        )

    def test_query_always_approved(self):
        intent = TradingIntent(action=TradeAction.QUERY, confidence=0.1)
        result = self.guard.assess(intent)
        assert result.approved is True
        assert result.risk_level == RiskLevel.LOW

    def test_low_confidence_blocked(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTCUSDT",
            quantity=1,
            confidence=0.1,
        )
        result = self.guard.assess(intent)
        assert result.approved is False
        assert "置信度过低" in result.blocked_reasons[0]

    def test_missing_symbol_blocked(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol=None,
            quantity=1,
            confidence=0.8,
        )
        result = self.guard.assess(intent)
        assert result.approved is False
        assert "品种未指定" in result.blocked_reasons[0]

    def test_missing_quantity_blocked(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTCUSDT",
            quantity=None,
            confidence=0.8,
        )
        result = self.guard.assess(intent)
        assert result.approved is False
        assert "数量未指定" in result.blocked_reasons[0]

    def test_blocked_symbol(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="FORBIDDEN",
            quantity=1,
            confidence=0.8,
        )
        result = self.guard.assess(intent)
        assert result.approved is False
        assert "禁止交易列表" in result.blocked_reasons[0]

    def test_blocked_symbol_matches_exchange_alias(self):
        guard = TradingRiskGuard(
            TradingRiskConfig(blocked_symbols=["BTC/USDT"], min_confidence_threshold=0.3)
        )
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTCUSDT",
            quantity=0.1,
            confidence=0.8,
        )

        result = guard.assess(intent)

        assert result.approved is False
        assert "禁止交易列表" in result.blocked_reasons[0]

    def test_valid_trade_approved(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTCUSDT",
            quantity=0.1,
            confidence=0.8,
            risk_level=RiskLevel.LOW,
        )
        result = self.guard.assess(intent)
        assert result.approved is True

    def test_high_value_requires_confirmation(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTCUSDT",
            quantity=1,
            price=8000,
            confidence=0.8,
            risk_level=RiskLevel.MEDIUM,
        )
        result = self.guard.assess(intent, account_balance=100000)
        assert result.approved is True
        assert result.requires_confirmation is True

    def test_market_order_without_reference_price_is_blocked_when_account_is_known(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTCUSDT",
            quantity=0.1,
            confidence=0.8,
            risk_level=RiskLevel.LOW,
        )

        result = self.guard.assess(intent, account_balance=100000)

        assert result.approved is False
        assert any("缺少价格或最新价" in reason for reason in result.blocked_reasons)

    def test_market_order_uses_reference_price_for_amount_limits(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTCUSDT",
            quantity=0.1,
            confidence=0.8,
            risk_level=RiskLevel.LOW,
            additional_params={"last_price": 60000},
        )

        result = self.guard.assess(intent, account_balance=100000)

        assert result.approved is True
        assert result.requires_confirmation is True
        assert result.max_loss_estimate == pytest.approx(300.0)

    def test_futures_trade_value_uses_contract_multiplier(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="IF2609",
            exchange="ctp",
            quantity=1,
            price=5000,
            confidence=0.8,
            risk_level=RiskLevel.LOW,
            additional_params={"multiplier": 300},
        )

        result = self.guard.assess(intent, account_balance=1_000_000)

        assert result.approved is False
        assert any("单笔交易金额" in reason for reason in result.blocked_reasons)
        assert result.max_loss_estimate == pytest.approx(75_000.0)

    def test_position_ratio_uses_projected_same_symbol_exposure(self):
        guard = TradingRiskGuard(
            TradingRiskConfig(
                max_single_trade_amount=100000,
                max_position_ratio=0.3,
                require_confirmation_above=100000,
                min_confidence_threshold=0.3,
            )
        )
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTCUSDT",
            quantity=0.1,
            price=100000,
            order_type=OrderType.LIMIT,
            confidence=0.8,
            risk_level=RiskLevel.LOW,
        )

        result = guard.assess(
            intent,
            account_balance=100000,
            current_positions=[{"symbol": "BTCUSDT", "size": 0.25}],
        )

        assert result.approved is True
        assert result.requires_confirmation is True
        assert any("预计品种持仓占账户比例 (35.0%)" in item for item in result.warnings)

    def test_position_ratio_uses_projected_exposure_after_reducing_trade(self):
        guard = TradingRiskGuard(
            TradingRiskConfig(
                max_single_trade_amount=100000,
                max_position_ratio=0.3,
                require_confirmation_above=100000,
                min_confidence_threshold=0.3,
            )
        )
        intent = TradingIntent(
            action=TradeAction.SELL,
            symbol="BTCUSDT",
            quantity=0.1,
            price=100000,
            order_type=OrderType.LIMIT,
            confidence=0.8,
            risk_level=RiskLevel.LOW,
        )

        result = guard.assess(
            intent,
            account_balance=100000,
            current_positions=[{"symbol": "BTC/USDT", "size": 0.35}],
        )

        assert result.approved is True
        assert result.requires_confirmation is False
        assert not any("预计品种持仓占账户比例" in item for item in result.warnings)

    def test_position_ratio_uses_gross_exposure_for_hedged_same_symbol(self):
        guard = TradingRiskGuard(
            TradingRiskConfig(
                max_single_trade_amount=100000,
                max_position_ratio=0.49,
                require_confirmation_above=100000,
                min_confidence_threshold=0.3,
            )
        )
        current_positions = [
            {"symbol": "BTCUSDT", "size": 0.25},
            {"symbol": "BTC/USDT", "size": -0.20},
        ]

        for action in (TradeAction.BUY, TradeAction.SELL):
            intent = TradingIntent(
                action=action,
                symbol="BTCUSDT",
                quantity=0.05,
                price=100000,
                order_type=OrderType.LIMIT,
                confidence=0.8,
                risk_level=RiskLevel.LOW,
            )

            result = guard.assess(
                intent,
                account_balance=100000,
                current_positions=current_positions,
            )

            assert result.approved is True
            assert result.requires_confirmation is True
            assert any("预计品种持仓占账户比例 (50.0%)" in item for item in result.warnings)

    def test_no_stop_loss_warning(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=1,
            order_type=OrderType.MARKET,
            confidence=0.8,
            risk_level=RiskLevel.LOW,
        )
        result = self.guard.assess(intent)
        assert result.approved is True
        assert any("止损" in w for w in result.warnings)

    def test_daily_trade_limit(self):
        # Set the last reset date to today so it won't reset
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.guard._daily_trade_count = 50
        self.guard._last_reset_date = today
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTCUSDT",
            quantity=1,
            confidence=0.8,
        )
        result = self.guard.assess(intent)
        assert result.approved is False
        assert "每日最大交易次数" in result.blocked_reasons[0]


class TestAITradingService:
    """Test the AI trading service orchestration."""

    @pytest.fixture
    def service(self):
        return AITradingService()

    def test_service_positions_preserve_provider_symbol_direction_and_unit(self, service):
        positions = service._service_positions(
            (
                {
                    "instrument": {"native_symbol": "BTC-USDT-SWAP"},
                    "side": "short",
                    "quantity": "0.25",
                    "qty_unit": "contract",
                    "observed_at_utc": "2026-10-17T00:00:00Z",
                },
                {
                    "instrument": {"native_symbol": "ETH-USDT-SWAP"},
                    "side": "net",
                    "quantity": "0",
                    "qty_unit": "contract",
                    "observed_at_utc": "2026-10-17T00:00:00Z",
                },
            )
        )

        assert positions == [
            {
                "symbol": "BTC-USDT-SWAP",
                "size": -0.25,
                "qty_unit": "contract",
                "observed_at_utc": "2026-10-17T00:00:00Z",
            }
        ]

    async def test_live_context_reads_only_subject_granted_service_account(self, service):
        class Worker:
            def __init__(self):
                self.reads = []

            async def read_account(self, account_ref):
                self.reads.append(account_ref)
                return _service_account_view(
                    account_ref,
                    positions=(
                        {
                            "resource": {"product_type": "SWAP", "margin_pool": "default"},
                            "instrument": {
                                "provider": "okx",
                                "venue": "OKX",
                                "environment": "live",
                                "product_type": "SWAP",
                                "instrument_id": "BTC-USDT-SWAP",
                                "native_symbol": "BTC-USDT-SWAP",
                            },
                            "side": "short",
                            "quantity": "0.25",
                            "qty_unit": "contract",
                            "average_price": "60000",
                            "price_currency": "USDT",
                            "observed_at_utc": "2026-10-17T00:00:00Z",
                        },
                    ),
                )

            async def read_order(self, *_args, **_kwargs):
                raise AssertionError("not used")

            async def read_strategy_health(self, *_args, **_kwargs):
                raise AssertionError("not used")

        from app.api.service_read import configure_service_read

        worker = Worker()
        directory = ServiceReadAccessDirectory(
            {
                "subject-a": ReadAccess(worker=worker, allow_account_refs={"account-a"}),
                "subject-b": ReadAccess(worker=Worker(), allow_account_refs={"account-b"}),
            }
        )
        configure_service_read(directory)
        try:
            context = await service._resolve_live_trading_context("subject-a", "account-a")
            denied = await service._resolve_live_trading_context("subject-a", "account-b")
        finally:
            configure_service_read(None)

        assert directory.account_refs_for("subject-a") == ("account-a",)
        assert directory.account_refs_for("unknown-subject") == ()
        assert worker.reads == ["account-a"]
        assert context["account_balance"] == 100000.0
        assert context["current_positions"] == [
            {
                "symbol": "BTC-USDT-SWAP",
                "size": -0.25,
                "qty_unit": "contract",
                "observed_at_utc": "2026-10-17T00:00:00Z",
            }
        ]
        assert context["currency"] == "USDT"
        assert context["read_provenance"]["source"] == "service-v2.account.snapshot"
        assert context["read_provenance"]["observed_at_utc"] == "2026-10-17T00:00:00Z"
        assert denied["degraded"] is True
        assert denied["read_status"] == "ACCOUNT_READ_ACCESS_DENIED"

    async def test_live_context_rejects_missing_service_read_and_incomplete_or_stale_views(
        self, service
    ):
        from app.api.service_read import configure_service_read

        try:
            configure_service_read(None)
            missing = await service._resolve_live_trading_context("subject-a", "account-a")
            stale_directory = ServiceReadAccessDirectory(
                {
                    "subject-a": ReadAccess(
                        worker=_StaticServiceReadWorker(
                            _service_account_view("account-a", quality=ReadQuality.STALE)
                        ),
                        allow_account_refs={"account-a"},
                    )
                }
            )
            configure_service_read(stale_directory)
            stale = await service._resolve_live_trading_context("subject-a", "account-a")
            incomplete_directory = ServiceReadAccessDirectory(
                {
                    "subject-a": ReadAccess(
                        worker=_StaticServiceReadWorker(
                            _service_account_view("account-a", positions_complete=False)
                        ),
                        allow_account_refs={"account-a"},
                    )
                }
            )
            configure_service_read(incomplete_directory)
            incomplete = await service._resolve_live_trading_context("subject-a", "account-a")
        finally:
            configure_service_read(None)

        assert missing["degraded"] is True
        assert missing["read_status"] == "SERVICE_READ_NOT_CONFIGURED"
        assert stale["degraded"] is True
        assert stale["read_status"] == "stale"
        assert incomplete["degraded"] is True
        assert incomplete["read_status"] == "ACCOUNT_OBSERVATION_INCOMPLETE"

    async def test_dry_run_execution(self, service):
        """Dry run should return confirmed status without real execution."""
        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=1,
            price=3500,
            confidence=0.9,
            risk_level=RiskLevel.LOW,
            reason="测试买入",
        )

        with (
            patch(
                "app.services.ai_trading_service.parse_trading_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch.object(
                service,
                "_resolve_trading_context",
                new_callable=AsyncMock,
                return_value={"account_balance": 100000.0, "current_positions": []},
            ),
            patch("app.services.ai_trading_service.query_local_asset_spec", return_value={}),
        ):
            request = AITradingRequest(message="买入1手螺纹钢", dry_run=True)
            result = await service.process_trading_request("user1", request)

        assert result.status == TradeStatus.CONFIRMED
        assert result.execution_result is not None
        assert result.execution_result.get("dry_run") is True

    async def test_dry_run_risk_uses_local_contract_multiplier(self, service):
        """Paper AI risk assessment must use local asset specs before dry-run approval."""
        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="IF2609",
            exchange="ctp",
            quantity=1,
            price=5000,
            confidence=0.9,
            risk_level=RiskLevel.LOW,
        )

        with (
            patch(
                "app.services.ai_trading_service.parse_trading_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch.object(
                service,
                "_resolve_trading_context",
                new_callable=AsyncMock,
                return_value={"account_balance": 1_000_000.0, "current_positions": []},
            ),
            patch(
                "app.services.ai_trading_service.query_local_asset_spec",
                return_value={"symbol": "IF2609", "multiplier": 300, "margin_rate": 0.1},
            ),
        ):
            request = AITradingRequest(message="买入1手IF2609", dry_run=True)
            result = await service.process_trading_request("user1", request)

        assert result.status == TradeStatus.REJECTED
        assert result.intent.additional_params["multiplier"] == 300
        assert any("单笔交易金额" in reason for reason in result.risk_assessment.blocked_reasons)

    async def test_dry_run_asset_spec_overrides_stale_parser_multiplier(self, service):
        """Authoritative local specs must override stale LLM/parser multiplier params."""
        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="IF2609",
            exchange="ctp",
            quantity=1,
            price=5000,
            confidence=0.9,
            risk_level=RiskLevel.LOW,
            additional_params={"multiplier": 1},
        )

        with (
            patch(
                "app.services.ai_trading_service.parse_trading_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch.object(
                service,
                "_resolve_trading_context",
                new_callable=AsyncMock,
                return_value={"account_balance": 1_000_000.0, "current_positions": []},
            ),
            patch(
                "app.services.ai_trading_service.query_local_asset_spec",
                return_value={"symbol": "IF2609", "multiplier": 300, "margin_rate": 0.1},
            ),
        ):
            request = AITradingRequest(message="买入1手IF2609", dry_run=True)
            result = await service.process_trading_request("user1", request)

        assert result.status == TradeStatus.REJECTED
        assert result.intent.additional_params["multiplier"] == 300
        assert any("单笔交易金额" in reason for reason in result.risk_assessment.blocked_reasons)

    async def test_rejected_by_risk_guard(self, service):
        """Low confidence intent should be rejected."""
        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol=None,
            quantity=1,
            confidence=0.1,
            risk_level=RiskLevel.HIGH,
        )

        with (
            patch(
                "app.services.ai_trading_service.parse_trading_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch.object(
                service,
                "_resolve_trading_context",
                new_callable=AsyncMock,
                return_value={"account_balance": 100000.0, "current_positions": []},
            ),
        ):
            request = AITradingRequest(message="买点什么", dry_run=True)
            result = await service.process_trading_request("user1", request)

        assert result.status == TradeStatus.REJECTED
        assert "风控拦截" in result.message

    async def test_missing_paper_account_context_raises(self, service):
        """Dry-run execution now requires an explicit paper-trading account context."""
        from app.services.ai_trading_service import MissingGatewayContextError

        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=1,
            confidence=0.9,
            risk_level=RiskLevel.LOW,
        )

        with patch(
            "app.services.ai_trading_service.parse_trading_intent",
            new_callable=AsyncMock,
            return_value=mock_intent,
        ):
            request = AITradingRequest(message="买入1手螺纹钢", dry_run=True)
            with pytest.raises(MissingGatewayContextError, match="account_id"):
                await service.process_trading_request("user1", request)

    async def test_live_context_without_service_read_returns_degraded_response(self, service):
        """Missing service-v2 configuration rejects without consulting legacy manager."""

        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=1,
            confidence=0.9,
            risk_level=RiskLevel.LOW,
        )

        with (
            patch(
                "app.services.ai_trading_service.parse_trading_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch(
                "app.services.live_trading_manager.get_live_trading_manager",
                side_effect=AssertionError("legacy manager must not be used"),
            ) as manager_getter,
        ):
            request = AITradingRequest(
                message="买入1手螺纹钢",
                dry_run=False,
                gateway_id="service-account-a",
            )
            result = await service.process_trading_request("user1", request)

        manager_getter.assert_not_called()
        assert result.status == TradeStatus.REJECTED
        assert result.degraded is True
        assert result.diagnostic_message is not None
        assert "SERVICE_READ_NOT_CONFIGURED" in result.diagnostic_message
        assert result.intent.additional_params["service_read_account"]["available"] is False

    async def test_live_context_read_failure_returns_degraded_response(self, service):
        """AI must not treat an unreadable service-v2 position book as flat."""
        from app.api.service_read import configure_service_read

        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=1,
            confidence=0.9,
            risk_level=RiskLevel.LOW,
        )

        manager_getter = patch(
            "app.services.live_trading_manager.get_live_trading_manager",
            side_effect=AssertionError("legacy manager must not be used"),
        )
        directory = ServiceReadAccessDirectory(
            {
                "user1": ReadAccess(
                    worker=_StaticServiceReadWorker(RuntimeError("position channel disconnected")),
                    allow_account_refs={"service-account-a"},
                )
            }
        )
        configure_service_read(directory)
        try:
            with (
                manager_getter as manager_getter_mock,
                patch(
                    "app.services.ai_trading_service.parse_trading_intent",
                    new_callable=AsyncMock,
                    return_value=mock_intent,
                ),
            ):
                request = AITradingRequest(
                    message="买入1手螺纹钢",
                    dry_run=False,
                    gateway_id="service-account-a",
                )
                result = await service.process_trading_request("user1", request)
        finally:
            configure_service_read(None)

        manager_getter_mock.assert_not_called()
        assert result.status == TradeStatus.REJECTED
        assert result.degraded is True
        assert result.diagnostic_message is not None
        assert "SERVICE_READ_FAILED" in result.diagnostic_message

    async def test_live_risk_uses_only_local_asset_multiplier(self, service):
        """Live risk enrichment reads local metadata and never the legacy order service."""
        from app.api.service_read import configure_service_read

        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="IF2609",
            exchange="ctp",
            quantity=1,
            price=5000,
            confidence=0.9,
            risk_level=RiskLevel.LOW,
        )

        directory = ServiceReadAccessDirectory(
            {
                "user1": ReadAccess(
                    worker=_StaticServiceReadWorker(_service_account_view("service-account-a")),
                    allow_account_refs={"service-account-a"},
                )
            }
        )
        configure_service_read(directory)
        try:
            with (
                patch(
                    "app.services.ai_trading_service.parse_trading_intent",
                    new_callable=AsyncMock,
                    return_value=mock_intent,
                ),
                patch(
                    "app.services.ai_trading_service.query_local_asset_spec",
                    return_value={"symbol": "IF2609", "multiplier": 300, "contract_size": 300},
                ),
                patch(
                    "app.services.live_trading_manager.get_live_trading_manager",
                    side_effect=AssertionError("legacy manager must not be used"),
                ) as manager_getter,
                patch("app.services.direct_order_service.DirectOrderService") as order_service,
            ):
                request = AITradingRequest(
                    message="买入1手IF2609",
                    dry_run=False,
                    gateway_id="service-account-a",
                    auto_confirm=True,
                )
                result = await service.process_trading_request("user1", request)
        finally:
            configure_service_read(None)

        manager_getter.assert_not_called()
        order_service.assert_not_called()
        assert result.status == TradeStatus.REJECTED
        assert result.intent.additional_params["multiplier"] == 300
        assert any("单笔交易金额" in reason for reason in result.risk_assessment.blocked_reasons)

    async def test_live_risk_rejects_missing_local_asset_multiplier(self, service):
        """Parser guesses cannot substitute for a verified local contract spec."""
        from app.api.service_read import configure_service_read

        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="UNKNOWN-SWAP",
            quantity=1,
            price=10,
            confidence=0.9,
            risk_level=RiskLevel.LOW,
            additional_params={"multiplier": 1},
        )
        directory = ServiceReadAccessDirectory(
            {
                "user1": ReadAccess(
                    worker=_StaticServiceReadWorker(_service_account_view("service-account-a")),
                    allow_account_refs={"service-account-a"},
                )
            }
        )
        configure_service_read(directory)
        try:
            with (
                patch(
                    "app.services.ai_trading_service.parse_trading_intent",
                    new_callable=AsyncMock,
                    return_value=mock_intent,
                ),
                patch("app.services.ai_trading_service.query_local_asset_spec", return_value={}),
                patch("app.services.direct_order_service.DirectOrderService") as order_service,
            ):
                result = await service.process_trading_request(
                    "user1",
                    AITradingRequest(
                        message="买入1张未知合约",
                        dry_run=False,
                        gateway_id="service-account-a",
                    ),
                )
        finally:
            configure_service_read(None)

        order_service.assert_not_called()
        assert result.status is TradeStatus.REJECTED
        assert result.degraded is True
        assert "本地资产乘数" in (result.diagnostic_message or "")
        assert "multiplier" not in result.intent.additional_params

    def test_live_local_asset_spec_replaces_parser_contract_guesses(self, service):
        """Only local contract metadata may reach live risk calculations."""
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTC-USD-SWAP",
            quantity=1,
            additional_params={
                "contract_type": "inverse",
                "multiplier": 999,
                "ctValCcy": "BTC",
                "is_inverse": True,
            },
        )
        request = AITradingRequest(
            message="buy one contract",
            dry_run=False,
            gateway_id="service-account-a",
        )

        with patch(
            "app.services.ai_trading_service.query_local_asset_spec",
            return_value={
                "source": "local_asset_info",
                "asset_type": "SWAP",
                "contract_type": "linear",
                "multiplier": 2,
            },
        ):
            assert service._enrich_intent_with_asset_spec(intent, request) is True

        assert intent.additional_params["contract_type"] == "linear"
        assert intent.additional_params["multiplier"] == 2
        assert "ctValCcy" not in intent.additional_params
        assert "is_inverse" not in intent.additional_params

    async def test_live_submission_remains_refused_without_legacy_order_adapter(self, service):
        """A configured context still cannot submit through an unscoped legacy channel."""
        request = AITradingRequest(message="buy BTC", dry_run=False, gateway_id="service-account-a")
        intent = TradingIntent(action=TradeAction.BUY, symbol="BTC-USDT-SWAP", quantity=1)

        with (
            patch(
                "app.services.live_trading_manager.get_live_trading_manager",
                side_effect=AssertionError("legacy manager must not be used"),
            ) as manager_getter,
            patch("app.services.direct_order_service.DirectOrderService") as order_service,
        ):
            result = await service._execute_trade("user1", intent, request)

        manager_getter.assert_not_called()
        order_service.assert_not_called()
        assert result == {
            "success": False,
            "type": "live_trade",
            "error": "service_v2_unavailable",
            "reason": "service_v2_scope_not_configured",
            "submitted": False,
            "message": "实盘交易暂不可用：尚未配置 service-v2 执行范围，订单未提交。",
        }

    async def test_live_risk_uses_local_inverse_contract_metadata(self, service):
        """Inverse risk uses local specs while live submission remains refused."""
        from app.api.service_read import configure_service_read

        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTC-USD-SWAP",
            exchange="okx",
            quantity=100,
            price=50000,
            stop_loss=45000,
            confidence=0.9,
            risk_level=RiskLevel.LOW,
        )

        directory = ServiceReadAccessDirectory(
            {
                "user1": ReadAccess(
                    worker=_StaticServiceReadWorker(_service_account_view("service-account-a")),
                    allow_account_refs={"service-account-a"},
                )
            }
        )
        configure_service_read(directory)
        try:
            with (
                patch(
                    "app.services.ai_trading_service.parse_trading_intent",
                    new_callable=AsyncMock,
                    return_value=mock_intent,
                ),
                patch(
                    "app.services.ai_trading_service.query_local_asset_spec",
                    return_value={
                        "source": "local_asset_info",
                        "asset_type": "SWAP",
                        "contract_type": "inverse",
                        "ctVal": 100,
                        "ctValCcy": "USD",
                        "baseCcy": "BTC",
                        "quoteCcy": "USD",
                        "settleCcy": "BTC",
                        "taker_commission_rate": 0.0005,
                    },
                ),
                patch("app.services.direct_order_service.DirectOrderService") as order_service,
            ):
                request = AITradingRequest(
                    message="买入100张BTC反向永续",
                    dry_run=False,
                    gateway_id="service-account-a",
                    auto_confirm=True,
                )
                result = await service.process_trading_request("user1", request)
        finally:
            configure_service_read(None)

        order_service.assert_not_called()
        assert result.status == TradeStatus.FAILED
        assert result.risk_assessment.approved is True
        assert result.risk_assessment.max_loss_estimate == pytest.approx(1000.0)
        assert result.intent.additional_params["contract_type"] == "inverse"
        assert result.execution_result["error"] == "service_v2_unavailable"


class TestAITradingAPI:
    """Test the AI trading API endpoints."""

    @pytest.fixture
    def client(self):
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def test_execute_requires_auth(self, client):
        """Execute endpoint requires authentication."""
        response = await client.post(
            "/api/v1/ai-trading/execute",
            json={
                "message": "买入1手螺纹钢",
            },
        )
        assert response.status_code in (401, 403)

    async def test_config_requires_auth(self, client):
        """Config endpoint requires authentication."""
        response = await client.get("/api/v1/ai-trading/config")
        assert response.status_code in (401, 403)

    async def test_history_requires_auth(self, client):
        """History endpoint requires authentication."""
        response = await client.get("/api/v1/ai-trading/history")
        assert response.status_code in (401, 403)

    async def test_execute_missing_context_returns_422(self, client, auth_headers):
        """Missing paper account context is translated to HTTP 422."""
        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=1,
            confidence=0.9,
            risk_level=RiskLevel.LOW,
        )

        with patch(
            "app.services.ai_trading_service.parse_trading_intent",
            new_callable=AsyncMock,
            return_value=mock_intent,
        ):
            response = await client.post(
                "/api/v1/ai-trading/execute",
                json={"message": "买入1手螺纹钢", "dry_run": True},
                headers=auth_headers,
            )

        assert response.status_code == 422
        payload = response.json()
        error_message = payload.get("detail") or payload.get("message") or ""
        assert "account_id" in error_message

    async def test_config_exposes_paper_and_subject_granted_service_accounts(
        self, client, auth_headers
    ):
        """Config lists paper accounts and only exact service-v2 grants for the caller."""
        with (
            patch(
                "app.api.ai_trading.list_authorized_service_account_refs", return_value=("svc-a",)
            ),
            patch.object(
                AITradingService,
                "list_available_accounts",
                new_callable=AsyncMock,
                return_value=[
                    {
                        "account_id": "paper-001",
                        "name": "主模拟账户",
                        "total_equity": 100000.0,
                        "current_cash": 80000.0,
                        "is_active": True,
                        "source": "paper",
                    }
                ],
            ),
        ):
            response = await client.get("/api/v1/ai-trading/config", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["available_gateways"] == []
        assert data["available_accounts"][0]["account_id"] == "paper-001"
        assert data["available_accounts"][1] == {
            "account_id": "svc-a",
            "name": "Service v2 · svc-a",
            "total_equity": None,
            "current_cash": None,
            "is_active": True,
            "source": "service_v2",
            "gateway_id": "svc-a",
        }


class TestTradingIntentParser:
    """Test the intent parser with mocked LLM responses."""

    async def test_call_llm_uses_observable_ai_chat_entrypoint(self):
        from app.services.trading_intent_parser import _call_llm

        mock_response = (
            '{"action":"query","symbol":null,"exchange":null,"quantity":null,'
            '"price":null,"order_type":"market","stop_loss":null,"take_profit":null,'
            '"reason":"查询","confidence":0.9,"risk_level":"low"}'
        )

        with patch("app.services.trading_intent_parser.AIChatService") as mock_service_class:
            service = mock_service_class.return_value
            service.is_enabled.return_value = True
            service.generate_answer = AsyncMock(
                return_value={
                    "answer": mock_response,
                    "tokens_used": 10,
                    "model_id": "gpt-4o-mini",
                    "strategy_draft": None,
                    "reasoning": None,
                }
            )
            result = await _call_llm("看看持仓", "system prompt")

        assert result == mock_response
        service.generate_answer.assert_awaited_once()

    async def test_parse_buy_intent(self):
        """Parse a simple buy instruction."""
        from app.services.trading_intent_parser import parse_trading_intent

        mock_response = '{"action":"buy","symbol":"rb2501","exchange":"ctp","quantity":1,"price":null,"order_type":"market","stop_loss":null,"take_profit":null,"reason":"用户要求买入螺纹钢","confidence":0.9,"risk_level":"low"}'

        with patch(
            "app.services.trading_intent_parser._call_llm",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            intent = await parse_trading_intent("买入1手螺纹钢主力合约")

        assert intent.action == TradeAction.BUY
        assert intent.symbol == "rb2501"
        assert intent.quantity == 1
        assert intent.order_type == OrderType.MARKET
        assert intent.confidence == 0.9

    async def test_parse_sell_with_price(self):
        """Parse a sell instruction with limit price."""
        from app.services.trading_intent_parser import parse_trading_intent

        mock_response = '{"action":"sell","symbol":"i2501","exchange":"ctp","quantity":2,"price":3500,"order_type":"limit","stop_loss":null,"take_profit":null,"reason":"限价卖出铁矿石","confidence":0.85,"risk_level":"medium"}'

        with patch(
            "app.services.trading_intent_parser._call_llm",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            intent = await parse_trading_intent("以3500限价卖出2手铁矿石")

        assert intent.action == TradeAction.SELL
        assert intent.symbol == "i2501"
        assert intent.quantity == 2
        assert intent.price == 3500
        assert intent.order_type == OrderType.LIMIT

    async def test_parse_crypto_buy(self):
        """Parse a crypto buy instruction."""
        from app.services.trading_intent_parser import parse_trading_intent

        mock_response = '{"action":"buy","symbol":"BTCUSDT","exchange":"binance","quantity":0.1,"price":null,"order_type":"market","stop_loss":null,"take_profit":null,"reason":"在币安买入BTC","confidence":0.88,"risk_level":"medium"}'

        with patch(
            "app.services.trading_intent_parser._call_llm",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            intent = await parse_trading_intent("帮我在币安买入0.1个BTC")

        assert intent.action == TradeAction.BUY
        assert intent.symbol == "BTCUSDT"
        assert intent.exchange == "binance"
        assert intent.quantity == 0.1

    async def test_parse_query_intent(self):
        """Parse a query/position check instruction."""
        from app.services.trading_intent_parser import parse_trading_intent

        mock_response = '{"action":"query","symbol":null,"exchange":null,"quantity":null,"price":null,"order_type":"market","stop_loss":null,"take_profit":null,"reason":"用户查询持仓","confidence":0.95,"risk_level":"low"}'

        with patch(
            "app.services.trading_intent_parser._call_llm",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            intent = await parse_trading_intent("看看我现在的持仓")

        assert intent.action == TradeAction.QUERY
        assert intent.confidence == 0.95

    async def test_parse_ambiguous_input(self):
        """Ambiguous input should have low confidence."""
        from app.services.trading_intent_parser import parse_trading_intent

        mock_response = '{"action":"query","symbol":null,"exchange":null,"quantity":null,"price":null,"order_type":"market","stop_loss":null,"take_profit":null,"reason":"指令不明确","confidence":0.2,"risk_level":"high"}'

        with patch(
            "app.services.trading_intent_parser._call_llm",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            intent = await parse_trading_intent("随便搞点什么")

        assert intent.confidence < 0.5

    async def test_parse_llm_failure_returns_safe_default(self):
        """LLM failure should return a safe query intent with zero confidence."""
        from app.services.trading_intent_parser import parse_trading_intent

        with patch(
            "app.services.trading_intent_parser._call_llm",
            new_callable=AsyncMock,
            side_effect=RuntimeError("AI not configured"),
        ):
            intent = await parse_trading_intent("买入1手螺纹钢")

        assert intent.action == TradeAction.QUERY
        assert intent.confidence == 0.0
        assert intent.risk_level == RiskLevel.HIGH

    async def test_parse_invalid_json_returns_safe_default(self):
        """Invalid JSON from LLM should return safe default."""
        from app.services.trading_intent_parser import parse_trading_intent

        with patch(
            "app.services.trading_intent_parser._call_llm",
            new_callable=AsyncMock,
            return_value="I cannot parse this as JSON, sorry!",
        ):
            intent = await parse_trading_intent("买入1手螺纹钢")

        assert intent.action == TradeAction.QUERY
        assert intent.confidence == 0.0


class TestAITradingServiceConfirmation:
    """Test the trade confirmation flow."""

    @pytest.fixture
    def service(self):
        from app.services.ai_trading_service import _pending_trades

        _pending_trades.clear()
        service = AITradingService()
        service.risk_guard = TradingRiskGuard(TradingRiskConfig())
        yield service
        _pending_trades.clear()

    async def test_pending_confirmation_flow(self, service):
        """High-risk trade should require confirmation."""
        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTCUSDT",
            quantity=0.1,
            price=100000,
            confidence=0.9,
            risk_level=RiskLevel.HIGH,  # HIGH risk triggers confirmation
        )

        with (
            patch(
                "app.services.ai_trading_service.parse_trading_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch.object(
                service,
                "_resolve_trading_context",
                new_callable=AsyncMock,
                return_value={"account_balance": 100000.0, "current_positions": []},
            ),
        ):
            request = AITradingRequest(message="买入1个BTC", account_id="paper-001", dry_run=True)
            result = await service.process_trading_request("user1", request)

        assert result.status == TradeStatus.PENDING_CONFIRMATION
        assert result.requires_confirmation is True
        assert result.trade_id

    async def test_confirm_trade_success(self, service):
        """Confirming a pending trade should execute it."""
        from app.schemas.ai_trading import TradeConfirmRequest

        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=1,
            price=3500,
            confidence=0.9,
            risk_level=RiskLevel.HIGH,
        )

        # First create a pending trade
        with (
            patch(
                "app.services.ai_trading_service.parse_trading_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch.object(
                service,
                "_resolve_trading_context",
                new_callable=AsyncMock,
                return_value={"account_balance": 100000.0, "current_positions": []},
            ),
        ):
            request = AITradingRequest(
                message="买入1手螺纹钢", account_id="paper-001", dry_run=True
            )
            pending_result = await service.process_trading_request("user1", request)

        assert pending_result.status == TradeStatus.PENDING_CONFIRMATION

        # Mock the execution for confirmation
        mock_execution = {"success": True, "type": "paper_trade", "message": "模拟执行成功"}
        with (
            patch.object(
                service,
                "_resolve_trading_context",
                new_callable=AsyncMock,
                return_value={"account_balance": 100000.0, "current_positions": []},
            ),
            patch.object(
                service, "_execute_trade", new_callable=AsyncMock, return_value=mock_execution
            ),
        ):
            confirm_req = TradeConfirmRequest(
                trade_id=pending_result.trade_id,
                confirmed=True,
            )
            confirm_result = await service.confirm_trade("user1", confirm_req)
        assert confirm_result.status == TradeStatus.FILLED

    async def test_confirm_trade_expired_does_not_execute(self, service):
        """Expired pending confirmations must not execute live orders."""
        from app.schemas.ai_trading import TradeConfirmRequest
        from app.services.ai_trading_service import _pending_trades

        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=1,
            price=3500,
            confidence=0.9,
            risk_level=RiskLevel.HIGH,
        )

        with (
            patch(
                "app.services.ai_trading_service.parse_trading_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch.object(
                service,
                "_resolve_trading_context",
                new_callable=AsyncMock,
                return_value={"account_balance": 100000.0, "current_positions": []},
            ),
        ):
            request = AITradingRequest(
                message="买入1手螺纹钢", account_id="paper-001", dry_run=True
            )
            pending_result = await service.process_trading_request("user1", request)

        _pending_trades[pending_result.trade_id]["expires_at"] = "2000-01-01T00:00:00+00:00"
        with patch.object(service, "_execute_trade", new_callable=AsyncMock) as mock_execute:
            confirm_result = await service.confirm_trade(
                "user1",
                TradeConfirmRequest(trade_id=pending_result.trade_id, confirmed=True),
            )

        assert confirm_result.status == TradeStatus.FAILED
        assert confirm_result.execution_result is not None
        assert confirm_result.execution_result["error"] == "confirmation_expired"
        mock_execute.assert_not_awaited()
        assert pending_result.trade_id not in _pending_trades

    async def test_confirm_trade_rechecks_risk_before_execution(self, service):
        """A confirmation must be rejected if current risk no longer passes."""
        from app.schemas.ai_trading import TradeConfirmRequest

        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=1,
            price=3500,
            confidence=0.9,
            risk_level=RiskLevel.HIGH,
        )

        with (
            patch(
                "app.services.ai_trading_service.parse_trading_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch.object(
                service,
                "_resolve_trading_context",
                new_callable=AsyncMock,
                return_value={"account_balance": 100000.0, "current_positions": []},
            ),
        ):
            request = AITradingRequest(
                message="买入1手螺纹钢", account_id="paper-001", dry_run=True
            )
            pending_result = await service.process_trading_request("user1", request)

        service.risk_guard.config.max_single_trade_amount = 1000.0
        with (
            patch.object(
                service,
                "_resolve_trading_context",
                new_callable=AsyncMock,
                return_value={"account_balance": 100000.0, "current_positions": []},
            ),
            patch.object(service, "_execute_trade", new_callable=AsyncMock) as mock_execute,
        ):
            confirm_result = await service.confirm_trade(
                "user1",
                TradeConfirmRequest(trade_id=pending_result.trade_id, confirmed=True),
            )

        assert confirm_result.status == TradeStatus.REJECTED
        assert confirm_result.execution_result is not None
        assert confirm_result.execution_result["error"] == "risk_recheck_failed"
        mock_execute.assert_not_awaited()

    async def test_reject_trade(self, service):
        """Rejecting a pending trade should cancel it."""
        from app.schemas.ai_trading import TradeConfirmRequest

        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=1,
            price=3500,
            confidence=0.9,
            risk_level=RiskLevel.HIGH,
        )

        with (
            patch(
                "app.services.ai_trading_service.parse_trading_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch.object(
                service,
                "_resolve_trading_context",
                new_callable=AsyncMock,
                return_value={"account_balance": 100000.0, "current_positions": []},
            ),
        ):
            request = AITradingRequest(
                message="买入1手螺纹钢", account_id="paper-001", dry_run=True
            )
            pending_result = await service.process_trading_request("user1", request)

        confirm_req = TradeConfirmRequest(
            trade_id=pending_result.trade_id,
            confirmed=False,
        )
        confirm_result = await service.confirm_trade("user1", confirm_req)
        assert confirm_result.status == TradeStatus.CANCELLED

    async def test_confirm_nonexistent_trade(self, service):
        """Confirming a non-existent trade should fail."""
        from app.schemas.ai_trading import TradeConfirmRequest

        confirm_req = TradeConfirmRequest(
            trade_id="nonexistent",
            confirmed=True,
        )
        result = await service.confirm_trade("user1", confirm_req)
        assert result.status == TradeStatus.FAILED
        assert "不存在" in result.message

    async def test_confirm_wrong_user(self, service):
        """Confirming another user's trade should fail."""
        from app.schemas.ai_trading import TradeConfirmRequest

        mock_intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="rb2501",
            quantity=1,
            price=3500,
            confidence=0.9,
            risk_level=RiskLevel.HIGH,
        )

        with (
            patch(
                "app.services.ai_trading_service.parse_trading_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch.object(
                service,
                "_resolve_trading_context",
                new_callable=AsyncMock,
                return_value={"account_balance": 100000.0, "current_positions": []},
            ),
        ):
            request = AITradingRequest(
                message="买入1手螺纹钢", account_id="paper-001", dry_run=True
            )
            pending_result = await service.process_trading_request("user1", request)

        confirm_req = TradeConfirmRequest(
            trade_id=pending_result.trade_id,
            confirmed=True,
        )
        result = await service.confirm_trade("user2", confirm_req)
        assert result.status == TradeStatus.FAILED
        assert "无权" in result.message


class TestRiskGuardEdgeCases:
    """Test edge cases in the risk guard."""

    def setup_method(self):
        self.guard = TradingRiskGuard(
            TradingRiskConfig(
                max_single_trade_amount=10000,
                max_daily_trades=50,
                require_confirmation_above=5000,
                min_confidence_threshold=0.3,
                allowed_exchanges=["ctp", "binance", "okx"],
            )
        )

    def test_exchange_not_in_whitelist(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="AAPL",
            exchange="nasdaq",
            quantity=10,
            confidence=0.8,
        )
        result = self.guard.assess(intent)
        assert result.approved is False
        assert "不在允许列表" in result.blocked_reasons[0]

    def test_exchange_in_whitelist(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTCUSDT",
            exchange="binance",
            quantity=0.1,
            confidence=0.8,
            risk_level=RiskLevel.LOW,
        )
        result = self.guard.assess(intent)
        assert result.approved is True

    def test_close_action_without_quantity(self):
        """Close action should still work without quantity."""
        intent = TradingIntent(
            action=TradeAction.CLOSE,
            symbol="rb2501",
            quantity=None,
            confidence=0.8,
        )
        result = self.guard.assess(intent)
        # Close doesn't require quantity in the same way buy/sell does
        assert result.approved is True

    def test_position_impact_description(self):
        intent = TradingIntent(
            action=TradeAction.BUY,
            symbol="BTCUSDT",
            quantity=0.5,
            confidence=0.8,
            risk_level=RiskLevel.LOW,
        )
        positions = [{"symbol": "BTCUSDT", "size": 1.0}]
        result = self.guard.assess(intent, current_positions=positions)
        assert result.position_impact is not None
        assert "增加" in result.position_impact

    def test_position_impact_matches_symbol_alias_and_skips_zero(self):
        intent = TradingIntent(
            action=TradeAction.SELL,
            symbol="BTCUSDT",
            quantity=0.25,
            confidence=0.8,
            risk_level=RiskLevel.LOW,
        )
        positions = [
            {"symbol": "BTC-USDT", "size": 0},
            {"symbol": "BTC/USDT", "size": 0.5},
        ]

        result = self.guard.assess(intent, current_positions=positions)

        assert result.position_impact is not None
        assert "当前持仓 0.5" in result.position_impact
        assert "减少" in result.position_impact

    def test_record_trade_increments_counter(self):
        assert self.guard._daily_trade_count == 0
        self.guard.record_trade(profit_loss=-100)
        assert self.guard._daily_trade_count == 1
        assert self.guard._daily_loss == 100


class TestConditionalOrders:
    """Test conditional order management."""

    def test_create_conditional_order(self):
        from app.services.ai_trading_service import ConditionalOrderManager

        manager = ConditionalOrderManager()
        result = manager.create_conditional_order(
            user_id="user1",
            condition="BTC跌到60000",
            action_message="买入0.1个BTC",
            dry_run=True,
            expiry_hours=24.0,
        )
        assert result["id"]
        assert result["status"] == "active"
        assert result["condition"] == "BTC跌到60000"
        assert result["action_message"] == "买入0.1个BTC"

    def test_list_conditional_orders(self):
        from app.services.ai_trading_service import ConditionalOrderManager, _conditional_orders

        _conditional_orders.clear()
        manager = ConditionalOrderManager()

        manager.create_conditional_order("user1", "条件A", "动作A")
        manager.create_conditional_order("user1", "条件B", "动作B")
        manager.create_conditional_order("user2", "条件C", "动作C")

        user1_orders = manager.list_conditional_orders("user1")
        assert len(user1_orders) == 2

        user2_orders = manager.list_conditional_orders("user2")
        assert len(user2_orders) == 1

    def test_cancel_conditional_order(self):
        from app.services.ai_trading_service import ConditionalOrderManager, _conditional_orders

        _conditional_orders.clear()
        manager = ConditionalOrderManager()

        result = manager.create_conditional_order("user1", "条件", "动作")
        order_id = result["id"]

        # Cancel by owner
        assert manager.cancel_conditional_order(order_id, "user1") is True
        orders = manager.list_conditional_orders("user1")
        assert orders[0]["status"] == "cancelled"

    def test_cancel_wrong_user(self):
        from app.services.ai_trading_service import ConditionalOrderManager, _conditional_orders

        _conditional_orders.clear()
        manager = ConditionalOrderManager()

        result = manager.create_conditional_order("user1", "条件", "动作")
        order_id = result["id"]

        # Cannot cancel another user's order
        assert manager.cancel_conditional_order(order_id, "user2") is False

    def test_expire_old_orders(self):
        from app.services.ai_trading_service import ConditionalOrderManager, _conditional_orders

        _conditional_orders.clear()
        manager = ConditionalOrderManager()

        # Create an order that's already expired
        manager.create_conditional_order("user1", "条件", "动作", expiry_hours=0.0)

        # Listing should mark it as expired
        import time

        time.sleep(0.01)  # Ensure time passes
        orders = manager.list_conditional_orders("user1")
        assert orders[0]["status"] == "expired"
