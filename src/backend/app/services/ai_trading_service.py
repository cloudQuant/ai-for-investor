"""AI Trading Service: orchestrates natural language trading execution.

This is the main entry point for the natural language trading feature.
It coordinates intent parsing, risk assessment, and order execution.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.db.database import async_session_maker
from app.models.ai_trading import AITradingLog
from app.schemas.ai_trading import (
    AITradingRequest,
    AITradingResponse,
    RiskAssessment,
    RiskLevel,
    TradeConfirmRequest,
    TradeConfirmResponse,
    TradeStatus,
    TradingIntent,
)
from app.services.ai_trading.conditional_orders import (
    ConditionalOrderManager,
    _conditional_orders,
    get_conditional_order_manager,
)
from app.services.ai_trading.messages import (
    build_confirmation_message as _build_confirmation_message,
)
from app.services.ai_trading.messages import (
    build_dry_run_message as _build_dry_run_message,
)
from app.services.ai_trading.messages import (
    build_execution_message as _build_execution_message,
)
from app.services.ai_trading.messages import (
    build_market_context as _build_market_context,
)
from app.services.ai_trading.messages import (
    build_rejection_message as _build_rejection_message,
)
from app.services.ai_trading.messages import (
    build_suggestions as _build_suggestions,
)
from app.services.service_read.client import ServiceReadUnavailableError
from app.services.service_read.contracts import AccountReadView, ReadQuality
from app.services.trading_asset_info_service import (
    query_local_asset_spec,
)
from app.services.trading_intent_parser import parse_trading_intent
from app.services.trading_risk_guard import TradingRiskConfig, TradingRiskGuard

logger = logging.getLogger(__name__)

# In-memory store for pending trades (production should use DB)
_pending_trades: dict[str, dict[str, Any]] = {}
PENDING_TRADE_TTL_SECONDS = 300
_UNVERIFIED_LIVE_ASSET_KEYS = frozenset(
    {
        "contract_value",
        "contractValue",
        "contract_value_amount",
        "contractValueAmount",
        "contract_notional_value",
        "okx_contract_value",
        "ctVal",
        "multiplier",
        "mult",
        "contract_multiplier",
        "contract_size",
        "trade_contract_size",
        "ctMult",
        "VolumeMultiple",
        "CONTRACT_MULTIPLIER",
        "contract_type",
        "ctType",
        "contractType",
        "category",
        "ctValCcy",
        "contract_value_currency",
        "contract_value_ccy",
        "contractValueCurrency",
        "inverse",
        "inverse_contract",
        "inverseContract",
        "base_asset",
        "baseCcy",
        "quote_asset",
        "quoteCcy",
        "settle_currency",
        "settleCcy",
        "fee_currency",
        "feeCcy",
        "is_inverse",
        "isInverse",
    }
)

# Global risk guard instance
_risk_guard: TradingRiskGuard | None = None


class MissingGatewayContextError(ValueError):
    """Raised when AI trading execution lacks a valid account or gateway context."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_risk_guard() -> TradingRiskGuard:
    """Get or create the global risk guard instance."""
    global _risk_guard
    if _risk_guard is None:
        _risk_guard = TradingRiskGuard(TradingRiskConfig())
    return _risk_guard


