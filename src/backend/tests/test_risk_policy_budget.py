"""Focused contract tests for static budgets written to the shared Risk catalog."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from bt_api_base.service_protocol import WireScope
from bt_api_risk.core.admission import RiskPolicy
from bt_api_risk.portfolio_analytics import FxObservationV1
from bt_api_risk.service_component import ConfirmedPolicyStore, PolicyCatalogStore

_POLICY_BUDGET_SOURCE = Path(os.environ["AFI_POLICY_BUDGET_SOURCE"]).resolve(strict=True)
_POLICY_BUDGET_SPEC = importlib.util.spec_from_file_location(
    "app.services.risk_policy_budget", _POLICY_BUDGET_SOURCE
)
if _POLICY_BUDGET_SPEC is None or _POLICY_BUDGET_SPEC.loader is None:
    raise RuntimeError("risk policy budget source loader unavailable")
_POLICY_BUDGET_MODULE = importlib.util.module_from_spec(_POLICY_BUDGET_SPEC)
sys.modules[_POLICY_BUDGET_SPEC.name] = _POLICY_BUDGET_MODULE
_POLICY_BUDGET_SPEC.loader.exec_module(_POLICY_BUDGET_MODULE)
AccountBudgetAllocation = _POLICY_BUDGET_MODULE.AccountBudgetAllocation
RiskPolicyBudgetError = _POLICY_BUDGET_MODULE.RiskPolicyBudgetError
StaticPortfolioBudgetPlan = _POLICY_BUDGET_MODULE.StaticPortfolioBudgetPlan
compile_static_portfolio_budget = _POLICY_BUDGET_MODULE.compile_static_portfolio_budget

_MEMBERSHIP_SHA256 = "a" * 64


def _plan(
    *,
    allocations: tuple[AccountBudgetAllocation, ...] | None = None,
    total: Decimal = Decimal("100.00"),
    unallocated: Decimal = Decimal("10.00"),
    metric: str = "max_increase_notional",
) -> StaticPortfolioBudgetPlan:
    return StaticPortfolioBudgetPlan(
        portfolio_ref="portfolio-demo",
        membership_version=7,
        membership_sha256=_MEMBERSHIP_SHA256,
        currency="USD",
        total_amount=total,
        unallocated_amount=unallocated,
        allocations=allocations
        or (
            AccountBudgetAllocation(
                "account-a", Decimal("60.00"), "USD", max_increase_count=3
            ),
            AccountBudgetAllocation(
                "account-b", Decimal("30.00"), "USD", max_increase_count=2
            ),
        ),
        metric=metric,
    )


def _policy_refs() -> dict[str, str]:
    return {
        "account-a": "afi.portfolio-demo.account-a-v3",
        "account-b": "afi.portfolio-demo.account-b-v3",
    }


def _cross_currency_plan() -> StaticPortfolioBudgetPlan:
    return _plan(
        total=Decimal("10"),
        unallocated=Decimal("0"),
        allocations=(
            AccountBudgetAllocation(
                "account-a", Decimal("3"), "EUR", max_increase_count=3
            ),
            AccountBudgetAllocation(
                "account-b", Decimal("6.296296329629629633"), "USD", max_increase_count=2
            ),
        ),
    )


def _fx_observation(
    *,
    now_ns: int,
    base: str = "EUR",
    quote: str = "USD",
    rate: Decimal = Decimal("1.234567890123456789"),
    as_of_ns: int | None = None,
    valid_until_ns: int | None = None,
) -> FxObservationV1:
    return FxObservationV1(
        observation_ref="fx-budget-eur-usd-v1",
        base_currency=base,
        quote_currency=quote,
        direction="BASE_TO_QUOTE",
        rate_unit="QUOTE_PER_BASE",
        rate=rate,
        as_of_ns=now_ns - 1_000_000_000 if as_of_ns is None else as_of_ns,
        valid_until_ns=now_ns + 3_600_000_000_000
        if valid_until_ns is None
        else valid_until_ns,
        source_ref="trusted-market-fx-reference",
        source_version="fx-reference-v1",
        source_generation="fx-reference-generation-7",
        source_cursor="fx-reference-cursor-42",
    )


def test_compiled_drafts_are_accepted_by_risk_policy_and_real_catalog(tmp_path) -> None:

    compiled = compile_static_portfolio_budget(_plan(), policy_refs=_policy_refs())
    requests = compiled.catalog_requests()

    assert [request["policy_ref"] for request in requests] == [
        "afi.portfolio-demo.account-a-v3",
        "afi.portfolio-demo.account-b-v3",
    ]
    assert compiled.total_amount == "100"
    assert compiled.unallocated_amount == "10"
    assert compiled.allocation_set_sha256 == compiled.drafts[0].catalog_content()[
        "afi_budget"
    ]["allocation_set_sha256"]
    assert compiled.allocation_set_sha256 == compiled.drafts[1].catalog_content()[
        "afi_budget"
    ]["allocation_set_sha256"]

    catalog = PolicyCatalogStore(str(tmp_path / "policy-catalog.sqlite"))
    confirmations = ConfirmedPolicyStore(str(tmp_path / "confirmed-policies.sqlite"))
    try:
        for request in requests:
            policy_ref = request["policy_ref"]
            content = request["content"]
            risk_policy = RiskPolicy(**content["risk_policy"])
            assert risk_policy.policy_id == policy_ref
            assert risk_policy.notional_unit == "USD"

            account_ref = content["afi_budget"]["account_ref"]
            scope = WireScope("afi-policy-budget-test", account_ref=account_ref)
            drafted = catalog.draft(
                policy_ref,
                content,
                principal_ref="afi-budget-manager",
                scope=scope,
            )
            assert drafted["state"] == "draft"
            assert len(drafted["policy_version"]) == 64

            approved = catalog.approve(policy_ref)
            assert approved["state"] == "approved"
            receipt = catalog.publish(policy_ref)
            assert receipt["policy_version"] == drafted["policy_version"]
            assert catalog.read(policy_ref)["content"] == content
            assert catalog.receipt(policy_ref, scope=scope) == receipt

            confirmed = confirmations.confirm(receipt)
            assert confirmed["policy_ref"] == policy_ref
            assert confirmed["policy_version"] == drafted["policy_version"]
    finally:
        confirmations.close()
        catalog.close()


def test_fresh_fx_converts_exactly_and_catalog_persists_source_facts(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_ns = 1_900_000_000_000_000_000
    monkeypatch.setattr(_POLICY_BUDGET_MODULE.time, "time_ns", lambda: now_ns)
    observation = _fx_observation(now_ns=now_ns)
    compiled = compile_static_portfolio_budget(
        _cross_currency_plan(),
        policy_refs=_policy_refs(),
        fx_observations={"EUR": observation},
    )
    requests = compiled.catalog_requests()
    account_a = next(
        request["content"]
        for request in requests
        if request["content"]["afi_budget"]["account_ref"] == "account-a"
    )
    assert account_a["risk_policy"]["max_increase_notional"] == "3.703703670370370367"
    assert account_a["risk_policy"]["notional_unit"] == "USD"
    budget = account_a["afi_budget"]
    assert budget["source_amount"] == "3"
    assert budget["source_currency"] == "EUR"
    assert budget["allocated_amount"] == "3.703703670370370367"
    assert budget["fx_observation"] == {
        "observation_ref": observation.observation_ref,
        "base_currency": "EUR",
        "quote_currency": "USD",
        "direction": "BASE_TO_QUOTE",
        "rate_unit": "QUOTE_PER_BASE",
        "rate": "1.234567890123456789",
        "as_of_ns": observation.as_of_ns,
        "valid_until_ns": observation.valid_until_ns,
        "source_ref": observation.source_ref,
        "source_version": observation.source_version,
        "source_generation": observation.source_generation,
        "source_cursor": observation.source_cursor,
    }
    # 3 EUR * the exact 18-place rate plus the USD allocation equals the
    # declared ten USD exactly; no Decimal-context rounding is permitted.
    assert compiled.total_amount == "10"
    assert compiled.unallocated_amount == "0"

    catalog_path = tmp_path / "fx-budget-catalog.sqlite"
    catalog = PolicyCatalogStore(str(catalog_path))
    account_a_policy_version: str | None = None
    try:
        for request in requests:
            content = request["content"]
            risk_policy = RiskPolicy(**content["risk_policy"])
            account_ref = content["afi_budget"]["account_ref"]
            scope = WireScope("afi-fx-budget-test", account_ref=account_ref)
            result = catalog.draft(
                request["policy_ref"],
                content,
                principal_ref="afi-budget-manager",
                scope=scope,
            )
            assert result["state"] == "draft"
            assert risk_policy.notional_unit == "USD"
            if account_ref == "account-a":
                account_a_policy_version = result["policy_version"]
    finally:
        catalog.close()

    # The accepted catalog intentionally requires generation-level approval for
    # budget policies. Read its persisted draft row after closing the writer to
    # verify FX provenance survived the actual SQLite store boundary.
    assert account_a_policy_version is not None
    with sqlite3.connect(str(catalog_path)) as reopened:
        reopened.row_factory = sqlite3.Row
        saved = reopened.execute(
            "SELECT state, digest, content_json FROM policy_catalog_versions "
            "WHERE reference = ?",
            ("afi.portfolio-demo.account-a-v3",),
        ).fetchone()
    assert saved is not None
    assert saved["state"] == "draft"
    assert saved["digest"] == account_a_policy_version
    assert json.loads(saved["content_json"]) == account_a
    assert json.loads(saved["content_json"])["afi_budget"]["fx_observation"]["source_cursor"] == (
        "fx-reference-cursor-42"
    )

def test_cross_currency_budget_fails_closed_without_current_bound_fx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_ns = 1_900_000_000_000_000_000
    monkeypatch.setattr(_POLICY_BUDGET_MODULE.time, "time_ns", lambda: now_ns)
    cases = (
        ({}, "BUDGET_FX_REQUIRED"),
        (
            {
                "EUR": _fx_observation(
                    now_ns=now_ns,
                    as_of_ns=now_ns - 86_400_000_000_001,
                    valid_until_ns=now_ns + 1_000_000_000,
                )
            },
            "BUDGET_FX_STALE",
        ),
        (
            {
                "EUR": _fx_observation(
                    now_ns=now_ns,
                    as_of_ns=now_ns + 1,
                    valid_until_ns=now_ns + 1_000_000_000,
                )
            },
            "BUDGET_FX_NOT_CURRENT",
        ),
        (
            {
                "EUR": _fx_observation(
                    now_ns=now_ns,
                    as_of_ns=now_ns - 1_000_000_000,
                    valid_until_ns=now_ns,
                )
            },
            "BUDGET_FX_NOT_CURRENT",
        ),
        (
            {"EUR": _fx_observation(now_ns=now_ns, base="GBP")},
            "BUDGET_FX_PAIR_MISMATCH",
        ),
    )
    for observations, expected_code in cases:
        with pytest.raises(RiskPolicyBudgetError) as error:
            compile_static_portfolio_budget(
                _cross_currency_plan(),
                policy_refs=_policy_refs(),
                fx_observations=observations,
            )
        assert error.value.code == expected_code


def test_allocation_set_hash_is_order_independent_and_binds_membership() -> None:
    plan = _plan()
    reversed_plan = replace(plan, allocations=tuple(reversed(plan.allocations)))
    compiled = compile_static_portfolio_budget(plan, policy_refs=_policy_refs())
    reordered = compile_static_portfolio_budget(
        reversed_plan, policy_refs=dict(reversed(tuple(_policy_refs().items())))
    )
    changed_membership = compile_static_portfolio_budget(
        replace(plan, membership_version=8), policy_refs=_policy_refs()
    )

    assert compiled.allocation_set_sha256 == reordered.allocation_set_sha256
    assert compiled.allocation_set_sha256 != changed_membership.allocation_set_sha256


def test_budget_conservation_does_not_round_large_decimal_allocations() -> None:
    plan = _plan(
        total=Decimal("10000000000000000000000000000.02"),
        unallocated=Decimal("0"),
        allocations=(
            AccountBudgetAllocation(
                "account-a", Decimal("9999999999999999999999999999.99"), "USD"
            ),
            AccountBudgetAllocation("account-b", Decimal("0.03"), "USD"),
        ),
    )

    compiled = compile_static_portfolio_budget(plan, policy_refs=_policy_refs())

    assert compiled.total_amount == "10000000000000000000000000000.02"


@pytest.mark.parametrize(
    ("plan", "policy_refs", "code"),
    [
        (
            _plan(total=Decimal("101")),
            _policy_refs(),
            "BUDGET_NOT_CONSERVED",
        ),
        (
            _plan(
                allocations=(
                    AccountBudgetAllocation("account-a", Decimal("60"), "USD"),
                    AccountBudgetAllocation("account-b", Decimal("30"), "EUR"),
                )
            ),
            _policy_refs(),
            "BUDGET_FX_REQUIRED",
        ),
        (
            _plan(
                allocations=(
                    AccountBudgetAllocation(
                        "account-a", Decimal("60"), "USD", metric="max_gross_occupancy_notional"
                    ),
                    AccountBudgetAllocation("account-b", Decimal("30"), "USD"),
                )
            ),
            _policy_refs(),
            "MIXED_BUDGET_METRIC",
        ),
        (_plan(), {"account-a": "afi.latest", "account-b": "afi.account-b-v1"}, "VERSIONED_POLICY_REF_REQUIRED"),
        (_plan(), {"account-a": "afi.shared-v1", "account-b": "afi.shared-v1"}, "DUPLICATE_POLICY_REF"),
    ],
)
def test_invalid_static_budget_is_rejected_before_catalog_access(
    plan: StaticPortfolioBudgetPlan,
    policy_refs: dict[str, str],
    code: str,
) -> None:
    with pytest.raises(RiskPolicyBudgetError) as error:
        compile_static_portfolio_budget(plan, policy_refs=policy_refs)
    assert error.value.code == code


@pytest.mark.parametrize(
    "amount",
    [100.0, 100, Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), Decimal("1E-19")],
)
def test_non_exact_or_out_of_range_amounts_are_rejected(amount: object) -> None:
    plan = replace(
        _plan(),
        allocations=(
            AccountBudgetAllocation("account-a", amount, "USD"),  # type: ignore[arg-type]
            AccountBudgetAllocation("account-b", Decimal("30"), "USD"),
        ),
    )
    with pytest.raises(RiskPolicyBudgetError) as error:
        compile_static_portfolio_budget(plan, policy_refs=_policy_refs())
    assert error.value.code == "INVALID_ALLOCATION_AMOUNT"


def test_duplicate_account_and_unsupported_metric_are_rejected() -> None:
    duplicate_account = _plan(
        allocations=(
            AccountBudgetAllocation("account-a", Decimal("40"), "USD"),
            AccountBudgetAllocation("account-a", Decimal("50"), "USD"),
        )
    )
    with pytest.raises(RiskPolicyBudgetError) as duplicate:
        compile_static_portfolio_budget(duplicate_account, policy_refs=_policy_refs())
    assert duplicate.value.code == "DUPLICATE_ACCOUNT"

    unsupported_metric = replace(_plan(), metric="fx_adjusted_notional")
    with pytest.raises(RiskPolicyBudgetError) as metric:
        compile_static_portfolio_budget(unsupported_metric, policy_refs=_policy_refs())
    assert metric.value.code == "UNSUPPORTED_BUDGET_METRIC"


def test_allocation_count_matches_portfolio_membership_bound() -> None:
    allocations = tuple(
        AccountBudgetAllocation(f"account-{index}", Decimal("1"), "USD")
        for index in range(257)
    )
    plan = _plan(allocations=allocations, total=Decimal("257"), unallocated=Decimal("0"))
    policy_refs = {item.account_ref: f"afi.{item.account_ref}-v1" for item in allocations}

    with pytest.raises(RiskPolicyBudgetError) as error:
        compile_static_portfolio_budget(plan, policy_refs=policy_refs)
    assert error.value.code == "INVALID_ALLOCATIONS"
