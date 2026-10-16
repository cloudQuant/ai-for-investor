"""AFI08 HTTP proof through the existing SDK owner host and RiskGate."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import queue
import socket
import threading
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

pytest.importorskip("bt_api_monitor", reason="optional Monitor SDK package is required")
pytest.importorskip("bt_api_risk", reason="optional Risk SDK package is required")
zmq = pytest.importorskip("zmq")

from app.api import monitoring as monitoring_api
from app.db.database import async_session_maker
from app.main import app
from app.models.alerts import Alert, AlertSeverity, AlertStatus, AlertType
from app.models.paper_trading import Account
from app.models.user import User
from app.services.monitoring_control import OwnerControlDeployment
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_monitor.control import (
    ControlAction,
    ControlCommandBinding,
    ControlIngress,
    ControlStatus,
    DurableControlLedger,
)
from bt_api_monitor.ingress import (
    ControlIssuerPolicy,
    ControlScopeGrant,
    HmacControlCommandVerifier,
    HmacControlKey,
)
from bt_api_monitor.service_control import MonitorControlService, MonitorControlTarget
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_monitor_control import MonitorControlRuntime, MonitorRiskControlOwner
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_risk import (
    AccountScope,
    DurableRiskGate,
    IntentAction,
    RiskDeniedError,
    RiskIntent,
    RiskPolicy,
)

_SERVICE_ID = "afi08-monitor-control-service"
_SERVICE_PRINCIPAL = "service:afi08-monitor-control"
_SERVICE_INSTANCE = "afi08-monitor-control-owner"
_SERVICE_ROOT_SCOPE_REF = "afi08-service-root-v1"
_SERVICE_SCOPE_REF = "afi08-monitor-control-route-v1"
_CLIENT_PRINCIPAL = "application:afi08-monitor-console"
_APPLICATION_REF = "application:afi08-monitor-console"
_MODE = "simulation"
_RECEIPT = hashlib.sha256(b"AFI08 operator-configured test receipt").hexdigest()
_RISK_POLICY = RiskPolicy(
    policy_id="afi08-owner-freeze-test-v1",
    max_increase_notional=Decimal("1000"),
    max_increase_count=10,
)


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


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"tcp://127.0.0.1:{port}"


def _communication(endpoint: str, *, server: bool) -> dict[str, Any]:
    profile = "listener-v1" if server else "client-curve-v1"
    security = "server-curve-v1" if server else "client-curve-v1"
    options: dict[str, int] = {"high_water_mark": 16, "max_message_bytes": 65_536}
    if not server:
        options["request_timeout_ms"] = 5_000
    return {
        "config_schema_version": 1,
        "profiles": {
            profile: {
                "backend": "zmq",
                "config_schema_version": 1,
                "endpoints": {"rpc_bind" if server else "rpc_connect": endpoint},
                "security_profile_ref": security,
                "options": options,
            }
        },
    }


def _service_config(endpoint: str):
    return parse_service_config(
        {
            "service_config_schema_version": 1,
            "process_role": "service",
            "service_id": _SERVICE_ID,
            "scope_ref": _SERVICE_ROOT_SCOPE_REF,
            "transport_ref": "listener-v1",
            "registration_policy_ref": "afi08-monitor-control-registration-v1",
            "service_requirements_ref": "afi08-monitor-control-requirements-v1",
            "components": {
                "monitor": {
                    "config_schema_version": 2,
                    "settings": {
                        "instance_id": _SERVICE_INSTANCE,
                        "bind_ports": ["service.monitor_control"],
                        "options": {"role": "control"},
                    },
                }
            },
            "communication": _communication(endpoint, server=True),
        }
    )


def _client_config(endpoint: str) -> dict[str, Any]:
    return {
        "client_config_schema_version": 1,
        "process_role": "application_client",
        "registration": {"application_ref": _APPLICATION_REF},
        "clients": {
            "monitor": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "application.monitor",
                            "service_id": _SERVICE_ID,
                            "instance_id": _SERVICE_INSTANCE,
                            "scope_ref": _SERVICE_SCOPE_REF,
                            "transport_ref": "client-curve-v1",
                        }
                    ],
                    "options": {"request_timeout_ms": 5_000},
                },
            }
        },
        "communication": _communication(endpoint, server=False),
    }


def _start_owner_host(
    tmp_path: Path,
    *,
    subject: str,
    afi_account_id: str,
    risk_account_id: str,
    lose_final_receipt: bool = False,
) -> tuple[OwnerControlDeployment, threading.Thread, threading.Event, dict[str, Any]]:
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    server_identity = WireIdentity(
        WireRole.SERVICE,
        _SERVICE_PRINCIPAL,
        _SERVICE_ID,
        "service-delegation:afi08-monitor-control",
    )
    client_identity = WireIdentity(
        WireRole.APPLICATION_CLIENT,
        _CLIENT_PRINCIPAL,
        _APPLICATION_REF,
        f"operator-delegation:{subject}",
    )
    owner_identity = WireIdentity(
        WireRole.SERVICE,
        "service:afi08-risk-owner",
        f"risk-owner:{risk_account_id}",
        f"monitor-owner-delegation:{risk_account_id}",
    )
    wire_scope = WireScope("paper:afi08-synthetic", account_ref=risk_account_id)
    issuer = f"operator:afi08:{subject}"
    key_ref = f"afi08-key-{uuid.uuid4().hex}"
    key_material = hashlib.sha256(f"afi08 synthetic key:{subject}".encode()).digest()
    now = time.time()
    client_config = _client_config(endpoint)
    deployment_json = {
        "schema_version": 1,
        "deployment_id": f"afi08-local-{uuid.uuid4().hex}",
        "deployment_version": "test-v1",
        "not_before_utc": now - 60.0,
        "expires_at_utc": now + 3600.0,
        "issuer_state_path": str((tmp_path / "afi-issuer-state.sqlite").resolve()),
        "bindings": [
            {
                "subject": subject,
                "afi_account_id": afi_account_id,
                "portfolio_ref": None,
                "account_id": risk_account_id,
                "mode": _MODE,
                "command_scope": f"account:{risk_account_id}:freeze",
                "issuer": issuer,
                "key_ref": key_ref,
                "key_material_b64": base64.b64encode(key_material).decode("ascii"),
                "issuer_policy_version": "afi08-freeze-policy-v1",
                "authority_receipt_digest": _RECEIPT,
                "not_before_utc": now - 60.0,
                "expires_at_utc": now + 3600.0,
                "issuer_sequence_start": 0,
                "allowed_actions": ["FREEZE"],
                "service_id": _SERVICE_ID,
                "instance_id": _SERVICE_INSTANCE,
                "scope_ref": _SERVICE_SCOPE_REF,
                "wire_account_ref": risk_account_id,
                "wire_portfolio_ref": None,
                "wire_scope": {
                    "execution_domain_ref": wire_scope.execution_domain_ref,
                    "account_ref": wire_scope.account_ref,
                },
                "client_identity": {
                    "principal_ref": client_identity.principal_ref,
                    "actor_ref": client_identity.actor_ref,
                    "delegate_ref": client_identity.delegate_ref,
                },
                "peer_identity": {
                    "principal_ref": server_identity.principal_ref,
                    "actor_ref": server_identity.actor_ref,
                    "delegate_ref": server_identity.delegate_ref,
                },
                "client_config": client_config,
                "curve_keys": {
                    "client-curve-v1": {
                        "server_key_z85": server_public.decode("ascii"),
                        "public_key_z85": client_public.decode("ascii"),
                        "secret_key_z85": client_secret.decode("ascii"),
                    }
                },
            }
        ],
    }
    deployment = OwnerControlDeployment.from_secret(
        SecretStr(json.dumps(deployment_json, sort_keys=True, separators=(",", ":")))
    )
    assert deployment is not None

    authority_policy = ControlIssuerPolicy(
        issuer=issuer,
        policy_id="afi08-freeze-policy-v1",
        grants=(
            ControlScopeGrant(
                account_id=risk_account_id,
                mode=_MODE,
                scope=f"account:{risk_account_id}:freeze",
                actions=(ControlAction.FREEZE,),
                receipt_digests=(_RECEIPT,),
                manual_resume_allowed=False,
            ),
        ),
        not_before_utc=now - 60.0,
        expires_at_utc=now + 3600.0,
    )
    issuer_key = HmacControlKey(
        key_id=key_ref,
        issuer=issuer,
        secret=key_material,
        not_before_utc=now - 60.0,
        expires_at_utc=now + 3600.0,
    )
    refs: dict[str, Any] = {"owner_apply_calls": 0, "ready": threading.Event()}
    stopped = threading.Event()
    host_result: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
    refs["host_result"] = host_result
    risk_scope = AccountScope("synthetic", risk_account_id, _MODE)

    def resource_provider(component, _instance_id, _options, _scope):
        if component != "monitor":
            raise AssertionError("the test host only serves Monitor control")
        gate = DurableRiskGate(tmp_path / "risk-owner.sqlite", _RISK_POLICY)
        gate.bind_policy(risk_scope)
        real_activate = gate.activate_freeze_once

        def apply_freeze(scope, cause_id, reason):
            refs["owner_apply_calls"] += 1
            refs["owner_apply_thread"] = threading.get_ident()
            applied = real_activate(scope, cause_id, reason)
            if lose_final_receipt:
                raise RuntimeError("synthetic owner acknowledgement uncertainty")
            return applied

        gate.activate_freeze_once = apply_freeze
        ledger = DurableControlLedger(tmp_path / "monitor-control.sqlite")
        verifier = HmacControlCommandVerifier(
            _KeyResolver(issuer_key), _PolicyResolver(authority_policy), max_command_ttl_seconds=30
        )
        ingress = ControlIngress(ledger, verifier)
        caller_binding = ControlCommandBinding(
            issuer=issuer,
            account_id=risk_account_id,
            mode=_MODE,
            scope=f"account:{risk_account_id}:freeze",
            actions=frozenset({ControlAction.FREEZE}),
        )
        target = MonitorControlTarget(
            ingress=ingress,
            caller_bindings={client_identity: caller_binding},
            owner_identity=owner_identity,
            executor_id=f"risk-owner:{risk_account_id}",
        )
        service = MonitorControlService({wire_scope: target})
        owner = MonitorRiskControlOwner(
            service,
            gate,
            risk_scope,
            wire_scope=wire_scope,
            owner_identity=owner_identity,
            executor_id=f"risk-owner:{risk_account_id}",
            account_id=risk_account_id,
            mode=_MODE,
            command_scope=f"account:{risk_account_id}:freeze",
        )
        runtime = MonitorControlRuntime(service, {wire_scope: owner})
        refs.update(gate=gate, ledger=ledger, service=service, owner=owner, runtime=runtime)
        return ComponentResources.owned(
            {"service": service, "owners": {wire_scope: owner}},
            ready=lambda: True,
            close=gate.close,
        )

    def serve() -> None:
        host = None
        try:
            refs["owner_thread"] = threading.get_ident()
            config = _service_config(endpoint)
            resource = ResourceGrant(
                _SERVICE_INSTANCE,
                "service.monitor_control",
                _SERVICE_SCOPE_REF,
                wire_scope,
                frozenset({"monitor.control", "monitor.control_status"}),
            )
            host = ServiceHost(
                config,
                TrustedServiceAuthority(
                    identity=server_identity,
                    scope=wire_scope,
                    scope_ref=config.scope_ref,
                    scope_version="afi08-synthetic-scope-v1",
                    security_ref="server-curve-v1",
                    security_version="afi08-synthetic-curve-v1",
                    registration_policy_ref=config.registration_policy_ref,
                    registration_policy_version="afi08-synthetic-registration-v1",
                    service_requirements_ref=config.service_requirements_ref,
                    service_requirements_version="afi08-synthetic-requirements-v1",
                    curve_public_key=server_public,
                    curve_secret_key=server_secret,
                    principals={client_public: _CLIENT_PRINCIPAL},
                    grants={
                        _CLIENT_PRINCIPAL: (
                            PrincipalGrant(client_identity, (resource,)),
                        )
                    },
                ),
                str(tmp_path / "service-registry.sqlite"),
                resource_provider,
            )
            host.start()
            refs["ready"].set()
            while not stopped.is_set():
                host.serve_once(25)
            host.close()
            host_result.put(("closed", host.state))
        except BaseException as error:
            refs["ready"].set()
            host_result.put(("error", getattr(error, "code", type(error).__name__)))
            if host is not None:
                try:
                    host.close()
                except BaseException:
                    pass

    thread = threading.Thread(target=serve, name="afi08-synthetic-monitor-owner", daemon=True)
    thread.start()
    if not refs["ready"].wait(10):
        stopped.set()
        thread.join(5)
        raise AssertionError("synthetic Monitor ServiceHost did not become ready")
    if "gate" not in refs:
        raise AssertionError(f"synthetic Monitor ServiceHost failed: {host_result.get(timeout=1)}")
    return deployment, thread, stopped, refs


async def _register_second_user(client: AsyncClient) -> dict[str, str]:
    username = f"afi08_{uuid.uuid4().hex[:12]}"
    registered = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@test.com", "password": "Test12345678"},
    )
    assert registered.status_code == 200, registered.text
    logged_in = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test12345678"}
    )
    assert logged_in.status_code == 200, logged_in.text
    return {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


async def _create_owned_alert(
    user_data: dict[str, str], *, alert_id: str, afi_account_id: str
) -> str:
    async with async_session_maker() as session:
        owner = await session.scalar(select(User).where(User.username == user_data["username"]))
        assert owner is not None
        session.add(Account(id=afi_account_id, user_id=owner.id, name="AFI08 synthetic control"))
        session.add(
            Alert(
                id=alert_id,
                user_id=owner.id,
                account_id=afi_account_id,
                alert_type=AlertType.RISK,
                severity=AlertSeverity.CRITICAL,
                status=AlertStatus.ACTIVE,
                title="Synthetic risk owner control",
                message="A separate signed owner freeze is required.",
                trigger_type="manual",
            )
        )
        await session.commit()
        return str(owner.id)


async def _stop_host(
    thread: threading.Thread, stopped: threading.Event, refs: dict[str, Any]
) -> None:
    stopped.set()
    thread.join(10)
    assert not thread.is_alive(), "synthetic Monitor ServiceHost did not close"
    result = refs["host_result"].get(timeout=1)
    assert result == ("closed", "closed"), result


async def _wait_for_owner_status(
    client: AsyncClient,
    command_id: str,
    headers: dict[str, str],
    expected_status: str,
) -> Any:
    deadline = time.monotonic() + 3.0
    last_response = None
    while time.monotonic() < deadline:
        last_response = await client.get(
            f"/api/v1/monitoring/control/commands/{command_id}", headers=headers
        )
        assert last_response.status_code in {200, 202}, last_response.text
        if last_response.json().get("status") == expected_status:
            return last_response
        await asyncio.sleep(0.025)
    raise AssertionError(
        f"owner status did not reach {expected_status!r}: "
        f"{last_response.status_code if last_response else None} "
        f"{last_response.text if last_response else '<no response>'}"
    )


@pytest.mark.asyncio
async def test_freeze_http_uses_authenticated_owner_runtime_and_ack_is_independent(
    client: AsyncClient, auth_user, tmp_path: Path
) -> None:
    user_data, headers = auth_user
    alert_id = f"afi08-alert-{uuid.uuid4().hex}"
    afi_account_id = f"afi08-account-{uuid.uuid4().hex}"
    risk_account_id = f"risk-account-{uuid.uuid4().hex}"
    subject = await _create_owned_alert(user_data, alert_id=alert_id, afi_account_id=afi_account_id)
    foreign_headers = await _register_second_user(client)
    deployment, host_thread, stopped, refs = _start_owner_host(
        tmp_path,
        subject=subject,
        afi_account_id=afi_account_id,
        risk_account_id=risk_account_id,
    )
    app.dependency_overrides[monitoring_api.get_owner_control_deployment] = lambda: deployment
    try:
        foreign_submit = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**foreign_headers, "Idempotency-Key": "foreign-freeze"},
            json={"action": "FREEZE", "portfolio_ref": None},
        )
        assert foreign_submit.status_code == 404

        response = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**headers, "Idempotency-Key": "freeze-alert-once"},
            json={"action": "FREEZE", "portfolio_ref": None},
        )
        assert response.status_code in {200, 202}, response.text
        submitted = response.json()
        command_id = submitted["command_id"]
        if submitted.get("owner_final") is True:
            projection = submitted
        else:
            completed = await _wait_for_owner_status(
                client, command_id, headers, ControlStatus.ACKNOWLEDGED.value
            )
            assert completed.status_code == 200
            projection = completed.json()
        assert projection["status"] == ControlStatus.ACKNOWLEDGED.value
        assert projection["outcome"] == "applied"
        assert projection["owner_final"] is True
        assert projection["reconciliation_required"] is False
        assert projection["effect_result"]["activation_status"] == "CREATED"

        repeat = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**headers, "Idempotency-Key": "freeze-alert-once"},
            json={"action": "FREEZE", "portfolio_ref": None},
        )
        assert repeat.status_code == 200
        assert repeat.json() == projection

        foreign_status = await client.get(
            f"/api/v1/monitoring/control/commands/{command_id}", headers=foreign_headers
        )
        assert foreign_status.status_code == 404
        status_response = await client.get(
            f"/api/v1/monitoring/control/commands/{command_id}", headers=headers
        )
        assert status_response.status_code == 200
        assert status_response.json() == projection

        for action, code in (
            ("DRAIN", "DRAIN_PENDING_IMPLEMENTATION"),
            ("CLOSE", "CLOSE_PENDING_DIM04_EXECUTION_JOURNAL_COORDINATION"),
        ):
            unsupported = await client.post(
                f"/api/v1/monitoring/control/alerts/{alert_id}",
                headers={**headers, "Idempotency-Key": f"unsupported-{action.lower()}"},
                json={"action": action, "portfolio_ref": None},
            )
            assert unsupported.status_code == 501
            assert unsupported.json()["details"]["code"] == code

        acknowledged = await client.put(
            f"/api/v1/monitoring/{alert_id}/acknowledge", headers=headers
        )
        assert acknowledged.status_code == 200
        async with async_session_maker() as session:
            saved_alert = await session.get(Alert, alert_id)
            assert saved_alert is not None
            assert saved_alert.status == AlertStatus.ACKNOWLEDGED

        gate = refs["gate"]
        saved_command = refs["ledger"].get(command_id)
        assert saved_command is not None
        assert saved_command.status is ControlStatus.ACKNOWLEDGED
        assert saved_command.outcome == "applied"
        assert gate.active_freeze_reasons(AccountScope("synthetic", risk_account_id, _MODE)) == [
            "AFI monitoring alert owner freeze"
        ]
        assert refs["owner_apply_calls"] == 1
        assert refs["owner_apply_thread"] == refs["owner_thread"]
        with pytest.raises(RiskDeniedError) as denied:
            gate.reserve(
                RiskIntent(
                    intent_id=f"afi08-increase-{uuid.uuid4().hex}",
                    scope=AccountScope("synthetic", risk_account_id, _MODE),
                    action=IntentAction.INCREASE,
                    notional=Decimal("1"),
                    payload_fingerprint="afi08-synthetic-increase",
                )
            )
        assert denied.value.code == "FROZEN"
    finally:
        await _stop_host(host_thread, stopped, refs)


@pytest.mark.asyncio
async def test_unknown_owner_receipt_stays_unknown_after_durable_freeze_effect(
    client: AsyncClient, auth_user, tmp_path: Path
) -> None:
    user_data, headers = auth_user
    alert_id = f"afi08-alert-{uuid.uuid4().hex}"
    afi_account_id = f"afi08-account-{uuid.uuid4().hex}"
    risk_account_id = f"risk-account-{uuid.uuid4().hex}"
    subject = await _create_owned_alert(user_data, alert_id=alert_id, afi_account_id=afi_account_id)
    deployment, host_thread, stopped, refs = _start_owner_host(
        tmp_path,
        subject=subject,
        afi_account_id=afi_account_id,
        risk_account_id=risk_account_id,
        lose_final_receipt=True,
    )
    app.dependency_overrides[monitoring_api.get_owner_control_deployment] = lambda: deployment
    try:
        response = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**headers, "Idempotency-Key": "freeze-owner-result-unknown"},
            json={"action": "FREEZE", "portfolio_ref": None},
        )
        assert response.status_code in {200, 202}, response.text
        submitted = response.json()
        command_id = submitted["command_id"]
        if submitted.get("status") == ControlStatus.UNKNOWN.value:
            command = submitted
        else:
            unknown = await _wait_for_owner_status(
                client, command_id, headers, ControlStatus.UNKNOWN.value
            )
            assert unknown.status_code == 202
            command = unknown.json()
        assert command["status"] == ControlStatus.UNKNOWN.value
        assert command["outcome"] == "unknown"
        assert command["owner_final"] is False
        assert command["reconciliation_required"] is True
        assert command["effect_ref"] is None
        assert command["effect_result"] is None

        status_response = await client.get(
            f"/api/v1/monitoring/control/commands/{command_id}", headers=headers
        )
        assert status_response.status_code == 202
        assert status_response.json()["status"] == ControlStatus.UNKNOWN.value
        assert status_response.json()["owner_final"] is False
        saved_command = refs["ledger"].get(command["command_id"])
        assert saved_command is not None
        assert saved_command.status is ControlStatus.UNKNOWN
        assert saved_command.outcome == "unknown"
        assert saved_command.effect_result is None
        assert refs["gate"].active_freeze_reasons(
            AccountScope("synthetic", risk_account_id, _MODE)
        ) == ["AFI monitoring alert owner freeze"]
        assert refs["owner_apply_calls"] >= 1
        assert refs["owner_apply_thread"] == refs["owner_thread"]
    finally:
        await _stop_host(host_thread, stopped, refs)


@pytest.mark.asyncio
async def test_unclaimed_expired_freeze_resolves_issuer_and_allows_next_command(
    client: AsyncClient, auth_user, tmp_path: Path
) -> None:
    user_data, headers = auth_user
    alert_id = f"afi08-alert-{uuid.uuid4().hex}"
    afi_account_id = f"afi08-account-{uuid.uuid4().hex}"
    risk_account_id = f"risk-account-{uuid.uuid4().hex}"
    subject = await _create_owned_alert(user_data, alert_id=alert_id, afi_account_id=afi_account_id)
    deployment, host_thread, stopped, refs = _start_owner_host(
        tmp_path,
        subject=subject,
        afi_account_id=afi_account_id,
        risk_account_id=risk_account_id,
    )
    app.dependency_overrides[monitoring_api.get_owner_control_deployment] = lambda: deployment
    owner = refs["owner"]
    owner_run_next = owner.run_next
    # Keep the real host and DurableRiskGate active while holding only the
    # actual owner executor, so the signed command remains unclaimed until TTL.
    owner.run_next = lambda: None
    control_clock = {"now": time.time() + 1.0}
    refs["ledger"]._clock = lambda: control_clock["now"]
    try:
        first = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**headers, "Idempotency-Key": "freeze-expire-unclaimed"},
            json={"action": "FREEZE", "portfolio_ref": None},
        )
        assert first.status_code == 202, first.text
        pending = first.json()
        first_id = pending["command_id"]
        assert pending["status"] == ControlStatus.PENDING.value
        assert pending["owner_final"] is False
        assert pending["effect_ref"] is None
        assert pending["effect_result"] is None
        assert refs["ledger"].get(first_id).status is ControlStatus.PENDING
        assert refs["owner_apply_calls"] == 0

        first_issuance = deployment._issuance_row(first_id)
        assert first_issuance is not None
        control_clock["now"] = float(first_issuance["expires_at"]) + 0.01
        owner.run_next = owner_run_next

        expired_response = await _wait_for_owner_status(
            client, first_id, headers, ControlStatus.EXPIRED.value
        )
        assert expired_response.status_code == 200
        expired = expired_response.json()
        assert expired["status"] == ControlStatus.EXPIRED.value
        assert expired["owner_final"] is False
        assert expired["outcome"] is None
        assert expired["reconciliation_required"] is False
        assert expired["effect_ref"] is None
        assert expired["effect_result"] is None
        first_saved = refs["ledger"].get(first_id)
        assert first_saved is not None
        assert first_saved.status is ControlStatus.EXPIRED
        assert first_saved.outcome == "command_ttl_elapsed"
        assert first_saved.effect_ref is None
        assert first_saved.effect_result is None
        first_issuance = deployment._issuance_row(first_id)
        assert first_issuance is not None
        assert first_issuance["owner_final"] == 0
        assert first_issuance["owner_status"] == ControlStatus.EXPIRED.value
        assert refs["owner_apply_calls"] == 0
        risk_scope = AccountScope("synthetic", risk_account_id, _MODE)
        assert refs["gate"].active_freeze_reasons(risk_scope) == []

        # Put the synthetic ledger clock back in step with the signer before
        # issuing the next fresh command from the same authorized issuer.
        control_clock["now"] = time.time() + 1.0
        second = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**headers, "Idempotency-Key": "freeze-after-expired-command"},
            json={"action": "FREEZE", "portfolio_ref": None},
        )
        assert second.status_code in {200, 202}, second.text
        second_projection = second.json()
        second_id = second_projection["command_id"]
        if second_projection.get("status") != ControlStatus.ACKNOWLEDGED.value:
            completed = await _wait_for_owner_status(
                client, second_id, headers, ControlStatus.ACKNOWLEDGED.value
            )
            assert completed.status_code == 200
            second_projection = completed.json()
        assert second_projection["status"] == ControlStatus.ACKNOWLEDGED.value
        assert second_projection["outcome"] == "applied"
        assert second_projection["owner_final"] is True
        assert refs["ledger"].get(second_id).status is ControlStatus.ACKNOWLEDGED
        second_issuance = deployment._issuance_row(second_id)
        assert second_issuance is not None
        assert second_issuance["issuer"] == first_issuance["issuer"]
        assert second_issuance["issuer_sequence"] > first_issuance["issuer_sequence"]
        assert refs["owner_apply_calls"] == 1
        assert refs["owner_apply_thread"] == refs["owner_thread"]
        assert refs["gate"].active_freeze_reasons(risk_scope) == [
            "AFI monitoring alert owner freeze"
        ]
    finally:
        owner.run_next = owner_run_next
        await _stop_host(host_thread, stopped, refs)
