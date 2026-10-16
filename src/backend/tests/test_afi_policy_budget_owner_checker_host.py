"""Authenticated maker/checker HTTP control plane over the Risk policy Host."""

from __future__ import annotations

import json
import socket
import threading
import traceback
import uuid
from pathlib import Path
from typing import Any

import pytest
import zmq
from pydantic import SecretStr
from sqlalchemy import insert, update

from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_risk.service_component import ConfirmedPolicyStore, PolicyCatalogStore
from app.db.database import async_session_maker
from app.models.permission import Role, user_roles
from app.models.user import User
from app.schemas.portfolio_composition import (
    PortfolioCompositionCreate,
    PortfolioCompositionMember,
)
from app.services.portfolio_composition import PortfolioCompositionService
from app.services.service_read.client import (
    RISK_POLICY_BUDGET_CHECKER_OPERATIONS,
    RISK_POLICY_BUDGET_MAKER_OPERATIONS,
)

import app.main as main_module


_DOMAIN = "afi-risk-budget-owner-checker"
_PORTFOLIO = "afi-budget-owner-checker-v1"
_POOL = "afi-budget-owner-checker-pool-v1"
_GENERATION = "afi-budget-owner-checker-generation-v1"
_ACCOUNTS = ("afi-budget-checker-account-a", "afi-budget-checker-account-b")
_SERVICE_ID = "afi-budget-checker-risk-owner"
_SERVICE_PRINCIPAL = "afi-budget-checker-risk-owner-principal"
_INSTANCE = "afi-budget-checker-policy-catalog-instance"
_SERVICE_SCOPE_REF = "afi-budget-checker-risk-owner-scope-v1"
_SERVICE_TRANSPORT_REF = "afi-budget-checker-risk-listener-v1"
_SERVICE_SECURITY_REF = "afi-budget-checker-risk-server-curve-v1"
_APP_TRANSPORT_REF = "afi-budget-checker-application-connect-v1"
_APP_SECURITY_REF = "afi-budget-checker-application-curve-v1"
_MAKER_PRINCIPAL = "afi-budget-checker-maker-principal-v1"
_MAKER_ACTOR = "afi-budget-checker-maker-actor-v1"
_CHECKER_PRINCIPAL = "afi-budget-checker-checker-principal-v1"
_CHECKER_ACTOR = "afi-budget-checker-checker-actor-v1"
_MANAGEMENT_SCOPE_REF = "afi-budget-checker-management-scope-v1"
_MEMBER_SCOPE_REFS = {
    _ACCOUNTS[0]: "afi-budget-checker-member-a-scope-v1",
    _ACCOUNTS[1]: "afi-budget-checker-member-b-scope-v1",
}


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _service_config(endpoint: str) -> Any:
    return parse_service_config(
        {
            "service_config_schema_version": 1,
            "process_role": "service",
            "service_id": _SERVICE_ID,
            "scope_ref": _SERVICE_SCOPE_REF,
            "transport_ref": _SERVICE_TRANSPORT_REF,
            "registration_policy_ref": "afi-budget-checker-registration-v1",
            "service_requirements_ref": "afi-budget-checker-requirements-v1",
            "components": {
                "risk": {
                    "config_schema_version": 2,
                    "settings": {
                        "instance_id": _INSTANCE,
                        "bind_ports": ["service.risk_policy"],
                        "options": {"role": "policy_catalog"},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    _SERVICE_TRANSPORT_REF: {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_bind": endpoint},
                        "security_profile_ref": _SERVICE_SECURITY_REF,
                        "options": {
                            "high_water_mark": 32,
                            "max_message_bytes": 65_536,
                        },
                    }
                },
            },
        }
    )


def _service_authority(keys: dict[str, bytes]) -> TrustedServiceAuthority:
    scopes: dict[str, WireScope] = {
        _MANAGEMENT_SCOPE_REF: WireScope(
            _DOMAIN,
            account_refs=tuple(sorted(_ACCOUNTS)),
            portfolio_ref=_PORTFOLIO,
        )
    }
    scopes.update(
        {
            scope_ref: WireScope(
                _DOMAIN,
                account_ref=account_ref,
                portfolio_ref=_PORTFOLIO,
            )
            for account_ref, scope_ref in _MEMBER_SCOPE_REFS.items()
        }
    )
    actors = (
        (
            _MAKER_PRINCIPAL,
            _MAKER_ACTOR,
            keys["maker_public"],
            RISK_POLICY_BUDGET_MAKER_OPERATIONS,
        ),
        (
            _CHECKER_PRINCIPAL,
            _CHECKER_ACTOR,
            keys["checker_public"],
            RISK_POLICY_BUDGET_CHECKER_OPERATIONS,
        ),
    )
    principals: dict[bytes, str] = {}
    grants: dict[str, tuple[PrincipalGrant, ...]] = {}
    for principal_ref, actor_ref, public_key, operations in actors:
        identity = WireIdentity(WireRole.APPLICATION_CLIENT, principal_ref, actor_ref)
        resources = tuple(
            ResourceGrant(
                _INSTANCE,
                "service.risk_policy",
                scope_ref,
                scope,
                operations,
            )
            for scope_ref, scope in scopes.items()
        )
        principals[public_key] = principal_ref
        grants[principal_ref] = (PrincipalGrant(identity, resources),)

    return TrustedServiceAuthority(
        identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID),
        scope=WireScope(_DOMAIN),
        scope_ref=_SERVICE_SCOPE_REF,
        scope_version="afi-budget-checker-service-scope-v1",
        security_ref=_SERVICE_SECURITY_REF,
        security_version="afi-budget-checker-server-curve-v1",
        registration_policy_ref="afi-budget-checker-registration-v1",
        registration_policy_version="afi-budget-checker-registration-policy-v1",
        service_requirements_ref="afi-budget-checker-requirements-v1",
        service_requirements_version="afi-budget-checker-requirements-policy-v1",
        curve_public_key=keys["server_public"],
        curve_secret_key=keys["server_secret"],
        principals=principals,
        grants=grants,
    )


