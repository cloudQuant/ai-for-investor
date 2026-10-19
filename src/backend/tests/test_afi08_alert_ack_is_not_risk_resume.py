"""AFI08 regression: acknowledging an alert cannot resolve an owner Risk freeze."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.database import async_session_maker
from app.models.alerts import Alert, AlertSeverity, AlertStatus, AlertType
from app.models.user import User

pytest.importorskip("bt_api_monitor", reason="optional SDK monitor control package is required")
pytest.importorskip("bt_api_risk", reason="optional SDK Risk package is required")

from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_monitor.control import (
    ControlAction,
    ControlCommandBinding,
    ControlIngress,
    ControlOwnerOutcome,
    ControlStatus,
    DurableControlLedger,
    monitor_freeze_cause_id,
)
from bt_api_monitor.ingress import (
    CONTROL_COMMAND_HMAC_DOMAIN,
    ControlIssuerPolicy,
    ControlScopeGrant,
    HmacControlCommandVerifier,
    HmacControlKey,
)
from bt_api_monitor.service_control import MonitorControlService, MonitorControlTarget
from bt_api_risk import AccountScope, DurableRiskGate, FreezeActivationStatus, RiskPolicy

_NOW = 1_800_000_000.0
_KEY_ID = "afi08-local-control-key"
_ISSUER = "operator:afi08-test"
_ACCOUNT_ID = "afi08-paper-account"
_MODE = "simulation"
_COMMAND_SCOPE = "account:afi08-paper-account"
_COMMAND_ID = "afi08-freeze-command"
_REASON = "AFI08 local synthetic risk hold"


class _FixedClock:
    def __call__(self) -> float:
        return _NOW


class _KeyResolver:
    def __init__(self, key: HmacControlKey) -> None:
        self._key = key

    def resolve(self, key_id: str) -> HmacControlKey | None:
        return self._key if key_id == self._key.key_id else None


class _PolicyResolver:
    def __init__(self, policy: ControlIssuerPolicy) -> None:
        self._policy = policy

    def resolve(self, issuer: str) -> ControlIssuerPolicy | None:
        return self._policy if issuer == self._policy.issuer else None


def _control_service(
    database_path: Path,
) -> tuple[
    DurableControlLedger,
    MonitorControlService,
    WireIdentity,
    WireIdentity,
    WireScope,
]:
    receipt_digest = hashlib.sha256(b"AFI08 local synthetic receipt").hexdigest()
    key = HmacControlKey(
        key_id=_KEY_ID,
        issuer=_ISSUER,
        secret=hashlib.sha256(b"AFI08 local synthetic signing key").digest(),
        not_before_utc=_NOW - 60,
        expires_at_utc=_NOW + 60,
    )
    policy = ControlIssuerPolicy(
        issuer=_ISSUER,
        policy_id="afi08-local-control-policy",
        grants=(
            ControlScopeGrant(
                account_id=_ACCOUNT_ID,
                mode=_MODE,
                scope=_COMMAND_SCOPE,
                actions=(ControlAction.FREEZE,),
                receipt_digests=(receipt_digest,),
            ),
        ),
        not_before_utc=_NOW - 60,
        expires_at_utc=_NOW + 60,
    )
    verifier = HmacControlCommandVerifier(
        _KeyResolver(key), _PolicyResolver(policy), max_command_ttl_seconds=60
    )
    ledger = DurableControlLedger(database_path, clock=_FixedClock())
    ingress = ControlIngress(ledger, verifier, clock=_FixedClock())
    caller = WireIdentity(
        role=WireRole.APPLICATION_CLIENT,
        principal_ref="application:afi08-test-console",
        actor_ref="operator:afi08-test-user",
        delegate_ref="operator-delegation:afi08-test",
    )
    owner = WireIdentity(
        role=WireRole.SERVICE,
        principal_ref="service:afi08-risk-owner",
        actor_ref="account-owner:afi08-paper-account",
        delegate_ref="risk-owner-delegation:afi08",
    )
    scope = WireScope(execution_domain_ref="paper:afi08", account_ref=_ACCOUNT_ID)
    binding = ControlCommandBinding(
        issuer=_ISSUER,
        account_id=_ACCOUNT_ID,
        mode=_MODE,
        scope=_COMMAND_SCOPE,
        actions=frozenset({ControlAction.FREEZE}),
    )
    target = MonitorControlTarget(
        ingress=ingress,
        caller_bindings={caller: binding},
        owner_identity=owner,
        executor_id="risk-owner:afi08-paper-account",
    )
    return ledger, MonitorControlService({scope: target}), caller, owner, scope


def _signed_freeze_arguments() -> dict[str, Any]:
    receipt_digest = hashlib.sha256(b"AFI08 local synthetic receipt").hexdigest()
    claims = {
        "schema_version": 1,
        "key_id": _KEY_ID,
        "issuer": _ISSUER,
        "command_id": _COMMAND_ID,
        "account_id": _ACCOUNT_ID,
        "mode": _MODE,
        "scope": _COMMAND_SCOPE,
        "action": ControlAction.FREEZE.value,
        "reason": _REASON,
        "receipt_digest": receipt_digest,
        "issued_at": _NOW - 1,
        "expires_at": _NOW + 30,
        "issuer_sequence": 1,
        "manual_resume_authorized": False,
    }
    payload = json.dumps(
        claims, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    key_id = _KEY_ID.encode("ascii")
    signature = hmac.new(
        hashlib.sha256(b"AFI08 local synthetic signing key").digest(),
        CONTROL_COMMAND_HMAC_DOMAIN + len(key_id).to_bytes(2, "big") + key_id + payload,
        hashlib.sha256,
    ).digest()
    return {
        "schema_version": 1,
        "payload_b64": base64.b64encode(payload).decode("ascii"),
        "signature_b64": base64.b64encode(signature).decode("ascii"),
    }


async def _register_second_user(client: AsyncClient) -> dict[str, str]:
    username = f"afi08_{uuid.uuid4().hex[:12]}"
    password = "Test12345678"
    registered = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@test.com", "password": password},
    )
    assert registered.status_code == 200, registered.text
    logged_in = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert logged_in.status_code == 200, logged_in.text
    return {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


@pytest.mark.asyncio
async def test_alert_acknowledgement_does_not_resume_a_durable_risk_freeze(
    client: AsyncClient, auth_user, tmp_path: Path
) -> None:
    owner_user, owner_headers = auth_user
    other_headers = await _register_second_user(client)

    async with async_session_maker() as session:
        owner = await session.scalar(select(User).where(User.username == owner_user["username"]))
        assert owner is not None
        alert = Alert(
            id="afi08-risk-freeze-alert",
            user_id=owner.id,
            alert_type=AlertType.RISK,
            severity=AlertSeverity.CRITICAL,
            status=AlertStatus.ACTIVE,
            title="Risk owner freeze active",
            message="New exposure remains frozen pending separate owner control.",
            details={"control_command_id": _COMMAND_ID},
            trigger_type="manual",
        )
        session.add(alert)
        await session.commit()

    ledger_path = tmp_path / "monitor-control.sqlite"
    ledger, control_service, caller, control_owner, wire_scope = _control_service(ledger_path)
    submitted = control_service.handle(
        "monitor.control",
        principal_ref=caller.principal_ref,
        identity=caller,
        scope=wire_scope,
        arguments=_signed_freeze_arguments(),
    )
    assert submitted["status"] == ControlStatus.PENDING.value
    claimed = control_service.handle(
        "monitor.claim",
        principal_ref=control_owner.principal_ref,
        identity=control_owner,
        scope=wire_scope,
        arguments={"schema_version": 2, "command_id": _COMMAND_ID},
    )
    assert claimed["claimed"] is True

    risk_path = tmp_path / "risk.sqlite"
    risk_scope = AccountScope("synthetic", _ACCOUNT_ID, _MODE)
    risk_gate = DurableRiskGate(
        risk_path,
        RiskPolicy("afi08-local-policy", Decimal("1000"), 10),
    )
    cause_id = monitor_freeze_cause_id(ledger.get(_COMMAND_ID).command)
    freeze_result = risk_gate.activate_freeze_once(risk_scope, cause_id, _REASON)
    assert freeze_result.status is FreezeActivationStatus.CREATED
    assert risk_gate.active_freeze_reasons(risk_scope) == [_REASON]

    effect_result = {
        "action": ControlAction.FREEZE.value,
        "cause_id": cause_id,
        "activation_status": freeze_result.status.value,
        "cause_active": True,
        "has_other_active_freezes": freeze_result.has_other_active_freezes,
        "risk_state": "active",
    }
    final_freeze = control_service.handle(
        "monitor.acknowledge",
        principal_ref=control_owner.principal_ref,
        identity=control_owner,
        scope=wire_scope,
        arguments={
            "schema_version": 2,
            "command_id": _COMMAND_ID,
            "outcome": ControlOwnerOutcome.APPLIED.value,
            "effect_ref": cause_id,
            "effect_result": effect_result,
        },
    )
    assert final_freeze["owner_final"] is True
    assert final_freeze["outcome"] == ControlOwnerOutcome.APPLIED.value
    assert final_freeze["effect_ref"] == cause_id

    unauthorized = await client.put(
        f"/api/v1/monitoring/{alert.id}/acknowledge", headers=other_headers
    )
    assert unauthorized.status_code == 404
    async with async_session_maker() as session:
        still_active = await session.get(Alert, alert.id)
        assert still_active is not None
        assert still_active.status == AlertStatus.ACTIVE
    assert ledger.get(_COMMAND_ID).status is ControlStatus.ACKNOWLEDGED
    assert risk_gate.active_freeze_reasons(risk_scope) == [_REASON]

    acknowledged = await client.put(
        f"/api/v1/monitoring/{alert.id}/acknowledge", headers=owner_headers
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json() == {"message": "Alert has been acknowledged"}

    async with async_session_maker() as session:
        saved_alert = await session.get(Alert, alert.id)
        assert saved_alert is not None
        assert saved_alert.status == AlertStatus.ACKNOWLEDGED

    reopened_ledger = DurableControlLedger(ledger_path, clock=_FixedClock())
    saved_command = reopened_ledger.get(_COMMAND_ID)
    assert saved_command is not None
    assert saved_command.command.action is ControlAction.FREEZE
    assert saved_command.status is ControlStatus.ACKNOWLEDGED
    assert saved_command.outcome == ControlOwnerOutcome.APPLIED.value
    assert saved_command.effect_ref == cause_id
    assert dict(saved_command.effect_result or {}) == effect_result
    reopened_risk_gate = DurableRiskGate(
        risk_path,
        RiskPolicy("afi08-local-policy", Decimal("1000"), 10),
    )
    assert reopened_risk_gate.active_freeze_reasons(risk_scope) == [_REASON]
