from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.legacy_paper_migration import (
    LegacyPaperInventory,
    assess_empty_account_cutover,
    paper_binding_fingerprint,
)


def _inventory(**overrides: object) -> LegacyPaperInventory:
    account = {
        "user_id": "subject-1",
        "is_active": True,
        "initial_cash": "100000",
        "current_cash": "100000",
        "total_equity": "100000",
        "profit_loss": "0",
        "profit_loss_pct": "0",
        "commission_rate": "0.001",
        "slippage_rate": "0",
    }
    account.update(overrides.pop("account", {}))  # type: ignore[arg-type]
    return LegacyPaperInventory(
        account_id="legacy-account-1",
        owner_id="subject-1",
        complete=True,
        digest="a" * 64,
        account=account,
        order_count=0,
        position_count=0,
        trade_count=0,
        **overrides,  # type: ignore[arg-type]
    )


def _binding(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "mount": "application.orders",
        "scope_ref": "paper-submit-scope",
        "query_scope_ref": "paper-query-scope",
        "legacy_account_id": "legacy-account-1",
        "account_ref": "simulation-account-1",
        "execution_domain_ref": "paper-domain-1",
        "strategy_ref": "strategy-1",
        "experiment_ref": "experiment-1",
        "model_ref": "model-1",
        "model_version": "model-v1",
        "quote_source_ref": "quotes-1",
        "cash_currency": "USD",
        "paper_domain_sha256": "b" * 64,
        "initial_cash": Decimal("100000"),
        "initial_fees": Decimal("0"),
        "fee_rate": Decimal("0.001"),
        "fee_quantum": Decimal("0.01"),
        "max_quote_age_ns": 1_000_000_000,
        "instrument_metadata_versions": {"BTCUSDT": "instrument-v7"},
        "opening_positions": (),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_empty_account_cutover_is_ready_without_claiming_data_migration() -> None:
    assessment = assess_empty_account_cutover(_inventory(), _binding())

    assert assessment.ready is True
    assert assessment.inventory_sha256 == "a" * 64
    assert assessment.order_count == assessment.position_count == assessment.trade_count == 0


@pytest.mark.parametrize(
    ("field", "count", "reason"),
    [
        ("order_count", 1, "legacy_orders_present"),
        ("position_count", 1, "legacy_positions_present"),
        ("trade_count", 1, "legacy_trades_present"),
    ],
)
def test_nonempty_legacy_tables_are_explicitly_held(
    field: str, count: int, reason: str
) -> None:
    assessment = assess_empty_account_cutover(_inventory(**{field: count}), _binding())

    assert assessment.ready is False
    assert reason in assessment.reasons


@pytest.mark.parametrize(
    ("inventory_override", "binding_override", "reason"),
    [
        ({"account": {"current_cash": "99999"}}, {}, "legacy_cash_or_equity_not_pristine"),
        ({"account": {"slippage_rate": "0.001"}}, {}, "legacy_slippage_not_representable"),
        ({}, {"fee_rate": Decimal("0.002")}, "managed_fee_rate_mismatch"),
        ({}, {"opening_positions": ({"instrument": "BTCUSDT", "net_quantity": "1"},)}, "managed_opening_positions_not_empty"),
    ],
)
def test_cutover_holds_when_cash_fees_or_positions_would_not_be_conserved(
    inventory_override: dict[str, object],
    binding_override: dict[str, object],
    reason: str,
) -> None:
    assessment = assess_empty_account_cutover(
        _inventory(**inventory_override), _binding(**binding_override)
    )

    assert assessment.ready is False
    assert reason in assessment.reasons


def test_binding_fingerprint_changes_with_trusted_scope_and_domain() -> None:
    base = _binding()
    changed_scope = _binding(scope_ref="paper-submit-scope-v2")
    changed_domain = _binding(paper_domain_sha256="c" * 64)

    assert paper_binding_fingerprint(base) != paper_binding_fingerprint(changed_scope)
    assert paper_binding_fingerprint(base) != paper_binding_fingerprint(changed_domain)
