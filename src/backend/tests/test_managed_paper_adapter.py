from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.ai_trading import OrderType as AIOrderType
from app.schemas.ai_trading import TradeAction, TradingIntent
from app.schemas.paper_trading import OrderRequest
from app.services import managed_paper_adapter as adapter_module
from app.services.legacy_paper_migration import LegacyPaperInventory
from app.services.managed_paper_adapter import (
    ManagedPaperOrderAdapter,
    ManagedPaperOrderError,
)
from app.services.service_read.contracts import OrderReadView, ReadQuality


class _Worker:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, dict[str, Any]]] = []
        self.queries: list[tuple[str, str]] = []
        self.reply: dict[str, Any] = {"ok": True, "code": "OK"}
        self.submit_error: BaseException | None = None
        self.view = OrderReadView(
            intent_id="afi-manual-" + "a" * 64,
            quality=ReadQuality.FRESH,
            state="ACKED",
            is_terminal=False,
        )

    async def submit_paper_order(self, scope_ref: str, arguments: dict[str, Any]) -> Any:
        self.submissions.append((scope_ref, dict(arguments)))
        if self.submit_error is not None:
            raise self.submit_error
        return dict(self.reply)

    async def read_order(self, scope_ref: str, intent_id: str) -> OrderReadView:
        self.queries.append((scope_ref, intent_id))
        if self.view.quality is ReadQuality.NOT_COLLECTED:
            return OrderReadView.not_collected(intent_id)
        if self.view.intent_id != intent_id:
            return OrderReadView(
                intent_id=intent_id,
                quality=self.view.quality,
                state=self.view.state,
                provider_order_id=self.view.provider_order_id,
                filled_quantity=self.view.filled_quantity,
                average_price=self.view.average_price,
                cumulative_commission=self.view.cumulative_commission,
                is_terminal=self.view.is_terminal,
                unknown_reason=self.view.unknown_reason,
                review_required=self.view.review_required,
                updated_at_ns=self.view.updated_at_ns,
                detail_code=self.view.detail_code,
            )
        return self.view


def _fixture(monkeypatch: pytest.MonkeyPatch) -> tuple[ManagedPaperOrderAdapter, _Worker]:
    subject = "subject-1"
    account_id = "legacy-account-1"
    worker = _Worker()
    binding = SimpleNamespace(
        mount="application.orders",
        scope_ref="paper-submit-scope",
        query_scope_ref="paper-query-scope",
        legacy_account_id=account_id,
        account_ref="simulation-account-1",
        execution_domain_ref="paper-domain-1",
        strategy_ref="strategy-1",
        instrument_metadata_versions={"BTCUSDT": "instrument-v7"},
        initial_cash=Decimal("100000"),
        initial_fees=Decimal("0"),
        fee_rate=Decimal("0.001"),
        opening_positions=(),
    )
    access = SimpleNamespace(
        paper_submit_bindings={account_id: binding},
        worker=worker,
    )
    adapter = ManagedPaperOrderAdapter(
        legacy_service_factory=object,
        access_resolver=lambda resolved_subject, resolved_account: (
            access
            if (resolved_subject, resolved_account) == (subject, account_id)
            else None,
            binding,
        ),
    )
    inventory = LegacyPaperInventory(
        account_id=account_id,
        owner_id=subject,
        complete=True,
        digest="b" * 64,
        account={
            "user_id": subject,
            "is_active": True,
            "initial_cash": "100000",
            "current_cash": "100000",
            "total_equity": "100000",
            "profit_loss": "0",
            "profit_loss_pct": "0",
            "commission_rate": "0.001",
            "slippage_rate": "0",
        },
        order_count=0,
        position_count=0,
        trade_count=0,
    )

    async def _receipt(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id="receipt-1", source_inventory_sha256=inventory.digest)

    async def _inventory(*_args: Any, **_kwargs: Any) -> LegacyPaperInventory:
        return inventory

    monkeypatch.setattr(adapter_module, "require_active_paper_cutover_receipt", _receipt)
    monkeypatch.setattr(adapter_module, "inspect_stable_legacy_paper_account", _inventory)
    return adapter, worker