def _application_profile(
    *,
    subject: str,
    owner_subject: str,
    actor_role: str,
    endpoint: str,
    keys: dict[str, bytes],
) -> dict[str, object]:
    if actor_role == "maker":
        principal_ref, actor_ref = _MAKER_PRINCIPAL, _MAKER_ACTOR
    else:
        principal_ref, actor_ref = _CHECKER_PRINCIPAL, _CHECKER_ACTOR
    bindings: list[dict[str, object]] = [
        {
            "mount": "application.risk_policy",
            "service_id": _SERVICE_ID,
            "instance_id": _INSTANCE,
            "portfolio_ref": _PORTFOLIO,
            "scope_ref": _MANAGEMENT_SCOPE_REF,
            "transport_ref": _APP_TRANSPORT_REF,
        }
    ]
    for account_ref, scope_ref in _MEMBER_SCOPE_REFS.items():
        bindings.append(
            {
                "mount": "application.risk_policy",
                "service_id": _SERVICE_ID,
                "instance_id": _INSTANCE,
                "account_ref": account_ref,
                "scope_ref": scope_ref,
                "transport_ref": _APP_TRANSPORT_REF,
            }
        )
    risk_binding = {
        "mount": "application.risk_policy",
        "pool_ref": _POOL,
        "management_scope_ref": _MANAGEMENT_SCOPE_REF,
        "member_scope_refs": _MEMBER_SCOPE_REFS,
        "owner_subject": owner_subject,
        "actor_role": actor_role,
        "maker_principal_ref": _MAKER_PRINCIPAL,
        "checker_principal_ref": _CHECKER_PRINCIPAL,
    }
    return {
        "subject": subject,
        "identity": {
            "principal_ref": principal_ref,
            "actor_ref": actor_ref,
            "delegate_ref": None,
        },
        "client_config": {
            "client_config_schema_version": 1,
            "process_role": "application_client",
            "registration": {"application_ref": actor_ref},
            "clients": {
                "risk": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": bindings,
                        "options": {"request_timeout_ms": 3_000},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    _APP_TRANSPORT_REF: {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_connect": endpoint},
                        "security_profile_ref": _APP_SECURITY_REF,
                        "options": {
                            "request_timeout_ms": 3_000,
                            "high_water_mark": 16,
                            "max_message_bytes": 65_536,
                        },
                    }
                },
            },
        },
        "scope_claims": {
            _MANAGEMENT_SCOPE_REF: {
                "execution_domain_ref": _DOMAIN,
                "account_refs": list(sorted(_ACCOUNTS)),
                "portfolio_ref": _PORTFOLIO,
            },
            **{
                scope_ref: {
                    "execution_domain_ref": _DOMAIN,
                    "account_ref": account_ref,
                    "portfolio_ref": _PORTFOLIO,
                }
                for account_ref, scope_ref in _MEMBER_SCOPE_REFS.items()
            },
        },
        "peer_identities": {
            _SERVICE_ID: {"principal_ref": _SERVICE_PRINCIPAL, "actor_ref": _SERVICE_ID}
        },
        "curve_keys": {
            _APP_SECURITY_REF: {
                "server_key": keys["server_public"].decode("ascii"),
                "public_key": keys[f"{actor_role}_public"].decode("ascii"),
                "secret_key": keys[f"{actor_role}_secret"].decode("ascii"),
            }
        },
        "grants": {
            "account_refs": [],
            "order_scope_refs": [],
            "monitor_scope_refs": [],
            "risk_policy_budget_refs": [_PORTFOLIO],
        },
        "account_bindings": {},
        "order_bindings": {},
        "monitor_bindings": {},
        "risk_policy_budget_bindings": {_PORTFOLIO: risk_binding},
        "worker": {"max_queue_size": 16, "maintenance_interval_seconds": 0.05},
    }


