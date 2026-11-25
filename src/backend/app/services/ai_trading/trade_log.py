"""Durable trade-log persistence helper for AITradingService."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db.database import async_session_maker
from app.models.ai_trading import AITradingLog
from app.schemas.ai_trading import (
    AITradingRequest,
    RiskAssessment,
    TradeStatus,
    TradingIntent,
)

logger = logging.getLogger(__name__)

_TERMINAL_OR_ACTIVE_CONFIRMED_STATUSES = frozenset(
    {
        TradeStatus.CONFIRMED,
        TradeStatus.CANCELLED,
        TradeStatus.REJECTED,
        TradeStatus.FILLED,
        TradeStatus.PARTIALLY_FILLED,
        TradeStatus.EXECUTING,
        TradeStatus.FAILED,
    }
)
_EXECUTED_STATUSES = frozenset(
    {
        TradeStatus.FILLED,
        TradeStatus.PARTIALLY_FILLED,
        TradeStatus.EXECUTING,
    }
)


async def persist_ai_trade_log(
    *,
    trade_id: str,
    user_id: str,
    request: AITradingRequest,
    intent: TradingIntent,
    risk_assessment: RiskAssessment,
    status: TradeStatus,
    execution_result: dict[str, Any] | None = None,
    session_maker: Any = async_session_maker,
) -> None:
    """Insert or update an ``AITradingLog`` row keyed by ``(trade_id, user_id)``."""
    now = datetime.now(timezone.utc)
    executed_at = now if status in _EXECUTED_STATUSES else None
    confirmed_at = now if status in _TERMINAL_OR_ACTIVE_CONFIRMED_STATUSES else None

    try:
        async with session_maker() as session:
            existing = (
                await session.execute(
                    select(AITradingLog).where(
                        AITradingLog.trade_id == trade_id,
                        AITradingLog.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.risk_approved = risk_assessment.approved
                existing.risk_warnings = risk_assessment.warnings
                existing.risk_blocked_reasons = risk_assessment.blocked_reasons
                existing.status = status.value
                existing.execution_result = execution_result
                if confirmed_at is not None and existing.confirmed_at is None:
                    existing.confirmed_at = confirmed_at
                if executed_at is not None and existing.executed_at is None:
                    existing.executed_at = executed_at
            else:
                session.add(
                    AITradingLog(
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
                        confirmed_at=confirmed_at,
                        executed_at=executed_at,
                    )
                )
            await session.commit()
    except Exception as exc:
        logger.warning("Failed to persist trade log: %s", exc)


async def get_ai_trading_history(
    user_id: str,
    limit: int = 20,
    *,
    session_maker: Any = async_session_maker,
) -> list[dict[str, Any]]:
    """Return persisted AI trade history rows for ``user_id`` ordered newest first."""
    try:
        async with session_maker() as session:
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
    except Exception as exc:
        logger.warning("Failed to fetch trading history: %s", exc)
        return []


def generate_simple_reflection(log: AITradingLog) -> str:
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


async def generate_ai_trade_reflection(
    trade_id: str,
    user_id: str,
    *,
    session_maker: Any = async_session_maker,
) -> dict[str, Any]:
    """Generate and persist reflection text for a completed user trade."""
    try:
        async with session_maker() as session:
            result = await session.execute(
                select(AITradingLog).where(
                    AITradingLog.trade_id == trade_id,
                    AITradingLog.user_id == user_id,
                )
            )
            log = result.scalar_one_or_none()
            if not log:
                return {"success": False, "message": "交易记录不存在"}

            reflection_text = generate_simple_reflection(log)
            log.reflection = reflection_text
            await session.commit()
            return {"success": True, "trade_id": trade_id, "reflection": reflection_text}
    except Exception as exc:
        logger.warning("Failed to generate reflection: %s", exc)
        return {"success": False, "message": f"反思生成失败: {exc}"}