@pytest.mark.asyncio
async def test_manual_market_submission_uses_managed_journal_state(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, worker = _fixture(monkeypatch)

    result = await adapter.submit_manual(
        subject="subject-1",
        request=OrderRequest(
            account_id="legacy-account-1",
            symbol="BTCUSDT",
            order_type="market",
            side="buy",
            size=0.25,
        ),
        idempotency_key="manual-click-1",
    )

    assert result["source"] == "managed_paper"
    assert result["state"] == "ACKED"
    assert result["status"] == "executing"
    assert result["submission_acknowledged"] is True
    assert len(worker.submissions) == 1
    assert worker.submissions[0][0] == "paper-submit-scope"
    arguments = worker.submissions[0][1]
    assert arguments["order_type"] == "MARKET"
    assert arguments["time_in_force"] == "FOK"
    assert arguments["side"] == "BUY"
    assert arguments["position_effect"] == "OPEN"
    assert arguments["metadata_version"] == "instrument-v7"
    assert worker.queries == [("paper-query-scope", result["intent_id"])]


@pytest.mark.asyncio
async def test_uncertain_submit_queries_once_without_resubmitting(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, worker = _fixture(monkeypatch)
    worker.submit_error = TimeoutError()
    worker.view = OrderReadView.not_collected("unused")

    result = await adapter.submit_manual(
        subject="subject-1",
        request=OrderRequest(
            account_id="legacy-account-1",
            symbol="BTCUSDT",
            order_type="market",
            side="buy",
            size=1,
        ),
        idempotency_key="manual-timeout-1",
    )

    assert len(worker.submissions) == 1
    assert len(worker.queries) == 1
    assert result["state"] == "UNKNOWN"
    assert result["submit_code"] == "TimeoutError"
    assert result["submission_acknowledged"] is False


@pytest.mark.asyncio
async def test_same_idempotency_key_keeps_same_intent_and_surfaces_payload_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, worker = _fixture(monkeypatch)
    calls = 0

    async def _submit(scope_ref: str, arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        worker.submissions.append((scope_ref, dict(arguments)))
        calls += 1
        return {"ok": False, "code": "INTENT_CONFLICT"} if calls == 2 else {"ok": True, "code": "OK"}

    worker.submit_paper_order = _submit  # type: ignore[method-assign]
    key = "manual-same-key"
    first = await adapter.submit_manual(
        subject="subject-1",
        request=OrderRequest(
            account_id="legacy-account-1",
            symbol="BTCUSDT",
            order_type="market",
            side="buy",
            size=1,
        ),
        idempotency_key=key,
    )
    with pytest.raises(ManagedPaperOrderError) as error:
        await adapter.submit_manual(
            subject="subject-1",
            request=OrderRequest(
                account_id="legacy-account-1",
                symbol="BTCUSDT",
                order_type="market",
                side="buy",
                size=2,
            ),
            idempotency_key=key,
        )

    assert error.value.code == "PAPER_IDEMPOTENCY_CONFLICT"
    assert worker.submissions[0][1]["intent_id"] == worker.submissions[1][1]["intent_id"]
    assert first["intent_id"] == worker.submissions[1][1]["intent_id"]


@pytest.mark.asyncio
async def test_unsupported_limit_order_is_rejected_before_service_resolution() -> None:
    def _unexpected_resolve(*_args: Any) -> Any:
        raise AssertionError("unsupported orders must not resolve or dispatch")

    adapter = ManagedPaperOrderAdapter(access_resolver=_unexpected_resolve)
    with pytest.raises(ManagedPaperOrderError) as error:
        await adapter.submit_manual(
            subject="subject-1",
            request=OrderRequest(
                account_id="legacy-account-1",
                symbol="BTCUSDT",
                order_type="limit",
                side="buy",
                size=1,
                price=100,
            ),
            idempotency_key="manual-limit-1",
        )
    assert error.value.code == "UNSUPPORTED_PAPER_ORDER_TYPE"


@pytest.mark.asyncio
async def test_query_refuses_a_journal_view_for_another_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, worker = _fixture(monkeypatch)

    async def _wrong_view(_scope_ref: str, _intent_id: str) -> OrderReadView:
        return OrderReadView(
            intent_id="afi-manual-" + "e" * 64,
            quality=ReadQuality.FRESH,
            state="FILLED",
            is_terminal=True,
        )

    worker.read_order = _wrong_view  # type: ignore[method-assign]
    requested_id = "afi-manual-" + "a" * 64

    with pytest.raises(ManagedPaperOrderError) as error:
        await adapter.read_order(
            subject="subject-1",
            legacy_account_id="legacy-account-1",
            intent_id=requested_id,
        )

    assert error.value.code == "MANAGED_ORDER_STATE_IDENTITY_MISMATCH"
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_ai_close_is_reduce_only_and_sell_open_is_not_reinterpreted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, worker = _fixture(monkeypatch)
    closed = await adapter.submit_ai(
        subject="subject-1",
        legacy_account_id="legacy-account-1",
        intent=TradingIntent(
            action=TradeAction.CLOSE,
            symbol="BTCUSDT",
            quantity=0.5,
            order_type=AIOrderType.MARKET,
        ),
        trade_id="ai-trade-close-1",
    )
    assert closed["state"] == "ACKED"
    close_arguments = worker.submissions[0][1]
    assert close_arguments["side"] == "SELL"
    assert close_arguments["position_effect"] == "CLOSE"
    assert close_arguments["reduce_only"] is True

    with pytest.raises(ManagedPaperOrderError) as error:
        await adapter.submit_ai(
            subject="subject-1",
            legacy_account_id="legacy-account-1",
            intent=TradingIntent(
                action=TradeAction.SELL,
                symbol="BTCUSDT",
                quantity=0.5,
                order_type=AIOrderType.MARKET,
            ),
            trade_id="ai-trade-sell-1",
        )
    assert error.value.code == "UNSUPPORTED_PAPER_ACTION"
    assert len(worker.submissions) == 1
