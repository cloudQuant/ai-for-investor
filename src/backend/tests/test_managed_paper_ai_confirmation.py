from __future__ import annotations

from typing import Any

import pytest

from app.schemas.ai_trading import (
    AITradingRequest,
    RiskAssessment,
    RiskLevel,
    TradeAction,
    TradeConfirmRequest,
    TradeStatus,
    TradingIntent,
)
from app.services import ai_trading_service as ai_module
from app.services.ai_trading_service import AITradingService


class _RiskGuard:
    def __init__(self, assessments: list[RiskAssessment]) -> None:
        self.assessments = assessments
        self.calls = 0

    def assess(self, **_kwargs: Any) -> RiskAssessment:
        result = self.assessments[self.calls]
        self.calls += 1
        return result


def _approved(*, requires_confirmation: bool = False) -> RiskAssessment:
    return RiskAssessment(
        approved=True,
        risk_level=RiskLevel.LOW,
        requires_confirmation=requires_confirmation,
    )


def _intent() -> TradingIntent:
    return TradingIntent(
        action=TradeAction.BUY,
        symbol="BTCUSDT",
        quantity=0.1,
        confidence=0.9,
    )


async def _parse_intent(**_kwargs: Any) -> TradingIntent:
    return _intent()


@pytest.mark.asyncio
async def test_dry_run_with_selected_paper_account_stays_a_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AITradingService()
    service.risk_guard = _RiskGuard([_approved()])
    monkeypatch.setattr(ai_module, "parse_trading_intent", _parse_intent)

    async def _context(**_kwargs: Any) -> dict[str, Any]:
        return {"account_balance": 100_000, "current_positions": []}

    async def _unexpected_submit(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("dry-run preview must not submit an order")

    monkeypatch.setattr(service, "_resolve_trading_context", _context)
    monkeypatch.setattr(service, "_enrich_intent_with_asset_spec", lambda *_args: None)
    from app.services.direct_order_service import DirectOrderService

    monkeypatch.setattr(DirectOrderService, "execute_paper_trade", _unexpected_submit)

    result = await service.process_trading_request(
        "subject-1",
        AITradingRequest(
            message="buy BTC",
            account_id="legacy-account-1",
            dry_run=True,
        ),
    )

    assert result.execution_result == {"dry_run": True, "would_execute": _intent().model_dump()}
    assert result.status is TradeStatus.CONFIRMED


@pytest.mark.asyncio
async def test_confirmed_paper_intent_rechecks_risk_and_reuses_trade_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AITradingService()
    guard = _RiskGuard([_approved(requires_confirmation=True), _approved()])
    service.risk_guard = guard
    monkeypatch.setattr(ai_module, "parse_trading_intent", _parse_intent)

    async def _context(**_kwargs: Any) -> dict[str, Any]:
        return {"account_balance": 100_000, "current_positions": []}

    async def _notify(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(service, "_resolve_trading_context", _context)
    monkeypatch.setattr(service, "_enrich_intent_with_asset_spec", lambda *_args: None)
    monkeypatch.setattr(service, "_notify_confirmation_needed", _notify)

    calls: list[dict[str, Any]] = []

    async def _submit(
        self: Any,
        *,
        intent: TradingIntent,
        user_id: str,
        account_id: str | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        calls.append(
            {
                "intent": intent,
                "user_id": user_id,
                "account_id": account_id,
                "operation_id": operation_id,
            }
        )
        return {
            "success": True,
            "type": "managed_paper_trade",
            "intent_id": "afi-ai-" + "d" * 64,
            "state": "ACKED",
        }

    from app.services.direct_order_service import DirectOrderService

    monkeypatch.setattr(DirectOrderService, "execute_paper_trade", _submit)
    preview = await service.process_trading_request(
        "subject-1",
        AITradingRequest(
            message="buy BTC",
            account_id="legacy-account-1",
            dry_run=True,
        ),
    )
    assert preview.status is TradeStatus.PENDING_CONFIRMATION
    assert preview.requires_confirmation is True
    assert calls == []

    confirmed = await service.confirm_trade(
        "subject-1",
        TradeConfirmRequest(trade_id=preview.trade_id, confirmed=True),
    )

    assert guard.calls == 2
    assert confirmed.trade_id == preview.trade_id
    assert confirmed.status is TradeStatus.EXECUTING
    assert calls == [
        {
            "intent": _intent(),
            "user_id": "subject-1",
            "account_id": "legacy-account-1",
            "operation_id": preview.trade_id,
        }
    ]
    ai_module._pending_trades.pop(preview.trade_id, None)