class _CatalogHostOwner:
    """Serve and close the local Risk Host on its dedicated owner thread."""

    def __init__(self, config: Any, authority: TrustedServiceAuthority, registry_path: Path, provider: Any):
        self.config = config
        self.authority = authority
        self.registry_path = registry_path
        self.provider = provider
        self.ready = threading.Event()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="afi-policy-budget-risk-host", daemon=False)
        self.host: ServiceHost | None = None
        self.error: str | None = None
        self.state: str | None = None
        self.summary: dict[str, object] | None = None

    def start(self) -> None:
        self.thread.start()
        assert self.ready.wait(timeout=15), "Risk Host startup timed out"
        assert self.error is None and self.state == "started", {
            "state": self.state,
            "error": self.error,
            "summary": self.summary,
        }

    def close(self, *, require_success: bool = True) -> None:
        self.stop.set()
        self.thread.join(timeout=15)
        assert not self.thread.is_alive(), "Risk Host owner thread remained alive"
        if require_success:
            assert self.error is None, self.error
            assert self.state == "closed", self.summary

    def _run(self) -> None:
        try:
            host = ServiceHost(
                self.config,
                self.authority,
                str(self.registry_path),
                self.provider,
            )
            self.host = host
            host.start()
            self.state = host.state
            self.ready.set()
            while not self.stop.is_set():
                host.serve_once(timeout_ms=20)
            host.close()
            self.state = host.state
            self.summary = host.summary
        except BaseException:
            self.error = traceback.format_exc()
            if self.host is not None:
                self.state = self.host.state
                try:
                    self.summary = self.host.summary
                except BaseException:
                    self.summary = {"summary_error": "unavailable"}
        finally:
            if self.host is not None and self.host.state not in {
                "closed",
                "failed",
                "close_failed",
            }:
                try:
                    self.host.close()
                except BaseException:
                    if self.error is None:
                        self.error = traceback.format_exc()
            self.ready.set()


