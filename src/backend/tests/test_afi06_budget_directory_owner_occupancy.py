"""Reconcile a durable static budget with reopened account Risk ledgers.

This is a local SQLite/service-adapter composition check. It does not exercise
HTTP, a ServiceHost, a provider, or a live account.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from bt_api_base.service_protocol import WireScope
from bt_api_risk import (
    AccountScope,
    DispatchResolutionReceiptStatus,
    DurableRiskGate,
    IntentAction,
    RiskIntent,
    RiskPolicy,
)
from bt_api_risk.budget_admission import PolicyCatalogBudgetAdmissionResolver
from bt_api_risk.service_component import (
    ConfirmedPolicyStore,
    PolicyCatalogService,
    PolicyCatalogStore,
    RiskReadService,
)

_DOMAIN = "afi06:budget-reconciliation"
_PORTFOLIO = "afi06-reconciliation-portfolio"
_POOL = "afi06-reconciliation-pool-v1"
_GENERATION = "afi06-reconciliation-generation-v1"
_ACCOUNTS = ("afi06-account-a", "afi06-account-b")
_CURRENCY = "USD"
_METRIC = "max_increase_notional"
_MEMBERSHIP_SHA256 = "a" * 64
_RISK_CLOCK = 1_800_000_000.0
_ALLOCATIONS = {
    _ACCOUNTS[0]: "25",
    _ACCOUNTS[1]: "15",
}


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _management_scope() -> WireScope:
    return WireScope(
        _DOMAIN,
        account_refs=_ACCOUNTS,
        portfolio_ref=_PORTFOLIO,
        group_id="afi06-budget-control",
    )


def _member_scope(account_ref: str) -> WireScope:
    return WireScope(_DOMAIN, account_ref=account_ref, portfolio_ref=_PORTFOLIO)


def _owner_scope(account_ref: str) -> AccountScope:
    return AccountScope(
        provider="synthetic-provider",
        account_id=account_ref,
        environment="simulation",
    )


def _risk_gate(database_path: Path, risk_policy: RiskPolicy) -> DurableRiskGate:
    return DurableRiskGate(database_path, risk_policy, clock=lambda: _RISK_CLOCK)


def _occupancy_intent(account_ref: str, *, intent_id: str, notional: str) -> RiskIntent:
    return RiskIntent(
        intent_id=intent_id,
        scope=_owner_scope(account_ref),
        action=IntentAction.INCREASE,
        notional=Decimal(notional),
        notional_unit=_CURRENCY,
        payload_fingerprint=f"synthetic:{intent_id}",
    )


def _service_result(
    service: PolicyCatalogService,
    operation: str,
    *,
    principal_ref: str,
    scope: WireScope,
    arguments: dict[str, object],
) -> dict[str, object]:
    response = service.handle(
        operation,
        principal_ref=principal_ref,
        scope=scope,
        arguments=arguments,
    )
    assert response["ok"] is True, response
    assert response["code"] == "OK", response
    assert type(response["result"]) is dict, response
    return response["result"]


def _make_ready_generation(
    service: PolicyCatalogService,
    catalog: PolicyCatalogStore,
    confirmations: ConfirmedPolicyStore,
) -> None:
    catalog.configure_budget_pool(
        _POOL,
        capacity_amount="100",
        currency=_CURRENCY,
        metric=_METRIC,
        scale=2,
        portfolio_ref=_PORTFOLIO,
        membership_version=1,
        membership_sha256=_MEMBERSHIP_SHA256,
        account_refs=_ACCOUNTS,
    )
    allocations = [
        {
            "account_ref": account_ref,
            "policy_ref": f"afi06-policy-{index}-v1",
            "amount": _ALLOCATIONS[account_ref],
            "max_increase_count": 5,
            "metric": _METRIC,
            "currency": _CURRENCY,
        }
        for index, account_ref in enumerate(_ACCOUNTS)
    ]
    manifest = {
        "kind": "afi.static_account_budget",
        "schema_version": 1,
        "portfolio_ref": _PORTFOLIO,
        "membership_version": 1,
        "membership_sha256": _MEMBERSHIP_SHA256,
        "metric": _METRIC,
        "currency": _CURRENCY,
        "total_amount": "50",
        "unallocated_amount": "10",
        "allocations": allocations,
    }
    allocation_set_sha256 = _digest(manifest)

    for allocation in allocations:
        account_ref = str(allocation["account_ref"])
        policy_ref = str(allocation["policy_ref"])
        amount = str(allocation["amount"])
        content = {
            "afi_budget": {
                "kind": "afi.static_account_budget",
                "schema_version": 1,
                "portfolio_ref": _PORTFOLIO,
                "membership_version": 1,
                "membership_sha256": _MEMBERSHIP_SHA256,
                "allocation_set_sha256": allocation_set_sha256,
                "metric": _METRIC,
                "currency": _CURRENCY,
                "total_amount": "50",
                "unallocated_amount": "10",
                "account_ref": account_ref,
                "allocated_amount": amount,
            },
            "risk_policy": {
                "policy_id": policy_ref,
                "max_increase_notional": amount,
                "max_increase_count": 5,
                "permit_ttl_seconds": 30.0,
                "require_strategy_allocation": False,
                "notional_unit": _CURRENCY,
            },
        }
        _service_result(
            service,
            "policy.draft",
            principal_ref="maker",
            scope=_member_scope(account_ref),
            arguments={"policy_ref": policy_ref, "content": content},
        )

    proposal = {
        "pool_ref": _POOL,
        "generation_ref": _GENERATION,
        "portfolio_ref": _PORTFOLIO,
        "membership_version": 1,
        "membership_sha256": _MEMBERSHIP_SHA256,
        "allocation_set_sha256": allocation_set_sha256,
        "currency": _CURRENCY,
        "metric": _METRIC,
        "total_amount": "50",
        "unallocated_amount": "10",
        "allocations": allocations,
    }
    control_scope = _management_scope()
    _service_result(
        service,
        "policy.budget.propose",
        principal_ref="maker",
        scope=control_scope,
        arguments=proposal,
    )
    _service_result(
        service,
        "policy.budget.approve",
        principal_ref="checker",
        scope=control_scope,
        arguments={"generation_ref": _GENERATION},
    )

    receipts: dict[str, dict[str, object]] = {}
    for account_ref in _ACCOUNTS:
        published = _service_result(
            service,
            "policy.budget.publish_member",
            principal_ref="checker",
            scope=control_scope,
            arguments={"generation_ref": _GENERATION, "account_ref": account_ref},
        )
        assert published["consumer_effective"] is False, published
        receipts[account_ref] = published["member"]
    for account_ref in _ACCOUNTS:
        confirmations.confirm(receipts[account_ref])
        confirmed = _service_result(
            service,
            "policy.budget.confirm_member",
            principal_ref="maker",
            scope=_member_scope(account_ref),
            arguments={"generation_ref": _GENERATION, "account_ref": account_ref},
        )
    assert confirmed["state"] == "authority_ready", confirmed
    assert confirmed["consumer_effective"] is False, confirmed


def _record_occupancy(
    gate: DurableRiskGate,
    scope: AccountScope,
    *,
    intent_id: str,
    notional: str,
    leave_dispatch_unresolved: bool,
) -> str:
    intent = _occupancy_intent(
        scope.account_id,
        intent_id=intent_id,
        notional=notional,
    )
    permit = gate.reserve(intent)
    if leave_dispatch_unresolved:
        gate.claim_for_dispatch(permit.permit_id, intent)
        gate.settle(permit.permit_id)
        receipt = gate.dispatch_resolution_receipt(permit.permit_id)
        assert receipt.status is DispatchResolutionReceiptStatus.UNRESOLVED_ACTIVE
        assert receipt.dispatch_latch_active is True
        assert receipt.proof is None
    return permit.permit_id


def test_reopened_budget_generation_reconciles_with_active_and_unknown_account_ledgers(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "budget-catalog.sqlite3"
    confirmations_path = tmp_path / "budget-confirmations.sqlite3"
    risk_paths = {
        account_ref: tmp_path / f"{account_ref}-risk.sqlite3" for account_ref in _ACCOUNTS
    }
    catalog = PolicyCatalogStore(
        str(catalog_path), trusted_approver_principals=("maker", "checker")
    )
    confirmations = ConfirmedPolicyStore(str(confirmations_path))
    service = PolicyCatalogService(catalog, confirmation_store=confirmations)
    gates: dict[str, DurableRiskGate] = {}
    reopened_gates: dict[str, DurableRiskGate] = {}
    permit_ids: dict[str, str] = {}
    try:
        _make_ready_generation(service, catalog, confirmations)
        initial_resolver = PolicyCatalogBudgetAdmissionResolver(catalog, confirmations)
        initial = {
            account_ref: initial_resolver.resolve(
                _POOL,
                account_ref,
                scope=_member_scope(account_ref),
            )
            for account_ref in _ACCOUNTS
        }
        for account_ref in _ACCOUNTS:
            scope = _owner_scope(account_ref)
            gate = _risk_gate(risk_paths[account_ref], initial[account_ref].risk_policy)
            gates[account_ref] = gate
            binding = gate.bind_policy(scope)
            assert binding.policy_id == initial[account_ref].policy_ref
            assert binding.policy_fingerprint == initial[account_ref].risk_policy.fingerprint

        permit_ids[_ACCOUNTS[0]] = _record_occupancy(
            gates[_ACCOUNTS[0]],
            _owner_scope(_ACCOUNTS[0]),
            intent_id="afi06-active-reservation",
            notional="7",
            leave_dispatch_unresolved=False,
        )
        permit_ids[_ACCOUNTS[1]] = _record_occupancy(
            gates[_ACCOUNTS[1]],
            _owner_scope(_ACCOUNTS[1]),
            intent_id="afi06-unknown-dispatch",
            notional="4",
            leave_dispatch_unresolved=True,
        )

        for gate in gates.values():
            gate.close()
        gates.clear()
        service.close()
        catalog.close()
        confirmations.close()

        catalog = PolicyCatalogStore(
            str(catalog_path), trusted_approver_principals=("maker", "checker")
        )
        confirmations = ConfirmedPolicyStore(str(confirmations_path))
        service = PolicyCatalogService(catalog, confirmation_store=confirmations)
        resolver = PolicyCatalogBudgetAdmissionResolver(catalog, confirmations)
        control_scope = _management_scope()
        generation = _service_result(
            service,
            "policy.budget.read",
            principal_ref="maker",
            scope=control_scope,
            arguments={"generation_ref": _GENERATION},
        )
        assert generation["state"] == "authority_ready", generation
        assert generation["consumer_effective"] is False, generation
        assert generation["portfolio_ref"] == _PORTFOLIO
        assert generation["currency"] == _CURRENCY
        assert generation["metric"] == _METRIC
        assert generation["total_amount"] == "50"
        assert generation["unallocated_amount"] == "10"
        members = {row["account_ref"]: row for row in generation["members"]}
        assert set(members) == set(_ACCOUNTS), members
        assert all(row["state"] == "confirmed" for row in members.values()), members
        assert sum(
            (Decimal(str(row["amount"])) for row in members.values()), Decimal("0")
        ) + Decimal(str(generation["unallocated_amount"])) == Decimal(
            str(generation["total_amount"])
        )

        pool = catalog.configure_budget_pool(
            _POOL,
            capacity_amount="100",
            currency=_CURRENCY,
            metric=_METRIC,
            scale=2,
            portfolio_ref=_PORTFOLIO,
            membership_version=1,
            membership_sha256=_MEMBERSHIP_SHA256,
            account_refs=_ACCOUNTS,
        )
        assert pool["capacity_amount"] == "100", pool
        assert pool["authority_generation_ref"] == _GENERATION, pool
        assert pool["portfolio_ref"] == _PORTFOLIO, pool
        assert pool["membership_version"] == 1, pool
        assert pool["membership_sha256"] == _MEMBERSHIP_SHA256, pool
        assert pool["account_refs"] == _ACCOUNTS, pool
        assert pool["currency"] == _CURRENCY, pool
        assert pool["metric"] == _METRIC, pool
        assert pool["used_amount"] == "50", pool
        assert pool["available_amount"] == "50", pool

        resolved = {
            account_ref: resolver.resolve(
                _POOL,
                account_ref,
                scope=_member_scope(account_ref),
            )
            for account_ref in _ACCOUNTS
        }
        snapshots: dict[str, object] = {}
        for account_ref in _ACCOUNTS:
            member = members[account_ref]
            budget = resolved[account_ref]
            assert budget.generation_ref == _GENERATION
            assert budget.policy_ref == member["policy_ref"]
            assert budget.policy_version == member["policy_version"]
            assert str(budget.risk_policy.max_increase_notional) == member["amount"]
            assert budget.risk_policy.notional_unit == _CURRENCY

            gate = _risk_gate(risk_paths[account_ref], budget.risk_policy)
            reopened_gates[account_ref] = gate
            owner_scope = _owner_scope(account_ref)
            binding = gate.bind_policy(owner_scope)
            assert binding.policy_id == budget.policy_ref
            assert binding.policy_fingerprint == budget.risk_policy.fingerprint
            if account_ref == _ACCOUNTS[0]:
                gate.validate_permit(
                    permit_ids[account_ref],
                    _occupancy_intent(
                        account_ref,
                        intent_id="afi06-active-reservation",
                        notional="7",
                    ),
                )
            else:
                unresolved = gate.dispatch_resolution_receipt(permit_ids[account_ref])
                assert unresolved.status is DispatchResolutionReceiptStatus.UNRESOLVED_ACTIVE
                assert unresolved.dispatch_latch_active is True
                assert unresolved.proof is None
            projection = RiskReadService(
                gate,
                {
                    _member_scope(account_ref): owner_scope,
                },
            ).handle(
                "risk.snapshot",
                principal_ref=f"afi06-owner-{account_ref}",
                scope=_member_scope(account_ref),
                arguments={},
            )
            assert projection["source"] == "local_risk_reservation_ledger", projection
            assert projection["policy_fingerprint"] == budget.risk_policy.fingerprint
            assert projection["increase_count"] == 1, projection
            snapshots[account_ref] = projection

        active = snapshots[_ACCOUNTS[0]]
        unknown = snapshots[_ACCOUNTS[1]]
        assert Decimal(str(active["increase_notional"])) == Decimal("7"), active
        assert active["active_freeze_reasons"] == (), active
        assert Decimal(str(unknown["increase_notional"])) == Decimal("4"), unknown
        assert unknown["active_freeze_reasons"] == ("dispatch-inflight:afi06-unknown-dispatch",), (
            unknown
        )
        assert Decimal(str(active["increase_notional"])) <= Decimal(members[_ACCOUNTS[0]]["amount"])
        assert Decimal(str(unknown["increase_notional"])) <= Decimal(
            members[_ACCOUNTS[1]]["amount"]
        )
        assert active["increase_count"] <= resolved[_ACCOUNTS[0]].risk_policy.max_increase_count
        assert unknown["increase_count"] <= resolved[_ACCOUNTS[1]].risk_policy.max_increase_count
        assert sum(
            (Decimal(str(snapshot["increase_notional"])) for snapshot in snapshots.values()),
            Decimal("0"),
        ) <= sum((Decimal(str(row["amount"])) for row in members.values()), Decimal("0"))
    finally:
        service.close()
        for gate in (*gates.values(), *reopened_gates.values()):
            gate.close()
        catalog.close()
        confirmations.close()