class AITradingService:
    """Orchestrates the natural language → trade execution pipeline."""

    def __init__(self) -> None:
        self.risk_guard = get_risk_guard()

    async def process_trading_request(
        self,
        user_id: str,
        request: AITradingRequest,
    ) -> AITradingResponse:
        """Process a natural language trading request.

        Pipeline:
        1. Parse natural language → TradingIntent
        2. Enrich with market context
        3. Risk assessment
        4. Execute or queue for confirmation

        Args:
            user_id: The authenticated user's ID.
            request: The trading request with natural language message.

        Returns:
            AITradingResponse with intent, risk assessment, and status.
        """
        trade_id = str(uuid.uuid4())[:12]

        # Step 1: Parse intent
        intent = await parse_trading_intent(
            user_input=request.message,
            market_context=self._build_market_context(request),
        )

        context = await self._resolve_trading_context(user_id=user_id, request=request)
        self._record_account_read_provenance(intent, context)
        if context.get("degraded"):
            diagnostic_message = str(context.get("diagnostic_message") or "交易上下文不可用")
            degraded_risk = self._build_degraded_risk_assessment(diagnostic_message)
            return AITradingResponse(
                trade_id=trade_id,
                intent=intent,
                risk_assessment=degraded_risk,
                status=TradeStatus.REJECTED,
                message=f"⚠️ 交易上下文不可用，已停止自动交易: {diagnostic_message}",
                ai_reasoning=intent.reason,
                suggestions=[
                    "请先在交易页面补齐可用账户或已连接网关后再重试",
                    *self._build_suggestions(intent, degraded_risk),
                ],
                degraded=True,
                diagnostic_message=diagnostic_message,
            )

        if not self._enrich_intent_with_asset_spec(intent, request):
            diagnostic_message = "缺少可验证的本地资产乘数，无法安全估算实盘风险。"
            if not request.dry_run:
                degraded_risk = self._build_degraded_risk_assessment(diagnostic_message)
                return AITradingResponse(
                    trade_id=trade_id,
                    intent=intent,
                    risk_assessment=degraded_risk,
                    status=TradeStatus.REJECTED,
                    message=f"⚠️ 交易上下文不可用，已停止自动交易: {diagnostic_message}",
                    ai_reasoning=intent.reason,
                    suggestions=self._build_suggestions(intent, degraded_risk),
                    degraded=True,
                    diagnostic_message=diagnostic_message,
                )

        # Step 2: Risk assessment
        risk_assessment = self.risk_guard.assess(
            intent=intent,
            account_balance=float(context.get("account_balance") or 0.0),
            current_positions=context.get("current_positions"),
        )

        # Step 3: Determine action based on risk assessment
        if not risk_assessment.approved:
            return AITradingResponse(
                trade_id=trade_id,
                intent=intent,
                risk_assessment=risk_assessment,
                status=TradeStatus.REJECTED,
                message=self._build_rejection_message(risk_assessment),
                ai_reasoning=intent.reason,
                suggestions=self._build_suggestions(intent, risk_assessment),
            )

        # Step 4: Check if confirmation is needed
        if risk_assessment.requires_confirmation and not request.auto_confirm:
            # Store pending trade for later confirmation
            created_at = _utc_now()
            expires_at = created_at + timedelta(seconds=PENDING_TRADE_TTL_SECONDS)
            _pending_trades[trade_id] = {
                "user_id": user_id,
                "intent": intent.model_dump(),
                "risk_assessment": risk_assessment.model_dump(),
                "request": request.model_dump(),
                "created_at": created_at.isoformat(),
                "expires_at": expires_at.isoformat(),
            }

            # Push WebSocket notification for real-time confirmation
            await self._notify_confirmation_needed(trade_id, intent, risk_assessment)

            return AITradingResponse(
                trade_id=trade_id,
                intent=intent,
                risk_assessment=risk_assessment,
                status=TradeStatus.PENDING_CONFIRMATION,
                message=self._build_confirmation_message(intent, risk_assessment),
                ai_reasoning=intent.reason,
                requires_confirmation=True,
                suggestions=self._build_suggestions(intent, risk_assessment),
            )

        # Step 5: Execute trade
        if request.dry_run:
            return AITradingResponse(
                trade_id=trade_id,
                intent=intent,
                risk_assessment=risk_assessment,
                status=TradeStatus.CONFIRMED,
                message=self._build_dry_run_message(intent),
                ai_reasoning=intent.reason,
                execution_result={"dry_run": True, "would_execute": intent.model_dump()},
                suggestions=self._build_suggestions(intent, risk_assessment),
            )

        # Real execution
        execution_result = await self._execute_trade(
            user_id, intent, request, operation_id=trade_id
        )
        status = self._execution_status(execution_result)

        return AITradingResponse(
            trade_id=trade_id,
            intent=intent,
            risk_assessment=risk_assessment,
            status=status,
            message=self._build_execution_message(intent, execution_result),
            ai_reasoning=intent.reason,
            execution_result=execution_result,
            suggestions=self._build_suggestions(intent, risk_assessment),
        )

    async def confirm_trade(
        self,
        user_id: str,
        request: TradeConfirmRequest,
    ) -> TradeConfirmResponse:
        """Confirm or reject a pending trade.

        Args:
            user_id: The authenticated user's ID.
            request: Confirmation request with trade_id and decision.

        Returns:
            TradeConfirmResponse with execution result.
        """
        pending = _pending_trades.get(request.trade_id)
        if not pending:
            return TradeConfirmResponse(
                trade_id=request.trade_id,
                status=TradeStatus.FAILED,
                message="交易不存在或已过期",
            )

        if pending["user_id"] != user_id:
            return TradeConfirmResponse(
                trade_id=request.trade_id,
                status=TradeStatus.FAILED,
                message="无权操作此交易",
            )

        if not request.confirmed:
            del _pending_trades[request.trade_id]
            return TradeConfirmResponse(
                trade_id=request.trade_id,
                status=TradeStatus.CANCELLED,
                message="交易已取消",
            )

        intent = TradingIntent(**pending["intent"])
        original_request = AITradingRequest(**pending["request"])
        if self._pending_trade_expired(pending):
            del _pending_trades[request.trade_id]
            return TradeConfirmResponse(
                trade_id=request.trade_id,
                status=TradeStatus.FAILED,
                message="确认已过期，请重新提交交易请求。",
                execution_result={
                    "success": False,
                    "error": "confirmation_expired",
                    "expires_at": pending.get("expires_at"),
                },
            )

        try:
            current_risk = await self._reassess_confirmed_trade(
                user_id=user_id,
                intent=intent,
                request=original_request,
            )
        except MissingGatewayContextError as exc:
            del _pending_trades[request.trade_id]
            diagnostic_message = str(exc)
            return TradeConfirmResponse(
                trade_id=request.trade_id,
                status=TradeStatus.REJECTED,
                message=f"交易上下文不可用，已取消确认执行: {diagnostic_message}",
                execution_result={
                    "success": False,
                    "error": "context_unavailable",
                    "message": diagnostic_message,
                },
            )

        if not current_risk.approved:
            del _pending_trades[request.trade_id]
            return TradeConfirmResponse(
                trade_id=request.trade_id,
                status=TradeStatus.REJECTED,
                message=self._build_rejection_message(current_risk),
                execution_result={
                    "success": False,
                    "error": "risk_recheck_failed",
                    "risk_assessment": current_risk.model_dump(),
                },
            )

        # Remove from pending immediately before execution to prevent double-submit.
        del _pending_trades[request.trade_id]

        execution_result = await self._execute_trade(
            user_id, intent, original_request, operation_id=request.trade_id
        )
        status = self._execution_status(execution_result)

        return TradeConfirmResponse(
            trade_id=request.trade_id,
            status=status,
            message=self._build_execution_message(intent, execution_result),
            execution_result=execution_result,
        )

    def _pending_trade_expired(self, pending: dict[str, Any]) -> bool:
        expires_at = _parse_datetime(pending.get("expires_at"))
        if expires_at is None:
            created_at = _parse_datetime(pending.get("created_at"))
            if created_at is None:
                return True
            expires_at = created_at + timedelta(seconds=PENDING_TRADE_TTL_SECONDS)
        return _utc_now() >= expires_at

    async def _reassess_confirmed_trade(
        self,
        *,
        user_id: str,
        intent: TradingIntent,
        request: AITradingRequest,
    ) -> RiskAssessment:
        context = await self._resolve_trading_context(user_id=user_id, request=request)
        self._record_account_read_provenance(intent, context)
        if context.get("degraded"):
            diagnostic_message = str(context.get("diagnostic_message") or "交易上下文不可用")
            raise MissingGatewayContextError(diagnostic_message)

        if self._enrich_intent_with_asset_spec(intent, request) is False:
            raise MissingGatewayContextError("缺少可验证的本地资产乘数，无法安全估算实盘风险。")
        return self.risk_guard.assess(
            intent=intent,
            account_balance=float(context.get("account_balance") or 0.0),
            current_positions=context.get("current_positions"),
        )

    async def _execute_trade(
        self,
        user_id: str,
        intent: TradingIntent,
        request: AITradingRequest,
        *,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a trade through the appropriate execution channel.

        Routes to paper trading or live trading based on dry_run flag.
        """
        try:
            if request.dry_run:
                # Use paper trading system
                from app.services.direct_order_service import DirectOrderService

                order_service = DirectOrderService()
                return await order_service.execute_paper_trade(
                    intent=intent,
                    user_id=user_id,
                    account_id=request.account_id,
                    operation_id=operation_id,
                )
            else:
                # AI live submission requires an explicit service-v2 scope and
                # durable operation key; the legacy gateway selector is not a
                # safe substitute for either value.
                return {
                    "success": False,
                    "type": "live_trade",
                    "error": "service_v2_unavailable",
                    "reason": "service_v2_scope_not_configured",
                    "submitted": False,
                    "message": "实盘交易暂不可用：尚未配置 service-v2 执行范围，订单未提交。",
                }
        except Exception as e:
            logger.error("Trade execution failed: %s", e, exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "message": f"交易执行失败: {e}",
            }

    @staticmethod
    def _execution_status(result: dict[str, Any]) -> TradeStatus:
        """Preserve the durable managed state instead of treating an ack as a fill."""
        state = result.get("state")
        if result.get("type") == "managed_paper_trade" and isinstance(state, str):
            return {
                "PENDING_ADMISSION": TradeStatus.EXECUTING,
                "PENDING_DISPATCH": TradeStatus.EXECUTING,
                "DISPATCHING": TradeStatus.EXECUTING,
                "FILLED": TradeStatus.FILLED,
                "PARTIALLY_FILLED": TradeStatus.PARTIALLY_FILLED,
                "REJECTED": TradeStatus.REJECTED,
                "BLOCKED": TradeStatus.REJECTED,
                "CANCELLED": TradeStatus.CANCELLED,
                "ACKED": TradeStatus.EXECUTING,
                "UNKNOWN": TradeStatus.EXECUTING,
            }.get(state, TradeStatus.EXECUTING)
        return TradeStatus.FILLED if result.get("success") else TradeStatus.FAILED

    async def _persist_trade_log(
        self,
        trade_id: str,
        user_id: str,
        request: AITradingRequest,
        intent: TradingIntent,
        risk_assessment: RiskAssessment,
        status: TradeStatus,
        execution_result: dict[str, Any] | None = None,
    ) -> None:
        """Persist a trade log entry to the database."""
        try:
            async with async_session_maker() as session:
                log_entry = AITradingLog(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    trade_id=trade_id,
                    user_input=request.message,
                    action=intent.action.value,
                    symbol=intent.symbol,
                    exchange=intent.exchange,
                    quantity=intent.quantity,
                    price=intent.price,
                    order_type=intent.order_type.value,
                    stop_loss=intent.stop_loss,
                    take_profit=intent.take_profit,
                    confidence=intent.confidence,
                    risk_level=intent.risk_level.value,
                    risk_approved=risk_assessment.approved,
                    risk_warnings=risk_assessment.warnings,
                    risk_blocked_reasons=risk_assessment.blocked_reasons,
                    requires_confirmation=risk_assessment.requires_confirmation,
                    status=status.value,
                    execution_result=execution_result,
                    gateway_id=request.gateway_id,
                    dry_run=request.dry_run,
                    ai_reasoning=intent.reason,
                )
                session.add(log_entry)
                await session.commit()
        except Exception as e:
            logger.warning("Failed to persist trade log: %s", e)

    async def _resolve_trading_context(
        self,
        user_id: str,
        request: AITradingRequest,
    ) -> dict[str, Any]:
        """Resolve account or gateway context for risk assessment.

        Returns a context dictionary with real account balance and positions.
        When live gateway data is unavailable but a gateway is selected, returns a
        degraded context instead of silently falling back to fake values.
        """
        if request.dry_run:
            return await self._resolve_paper_trading_context(
                user_id=user_id,
                account_id=request.account_id,
            )
        return await self._resolve_live_trading_context(
            subject=user_id,
            account_ref=request.gateway_id,
        )

    async def _resolve_paper_trading_context(
        self,
        user_id: str,
        account_id: str | None,
    ) -> dict[str, Any]:
        """Load real paper-trading account balance and positions."""
        if not account_id:
            raise MissingGatewayContextError(
                "模拟交易必须提供有效的 paper trading 账户 account_id。"
            )

        from app.services.paper_trading_service import PaperTradingService

        service = PaperTradingService()
        account = await service.get_account(account_id)
        if account is None or account.user_id != user_id or not account.is_active:
            raise MissingGatewayContextError(
                "未找到当前用户可用的模拟交易账户，请先选择有效的 account_id。"
            )

        positions, _ = await service.list_positions(
            filters={"account_id": account.id},
            limit=200,
            offset=0,
        )
        return {
            "account_balance": float(account.total_equity),
            "current_positions": [
                {"symbol": position.symbol, "size": position.size} for position in positions
            ],
        }

    async def _resolve_live_trading_context(
        self, subject: str, account_ref: str | None
    ) -> dict[str, Any]:
        """Read fresh, complete provider facts from the subject's service grant."""

        if not account_ref:
            raise MissingGatewayContextError(
                "实盘 AI 风险评估必须选择服务端授权的 service-v2 account_ref。"
            )
        from app.api.service_read import read_authorized_service_account

        try:
            view = await read_authorized_service_account(subject, account_ref)
        except ServiceReadUnavailableError as error:
            status = self._safe_service_read_status(error.code)
            return self._build_degraded_context(
                f"service-v2 账户读取不可用 ({status})，已停止自动交易。",
                read_status=status,
                read_provenance=self._unavailable_account_read_provenance(account_ref, status),
            )
        except Exception as error:  # noqa: BLE001 - retain only a finite diagnostic
            code = self._safe_service_read_status(getattr(error, "code", None))
            return self._build_degraded_context(
                f"service-v2 账户读取失败 ({code})，已停止自动交易。",
                read_status=code,
                read_provenance=self._unavailable_account_read_provenance(account_ref, code),
            )

        if type(view) is not AccountReadView or view.account_ref != account_ref:
            return self._build_degraded_context(
                "service-v2 返回的账户视图与授权账户不匹配。",
                read_status="ACCOUNT_VIEW_MISMATCH",
                read_provenance=self._unavailable_account_read_provenance(
                    account_ref, "ACCOUNT_VIEW_MISMATCH"
                ),
            )
        observation = view.provider_observation
        if view.quality is not ReadQuality.FRESH:
            return self._build_degraded_context(
                "service-v2 账户快照已过期或尚未采集，已停止自动交易。",
                read_status=view.quality.value,
                read_provenance=self._account_read_provenance(view, observation, available=False),
            )
        if (
            not isinstance(observation, Mapping)
            or observation.get("balances_complete") is not True
            or observation.get("positions_complete") is not True
        ):
            return self._build_degraded_context(
                "service-v2 账户快照未证明余额与持仓完整，已停止自动交易。",
                read_status="ACCOUNT_OBSERVATION_INCOMPLETE",
                read_provenance=self._account_read_provenance(view, observation, available=False),
            )
        if view.value is None:
            return self._build_degraded_context(
                "service-v2 未返回该账户币种的权益值，已停止自动交易。",
                read_status="ACCOUNT_EQUITY_NOT_COLLECTED",
                read_provenance=self._account_read_provenance(view, observation, available=False),
            )
        try:
            account_balance = float(view.value)
        except (TypeError, ValueError, OverflowError):
            account_balance = float("nan")
        if not math.isfinite(account_balance) or account_balance <= 0:
            return self._build_degraded_context(
                "service-v2 账户权益值不可用于风险估算，已停止自动交易。",
                read_status="INVALID_ACCOUNT_EQUITY",
                read_provenance=self._account_read_provenance(view, observation, available=False),
            )

        try:
            positions = self._service_positions(observation.get("positions"))
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            return self._build_degraded_context(
                "service-v2 持仓数量无法安全映射到 AI 风险模型。",
                read_status="INVALID_ACCOUNT_POSITIONS",
                read_provenance=self._account_read_provenance(view, observation, available=False),
            )
        return {
            "account_balance": account_balance,
            "current_positions": positions,
            "currency": view.currency,
            "read_status": "FRESH",
            "read_provenance": self._account_read_provenance(view, observation, available=True),
        }

    def _build_degraded_context(
        self,
        diagnostic_message: str,
        *,
        read_status: str | None = None,
        read_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a degraded context marker with a diagnostic message."""
        result = {
            "degraded": True,
            "diagnostic_message": diagnostic_message,
        }
        if read_status is not None:
            result["read_status"] = read_status
        if read_provenance is not None:
            result["read_provenance"] = read_provenance
        return result

    def _service_positions(self, raw_positions: Any) -> list[dict[str, Any]]:
        """Map complete typed provider positions without changing their units."""

        if type(raw_positions) is not tuple:
            raise ValueError("invalid positions")
        positions: list[dict[str, Any]] = []
        for row in raw_positions:
            if not isinstance(row, Mapping):
                raise ValueError("invalid position row")
            instrument = row.get("instrument")
            if not isinstance(instrument, Mapping):
                raise ValueError("invalid instrument")
            symbol = instrument.get("native_symbol")
            if type(symbol) is not str or not symbol:
                raise ValueError("missing symbol")
            quantity = Decimal(str(row.get("quantity")))
            size = float(quantity)
            if not math.isfinite(size):
                raise ValueError("invalid quantity")
            side = row.get("side")
            if side == "long":
                size = abs(size)
            elif side == "short":
                size = -abs(size)
            elif side != "net":
                raise ValueError("invalid side")
            if abs(size) <= 1e-12:
                continue
            positions.append(
                {
                    "symbol": symbol,
                    "size": size,
                    "qty_unit": row.get("qty_unit"),
                    "observed_at_utc": row.get("observed_at_utc"),
                }
            )
        return positions

    def _account_read_provenance(
        self, view: AccountReadView, observation: Any, *, available: bool
    ) -> dict[str, Any]:
        completed_at = (
            observation.get("completed_at_utc") if isinstance(observation, Mapping) else None
        )
        return {
            "source": "service-v2.account.snapshot",
            "account_ref": view.account_ref,
            "status": view.quality.value,
            "available": available,
            "account_key_id": view.account_key_id,
            "currency": view.currency,
            "quality": view.quality.value,
            "observed_at_utc": view.observed_at_utc or completed_at,
            "received_age_seconds": view.received_age_seconds,
            "session_generation": view.session_generation,
            "positions_complete": (
                observation.get("positions_complete") is True
                if isinstance(observation, Mapping)
                else False
            ),
            "balances_complete": (
                observation.get("balances_complete") is True
                if isinstance(observation, Mapping)
                else False
            ),
        }

    @staticmethod
    def _unavailable_account_read_provenance(account_ref: str, status: str) -> dict[str, Any]:
        return {
            "source": "service-v2.account.snapshot",
            "account_ref": account_ref,
            "status": status,
            "available": False,
        }

    @staticmethod
    def _safe_service_read_status(value: Any) -> str:
        if type(value) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value):
            return value
        return "SERVICE_READ_FAILED"

    def _record_account_read_provenance(
        self, intent: TradingIntent, context: dict[str, Any]
    ) -> None:
        provenance = context.get("read_provenance")
        if not isinstance(provenance, dict):
            read_status = context.get("read_status")
            if type(read_status) is not str:
                return
            provenance = {
                "source": "service-v2.account.snapshot",
                "status": self._safe_service_read_status(read_status),
                "available": False,
            }
        params = dict(intent.additional_params or {})
        params["service_read_account"] = dict(provenance)
        intent.additional_params = params

    def _build_degraded_risk_assessment(self, diagnostic_message: str) -> RiskAssessment:
        """Build a rejected risk assessment for degraded responses."""
        return RiskAssessment(
            approved=False,
            risk_level=RiskLevel.HIGH,
            warnings=[diagnostic_message],
            blocked_reasons=[diagnostic_message],
            requires_confirmation=False,
        )

    def _enrich_intent_with_asset_spec(
        self,
        intent: TradingIntent,
        request: AITradingRequest,
    ) -> bool:
        """Attach asset specs before risk checks use notional values."""
        if not intent.symbol:
            if not request.dry_run:
                self._clear_unverified_live_asset_spec(intent)
            return request.dry_run
        if request.dry_run:
            try:
                asset_spec = query_local_asset_spec(intent.symbol)
            except Exception as exc:
                logger.debug("Failed to enrich AI paper intent with local asset spec: %s", exc)
                return True
        else:
            # Never let parser/LLM guesses survive merely because a local spec
            # supplies only some of the asset fields.
            self._clear_unverified_live_asset_spec(intent)
            try:
                asset_spec = query_local_asset_spec(intent.symbol)
            except Exception as exc:
                logger.debug("Failed to read local AI live asset spec: %s", type(exc).__name__)
                self._clear_unverified_live_asset_spec(intent)
                return False
        if not isinstance(asset_spec, dict) or not asset_spec:
            if not request.dry_run:
                self._clear_unverified_live_asset_spec(intent)
            return request.dry_run

        multiplier_keys = (
            "contract_value",
            "contractValue",
            "contract_value_amount",
            "contractValueAmount",
            "contract_notional_value",
            "okx_contract_value",
            "ctVal",
            "multiplier",
            "mult",
            "contract_multiplier",
            "contract_size",
            "trade_contract_size",
            "ctMult",
            "VolumeMultiple",
            "CONTRACT_MULTIPLIER",
        )
        has_multiplier = False
        for key in multiplier_keys:
            multiplier = self._coerce_optional_float(asset_spec.get(key))
            if multiplier is not None and math.isfinite(multiplier) and multiplier > 0:
                has_multiplier = True
                break
        if not request.dry_run and not has_multiplier:
            self._clear_unverified_live_asset_spec(intent)
            return False

        params = dict(intent.additional_params or {})
        for key, value in asset_spec.items():
            if value in (None, ""):
                continue
            params[key] = value
        intent.additional_params = params
        return has_multiplier or request.dry_run

    @staticmethod
    def _clear_unverified_live_asset_spec(intent: TradingIntent) -> None:
        params = dict(intent.additional_params or {})
        for key in _UNVERIFIED_LIVE_ASSET_KEYS:
            params.pop(key, None)
        intent.additional_params = params

    def _enrich_intent_with_live_asset_spec(
        self,
        intent: TradingIntent,
        request: AITradingRequest,
    ) -> bool:
        """Backward-compatible wrapper for live-only callers."""
        return self._enrich_intent_with_asset_spec(intent, request)

    def _coerce_optional_float(self, value: Any) -> float | None:
        """Safely coerce a value to float."""
        if value is None or value == "":
            return None
        if isinstance(value, dict):
            for key in ("amount", "value", "balance", "total"):
                parsed = self._coerce_optional_float(value.get(key))
                if parsed is not None:
                    return parsed
            return None
        try:
            return float(str(value).strip().replace(",", ""))
        except (TypeError, ValueError):
            return None

    async def list_available_accounts(self, user_id: str) -> list[dict[str, Any]]:
        """List selectable paper-trading accounts for the current user."""
        try:
            from app.services.paper_trading_service import PaperTradingService

            service = PaperTradingService()
            accounts, _ = await service.list_accounts(user_id=user_id, limit=100, offset=0)
            return [
                {
                    "account_id": account.id,
                    "name": account.name,
                    "total_equity": float(account.total_equity),
                    "current_cash": float(account.current_cash),
                    "is_active": bool(account.is_active),
                    "source": "paper",
                }
                for account in accounts
            ]
        except Exception as exc:
            logger.debug("Failed to list available paper-trading accounts: %s", exc)
            return []

    def _build_market_context(self, request: AITradingRequest) -> str:
        """Build market context string for intent parsing."""
        return _build_market_context(request)

    def _build_rejection_message(self, risk: RiskAssessment) -> str:
        """Build user-friendly rejection message."""
        return _build_rejection_message(risk)

    def _build_confirmation_message(self, intent: TradingIntent, risk: RiskAssessment) -> str:
        """Build confirmation request message."""
        return _build_confirmation_message(intent, risk)

    def _build_dry_run_message(self, intent: TradingIntent) -> str:
        """Build dry run result message."""
        return _build_dry_run_message(intent)

    def _build_execution_message(self, intent: TradingIntent, result: dict[str, Any]) -> str:
        """Build execution result message."""
        if result.get("type") == "managed_paper_trade":
            state = result.get("state")
            if state in {"UNKNOWN", None}:
                return "托管纸面订单状态未知。请查询该托管订单，核对完成前不要再次提交。"
            if state == "ACKED":
                return "托管纸面订单已受理，等待执行服务更新成交状态。"
            if state == "PARTIALLY_FILLED":
                return "托管纸面订单已部分成交；详情以执行服务记录为准。"
            if state == "REJECTED":
                return "托管纸面执行服务已拒绝此订单。"
            if state == "BLOCKED":
                return "托管纸面风控或执行门禁已阻止此订单。"
            if state == "CANCELLED":
                return "托管纸面订单已取消。"
            if state == "FILLED":
                return "托管纸面订单已成交。"
        return _build_execution_message(intent, result)

    def _build_suggestions(self, intent: TradingIntent, risk: RiskAssessment) -> list[str]:
        """Build actionable suggestions for the user."""
        return _build_suggestions(intent, risk)

    async def _notify_confirmation_needed(
        self,
        trade_id: str,
        intent: TradingIntent,
        risk_assessment: RiskAssessment,
    ) -> None:
        """Push WebSocket notification when a trade requires confirmation."""
        try:
            from app.websocket_manager import manager as ws_manager

            message = {
                "type": "ai_trading_confirmation",
                "trade_id": trade_id,
                "action": intent.action.value,
                "symbol": intent.symbol,
                "quantity": intent.quantity,
                "price": intent.price,
                "risk_level": risk_assessment.risk_level.value,
                "warnings": risk_assessment.warnings,
                "message": (
                    f"AI 交易需要确认: {intent.action.value} {intent.quantity} {intent.symbol}"
                ),
            }
            await ws_manager.broadcast(message)
        except Exception as e:
            logger.debug("WebSocket notification failed (non-critical): %s", e)

    async def get_history(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get trading history for a user.

        Args:
            user_id: The user's ID.
            limit: Maximum number of records.

        Returns:
            List of trade log entries as dicts.
        """
        try:
            from sqlalchemy import select

            async with async_session_maker() as session:
                result = await session.execute(
                    select(AITradingLog)
                    .where(AITradingLog.user_id == user_id)
                    .order_by(AITradingLog.created_at.desc())
                    .limit(limit)
                )
                logs = result.scalars().all()
                return [
                    {
                        "trade_id": log.trade_id,
                        "user_input": log.user_input,
                        "action": log.action,
                        "symbol": log.symbol,
                        "quantity": log.quantity,
                        "price": log.price,
                        "status": log.status,
                        "confidence": log.confidence,
                        "risk_level": log.risk_level,
                        "ai_reasoning": log.ai_reasoning,
                        "dry_run": log.dry_run,
                        "created_at": log.created_at.isoformat() if log.created_at else None,
                        "executed_at": log.executed_at.isoformat() if log.executed_at else None,
                    }
                    for log in logs
                ]
        except Exception as e:
            logger.warning("Failed to fetch trading history: %s", e)
            return []

    async def generate_reflection(
        self,
        trade_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Generate AI reflection on a completed trade.

        Analyzes the trade decision, execution result, and provides
        lessons learned for future improvement.

        Args:
            trade_id: The trade to reflect on.
            user_id: The user's ID.

        Returns:
            Reflection result with analysis and suggestions.
        """
        try:
            from sqlalchemy import select

            async with async_session_maker() as session:
                result = await session.execute(
                    select(AITradingLog).where(
                        AITradingLog.trade_id == trade_id,
                        AITradingLog.user_id == user_id,
                    )
                )
                log = result.scalar_one_or_none()
                if not log:
                    return {"success": False, "message": "交易记录不存在"}

                # Build reflection prompt (for future LLM-based reflection)
                # reflection_context includes trade details for AI analysis
                reflection_text = self._generate_simple_reflection(log)

                # Persist reflection
                log.reflection = reflection_text
                await session.commit()

                return {
                    "success": True,
                    "trade_id": trade_id,
                    "reflection": reflection_text,
                }
        except Exception as e:
            logger.warning("Failed to generate reflection: %s", e)
            return {"success": False, "message": f"反思生成失败: {e}"}

    def _generate_simple_reflection(self, log: AITradingLog) -> str:
        """Generate a simple rule-based reflection without LLM."""
        parts = []

        if log.status == "filled":
            parts.append("✅ 交易已成功执行。")
        elif log.status == "rejected":
            parts.append("⚠️ 交易被风控拦截。")
            if log.risk_blocked_reasons:
                parts.append(f"拦截原因: {', '.join(log.risk_blocked_reasons)}")
        elif log.status == "cancelled":
            parts.append("ℹ️ 交易被用户取消。")

        if log.confidence and log.confidence < 0.5:
            parts.append("建议: 下次尝试更明确地描述交易意图以提高解析准确度。")

        if log.action in ("buy", "sell") and not log.stop_loss:
            parts.append("建议: 考虑设置止损以控制下行风险。")

        return " ".join(parts) if parts else "交易已记录。"

    def build_conversation_context(
        self,
        user_id: str,
        recent_messages: list[dict[str, str]],
    ) -> str:
        """Build conversation context for multi-turn trading dialogue.

        Extracts relevant context from recent messages to help the LLM
        understand follow-up instructions like "再买1手" or "把止损改到3400".

        Args:
            user_id: The user's ID.
            recent_messages: Recent conversation messages.

        Returns:
            Context string to prepend to the intent parsing prompt.
        """
        if not recent_messages:
            return ""

        context_parts = []
        for msg in recent_messages[-5:]:  # Last 5 messages
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                context_parts.append(f"用户: {content}")
            elif role == "assistant":
                # Extract key info from assistant response
                if "买入" in content or "卖出" in content:
                    context_parts.append(f"AI: {content[:100]}")

        if context_parts:
            return "对话上下文:\n" + "\n".join(context_parts) + "\n\n"
        return ""


# ─── Backward-compatible re-exports ──────────────────────────────────────────
# These names used to live in this module; iteration 174 (C9) moved them to
# ``app.services.ai_trading.conditional_orders`` but tests still import them
# from here, so we keep them visible.
__all__ = [
    "AITradingService",
    "ConditionalOrderManager",
    "MissingGatewayContextError",
    "_conditional_orders",
    "_pending_trades",
    "get_conditional_order_manager",
    "get_risk_guard",
]