async def _register_policy_actor(
    client: Any,
    *,
    label: str,
    policy_admin: bool,
    service_principal: bool = False,
) -> tuple[str, dict[str, str]]:
    username = f"afi_budget_{label}_{uuid.uuid4().hex[:10]}"
    password = "Test12345678"
    registration = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@test.com", "password": password},
    )
    assert registration.status_code == 200, registration.text
    subject = str(registration.json()["id"])
    async with async_session_maker() as db:
        await db.execute(insert(user_roles).values(user_id=subject, role=Role.USER.value))
        if policy_admin:
            await db.execute(
                insert(user_roles).values(
                    user_id=subject, role=Role.TRADE_POLICY_ADMIN.value
                )
            )
        if service_principal:
            await db.execute(
                update(User).where(User.id == subject).values(principal_kind="SERVICE")
            )
        await db.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    return subject, {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_authenticated_budget_maker_checker_permissions_over_http_and_risk_host(
    tmp_path: Path,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maker_subject, maker_headers = await _register_policy_actor(
        client, label="maker", policy_admin=True
    )
    checker_subject, checker_headers = await _register_policy_actor(
        client, label="checker", policy_admin=True
    )
    ordinary_subject, ordinary_headers = await _register_policy_actor(
        client, label="ordinary", policy_admin=False
    )
    _service_subject, service_headers = await _register_policy_actor(
        client, label="service", policy_admin=True, service_principal=True
    )
    assert len({maker_subject, checker_subject, ordinary_subject}) == 3
    assert "policy.budget.approve" not in RISK_POLICY_BUDGET_MAKER_OPERATIONS
    assert "policy.budget.publish_member" not in RISK_POLICY_BUDGET_CHECKER_OPERATIONS

    async with async_session_maker() as db:
        membership = await PortfolioCompositionService(db).create_version(
            maker_subject,
            PortfolioCompositionCreate(
                portfolio_ref=_PORTFOLIO,
                source_type="live",
                base_currency="USD",
                members=[
                    PortfolioCompositionMember(kind="account", ref=account_ref)
                    for account_ref in _ACCOUNTS
                ],
            ),
        )

    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    maker_public, maker_secret = zmq.curve_keypair()
    checker_public, checker_secret = zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "maker_public": maker_public,
        "maker_secret": maker_secret,
        "checker_public": checker_public,
        "checker_secret": checker_secret,
    }
    maker_profile = _application_profile(
        subject=maker_subject,
        owner_subject=maker_subject,
        actor_role="maker",
        endpoint=endpoint,
        keys=keys,
    )
    checker_profile = _application_profile(
        subject=checker_subject,
        owner_subject=maker_subject,
        actor_role="checker",
        endpoint=endpoint,
        keys=keys,
    )

    catalog_path = tmp_path / "afi-policy-budget-control-catalog.sqlite3"
    confirmation_path = tmp_path / "afi-policy-budget-control-confirmed.sqlite3"
    catalog = PolicyCatalogStore(
        str(catalog_path), trusted_approver_principals=(_CHECKER_PRINCIPAL,)
    )
    confirmations = ConfirmedPolicyStore(str(confirmation_path))
    catalog.configure_budget_pool(
        _POOL,
        capacity_amount="100",
        currency="USD",
        metric="max_increase_notional",
        scale=2,
        portfolio_ref=_PORTFOLIO,
        membership_version=membership.membership_version,
        membership_sha256=membership.membership_sha256,
        account_refs=tuple(sorted(_ACCOUNTS)),
    )

    def provide_policy_catalog(component: str, instance_id: str, options: Any, _scope: Any):
        assert component == "risk" and instance_id == _INSTANCE, (component, instance_id)
        assert options.get("role") == "policy_catalog", options
        return ComponentResources.borrowed(
            {"catalog": catalog, "confirmed_policy_store": confirmations},
            ready=lambda: True,
        )

    host_owner = _CatalogHostOwner(
        _service_config(endpoint),
        _service_authority(keys),
        tmp_path / "afi-policy-budget-control-registry.sqlite3",
        provide_policy_catalog,
    )
    application = main_module.app
    prior_deployment = getattr(application.state, "service_read_deployment", None)
    assert prior_deployment is None or prior_deployment.closed, prior_deployment
    deployment = None
    host_started = False
    host_closed = False
    stores_closed = False
    monkeypatch.setattr(main_module.settings, "DB_AUTO_CREATE_SCHEMA", True)
    monkeypatch.setattr(main_module.settings, "RAG_VECTOR_ENABLED", False)
    monkeypatch.setattr(
        main_module.settings,
        "SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON",
        SecretStr(""),
    )
    monkeypatch.setattr(
        main_module.settings,
        "SERVICE_READ_DEPLOYMENT_JSON",
        SecretStr(
            json.dumps(
                {"schema_version": 1, "subjects": [maker_profile, checker_profile]},
                separators=(",", ":"),
            )
        ),
    )
    url = f"/api/v1/risk-policy-budgets/{_PORTFOLIO}/generations/{_GENERATION}"
    plan = {
        "membership_version": membership.membership_version,
        "membership_sha256": membership.membership_sha256,
        "currency": "USD",
        "total_amount": "60",
        "unallocated_amount": "10",
        "allocations": [
            {
                "account_ref": account_ref,
                "amount": "25",
                "currency": "USD",
                "metric": "max_increase_notional",
                "max_increase_count": 2,
            }
            for account_ref in _ACCOUNTS
        ],
    }
    try:
        host_owner.start()
        host_started = True
        async with main_module.lifespan(application):
            deployment = application.state.service_read_deployment
            assert deployment is not None and not deployment.closed

            ordinary = await client.get(url, headers=ordinary_headers)
            assert ordinary.status_code == 403, ordinary.text
            assert ordinary.json()["message"] == "Insufficient permissions"

            service = await client.get(url, headers=service_headers)
            assert service.status_code == 403, service.text
            assert service.json()["details"]["code"] == "PERSISTED_OWNER_SCOPE_UNAVAILABLE"

            drafts = await client.post(f"{url}/drafts", json=plan, headers=maker_headers)
            assert drafts.status_code == 200, drafts.text
            draft_payload = drafts.json()
            assert draft_payload["state"] == "drafts_ready", draft_payload
            assert draft_payload["consumer_effective"] is False, draft_payload
            assert {row["account_ref"] for row in draft_payload["members"]} == set(_ACCOUNTS)

            proposed = await client.post(f"{url}/propose", json=plan, headers=maker_headers)
            assert proposed.status_code == 200, proposed.text
            assert proposed.json()["state"] == "proposed", proposed.json()
            assert proposed.json()["consumer_effective"] is False

            maker_self_approval = await client.post(url + "/approve", json={}, headers=maker_headers)
            assert maker_self_approval.status_code == 403, maker_self_approval.text
            assert maker_self_approval.json()["details"]["code"] == (
                "RISK_POLICY_BUDGET_ACTOR_NOT_AUTHORIZED"
            )

            checker_draft = await client.post(f"{url}/drafts", json=plan, headers=checker_headers)
            assert checker_draft.status_code == 403, checker_draft.text
            checker_publish = await client.post(
                f"{url}/members/{_ACCOUNTS[0]}/publish",
                json={},
                headers=checker_headers,
            )
            assert checker_publish.status_code == 403, checker_publish.text
            assert checker_publish.json()["details"]["code"] == (
                "RISK_POLICY_BUDGET_ACTOR_NOT_AUTHORIZED"
            )

            approved = await client.post(url + "/approve", json={}, headers=checker_headers)
            assert approved.status_code == 200, approved.text
            assert approved.json()["state"] == "approved", approved.json()
            assert approved.json()["consumer_effective"] is False

            maker_read = await client.get(url, headers=maker_headers)
            assert maker_read.status_code == 200, maker_read.text
            assert maker_read.json()["approved_by"] == _CHECKER_PRINCIPAL
            assert maker_read.json()["consumer_effective"] is False

            for account_ref in _ACCOUNTS:
                published = await client.post(
                    f"{url}/members/{account_ref}/publish",
                    json={},
                    headers=maker_headers,
                )
                assert published.status_code == 200, published.text
                assert published.json()["consumer_effective"] is False

            first_confirmation = await client.post(
                f"{url}/members/{_ACCOUNTS[0]}/confirm",
                json={},
                headers=maker_headers,
            )
            assert first_confirmation.status_code == 200, first_confirmation.text
            assert first_confirmation.json()["authority_ready"] is False
            assert first_confirmation.json()["consumer_effective"] is False

            checker_owner_confirm = await client.post(
                f"{url}/members/{_ACCOUNTS[1]}/confirm",
                json={},
                headers=checker_headers,
            )
            assert checker_owner_confirm.status_code == 403, checker_owner_confirm.text

            second_confirmation = await client.post(
                f"{url}/members/{_ACCOUNTS[1]}/confirm",
                json={},
                headers=maker_headers,
            )
            assert second_confirmation.status_code == 200, second_confirmation.text
            ready_payload = second_confirmation.json()
            assert ready_payload["state"] == "authority_ready", ready_payload
            assert ready_payload["authority_ready"] is True
            assert ready_payload["consumer_effective"] is False
            assert ready_payload["consumer_status"] == "awaiting_account_gate_binding"

            checker_read = await client.get(url, headers=checker_headers)
            assert checker_read.status_code == 200, checker_read.text
            assert checker_read.json()["state"] == "authority_ready"
            assert checker_read.json()["consumer_effective"] is False

        assert deployment is not None and deployment.closed
        assert deployment.close_failures == ()
        assert application.state.service_read_deployment is None
        host_owner.close()
        host_closed = True
        assert host_owner.summary is not None
        assert host_owner.summary.get("state") == "closed", host_owner.summary

        catalog.close()
        confirmations.close()
        stores_closed = True
        from bt_api_risk.budget_admission import PolicyCatalogBudgetAdmissionResolver

        reopened_catalog = PolicyCatalogStore(
            str(catalog_path), trusted_approver_principals=(_CHECKER_PRINCIPAL,)
        )
        reopened_confirmations = ConfirmedPolicyStore(str(confirmation_path))
        try:
            resolver = PolicyCatalogBudgetAdmissionResolver(
                reopened_catalog, reopened_confirmations
            )
            resolved_rows = [
                resolver.resolve(
                    _POOL,
                    account_ref,
                    scope=WireScope(
                        _DOMAIN,
                        account_ref=account_ref,
                        portfolio_ref=_PORTFOLIO,
                    ),
                )
                for account_ref in _ACCOUNTS
            ]
            assert {row.account_ref for row in resolved_rows} == set(_ACCOUNTS)
            assert {row.generation_ref for row in resolved_rows} == {_GENERATION}
            assert {str(row.risk_policy.max_increase_notional) for row in resolved_rows} == {"25"}
            assert {row.risk_policy.notional_unit for row in resolved_rows} == {"USD"}
        finally:
            reopened_catalog.close()
            reopened_confirmations.close()
    finally:
        if deployment is not None and not deployment.closed:
            await deployment.aclose()
        if not host_closed and host_owner.thread.ident is not None:
            host_owner.close(require_success=False)
        if not stores_closed:
            catalog.close()
            confirmations.close()

