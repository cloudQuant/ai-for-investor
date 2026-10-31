"""AFI08 HTTP proof through the existing SDK owner host and RiskGate."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import queue
import re
import socket
import sys
import threading
import time
import uuid
from collections.abc import Mapping
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

from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
from bt_api_execution import (  # noqa: E402
    CancelObservation,
    ExecutionScope,
    ProviderObservation,
    SqliteExecutionStore,
)
from bt_api_monitor.control import (  # noqa: E402
    ControlAction,
    ControlCommandBinding,
    ControlIngress,
    ControlStatus,
    DurableControlLedger,
)
from bt_api_monitor.ingress import (  # noqa: E402
    ControlIssuerPolicy,
    ControlScopeGrant,
    HmacControlCommandVerifier,
    HmacControlKey,
)
from bt_api_monitor.service_control import MonitorControlService, MonitorControlTarget  # noqa: E402
from bt_api_py.service_components import ComponentResources  # noqa: E402
from bt_api_py.service_config import parse_client_config, parse_service_config  # noqa: E402
from bt_api_py.service_execution_risk_cancel import RiskExecutionCancelAdmissionGate  # noqa: E402
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority  # noqa: E402
from bt_api_py.service_monitor_control import (  # noqa: E402
    MonitorControlRuntime,
    MonitorRiskControlOwner,
)
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant  # noqa: E402
from bt_api_py.service_risk_order_journal import RiskOrderJournal  # noqa: E402
from bt_api_py.service_runtime import (  # noqa: E402
    ClientCurveKeys,
    ServiceClientRuntime,
    ZmqTransportFactory,
)
from bt_api_risk import (  # noqa: E402
    AccountScope,
    DurableRiskGate,
    IntentAction,
    RiskDeniedError,
    RiskIntent,
    RiskPolicy,
)

from app.api import monitoring as monitoring_api  # noqa: E402
from app.db.database import async_session_maker  # noqa: E402
from app.main import app  # noqa: E402
from app.models.alerts import Alert, AlertSeverity, AlertStatus, AlertType  # noqa: E402
from app.models.paper_trading import Account  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import monitoring_control as monitoring_control_service  # noqa: E402
from app.services.monitoring_control import OwnerControlDeployment, OwnerControlError  # noqa: E402

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
    owner_action: ControlAction = ControlAction.FREEZE,
    lose_final_receipt: bool = False,
    command_scope_override: str | None = None,
    setup_resources: dict[str, Any] | None = None,
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
    stop_new = owner_action is ControlAction.STOP_NEW
    strategy_ref = f"strategy:afi08-{uuid.uuid4().hex}" if stop_new else None
    run_id = f"run:afi08-{uuid.uuid4().hex}" if stop_new else None
    wire_scope = WireScope(
        "paper:afi08-synthetic",
        account_ref=risk_account_id,
        strategy_ref=strategy_ref,
        run_id=run_id,
    )
    command_scope = (
        f"strategy:{strategy_ref}:{run_id}:stop_new"
        if stop_new
        else f"account:{risk_account_id}:freeze"
    )
    if command_scope_override is not None:
        command_scope = command_scope_override
    action_label = "stop-new" if stop_new else "freeze"
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
                "command_scope": command_scope,
                "issuer": issuer,
                "key_ref": key_ref,
                "key_material_b64": base64.b64encode(key_material).decode("ascii"),
                "issuer_policy_version": f"afi08-{action_label}-policy-v1",
                "authority_receipt_digest": _RECEIPT,
                "not_before_utc": now - 60.0,
                "expires_at_utc": now + 3600.0,
                "issuer_sequence_start": 0,
                "allowed_actions": [owner_action.name],
                "service_id": _SERVICE_ID,
                "instance_id": _SERVICE_INSTANCE,
                "scope_ref": _SERVICE_SCOPE_REF,
                "wire_account_ref": risk_account_id,
                "wire_portfolio_ref": None,
                "wire_scope": {
                    "execution_domain_ref": wire_scope.execution_domain_ref,
                    "account_ref": wire_scope.account_ref,
                    **(
                        {"strategy_ref": strategy_ref, "run_id": run_id}
                        if stop_new
                        else {}
                    ),
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
        policy_id=f"afi08-{action_label}-policy-v1",
        grants=(
            ControlScopeGrant(
                account_id=risk_account_id,
                mode=_MODE,
                scope=command_scope,
                actions=(owner_action,),
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
            scope=command_scope,
            actions=frozenset({owner_action}),
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
            command_scope=command_scope,
        )
        runtime = MonitorControlRuntime(service, {wire_scope: owner})
        refs.update(gate=gate, ledger=ledger, service=service, owner=owner, runtime=runtime)
        return ComponentResources.owned(
            {"service": service, "owners": {wire_scope: owner}},
            ready=lambda: True,
            close=gate.close,
        )

    def finite_error_code(error: BaseException) -> str:
        code = getattr(error, "code", None)
        if (
            type(code) is str
            and code
            and code.isascii()
            and code.replace("_", "").isalnum()
            and code.isupper()
        ):
            return code
        return type(error).__name__

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
            refs["host"] = host
            host.start()
            if stop_new:
                registry = host._registry
                if registry is None:
                    raise AssertionError("synthetic ServiceHost has no owner Registry")
                with registry._transaction():
                    claim = registry._claim_strategy_write(
                        wire_scope,
                        registry._now(),
                        f"afi08-seed-{uuid.uuid4().hex}",
                        frozenset({"orders.submit"}),
                    )
                if claim is not None:
                    raise AssertionError(f"synthetic strategy run was not claimed: {claim}")
                refs.update(registry=registry, wire_scope=wire_scope)
            refs["ready"].set()
            while not stopped.is_set():
                host.serve_once(25)
            host.close()
            host_result.put(("closed", host.state))
        except BaseException as error:
            cleanup_result: tuple[str, Any]
            if host is not None:
                try:
                    host.close()
                    cleanup_result = ("closed", getattr(host, "state", None))
                except BaseException as close_error:
                    cleanup_result = ("close_error", type(close_error).__name__)
            else:
                cleanup_result = ("not_created", None)
            host_result.put(("error", finite_error_code(error), cleanup_result))
            # `ready` means startup completed or failed with cleanup attempted.  It is
            # never a signal that a partially constructed owner is usable.
            refs["ready"].set()

    thread = threading.Thread(target=serve, name="afi08-synthetic-monitor-owner", daemon=True)
    if setup_resources is not None:
        # The test owns the thread/queue/refs before startup can block or fail.
        setup_resources["owner"] = (sys.modules[__name__], thread, stopped, refs)
    thread.start()
    if not refs["ready"].wait(10):
        stopped.set()
        thread.join(10)
        if thread.is_alive():
            raise AssertionError(
                "synthetic Monitor ServiceHost remained alive after startup timeout"
            )
        try:
            startup_result = host_result.get(timeout=1)
        except queue.Empty:
            startup_result = None
        refs["_owner_startup_result"] = startup_result
        if startup_result == ("closed", "closed") or (
            isinstance(startup_result, tuple)
            and len(startup_result) >= 3
            and startup_result[0] == "error"
            and startup_result[2] == ("closed", "closed")
        ):
            refs["_owner_close_result"] = ("closed", "closed")
        raise AssertionError("synthetic Monitor ServiceHost did not become ready")
    if not thread.is_alive():
        result = host_result.get(timeout=1)
        refs["_owner_startup_result"] = result
        if result == ("closed", "closed") or (
            isinstance(result, tuple)
            and len(result) >= 3
            and result[0] == "error"
            and result[2] == ("closed", "closed")
        ):
            refs["_owner_close_result"] = ("closed", "closed")
        if result[0] == "error":
            raise AssertionError(
                "synthetic Monitor ServiceHost failed before readiness: "
                f"{result[1]} cleanup={result[2]}"
            )
        raise AssertionError(f"synthetic Monitor ServiceHost exited before readiness: {result}")
    try:
        unexpected = host_result.get_nowait()
    except queue.Empty:
        unexpected = None
    if unexpected is not None:
        stopped.set()
        thread.join(10)
        refs["_owner_startup_result"] = unexpected
        if not thread.is_alive() and (
            unexpected == ("closed", "closed")
            or (
                isinstance(unexpected, tuple)
                and len(unexpected) >= 3
                and unexpected[0] == "error"
                and unexpected[2] == ("closed", "closed")
            )
        ):
            refs["_owner_close_result"] = ("closed", "closed")
        raise AssertionError(
            f"synthetic Monitor ServiceHost produced an early result: {unexpected}"
        )
    required_refs = {"owner_thread", "gate", "ledger", "service", "owner", "runtime"}
    if stop_new:
        required_refs.update({"registry", "wire_scope"})
    missing_refs = sorted(required_refs.difference(refs))
    if missing_refs:
        stopped.set()
        thread.join(10)
        if thread.is_alive():
            raise AssertionError(
                "synthetic Monitor ServiceHost missed required readiness fields and remained alive: "
                f"{missing_refs}"
            )
        result = host_result.get(timeout=1)
        refs["_owner_startup_result"] = result
        if result == ("closed", "closed") or (
            isinstance(result, tuple)
            and len(result) >= 3
            and result[0] == "error"
            and result[2] == ("closed", "closed")
        ):
            refs["_owner_close_result"] = ("closed", "closed")
        raise AssertionError(
            "synthetic Monitor ServiceHost missed required readiness fields: "
            f"{missing_refs}; shutdown={result}"
        )
    return deployment, thread, stopped, refs


def close_owner_host_thread(
    thread: threading.Thread, stopped: threading.Event, refs: dict[str, Any]
) -> None:
    prior_result = refs.get("_owner_close_result")
    if prior_result is not None:
        assert prior_result == ("closed", "closed"), prior_result
        return
    stopped.set()
    thread.join(10)
    assert not thread.is_alive(), "synthetic Monitor ServiceHost did not close"
    result = refs["host_result"].get(timeout=1)
    refs["_owner_close_result"] = result
    assert result == ("closed", "closed"), result


def test_stop_new_deployment_rejects_scope_label_not_bound_to_exact_run(tmp_path: Path) -> None:
    with pytest.raises(OwnerControlError) as raised:
        _start_owner_host(
            tmp_path,
            subject="operator:afi08-scope-binding",
            afi_account_id="afi08-account-scope-binding",
            risk_account_id="risk-account-scope-binding",
            owner_action=ControlAction.STOP_NEW,
            command_scope_override="strategy:some-other-run:stop_new",
        )
    assert raised.value.code == "DEPLOYMENT_INVALID"


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
    close_owner_host_thread(thread, stopped, refs)


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


_CANCEL_SERVICE_ID = "afi08-http-cancel-service"
_CANCEL_INSTANCE_ID = "afi08-http-cancel-execution-owner"
_CANCEL_DOMAIN = "paper:afi08-http-cancel"
_CANCEL_SCOPE_REF = "afi08-http-cancel-run-v1"
_CANCEL_LISTENER_REF = "afi08-http-cancel-listener-v1"
_CANCEL_OWNER_LISTENER_REF = "afi08-http-cancel-owner-client-listener-v1"
_CANCEL_CONNECT_REF = "afi08-http-cancel-connect-v1"
_CANCEL_SERVER_SECURITY_REF = "afi08-http-cancel-server-security-v1"
_CANCEL_STRATEGY_SECURITY_REF = "afi08-http-cancel-strategy-security-v1"
_CANCEL_OWNER_SECURITY_REF = "afi08-http-cancel-owner-security-v1"
_CANCEL_SERVICE_PRINCIPAL = "afi08-http-cancel-service-principal"
_CANCEL_STRATEGY_PRINCIPAL = "afi08-http-cancel-strategy-principal"
_CANCEL_OWNER_PRINCIPAL = "afi08-http-cancel-owner-principal"


def _cancel_execution_service_config(endpoint: str):
    return parse_service_config(
        {
            "service_config_schema_version": 1,
            "process_role": "service",
            "service_id": _CANCEL_SERVICE_ID,
            "scope_ref": "afi08-http-cancel-service-scope-v1",
            "transport_ref": _CANCEL_LISTENER_REF,
            "registration_policy_ref": "afi08-http-cancel-registration-v1",
            "service_requirements_ref": "afi08-http-cancel-requirements-v1",
            "components": {
                "execution": {
                    "config_schema_version": 2,
                    "settings": {
                        "instance_id": _CANCEL_INSTANCE_ID,
                        "bind_ports": [
                            "service.order_entry",
                            "service.order_query",
                            "service.owner_control",
                        ],
                        "options": {"role": "account_owner"},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    _CANCEL_LISTENER_REF: {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_bind": endpoint},
                        "security_profile_ref": _CANCEL_SERVER_SECURITY_REF,
                        "options": {"high_water_mark": 32, "max_message_bytes": 1_000_000},
                    }
                },
            },
        }
    )


def _cancel_owner_client_config(
    endpoint: str,
    *,
    strategy: bool,
    account_ref: str,
    strategy_ref: str | None = None,
) -> Any:
    if strategy:
        role = "strategy_client"
        if type(strategy_ref) is not str or not strategy_ref:
            raise ValueError("strategy_ref is required for a strategy client")
        registration: dict[str, Any] = {"strategy_ref": strategy_ref}
        mount = "broker.orders"
        security_ref = _CANCEL_STRATEGY_SECURITY_REF
        version = {"client_config_schema_version": 1}
    else:
        role = "service"
        registration = {
            "service_id": "afi08-http-cancel-owner-client",
            "scope_ref": "afi08-http-cancel-owner-client-scope-v1",
            "transport_ref": _CANCEL_OWNER_LISTENER_REF,
            "registration_policy_ref": "afi08-http-cancel-owner-client-registration-v1",
            "service_requirements_ref": "afi08-http-cancel-owner-client-requirements-v1",
        }
        mount = "upstream.owner_control"
        security_ref = _CANCEL_OWNER_SECURITY_REF
        version = {"service_config_schema_version": 1}
    config: dict[str, Any] = {
        "process_role": role,
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": mount,
                            "service_id": _CANCEL_SERVICE_ID,
                            "instance_id": _CANCEL_INSTANCE_ID,
                            "scope_ref": _CANCEL_SCOPE_REF,
                            "transport_ref": _CANCEL_CONNECT_REF,
                            "account_ref": account_ref,
                        }
                    ],
                    "options": {
                        "request_timeout_ms": 3_000,
                        "heartbeat_interval_seconds": 5,
                    },
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _CANCEL_CONNECT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": endpoint},
                    "security_profile_ref": security_ref,
                    "options": {
                        "request_timeout_ms": 3_000,
                        "high_water_mark": 32,
                        "max_message_bytes": 1_000_000,
                    },
                }
            },
        },
    }
    if strategy:
        config.update(version)
        config["registration"] = registration
        return parse_client_config(config)
    config.update(registration)
    config.update(version)
    config["components"] = {
        "monitor": {
            "config_schema_version": 2,
            "settings": {
                "instance_id": "afi08-http-cancel-unused-monitor",
                "bind_ports": ["service.monitor_query"],
                "options": {},
            },
        }
    }
    config["communication"]["profiles"][_CANCEL_OWNER_LISTENER_REF] = {
        "backend": "zmq",
        "config_schema_version": 1,
        "endpoints": {"rpc_bind": "tcp://127.0.0.1:9"},
        "security_profile_ref": security_ref,
        "options": {"high_water_mark": 32, "max_message_bytes": 1_000_000},
    }
    return parse_service_config(config)


class _HttpCancelProvider:
    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.cancelled: list[str] = []

    def submit(self, intent: Any) -> ProviderObservation:
        self.submitted.append(intent.intent_id)
        return ProviderObservation.accepted(
            intent.intent_id, f"provider-order:{intent.intent_id}"
        )

    def cancel(self, intent: Any) -> CancelObservation:
        self.cancelled.append(intent.cancel_id)
        if intent.target_intent_id.endswith("-unknown"):
            raise TimeoutError("synthetic provider secret detail must not reach HTTP")
        return CancelObservation.accepted(
            intent.cancel_id, intent.target_intent_id, intent.provider_order_id
        )


def _start_cancel_execution_host(
    tmp_path: Path,
    *,
    afi_subject: str,
    afi_account_id: str,
    risk_account_id: str,
    strategy_ref: str,
    run_id: str,
    endpoint: str,
) -> tuple[OwnerControlDeployment, threading.Thread, threading.Event, dict[str, Any]]:
    server_public, server_secret = zmq.curve_keypair()
    strategy_public, strategy_secret = zmq.curve_keypair()
    owner_public, owner_secret = zmq.curve_keypair()
    service_identity = WireIdentity(
        WireRole.SERVICE,
        _CANCEL_SERVICE_PRINCIPAL,
        _CANCEL_SERVICE_ID,
        "service-delegation:afi08-http-cancel",
    )
    strategy_identity = WireIdentity(
        WireRole.STRATEGY_CLIENT,
        _CANCEL_STRATEGY_PRINCIPAL,
        strategy_ref,
    )
    owner_identity = WireIdentity(
        WireRole.SERVICE,
        _CANCEL_OWNER_PRINCIPAL,
        f"operator:afi08:{afi_subject}",
        f"owner-delegation:afi08:{afi_subject}",
    )
    wire_scope = WireScope(
        _CANCEL_DOMAIN,
        account_ref=risk_account_id,
        strategy_ref=strategy_ref,
        run_id=run_id,
    )
    target_scope = WireScope(
        _CANCEL_DOMAIN,
        account_ref=risk_account_id,
        strategy_ref=strategy_ref,
    )
    execution_scope = ExecutionScope(
        "PAPER", "simulation", risk_account_id, strategy_ref, "afi08-http-cancel-session"
    )
    config = _cancel_execution_service_config(endpoint)
    authority = TrustedServiceAuthority(
        identity=service_identity,
        scope=WireScope(_CANCEL_DOMAIN),
        scope_ref=config.scope_ref,
        scope_version="afi08-http-cancel-scope-v1",
        security_ref=_CANCEL_SERVER_SECURITY_REF,
        security_version="curve-v1",
        registration_policy_ref=config.registration_policy_ref,
        registration_policy_version="afi08-http-cancel-registration-v1",
        service_requirements_ref=config.service_requirements_ref,
        service_requirements_version="afi08-http-cancel-requirements-v1",
        curve_public_key=server_public,
        curve_secret_key=server_secret,
        principals={
            strategy_public: _CANCEL_STRATEGY_PRINCIPAL,
            owner_public: _CANCEL_OWNER_PRINCIPAL,
        },
        grants={
            _CANCEL_STRATEGY_PRINCIPAL: (
                PrincipalGrant(
                    strategy_identity,
                    (
                        ResourceGrant(
                            _CANCEL_INSTANCE_ID,
                            "service.order_entry",
                            _CANCEL_SCOPE_REF,
                            target_scope,
                            frozenset({"orders.submit"}),
                        ),
                    ),
                ),
            ),
            _CANCEL_OWNER_PRINCIPAL: (
                PrincipalGrant(
                    owner_identity,
                    (
                        ResourceGrant(
                            _CANCEL_INSTANCE_ID,
                            "service.owner_control",
                            _CANCEL_SCOPE_REF,
                            wire_scope,
                            frozenset({"owner.cancel"}),
                        ),
                    ),
                ),
            ),
        },
    )
    execution_store = SqliteExecutionStore(tmp_path / "http-cancel-execution.sqlite3")
    risk_journal = RiskOrderJournal(
        tmp_path / "http-cancel-risk-journal.sqlite3", writer_id="afi08-http-cancel-journal"
    )
    risk_scope = AccountScope("PAPER", risk_account_id, "simulation")
    risk_gate = DurableRiskGate(
        tmp_path / "http-cancel-risk.sqlite3",
        RiskPolicy(
            "afi08-http-cancel-risk-v1",
            Decimal("0"),
            max_increase_count=0,
            permit_ttl_seconds=30,
            notional_unit="USD",
        ),
        execution_journal_authority=risk_journal,
    )
    cancel_gate = RiskExecutionCancelAdmissionGate(
        risk_gate,
        risk_journal,
        execution_store,
        risk_scope=risk_scope,
        execution_scope=execution_scope,
        wire_scope_template=target_scope,
    )
    provider = _HttpCancelProvider()
    quota_calls: list[tuple[object, ...]] = []

    def quota_admission(*args: object) -> None:
        quota_calls.append(args)
        return None

    def resource_provider(component: str, instance_id: str, _options: Any, _scope: Any):
        assert component == "execution" and instance_id == _CANCEL_INSTANCE_ID
        return ComponentResources.borrowed(
            {
                "store": execution_store,
                "targets": {target_scope: execution_scope},
                "dispatch": provider,
                "admission": {
                    "cancel_gate": cancel_gate,
                    "cancel_quota_admission": quota_admission,
                    "allow_unprotected": True,
                },
            },
            ready=lambda: True,
        )

    host = ServiceHost(
        config,
        authority,
        tmp_path / "http-cancel-registry.sqlite3",
        resource_provider,
    )
    stopped = threading.Event()
    ready = threading.Event()
    host_result: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
    refs: dict[str, Any] = {
        "host": host,
        "host_result": host_result,
        "ready": ready,
        "provider": provider,
        "quota_calls": quota_calls,
        "execution_store": execution_store,
        "risk_gate": risk_gate,
    }

    def serve() -> None:
        try:
            refs["owner_thread"] = threading.get_ident()
            host.start()
            ready.set()
            while not stopped.is_set():
                host.serve_once(timeout_ms=15)
            host.close()
            host_result.put(("closed", host.state))
        except BaseException as error:
            ready.set()
            host_result.put(
                (
                    "error",
                    getattr(error, "code", type(error).__name__),
                    host.summary,
                )
            )
            try:
                if host.state != "closed":
                    host.close()
            except BaseException:
                pass

    thread = threading.Thread(target=serve, name="afi08-http-cancel-execution-host", daemon=True)
    thread.start()
    if not ready.wait(10):
        stopped.set()
        thread.join(5)
        raise AssertionError("synthetic Execution ServiceHost did not become ready")
    host_result_value = host_result.get_nowait() if not host_result.empty() else None
    if host_result_value is not None:
        stopped.set()
        thread.join(5)
        risk_gate.close()
        execution_store.close()
        raise AssertionError(f"synthetic Execution ServiceHost failed: {host_result_value}")

    now = time.time()
    client_config = _cancel_owner_client_config(
        endpoint, strategy=False, account_ref=risk_account_id
    ).to_public_dict()
    server_public_z85 = server_public.decode("ascii")
    owner_public_z85 = owner_public.decode("ascii")
    owner_secret_z85 = owner_secret.decode("ascii")
    issuer = f"operator:afi08:{afi_subject}:cancel"
    binding = {
        "subject": afi_subject,
        "afi_account_id": afi_account_id,
        "portfolio_ref": None,
        "account_id": risk_account_id,
        "mode": "simulation",
        "command_scope": f"strategy:{strategy_ref}:{run_id}:cancel",
        "issuer": issuer,
        "key_ref": f"afi08-cancel-key-{uuid.uuid4().hex}",
        "key_material_b64": base64.b64encode(
            hashlib.sha256(f"AFI08 cancel key:{afi_subject}".encode()).digest()
        ).decode("ascii"),
        "issuer_policy_version": "afi08-cancel-policy-v1",
        "authority_receipt_digest": hashlib.sha256(b"AFI08 exact-run cancel receipt").hexdigest(),
        "not_before_utc": now - 60,
        "expires_at_utc": now + 3600,
        "issuer_sequence_start": 0,
        "allowed_actions": ["CANCEL"],
        "service_id": _CANCEL_SERVICE_ID,
        "instance_id": _CANCEL_INSTANCE_ID,
        "scope_ref": _CANCEL_SCOPE_REF,
        "wire_account_ref": risk_account_id,
        "wire_portfolio_ref": None,
        "wire_scope": {
            "execution_domain_ref": _CANCEL_DOMAIN,
            "account_ref": risk_account_id,
            "strategy_ref": strategy_ref,
            "run_id": run_id,
        },
        "client_identity": {
            "principal_ref": _CANCEL_OWNER_PRINCIPAL,
            "actor_ref": owner_identity.actor_ref,
            "delegate_ref": owner_identity.delegate_ref,
        },
        "peer_identity": {
            "principal_ref": service_identity.principal_ref,
            "actor_ref": service_identity.actor_ref,
            "delegate_ref": service_identity.delegate_ref,
        },
        "client_config": client_config,
        "curve_keys": {
            _CANCEL_OWNER_SECURITY_REF: {
                "server_key_z85": server_public_z85,
                "public_key_z85": owner_public_z85,
                "secret_key_z85": owner_secret_z85,
            }
        },
    }
    deployment_json = {
        "schema_version": 1,
        "deployment_id": f"afi08-cancel-deployment-{uuid.uuid4().hex}",
        "deployment_version": "test-cancel-v1",
        "not_before_utc": now - 60,
        "expires_at_utc": now + 3600,
        "issuer_state_path": str((tmp_path / "afi08-cancel-issuer.sqlite3").resolve()),
        "bindings": [binding],
    }
    deployment = OwnerControlDeployment.from_secret(
        SecretStr(json.dumps(deployment_json, sort_keys=True, separators=(",", ":")))
    )
    assert deployment is not None
    refs["deployment"] = deployment
    refs["strategy_runtime_config"] = _cancel_owner_client_config(
        endpoint,
        strategy=True,
        account_ref=risk_account_id,
        strategy_ref=strategy_ref,
    )
    refs["strategy_identity"] = strategy_identity
    refs["strategy_public"] = strategy_public
    refs["strategy_secret"] = strategy_secret
    refs["server_public"] = server_public
    refs["service_identity"] = service_identity
    refs["target_scope"] = target_scope
    refs["wire_scope"] = wire_scope
    return deployment, thread, stopped, refs


@pytest.mark.asyncio
async def test_cancel_http_projects_partial_unknown_without_redispatch(
    client: AsyncClient, auth_user, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_data, headers = auth_user
    alert_id = f"afi08-cancel-alert-{uuid.uuid4().hex}"
    afi_account_id = f"afi08-cancel-account-{uuid.uuid4().hex}"
    risk_account_id = f"risk-afi08-cancel-account-{uuid.uuid4().hex}"
    strategy_ref = f"strategy:afi08-cancel-{uuid.uuid4().hex}"
    run_id = f"run:afi08-cancel-{uuid.uuid4().hex}"
    endpoint = _endpoint()
    subject = await _create_owned_alert(
        user_data, alert_id=alert_id, afi_account_id=afi_account_id
    )
    foreign_headers = await _register_second_user(client)
    deployment, host_thread, stopped, refs = _start_cancel_execution_host(
        tmp_path,
        afi_subject=subject,
        afi_account_id=afi_account_id,
        risk_account_id=risk_account_id,
        strategy_ref=strategy_ref,
        run_id=run_id,
        endpoint=endpoint,
    )
    app.dependency_overrides[monitoring_api.get_owner_control_deployment] = lambda: deployment
    owner_rpc_observations: list[dict[str, Any]] = []
    original_load_sdk = monitoring_control_service._load_sdk

    def load_traced_sdk() -> Any:
        sdk = original_load_sdk()
        runtime_type = sdk.ServiceClientRuntime

        class TracedServiceClientRuntime(runtime_type):
            def start(self):
                summary = super().start()
                owner_rpc_observations.append(
                    {
                        "phase": "runtime_started",
                        "degraded_count": summary.degraded_count,
                        "binding_count": len(summary.bindings),
                    }
                )
                return summary

            def call(self, mount: str, operation: str, arguments: Any, **kwargs: Any):
                try:
                    reply = super().call(mount, operation, arguments, **kwargs)
                except Exception as error:
                    if operation == "owner.cancel":
                        owner_rpc_observations.append(
                            {
                                "phase": "owner_call_error",
                                "error_type": type(error).__name__,
                                "error_code": getattr(error, "code", None),
                            }
                        )
                    raise
                if operation == "owner.cancel":
                    result = reply.get("result") if isinstance(reply, Mapping) else None
                    owner_rpc_observations.append(
                        {
                            "phase": "owner_reply",
                            "reply_type": type(reply).__name__,
                            "reply_fields": sorted(reply) if isinstance(reply, Mapping) else None,
                            "reply_code": reply.get("code") if isinstance(reply, Mapping) else None,
                            "result_fields": sorted(result) if isinstance(result, Mapping) else None,
                            "outcome": result.get("outcome") if isinstance(result, Mapping) else None,
                            "item_count": len(result.get("items", ()))
                            if isinstance(result, Mapping)
                            and type(result.get("items")) in (list, tuple)
                            else None,
                        }
                    )
                return reply

        return type("_TracedSdk", (), sdk.__dict__ | {"ServiceClientRuntime": TracedServiceClientRuntime})

    monkeypatch.setattr(monitoring_control_service, "_load_sdk", load_traced_sdk)
    strategy_runtime: ServiceClientRuntime | None = None
    try:
        foreign_submit = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**foreign_headers, "Idempotency-Key": "foreign-cancel"},
            json={"action": "CANCEL", "portfolio_ref": None},
        )
        assert foreign_submit.status_code == 404

        caller_selected_orders = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**headers, "Idempotency-Key": "caller-selected-cancel"},
            json={"action": "CANCEL", "portfolio_ref": None, "order_ids": ["forged"]},
        )
        assert caller_selected_orders.status_code == 422

        strategy_identity = refs["strategy_identity"]
        target_scope = refs["target_scope"]
        service_identity = refs["service_identity"]
        strategy_runtime = ServiceClientRuntime(
            refs["strategy_runtime_config"],
            identity=strategy_identity,
            scope_resolver=lambda _scope_ref: target_scope,
            peer_resolver=lambda _service_id: service_identity,
            transport_factory=ZmqTransportFactory(
                {
                    _CANCEL_STRATEGY_SECURITY_REF: ClientCurveKeys(
                        refs["server_public"], refs["strategy_public"], refs["strategy_secret"]
                    )
                }
            ),
            run_id=run_id,
            requested_operations={"broker.orders": frozenset({"orders.submit"})},
        )
        summary = strategy_runtime.start()
        assert summary.degraded_count == 0 and len(summary.bindings) == 1
        for suffix in ("-ack", "-unknown"):
            intent_id = f"afi08-http-cancel-order{suffix}"
            submitted = strategy_runtime.call(
                "broker.orders",
                "orders.submit",
                {
                    "intent_id": intent_id,
                    "signal_id": f"signal:{intent_id}",
                    "instrument": "BTC-USDT",
                    "side": "BUY",
                    "position_effect": "OPEN",
                    "order_type": "LIMIT",
                    "quantity": "1",
                    "price": "50000",
                    "time_in_force": "GTC",
                    "reduce_only": False,
                    "metadata_version": "afi08-http-cancel-v1",
                    "deadline_ns": None,
                    "tags": {},
                },
                account_ref=risk_account_id,
                scope_ref=_CANCEL_SCOPE_REF,
            )
            assert submitted["ok"] is True and submitted["result"]["found"] is True
            assert submitted["result"]["record"]["state"] == "ACKED"
        assert refs["provider"].submitted == [
            "afi08-http-cancel-order-ack",
            "afi08-http-cancel-order-unknown",
        ]

        response = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**headers, "Idempotency-Key": "cancel-exact-run-once"},
            json={"action": "CANCEL", "portfolio_ref": None},
        )
        assert response.status_code == 202, response.text
        projection = response.json()
        assert projection["action"] == "cancel"
        assert projection["status"] == "unknown"
        assert projection["outcome"] == "unknown"
        assert projection["owner_final"] is False
        assert projection["reconciliation_required"] is True
        assert "scope_key" not in json.dumps(projection)
        assert "synthetic provider secret detail" not in response.text
        items = projection["effect_result"]["items"]
        assert len(items) == 2, {
            "projection": projection,
            "owner_rpc_observations": owner_rpc_observations,
            "host_state": refs["host"].state,
            "host_thread_alive": host_thread.is_alive(),
            "host_provider_cancel_count": len(refs["provider"].cancelled),
        }
        by_suffix = {item["intent_id"].rsplit("-", 1)[-1]: item for item in items}
        assert by_suffix["ack"]["cancel_state"] == "ACKED"
        assert by_suffix["ack"]["dispatch_attempts"] == 1
        assert by_suffix["unknown"]["cancel_state"] == "UNKNOWN"
        assert by_suffix["unknown"]["dispatch_attempts"] == 1
        assert by_suffix["unknown"]["unknown_reason"] == "outcome_unknown"
        assert len(refs["provider"].cancelled) == 2
        assert len(refs["quota_calls"]) == 2
        for call in refs["quota_calls"]:
            assert call[:5] == (risk_account_id, strategy_ref, run_id, "BTC-USDT", "CANCEL")
            assert type(call[5]) is int and call[5] > 0

        command_id = projection["command_id"]
        foreign_status = await client.get(
            f"/api/v1/monitoring/control/commands/{command_id}", headers=foreign_headers
        )
        assert foreign_status.status_code == 404
        status_response = await client.get(
            f"/api/v1/monitoring/control/commands/{command_id}", headers=headers
        )
        assert status_response.status_code == 202, status_response.text
        assert status_response.json() == projection

        replay = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**headers, "Idempotency-Key": "cancel-exact-run-once"},
            json={"action": "CANCEL", "portfolio_ref": None},
        )
        assert replay.status_code == 202, replay.text
        assert replay.json() == projection
        assert refs["provider"].cancelled == [item["cancel_id"] for item in items]
        assert len(refs["quota_calls"]) == 2
        issued = deployment._issuance_row(command_id)
        assert issued is not None and issued["owner_final"] == 0
        saved = json.loads(issued["owner_projection_json"])
        assert saved == projection
    finally:
        app.dependency_overrides.pop(monitoring_api.get_owner_control_deployment, None)
        if strategy_runtime is not None:
            strategy_runtime.close()
        await _stop_host(host_thread, stopped, refs)
        refs["risk_gate"].close()
        refs["execution_store"].close()


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


@pytest.mark.asyncio
async def test_stop_new_http_fences_exact_owner_run_and_returns_persisted_receipt(
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
        owner_action=ControlAction.STOP_NEW,
    )
    app.dependency_overrides[monitoring_api.get_owner_control_deployment] = lambda: deployment
    try:
        foreign = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**foreign_headers, "Idempotency-Key": "foreign-stop-new"},
            json={"action": "STOP_NEW", "portfolio_ref": None},
        )
        assert foreign.status_code == 404

        response = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**headers, "Idempotency-Key": "stop-new-exact-run"},
            json={"action": "STOP_NEW", "portfolio_ref": None},
        )
        assert response.status_code in {200, 202}, response.text
        submitted = response.json()
        command_id = submitted["command_id"]
        assert command_id.startswith("afi-monitor-stop-new-v1-")
        assert submitted["action"] == "stop_new"
        if submitted.get("status") == ControlStatus.ACKNOWLEDGED.value:
            applied = submitted
        else:
            completed = await _wait_for_owner_status(
                client, command_id, headers, ControlStatus.ACKNOWLEDGED.value
            )
            assert completed.status_code == 200
            applied = completed.json()
        assert applied["status"] == ControlStatus.ACKNOWLEDGED.value
        assert applied["outcome"] == "applied"
        assert applied["owner_final"] is True
        assert applied["reconciliation_required"] is False
        assert applied["effect_result"] == {"action": "stop_new", "result": "fenced"}
        assert re.fullmatch(r"strategy-stop-new-v1:[0-9a-f]{64}", applied["effect_ref"])

        status_response = await client.get(
            f"/api/v1/monitoring/control/commands/{command_id}", headers=headers
        )
        assert status_response.status_code == 200
        assert status_response.json() == applied
        repeat = await client.post(
            f"/api/v1/monitoring/control/alerts/{alert_id}",
            headers={**headers, "Idempotency-Key": "stop-new-exact-run"},
            json={"action": "STOP_NEW", "portfolio_ref": None},
        )
        assert repeat.status_code == 200
        assert repeat.json() == applied

        registry = refs["registry"]
        scope = refs["wire_scope"]
        assert registry._strategy_write_is_stopped(scope) is True
        with registry._transaction():
            fence = registry._db.execute(
                "SELECT stop_new_command_id FROM strategy_write_claims "
                "WHERE execution_domain_ref=? AND strategy_ref=? AND account_ref=?",
                (scope.execution_domain_ref, scope.strategy_ref, scope.account_ref),
            ).fetchone()
            receipt = registry._db.execute(
                "SELECT status, effect_ref, effect_result_json FROM strategy_stop_new_receipts "
                "WHERE command_id=?",
                (command_id,),
            ).fetchone()
            denied_reentry = registry._claim_strategy_write(
                scope,
                registry._now(),
                f"afi08-late-registration-{uuid.uuid4().hex}",
                frozenset({"orders.submit"}),
            )
        assert fence is not None and fence["stop_new_command_id"] == command_id
        assert receipt is not None and receipt["status"] == "applied"
        assert json.loads(receipt["effect_result_json"]) == applied["effect_result"]
        assert denied_reentry == "STRATEGY_STOPPED"
        assert refs["ledger"].get(command_id).status is ControlStatus.ACKNOWLEDGED
        assert refs["gate"].active_freeze_reasons(
            AccountScope("synthetic", risk_account_id, _MODE)
        ) == []

        for action, code in (
            ("DRAIN", "DRAIN_PENDING_IMPLEMENTATION"),
            ("CLOSE", "CLOSE_PENDING_DIM04_EXECUTION_JOURNAL_COORDINATION"),
        ):
            pending = await client.post(
                f"/api/v1/monitoring/control/alerts/{alert_id}",
                headers={**headers, "Idempotency-Key": f"unsupported-{action.lower()}"},
                json={"action": action, "portfolio_ref": None},
            )
            assert pending.status_code == 501
            assert pending.json()["details"]["code"] == code
    finally:
        await _stop_host(host_thread, stopped, refs)
