"""Owner-scoped HTTP start/stop through the real local Gateway account Host."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import zmq
from bt_api_base.account_protocol import (
    AccountBalance,
    AccountKey,
    AccountObservation,
    AccountResourceKey,
    AccountValuation,
)
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_gateway.event_journal import GatewayEventJournal
from bt_api_gateway.router import GatewayCommandKind, GatewayPrincipal
from bt_api_gateway.service_component import GatewayServiceAccountScope
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_gateway.session_owner import GatewaySessionOwner
from bt_api_py.gateway_operator import GatewayAccountSessionBinding, GatewayOperatorDeployment
from bt_api_py.gateway_operator_application import (
    GatewayOperatorProfile,
    GatewayOperatorProfileRegistry,
)
from bt_api_py.service_config import parse_service_config
from bt_api_py.service_host import TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from fastapi import FastAPI

from app.api.afi_owner_scope import PersistedOwnerScope, require_persisted_owner_scope
from app.api.service_gateway_operator import router as operator_router
from app.services.live_trading import manager as live_manager_module
from app.services.service_gateway_operator import ServiceGatewayOperatorControl

_OWNER = "afi08-account-owner"
_FOREIGN_OWNER = "afi08-foreign-owner"
_PROFILE_REF = "afi08-local-account-operator"
_FOREIGN_PROFILE_REF = "afi08-foreign-account-operator"
_ACCOUNT_REF = "afi08-local-account"
_FOREIGN_ACCOUNT_REF = "afi08-foreign-account"
_DOMAIN_REF = "paper:afi08-local-account-owner"
_SERVICE_ID = "afi08-local-gateway-service"
_INSTANCE_ID = "afi08-local-gateway"
_SCOPE_REF = "afi08-local-gateway-scope"
_SECURITY_REF = "afi08-local-gateway-security"
_TRANSPORT_REF = "afi08-local-gateway-transport"
_SESSION_REF = "afi08-local-account-session"
_CREDENTIAL_REF = "afi08-synthetic-credential-ref"
_SERVICE_PRINCIPAL = "afi08-local-gateway-service-principal"
_CLIENT_PRINCIPAL = "afi08-local-gateway-client-principal"
_CLIENT_APPLICATION = "afi08-local-gateway-client"


def _free_rpc_endpoint() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"
    finally:
        probe.close()


def _account_service_config(rpc_bind: str) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _SERVICE_ID,
        "scope_ref": _SCOPE_REF,
        "transport_ref": _TRANSPORT_REF,
        "registration_policy_ref": "afi08-local-gateway-policy",
        "service_requirements_ref": "afi08-local-gateway-requirements",
        "components": {
            "gateway": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _INSTANCE_ID,
                    "bind_ports": ["service.account_read", "service.provider_session"],
                    "options": {
                        "role": "account_session_worker",
                        "account_session_ref": _SESSION_REF,
                    },
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": rpc_bind},
                    "security_profile_ref": _SECURITY_REF,
                    "options": {"high_water_mark": 32, "max_message_bytes": 262_144},
                }
            },
        },
    }


class _SyntheticAccountProvider:
    """Local provider leaf; the production Gateway worker and Host stay real."""

    def __init__(self, account_key: AccountKey) -> None:
        self._account_key = account_key
        self._generation: str | None = None
        self.calls: list[tuple[str, int]] = []
        self.close_calls = 0

    def connect(self, *, account_key: AccountKey, generation: str, timeout: float) -> None:
        assert account_key == self._account_key
        assert generation and timeout > 0
        assert self._generation is None
        self.calls.append(("connect", threading.get_ident()))
        self._generation = generation

    def read_account(self, *, generation: str, timeout: float) -> AccountObservation:
        assert generation == self._generation
        assert timeout > 0
        self.calls.append(("read_account", threading.get_ident()))
        observed_at = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        cash = AccountResourceKey("spot", "cash")
        return AccountObservation(
            account_key=self._account_key,
            observation_id="afi08-local-account-snapshot-1",
            coverage=(cash,),
            balances=(
                AccountBalance(
                    resource=cash,
                    currency="USD",
                    total="100",
                    available="100",
                    locked="0",
                    observed_at_utc=observed_at,
                ),
            ),
            positions=(),
            valuation=AccountValuation(
                currency="USD",
                available_cash="100",
                equity="100",
                observed_at_utc=observed_at,
            ),
            started_at_utc=observed_at,
            completed_at_utc=observed_at,
            consistency="provider_atomic",
            balances_complete=True,
            positions_complete=True,
        )

    def close(self) -> bool:
        self.calls.append(("close", threading.get_ident()))
        self.close_calls += 1
        self._generation = None
        return True


@pytest.mark.integration
def test_owner_http_start_stop_controls_only_granted_account_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the existing HTTP route, SDK operator, CURVE Host and account worker."""

    monkeypatch.setattr(live_manager_module, "get_existing_live_trading_manager", lambda: None)

    rpc_bind = _free_rpc_endpoint()
    config = parse_service_config(_account_service_config(rpc_bind))
    server_public, server_secret = zmq.curve_keypair()
    client_public, _client_secret = zmq.curve_keypair()
    account_key = AccountKey("synthetic", "loopback", "paper", "afi08-account-key")
    account_scope = GatewayServiceAccountScope(
        account_ref=_ACCOUNT_REF,
        execution_domain_ref=_DOMAIN_REF,
        journal_account_scope="afi08-journal-account",
        account_read_strategy_scope="afi08-account-view",
    )
    app_principal = GatewayPrincipal(
        principal_id=_CLIENT_PRINCIPAL,
        account_scopes=frozenset({account_scope.journal_account_scope}),
        strategy_scopes=frozenset({"afi08-account-view"}),
        allowed_kinds=frozenset({GatewayCommandKind.READ}),
    )
    app_identity = WireIdentity(WireRole.APPLICATION_CLIENT, _CLIENT_PRINCIPAL, _CLIENT_APPLICATION)
    account_read_scope = WireScope(_DOMAIN_REF, account_ref=_ACCOUNT_REF)
    authority = TrustedServiceAuthority(
        identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID),
        scope=WireScope(_DOMAIN_REF),
        scope_ref=_SCOPE_REF,
        scope_version="afi08-local-gateway-scope-v1",
        security_ref=_SECURITY_REF,
        security_version="afi08-local-gateway-curve-v1",
        registration_policy_ref=config.registration_policy_ref,
        registration_policy_version="afi08-local-gateway-policy-v1",
        service_requirements_ref=config.service_requirements_ref,
        service_requirements_version="afi08-local-gateway-requirements-v1",
        curve_public_key=server_public,
        curve_secret_key=server_secret,
        principals={client_public: _CLIENT_PRINCIPAL},
        grants={
            _CLIENT_PRINCIPAL: (
                PrincipalGrant(
                    app_identity,
                    (
                        ResourceGrant(
                            _INSTANCE_ID,
                            "service.account_read",
                            _SCOPE_REF,
                            account_read_scope,
                            frozenset({"account.head", "account.snapshot"}),
                        ),
                    ),
                ),
            )
        },
    )
    provider_instances: list[_SyntheticAccountProvider] = []
    deployment_instances: list[GatewayOperatorDeployment] = []
    deployment_factory_threads: list[int] = []

    def resolve_credential(credential_ref: str) -> object:
        assert credential_ref == _CREDENTIAL_REF
        return "afi08-local-synthetic-credential"

    def provider_factory(session_ref: str, credential: object) -> _SyntheticAccountProvider:
        assert session_ref == _SESSION_REF
        assert credential == "afi08-local-synthetic-credential"
        provider = _SyntheticAccountProvider(account_key)
        provider_instances.append(provider)
        return provider

    session_owner = GatewaySessionOwner(
        {_SESSION_REF: _CREDENTIAL_REF},
        resolve_credential=resolve_credential,
        provider_factory=provider_factory,
    )
    guard_directory = tmp_path / "afi08-account-guard"
    guard_directory.mkdir()

    def deployment_factory() -> GatewayOperatorDeployment:
        deployment_factory_threads.append(threading.get_ident())
        # The local guard captures its owner thread when constructed. Build it
        # alongside the deployment factory on GatewayOperatorApplication's
        # actual owner thread, rather than borrowing a test-thread guard.
        journal = GatewayEventJournal(tmp_path / "afi08-account-journal.sqlite3")
        account_binding = GatewayAccountSessionBinding(
            account_session_ref=_SESSION_REF,
            journal=journal,
            account_key=account_key,
            account_scope=account_scope,
            state_scope="afi08-account-view",
            guard=LocalAccountSessionGuard(
                guard_directory,
                account_key.account_key_id,
                owner_ref="afi08-local-owner-control-test",
            ),
            required_coverage=(AccountResourceKey("spot", "cash"),),
            principals={_CLIENT_PRINCIPAL: app_principal},
            refresh_interval_seconds=3_600,
            max_staleness_seconds=7_200,
            request_timeout_seconds=2.0,
        )
        deployment = GatewayOperatorDeployment(
            config,
            authority,
            tmp_path / "afi08-account-service-host.sqlite3",
            resource_provider=lambda *_args: pytest.fail(
                "the configured Gateway account profile must use its SDK owner composition"
            ),
            session_owner=session_owner,
            account_session=account_binding,
        )
        deployment_instances.append(deployment)
        return deployment

    def forbidden_foreign_deployment() -> GatewayOperatorDeployment:
        pytest.fail("HTTP authorization must precede foreign account Host construction")

    profile_registry = GatewayOperatorProfileRegistry(
        (
            GatewayOperatorProfile(
                _PROFILE_REF,
                "account_session_worker",
                deployment_factory,
            ),
            GatewayOperatorProfile(
                _FOREIGN_PROFILE_REF,
                "account_session_worker",
                forbidden_foreign_deployment,
            ),
        )
    )
    operator_deployment = json.dumps(
        {
            "schema_version": 1,
            "operators": [
                {
                    "profile_ref": _PROFILE_REF,
                    "account_ref": _ACCOUNT_REF,
                    "authorized_subjects": [_OWNER],
                    "operations": ["status", "start", "stop"],
                    "auto_start": False,
                    "legacy_gateway_keys": ["afi08:account:local-1"],
                },
                {
                    "profile_ref": _FOREIGN_PROFILE_REF,
                    "account_ref": _FOREIGN_ACCOUNT_REF,
                    "authorized_subjects": [_FOREIGN_OWNER],
                    "operations": ["status", "start", "stop"],
                    "auto_start": False,
                    "legacy_gateway_keys": ["afi08:account:foreign-2"],
                },
            ],
        }
    )
    control = ServiceGatewayOperatorControl.from_value(
        operator_deployment,
        profile_registry=profile_registry,
    )
    assert control is not None

    app = FastAPI()
    app.state.service_gateway_operator_control = control
    app.include_router(operator_router, prefix="/api/v1")
    current_subject = [_OWNER]
    app.dependency_overrides[require_persisted_owner_scope] = lambda: PersistedOwnerScope(
        current_subject[0], "HUMAN"
    )

    async def exercise_http() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            before = await client.get(f"/api/v1/service-gateway/operators/{_PROFILE_REF}")
            assert before.status_code == 200, before.text
            assert before.json()["state"] == "new"
            assert before.json()["ready"] is False
            assert deployment_instances == []

            current_subject[0] = _FOREIGN_OWNER
            foreign_owner = await client.post(
                f"/api/v1/service-gateway/operators/{_PROFILE_REF}/start"
            )
            assert foreign_owner.status_code == 403
            assert foreign_owner.json()["detail"]["code"] == "OWNER_NOT_AUTHORIZED"
            assert deployment_instances == []

            current_subject[0] = _OWNER
            ungranted_account = await client.post(
                f"/api/v1/service-gateway/operators/{_FOREIGN_PROFILE_REF}/start"
            )
            assert ungranted_account.status_code == 403
            assert ungranted_account.json()["detail"]["code"] == "OWNER_NOT_AUTHORIZED"
            assert deployment_instances == []

            started = await client.post(f"/api/v1/service-gateway/operators/{_PROFILE_REF}/start")
            assert started.status_code == 200, started.text
            assert started.json()["state"] == "running"
            assert started.json()["ready"] is True
            assert started.json()["operation"] == {
                "name": "start",
                "state": "succeeded",
                "error_code": None,
            }
            assert started.json()["account_session"]["state"] == "ready"
            assert started.json()["account_session"]["ready"] is True

            status = await client.get(f"/api/v1/service-gateway/operators/{_PROFILE_REF}")
            assert status.status_code == 200, status.text
            assert status.json()["state"] == "running"
            assert status.json()["ready"] is True

            stopped = await client.post(f"/api/v1/service-gateway/operators/{_PROFILE_REF}/stop")
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()["state"] == "closed"
            assert stopped.json()["ready"] is False
            assert stopped.json()["operation"] == {
                "name": "stop",
                "state": "succeeded",
                "error_code": None,
            }
            assert stopped.json()["cleanup"] == {
                "unclaimed_provider_count": 0,
                "last_cleanup_code": None,
            }

            final_status = await client.get(f"/api/v1/service-gateway/operators/{_PROFILE_REF}")
            assert final_status.status_code == 200, final_status.text
            assert final_status.json()["state"] == "closed"
            assert final_status.json()["ready"] is False
            assert final_status.json()["account_session"]["ready"] is False

    try:
        asyncio.run(exercise_http())
        assert len(deployment_instances) == 1
        assert len(provider_instances) == 1
        deployment = deployment_instances[0]
        application = control._applications[_PROFILE_REF]
        assert deployment_factory_threads == [deployment._owner_thread_id]
        assert application._thread is not None
        assert application._thread.ident == deployment._owner_thread_id
        assert not application._thread.is_alive()
        assert deployment.state == "closed"
        assert session_owner.claimed_session_count == 1
        assert session_owner.uncertain_provider_count == 0
        assert provider_instances[0].close_calls == 1
        assert {thread_id for _operation, thread_id in provider_instances[0].calls} == {
            deployment._owner_thread_id
        }
        assert [operation for operation, _thread_id in provider_instances[0].calls] == [
            "connect",
            "read_account",
            "close",
        ]
    finally:
        control.close()

    assert control.closed is True
    assert not live_manager_module.get_existing_live_trading_manager()
