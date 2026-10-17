"""Ordinary per-account policy partial activation through authenticated HTTP and Risk Hosts."""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

import pytest
import zmq
from bt_api_base.account_protocol import AccountKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_risk import (
    AccountScope,
    DurableRiskAdmissionAdapter,
    DurableRiskGate,
    InstrumentRiskAdmissionMapper,
    InstrumentRiskMetadata,
    InstrumentRiskRegistry,
    IntentAction,
    RiskIntent,
)
from bt_api_risk.policy_admission import (
    PolicyCatalogAccountAdmissionResolver,
    PolicyAdmissionResolutionError,
)
from bt_api_risk.service_component import ConfirmedPolicyStore, PolicyCatalogStore
from bt_api_py.bt_api import BtApi
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_py.service_risk_order_entry import RiskBtApiProviderContract, RiskOrderTarget
from bt_api_py.service_risk_order_journal import RiskOrderJournal
from pydantic import SecretStr

from app.api.service_read import configure_service_read
from app.services.service_read.client import (
    RISK_ACCOUNT_POLICY_CHECKER_OPERATIONS,
    RISK_ACCOUNT_POLICY_MAKER_OPERATIONS,
)
import app.main as main_module
from tests import test_afi_budget_manual_admission_host as manual
from tests import test_afi_policy_budget_owner_checker_host as policy_control


_DOMAIN = policy_control._DOMAIN
_ACCOUNT_A = "afi-ordinary-policy-account-a"
_ACCOUNT_B = "afi-ordinary-policy-account-b"
_ACCOUNTS = (_ACCOUNT_A, _ACCOUNT_B)
_MANUAL_BOOKS = {
    _ACCOUNT_A: "afi-ordinary-policy-manual-a",
    _ACCOUNT_B: "afi-ordinary-policy-manual-b",
}
_ACCOUNT_SCOPE_REFS = {
    _ACCOUNT_A: "afi-ordinary-policy-account-a-manual-scope-v1",
    _ACCOUNT_B: "afi-ordinary-policy-account-b-manual-scope-v1",
}
_POLICY_REFS = {
    _ACCOUNT_A: {
        "old": "afi-ordinary-policy-a-v1",
        "new": "afi-ordinary-policy-a-v2",
    },
    _ACCOUNT_B: {
        "old": "afi-ordinary-policy-b-v1",
        "new": "afi-ordinary-policy-b-v2",
    },
}
_ORDER_SERVICE_IDS = {
    _ACCOUNT_A: "afi-ordinary-account-a-risk-owner",
    _ACCOUNT_B: "afi-ordinary-account-b-risk-owner",
}
_ORDER_INSTANCE_IDS = {
    account_ref: f"{service_id}-instance"
    for account_ref, service_id in _ORDER_SERVICE_IDS.items()
}
_ORDER_SERVICE_PRINCIPALS = {
    account_ref: f"{service_id}-principal"
    for account_ref, service_id in _ORDER_SERVICE_IDS.items()
}
_ORDER_SERVICE_SCOPE_REFS = {
    account_ref: f"{service_id}-scope-v1"
    for account_ref, service_id in _ORDER_SERVICE_IDS.items()
}
_ORDER_SERVICE_SECURITY_REFS = {
    account_ref: f"{service_id}-server-curve-v1"
    for account_ref, service_id in _ORDER_SERVICE_IDS.items()
}
_ORDER_SERVICE_TRANSPORT_REFS = {
    account_ref: f"{service_id}-listener-v1"
    for account_ref, service_id in _ORDER_SERVICE_IDS.items()
}
_ORDER_APP_TRANSPORT_REFS = {
    account_ref: f"afi-ordinary-app-connect-{account_ref[-1]}-v1"
    for account_ref in _ACCOUNTS
}
_APP_SECURITY_REF = "afi-ordinary-policy-application-curve-v1"
_SERVER_SECURITY_REF = policy_control._SERVICE_SECURITY_REF
_CATALOG_SERVICE_ID = policy_control._SERVICE_ID
_CATALOG_INSTANCE_ID = policy_control._INSTANCE
_CATALOG_SCOPE_REF = policy_control._SERVICE_SCOPE_REF
_CATALOG_APP_TRANSPORT_REF = policy_control._APP_TRANSPORT_REF
_CATALOG_APP_SECURITY_REF = policy_control._APP_SECURITY_REF
_MAKER_PRINCIPAL = policy_control._MAKER_PRINCIPAL
_MAKER_ACTOR = policy_control._MAKER_ACTOR
_CHECKER_PRINCIPAL = policy_control._CHECKER_PRINCIPAL
_CHECKER_ACTOR = policy_control._CHECKER_ACTOR
_ORDER_DOMAIN = "PAPER"
_EXCHANGE = "PAPER___SPOT"
_INSTRUMENT = "BTC-USDT"
_CURRENCY = "USD"
_STRATEGY_ID = "afi-internal-ordinary-manual-target-v1"


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _scope(account_ref: str) -> WireScope:
    return WireScope(
        _DOMAIN,
        account_ref=account_ref,
        manual_book_ref=_MANUAL_BOOKS[account_ref],
    )


def _profile_scope_claim(account_ref: str) -> dict[str, str]:
    return {
        "execution_domain_ref": _DOMAIN,
        "account_ref": account_ref,
        "manual_book_ref": _MANUAL_BOOKS[account_ref],
    }


def _transport(endpoint: str) -> dict[str, object]:
    return {
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


def _application_profile(
    *,
    subject: str,
    actor_role: str,
    owner_subject: str,
    keys: Mapping[str, bytes],
    catalog_endpoint: str,
    order_endpoints: Mapping[str, str] | None = None,
) -> dict[str, object]:
    if actor_role == "maker":
        principal_ref, actor_ref = _MAKER_PRINCIPAL, _MAKER_ACTOR
        key_prefix = "maker"
        policy_operations = RISK_ACCOUNT_POLICY_MAKER_OPERATIONS
    else:
        principal_ref, actor_ref = _CHECKER_PRINCIPAL, _CHECKER_ACTOR
        key_prefix = "checker"
        policy_operations = RISK_ACCOUNT_POLICY_CHECKER_OPERATIONS

    risk_bindings = [
        {
            "mount": "application.risk_policy",
            "service_id": _CATALOG_SERVICE_ID,
            "instance_id": _CATALOG_INSTANCE_ID,
            "account_ref": account_ref,
            "scope_ref": _ACCOUNT_SCOPE_REFS[account_ref],
            "transport_ref": _CATALOG_APP_TRANSPORT_REF,
        }
        for account_ref in _ACCOUNTS
    ]
    clients: dict[str, object] = {
        "risk": {
            "config_schema_version": 1,
            "settings": {
                "bindings": risk_bindings,
                "options": {"request_timeout_ms": 3_000},
            },
        }
    }
    peer_identities = {
        _CATALOG_SERVICE_ID: {
            "principal_ref": policy_control._SERVICE_PRINCIPAL,
            "actor_ref": _CATALOG_SERVICE_ID,
        }
    }
    transports: dict[str, object] = {
        _CATALOG_APP_TRANSPORT_REF: _transport(catalog_endpoint)
    }
    order_bindings: dict[str, object] = {}
    order_scope_refs: list[str] = []
    if order_endpoints:
        bindings: list[dict[str, object]] = []
        for account_ref, endpoint in order_endpoints.items():
            scope_ref = _ACCOUNT_SCOPE_REFS[account_ref]
            service_id = _ORDER_SERVICE_IDS[account_ref]
            transport_ref = _ORDER_APP_TRANSPORT_REFS[account_ref]
            bindings.append(
                {
                    "mount": "application.orders",
                    "service_id": service_id,
                    "instance_id": _ORDER_INSTANCE_IDS[account_ref],
                    "scope_ref": scope_ref,
                    "transport_ref": transport_ref,
                    "account_ref": account_ref,
                }
            )
            transports[transport_ref] = _transport(endpoint)
            peer_identities[service_id] = {
                "principal_ref": _ORDER_SERVICE_PRINCIPALS[account_ref],
                "actor_ref": service_id,
            }
            order_scope_refs.append(scope_ref)
            order_bindings[scope_ref] = {
                "mount": "application.orders",
                "account_ref": account_ref,
                "manual_book_ref": _MANUAL_BOOKS[account_ref],
                "instrument_metadata_versions": {
                    _INSTRUMENT: "afi-synthetic-risk-metadata-v1"
                },
            }
        clients["execution"] = {
            "config_schema_version": 1,
            "settings": {
                "bindings": bindings,
                "options": {"request_timeout_ms": 3_000},
            },
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
            "clients": clients,
            "communication": {
                "config_schema_version": 1,
                "profiles": transports,
            },
        },
        "scope_claims": {
            _ACCOUNT_SCOPE_REFS[account_ref]: _profile_scope_claim(account_ref)
            for account_ref in _ACCOUNTS
        },
        "peer_identities": peer_identities,
        "curve_keys": {
            _APP_SECURITY_REF: {
                "server_key": keys["server_public"].decode("ascii"),
                "public_key": keys[f"{key_prefix}_public"].decode("ascii"),
                "secret_key": keys[f"{key_prefix}_secret"].decode("ascii"),
            }
        },
        "grants": {
            "account_refs": [],
            "order_scope_refs": [],
            "monitor_scope_refs": [],
            "risk_account_policy_refs": list(_ACCOUNTS),
            "order_submit_scope_refs": order_scope_refs,
        },
        "account_bindings": {},
        "order_bindings": {},
        "monitor_bindings": {},
        "risk_account_policy_bindings": {
            account_ref: {
                "mount": "application.risk_policy",
                "scope_ref": _ACCOUNT_SCOPE_REFS[account_ref],
                "owner_subject": owner_subject,
                "actor_role": actor_role,
                "maker_principal_ref": _MAKER_PRINCIPAL,
                "checker_principal_ref": _CHECKER_PRINCIPAL,
            }
            for account_ref in _ACCOUNTS
        },
        "order_submit_bindings": order_bindings,
        "worker": {"max_queue_size": 16, "maintenance_interval_seconds": 0.05},
    }


def _catalog_authority(keys: Mapping[str, bytes]) -> TrustedServiceAuthority:
    scopes = {
        _ACCOUNT_SCOPE_REFS[account_ref]: _scope(account_ref)
        for account_ref in _ACCOUNTS
    }
    principals: dict[bytes, str] = {}
    grants: dict[str, tuple[PrincipalGrant, ...]] = {}
    actors = (
        (
            _MAKER_PRINCIPAL,
            _MAKER_ACTOR,
            keys["maker_public"],
            RISK_ACCOUNT_POLICY_MAKER_OPERATIONS,
        ),
        (
            _CHECKER_PRINCIPAL,
            _CHECKER_ACTOR,
            keys["checker_public"],
            RISK_ACCOUNT_POLICY_CHECKER_OPERATIONS,
        ),
    )
    for principal_ref, actor_ref, public_key, operations in actors:
        identity = WireIdentity(WireRole.APPLICATION_CLIENT, principal_ref, actor_ref)
        resources = tuple(
            ResourceGrant(
                _CATALOG_INSTANCE_ID,
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
        identity=WireIdentity(
            WireRole.SERVICE,
            policy_control._SERVICE_PRINCIPAL,
            _CATALOG_SERVICE_ID,
        ),
        scope=WireScope(_DOMAIN),
        scope_ref=_CATALOG_SCOPE_REF,
        scope_version="afi-budget-checker-service-scope-v1",
        security_ref=_SERVER_SECURITY_REF,
        security_version="afi-budget-checker-risk-server-curve-v1",
        registration_policy_ref="afi-budget-checker-registration-v1",
        registration_policy_version="afi-budget-checker-registration-policy-v1",
        service_requirements_ref="afi-budget-checker-requirements-v1",
        service_requirements_version="afi-budget-checker-requirements-policy-v1",
        curve_public_key=keys["server_public"],
        curve_secret_key=keys["server_secret"],
        principals=principals,
        grants=grants,
    )


def _order_service_config(
    *, account_ref: str, policy_ref: str, endpoint: str
) -> Any:
    service_id = _ORDER_SERVICE_IDS[account_ref]
    return parse_service_config(
        {
            "service_config_schema_version": 1,
            "process_role": "service",
            "service_id": service_id,
            "scope_ref": _ORDER_SERVICE_SCOPE_REFS[account_ref],
            "transport_ref": _ORDER_SERVICE_TRANSPORT_REFS[account_ref],
            "registration_policy_ref": f"{service_id}-registration-v1",
            "service_requirements_ref": f"{service_id}-requirements-v1",
            "components": {
                "risk": {
                    "config_schema_version": 2,
                    "settings": {
                        "instance_id": _ORDER_INSTANCE_IDS[account_ref],
                        "bind_ports": ["service.order_entry"],
                        "options": {
                            "role": "account_owner",
                            "account_policy_ref": policy_ref,
                        },
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    _ORDER_SERVICE_TRANSPORT_REFS[account_ref]: {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_bind": endpoint},
                        "security_profile_ref": _ORDER_SERVICE_SECURITY_REFS[account_ref],
                        "options": {"high_water_mark": 32, "max_message_bytes": 65_536},
                    }
                },
            },
        }
    )


def _order_service_authority(
    *, account_ref: str, scope_ref: str, keys: Mapping[str, bytes]
) -> TrustedServiceAuthority:
    service_id = _ORDER_SERVICE_IDS[account_ref]
    service_scope_ref = _ORDER_SERVICE_SCOPE_REFS[account_ref]
    application = WireIdentity(
        WireRole.APPLICATION_CLIENT,
        _MAKER_PRINCIPAL,
        _MAKER_ACTOR,
    )
    grant = ResourceGrant(
        _ORDER_INSTANCE_IDS[account_ref],
        "service.order_entry",
        scope_ref,
        _scope(account_ref),
        frozenset({"orders.submit"}),
    )
    return TrustedServiceAuthority(
        identity=WireIdentity(
            WireRole.SERVICE,
            _ORDER_SERVICE_PRINCIPALS[account_ref],
            service_id,
        ),
        scope=WireScope(_DOMAIN),
        scope_ref=service_scope_ref,
        scope_version=f"{service_id}-scope-version-v1",
        security_ref=_ORDER_SERVICE_SECURITY_REFS[account_ref],
        security_version=f"{service_id}-server-curve-version-v1",
        registration_policy_ref=f"{service_id}-registration-v1",
        registration_policy_version=f"{service_id}-registration-policy-v1",
        service_requirements_ref=f"{service_id}-requirements-v1",
        service_requirements_version=f"{service_id}-requirements-policy-v1",
        curve_public_key=keys["server_public"],
        curve_secret_key=keys["server_secret"],
        principals={keys["maker_public"]: _MAKER_PRINCIPAL},
        grants={_MAKER_PRINCIPAL: (PrincipalGrant(application, (grant,)),)},
    )


class _SyntheticProvider:
    """Synthetic provider leaf keyed to one local account; it performs no I/O."""

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self.rows: dict[str, dict[str, object]] = {}
        self.writes: list[str] = []
        self.order_queries: list[str] = []
        self.fill_queries: list[str] = []

    def make_order(
        self,
        symbol: str,
        volume: float,
        _price: float,
        order_type: str,
        *,
        client_order_id: str,
        **_kwargs: Any,
    ) -> dict[str, object]:
        row: dict[str, object] = {
            "account_id": self.account_id,
            "client_order_id": client_order_id,
            "filled": 0,
            "order_id": f"provider-{client_order_id}",
            "quantity": volume,
            "side": order_type.split("-", 1)[0],
            "status": "open",
            "symbol": symbol,
        }
        self.rows[client_order_id] = row
        self.writes.append(client_order_id)
        return {
            "account_id": self.account_id,
            "client_order_id": client_order_id,
            "complete": True,
            "schema_version": "afi.fixture.order.v1",
            "watermark": len(self.writes),
            "data": [dict(row)],
        }

    def query_order(self, _symbol: str, order_id: str, **_kwargs: Any) -> dict[str, object]:
        self.order_queries.append(order_id)
        row = self.rows.get(order_id)
        return {
            "account_id": self.account_id,
            "client_order_id": order_id,
            "complete": True,
            "schema_version": "afi.fixture.order.v1",
            "watermark": len(self.order_queries),
            "data": [] if row is None else [dict(row)],
        }

    def get_deals(
        self, _symbol: str | None, *, client_order_id: str, **_kwargs: Any
    ) -> dict[str, object]:
        self.fill_queries.append(client_order_id)
        return {
            "account_id": self.account_id,
            "client_order_id": client_order_id,
            "complete": True,
            "schema_version": "afi.fixture.fills.v1",
            "watermark": len(self.fill_queries),
            "data": [],
        }


def _account_owner(
    *,
    account_ref: str,
    policy_ref: str,
    endpoint: str,
    root: Path,
    resolver: PolicyCatalogAccountAdmissionResolver,
    keys: Mapping[str, bytes],
) -> tuple[Any, dict[str, Any], Path]:
    account_key = AccountKey(
        provider="PAPER",
        venue="synthetic-venue",
        environment="simulation",
        account_id=f"synthetic-provider-{account_ref}",
    )
    account_scope = AccountScope(
        account_key.provider,
        account_key.account_key_id,
        account_key.environment,
    )
    wire_scope = _scope(account_ref)
    scope_ref = _ACCOUNT_SCOPE_REFS[account_ref]
    risk_path = root / f"{account_ref}-risk.sqlite3"
    journal_path = root / f"{account_ref}-journal.sqlite3"
    registry_path = root / f"{account_ref}-service-registry.sqlite3"
    provider = _SyntheticProvider(account_key.account_key_id)
    resources: dict[str, Any] = {
        "account_scope": account_scope,
        "provider": provider,
    }

    def provide(component: str, _instance_id: str, _options: Any, _scope: WireScope):
        if component != "risk":
            raise AssertionError(f"unexpected component: {component}")
        try:
            try:
                # Prefer the exact durable document for a previously confirmed
                # policy. Only an unconfirmed first activation may read the
                # immutable published catalog document.
                resolved = resolver.resolve_confirmed(
                    policy_ref,
                    account_ref,
                    scope=wire_scope,
                )
            except PolicyAdmissionResolutionError as error:
                if error.code != "POLICY_NOT_CONFIRMED":
                    raise
                resolved = resolver.resolve_published(
                    policy_ref,
                    account_ref,
                    scope=wire_scope,
                )
        except PolicyAdmissionResolutionError as error:
            resources["resolution_error_code"] = error.code
            raise
        resources["resolved_policy"] = resolved
        now_ns = time.time_ns()
        instrument_metadata = InstrumentRiskMetadata(
            instrument=_INSTRUMENT,
            metadata_version="afi-synthetic-risk-metadata-v1",
            as_of_ns=now_ns - 1_000_000_000,
            expires_at_ns=now_ns + 600_000_000_000,
            tick_size=Decimal("1"),
            quantity_step=Decimal("1"),
            contract_multiplier=Decimal("1"),
            max_gross_notional=Decimal("1000"),
            taker_fee_bps=Decimal("0"),
            fixed_fee=Decimal("0"),
            max_slippage_bps=Decimal("0"),
            quantity_unit="BTC",
            valuation_unit=_CURRENCY,
        )
        instrument_registry = InstrumentRiskRegistry((instrument_metadata,))
        bt_api = BtApi(debug=False)
        bt_api.exchange_feeds[_EXCHANGE] = provider
        journal = RiskOrderJournal(
            str(journal_path), writer_id=f"afi-ordinary-{account_ref}"
        )
        resources["bt_api"] = bt_api
        resources["journal"] = journal
        try:
            gate = DurableRiskGate(
                str(risk_path),
                resolved.risk_policy,
                execution_journal_authority=journal,
            )
        except BaseException as error:
            resources["ledger_error_code"] = getattr(error, "code", type(error).__name__)
            journal.close()
            bt_api.close()
            raise
        resources["gate"] = gate
        adapter = DurableRiskAdmissionAdapter(
            gate,
            InstrumentRiskAdmissionMapper(
                account_scope,
                instrument_registry,
                clock_ns=time.time_ns,
            ),
        )
        target = RiskOrderTarget(
            account_scope=account_scope,
            strategy_id=_STRATEGY_ID,
            exchange_name=_EXCHANGE,
            provider_account_id=account_key.account_key_id,
            registry=instrument_registry,
        )
        contract = RiskBtApiProviderContract(
            exchange_name=_EXCHANGE,
            profile_id="afi-ordinary-policy-provider-contract-v1",
            order_schema="afi.fixture.order.v1",
            fill_schema="afi.fixture.fills.v1",
            client_order_id_query=True,
            complete_order_snapshot=True,
            complete_fill_history=True,
            provider_accepts_client_order_id=True,
            client_order_id_query_unique=True,
            provider_status_mapping=(
                ("open", "accepted"),
                ("filled", "completed"),
                ("cancelled", "canceled"),
                ("expired", "expired"),
                ("rejected", "rejected"),
            ),
            supported_order_types=("LIMIT",),
            supported_time_in_force=("GTC",),
            supported_position_effects=("OPEN",),
        )
        resources["target"] = target
        return ComponentResources.borrowed(
            {
                "bt_api": bt_api,
                "targets": {wire_scope: target},
                "admission": {wire_scope: adapter},
                "journal": journal,
                "gate": gate,
                "provider_contracts": {wire_scope: contract},
                "account_policy_admission_resolver": resolver,
                "account_policy_scope": wire_scope,
            },
            ready=lambda: True,
        )

    authority = _order_service_authority(
        account_ref=account_ref,
        scope_ref=scope_ref,
        keys=keys,
    )
    owner = manual._HostOwner(
        _order_service_config(
            account_ref=account_ref,
            policy_ref=policy_ref,
            endpoint=endpoint,
        ),
        authority,
        registry_path,
        provide,
        resources,
    )
    return owner, resources, risk_path


@asynccontextmanager
async def _service_read_lifespan(
    *,
    monkeypatch: pytest.MonkeyPatch,
    profiles: list[dict[str, object]],
) -> AsyncIterator[None]:
    application = main_module.app
    previous = getattr(application.state, "service_read_deployment", None)
    assert previous is None or previous.closed, previous
    deployment_json = json.dumps(
        {"schema_version": 1, "subjects": profiles},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    monkeypatch.setattr(main_module.settings, "DB_AUTO_CREATE_SCHEMA", True)
    monkeypatch.setattr(main_module.settings, "RAG_VECTOR_ENABLED", False)
    monkeypatch.setattr(
        main_module.settings,
        "SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON",
        "",
    )
    monkeypatch.setattr(
        main_module.settings,
        "SERVICE_READ_DEPLOYMENT_JSON",
        SecretStr(deployment_json),
    )
    configure_service_read(None)
    deployment = None
    try:
        async with main_module.lifespan(application):
            deployment = application.state.service_read_deployment
            assert deployment is not None and not deployment.closed
            yield
        assert deployment is not None and deployment.closed
        assert application.state.service_read_deployment is None
    finally:
        configure_service_read(None)
        if deployment is not None and not deployment.closed:
            await deployment.aclose()


def _policy_body(policy_ref: str, max_notional: str) -> dict[str, object]:
    return {
        "policy_ref": policy_ref,
        "max_increase_notional": max_notional,
        "max_increase_count": 8,
        "permit_ttl_seconds": 300.0,
        "require_strategy_allocation": False,
        "notional_unit": _CURRENCY,
    }


async def _publish_via_http(
    *,
    client: Any,
    maker_headers: dict[str, str],
    checker_headers: dict[str, str],
    account_ref: str,
    policy_ref: str,
    max_notional: str,
) -> dict[str, object]:
    base = f"/api/v1/risk-policies/accounts/{account_ref}/policies"
    draft = await client.post(base, json=_policy_body(policy_ref, max_notional), headers=maker_headers)
    assert draft.status_code == 201, draft.text
    draft_payload = draft.json()
    assert draft_payload["policy_ref"] == policy_ref and draft_payload["state"] == "draft"
    maker_approval = await client.post(
        f"{base}/{policy_ref}/approve", headers=maker_headers
    )
    assert maker_approval.status_code == 403, maker_approval.text
    checker_draft = await client.post(
        base,
        json=_policy_body(policy_ref + "-checker-forbidden", max_notional),
        headers=checker_headers,
    )
    assert checker_draft.status_code == 403, checker_draft.text
    approval = await client.post(
        f"{base}/{policy_ref}/approve", headers=checker_headers
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["state"] == "approved", approval.json()
    checker_publish = await client.post(
        f"{base}/{policy_ref}/publish", headers=checker_headers
    )
    assert checker_publish.status_code == 403, checker_publish.text
    published = await client.post(
        f"{base}/{policy_ref}/publish", headers=maker_headers
    )
    assert published.status_code == 200, published.text
    receipt = published.json()
    assert receipt["state"] == "published" and receipt["policy_ref"] == policy_ref
    assert type(receipt["policy_version"]) is str and len(receipt["policy_version"]) == 64
    return receipt


async def _read_policy(
    *, client: Any, headers: dict[str, str], account_ref: str, policy_ref: str
) -> dict[str, Any]:
    response = await client.get(
        f"/api/v1/risk-policies/accounts/{account_ref}/policies/{policy_ref}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["account_ref"] == account_ref and payload["policy_ref"] == policy_ref
    assert "consumer_effective" not in payload
    return payload


async def _submit_manual_order(
    *,
    client: Any,
    headers: dict[str, str],
    account_ref: str,
    idempotency_key: str,
    quantity: str,
    price: str,
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/service-orders/manual",
        json={
            "scope_ref": _ACCOUNT_SCOPE_REFS[account_ref],
            "instrument": _INSTRUMENT,
            "side": "BUY",
            "position_effect": "OPEN",
            "order_type": "LIMIT",
            "quantity": quantity,
            "price": price,
            "time_in_force": "GTC",
            "reduce_only": False,
        },
        headers={**headers, "Idempotency-Key": idempotency_key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _snapshot_for_confirmed_policy(
    *,
    resolver: PolicyCatalogAccountAdmissionResolver,
    policy_ref: str,
    account_ref: str,
    risk_path: Path,
) -> dict[str, object]:
    confirmed = resolver.resolve_confirmed(
        policy_ref,
        account_ref,
        scope=_scope(account_ref),
    )
    account_key = AccountKey(
        provider="PAPER",
        venue="synthetic-venue",
        environment="simulation",
        account_id=f"synthetic-provider-{account_ref}",
    )
    gate = DurableRiskGate(
        str(risk_path),
        confirmed.risk_policy,
    )
    try:
        return gate.snapshot(
            AccountScope(
                account_key.provider,
                account_key.account_key_id,
                account_key.environment,
            )
        )
    finally:
        gate.close()


@pytest.mark.asyncio
async def test_authenticated_ordinary_account_policy_partially_activates_a_and_retains_b_old_version(
    tmp_path: Path,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maker_subject, maker_headers = await policy_control._register_policy_actor(
        client, label="ordinary_maker", policy_admin=True
    )
    checker_subject, checker_headers = await policy_control._register_policy_actor(
        client, label="ordinary_checker", policy_admin=True
    )
    _ordinary_subject, ordinary_headers = await policy_control._register_policy_actor(
        client, label="ordinary_unprivileged", policy_admin=False
    )
    _service_subject, service_headers = await policy_control._register_policy_actor(
        client,
        label="ordinary_service_principal",
        policy_admin=True,
        service_principal=True,
    )
    assert maker_subject != checker_subject
    endpoint_catalog = _endpoint()
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

    catalog_path = tmp_path / "afi-ordinary-catalog.sqlite3"
    confirmation_path = tmp_path / "afi-ordinary-confirmed.sqlite3"
    catalog = PolicyCatalogStore(
        str(catalog_path),
        trusted_approver_principals=(_CHECKER_PRINCIPAL,),
    )
    confirmations = ConfirmedPolicyStore(str(confirmation_path))
    resolver = PolicyCatalogAccountAdmissionResolver(catalog, confirmations)
    def catalog_resources(component: str, _instance_id: str, _options: Any, _scope: WireScope):
        if component != "risk":
            raise AssertionError(f"unexpected component: {component}")
        return ComponentResources.borrowed(
            {"catalog": catalog, "confirmed_policy_store": confirmations},
            ready=lambda: True,
        )

    catalog_host = policy_control._CatalogHostOwner(
        policy_control._service_config(endpoint_catalog),
        _catalog_authority(keys),
        tmp_path / "afi-ordinary-catalog-service.sqlite3",
        catalog_resources,
    )
    catalog_attempted = False
    owners: list[Any] = []
    app = main_module.app
    try:
        catalog_attempted = True
        catalog_host.start()
        maker_control_profile = _application_profile(
            subject=maker_subject,
            actor_role="maker",
            owner_subject=maker_subject,
            keys=keys,
            catalog_endpoint=endpoint_catalog,
        )
        checker_profile = _application_profile(
            subject=checker_subject,
            actor_role="checker",
            owner_subject=maker_subject,
            keys=keys,
            catalog_endpoint=endpoint_catalog,
        )
        async with _service_read_lifespan(
            monkeypatch=monkeypatch,
            profiles=[maker_control_profile, checker_profile],
        ):
            for account_ref in _ACCOUNTS:
                await _publish_via_http(
                    client=client,
                    maker_headers=maker_headers,
                    checker_headers=checker_headers,
                    account_ref=account_ref,
                    policy_ref=_POLICY_REFS[account_ref]["old"],
                    max_notional="100",
                )
            ordinary_read = await client.get(
                f"/api/v1/risk-policies/accounts/{_ACCOUNT_A}/policies/{_POLICY_REFS[_ACCOUNT_A]['old']}",
                headers=ordinary_headers,
            )
            assert ordinary_read.status_code == 403, ordinary_read.text
            service_approve = await client.post(
                f"/api/v1/risk-policies/accounts/{_ACCOUNT_A}/policies/{_POLICY_REFS[_ACCOUNT_A]['old']}/approve",
                headers=service_headers,
            )
            assert service_approve.status_code == 403, service_approve.text
            before_a = await _read_policy(
                client=client,
                headers=maker_headers,
                account_ref=_ACCOUNT_A,
                policy_ref=_POLICY_REFS[_ACCOUNT_A]["old"],
            )
            assert before_a["owner_confirmed"] is False
            assert before_a["owner_document_available"] is False

        # B1 is the only first-version policy bound at this stage. A1 remains
        # published but unconfirmed so A2 can be the account's first binding.
        # B receives an open order, leaving a durable reservation in B1's ledger.
        first_endpoints = {_ACCOUNT_B: _endpoint()}
        first_owners: dict[str, Any] = {}
        first_resources: dict[str, dict[str, Any]] = {}
        risk_paths: dict[str, Path] = {}
        owner, resources, risk_path = _account_owner(
            account_ref=_ACCOUNT_B,
            policy_ref=_POLICY_REFS[_ACCOUNT_B]["old"],
            endpoint=first_endpoints[_ACCOUNT_B],
            root=tmp_path,
            resolver=resolver,
            keys=keys,
        )
        first_owners[_ACCOUNT_B] = owner
        first_resources[_ACCOUNT_B] = resources
        risk_paths[_ACCOUNT_B] = risk_path
        assert owner.start(), owner.diagnostics()
        owners.append(owner)
        old_order_profile = _application_profile(
            subject=maker_subject,
            actor_role="maker",
            owner_subject=maker_subject,
            keys=keys,
            catalog_endpoint=endpoint_catalog,
            order_endpoints=first_endpoints,
        )
        async with _service_read_lifespan(
            monkeypatch=monkeypatch,
            profiles=[old_order_profile, checker_profile],
        ):
            a1_status = await _read_policy(
                client=client,
                headers=maker_headers,
                account_ref=_ACCOUNT_A,
                policy_ref=_POLICY_REFS[_ACCOUNT_A]["old"],
            )
            assert a1_status["state"] == "published", a1_status
            assert a1_status["owner_confirmed"] is False, a1_status
            assert a1_status["owner_confirmed_version"] is None, a1_status
            assert a1_status["owner_document_available"] is False, a1_status
            b1_status = await _read_policy(
                client=client,
                headers=maker_headers,
                account_ref=_ACCOUNT_B,
                policy_ref=_POLICY_REFS[_ACCOUNT_B]["old"],
            )
            assert b1_status["owner_confirmed"] is True, b1_status
            assert b1_status["owner_confirmed_version"] == b1_status["policy_version"]
            assert b1_status["owner_document_available"] is True, b1_status
            forged_metadata = await client.post(
                "/api/v1/service-orders/manual",
                json={
                    "scope_ref": _ACCOUNT_SCOPE_REFS[_ACCOUNT_B],
                    "instrument": _INSTRUMENT,
                    "side": "BUY",
                    "position_effect": "OPEN",
                    "order_type": "LIMIT",
                    "quantity": "1",
                    "price": "10",
                    "time_in_force": "GTC",
                    "reduce_only": False,
                    "metadata_version": "client-forged-version",
                },
                headers={
                    **maker_headers,
                    "Idempotency-Key": "afi-ordinary-b-forged-metadata",
                },
            )
            assert forged_metadata.status_code == 422, forged_metadata.text
            after_forgery = first_owners[_ACCOUNT_B].observe()
            assert after_forgery["increase_count"] == 0, after_forgery
            assert after_forgery["provider_writes"] == (), after_forgery
            b1_order = await _submit_manual_order(
                client=client,
                headers=maker_headers,
                account_ref=_ACCOUNT_B,
                idempotency_key="afi-ordinary-b-v1-open-reservation",
                quantity="1",
                price="10",
            )
            assert b1_order["operation_kind"] == "manual_order", b1_order
            assert b1_order["service_code"] == "OK", b1_order
            assert b1_order["record"]["state"] == "ACKED_TRACKED", b1_order
            assert b1_order["record"]["provider_order_id"].startswith("provider-"), b1_order
            before_b_snapshot = first_owners[_ACCOUNT_B].observe()
            assert before_b_snapshot["policy_id"] == _POLICY_REFS[_ACCOUNT_B]["old"]
            assert before_b_snapshot["increase_count"] == 1, before_b_snapshot
            assert Decimal(before_b_snapshot["increase_notional"]) == Decimal("10")
            assert len(before_b_snapshot["provider_writes"]) == 1

        first_owners[_ACCOUNT_B].close()
        assert first_owners[_ACCOUNT_B].state == "closed", first_owners[_ACCOUNT_B].diagnostics()
        assert first_owners[_ACCOUNT_B].error is None, first_owners[_ACCOUNT_B].diagnostics()
        owners.remove(first_owners[_ACCOUNT_B])
        persisted_b_snapshot = _snapshot_for_confirmed_policy(
            resolver=resolver,
            policy_ref=_POLICY_REFS[_ACCOUNT_B]["old"],
            account_ref=_ACCOUNT_B,
            risk_path=risk_paths[_ACCOUNT_B],
        )
        assert persisted_b_snapshot["increase_count"] == 1, persisted_b_snapshot
        assert persisted_b_snapshot["increase_notional"] == Decimal("10")

        # Publish v2 for both accounts. A has never bound A1, so A2 may be its
        # first confirmed account policy. B2 cannot replace confirmed B1 while
        # B1's open order remains reserved; failure must preserve B1's receipt
        # and ledger.
        async with _service_read_lifespan(
            monkeypatch=monkeypatch,
            profiles=[maker_control_profile, checker_profile],
        ):
            await _publish_via_http(
                client=client,
                maker_headers=maker_headers,
                checker_headers=checker_headers,
                account_ref=_ACCOUNT_A,
                policy_ref=_POLICY_REFS[_ACCOUNT_A]["new"],
                max_notional="12",
            )
            await _publish_via_http(
                client=client,
                maker_headers=maker_headers,
                checker_headers=checker_headers,
                account_ref=_ACCOUNT_B,
                policy_ref=_POLICY_REFS[_ACCOUNT_B]["new"],
                max_notional="5",
            )

        a2_endpoint = _endpoint()
        a2_owner, a2_resources, a2_risk_path = _account_owner(
            account_ref=_ACCOUNT_A,
            policy_ref=_POLICY_REFS[_ACCOUNT_A]["new"],
            endpoint=a2_endpoint,
            root=tmp_path,
            resolver=resolver,
            keys=keys,
        )
        risk_paths[_ACCOUNT_A] = a2_risk_path
        assert risk_paths[_ACCOUNT_A] == tmp_path / f"{_ACCOUNT_A}-risk.sqlite3"
        assert a2_owner.start(), a2_owner.diagnostics()
        owners.append(a2_owner)
        a2_observation = a2_owner.observe()
        a2_resolved = a2_resources["resolved_policy"]
        assert a2_observation["policy_id"] == _POLICY_REFS[_ACCOUNT_A]["new"]
        assert a2_observation["policy_fingerprint"] == a2_resolved.risk_policy.fingerprint
        assert a2_observation["increase_count"] == 0, a2_observation
        assert a2_observation["provider_writes"] == (), a2_observation

        b2_endpoint = _endpoint()
        b2_owner, b2_resources, b2_risk_path = _account_owner(
            account_ref=_ACCOUNT_B,
            policy_ref=_POLICY_REFS[_ACCOUNT_B]["new"],
            endpoint=b2_endpoint,
            root=tmp_path,
            resolver=resolver,
            keys=keys,
        )
        assert b2_risk_path == risk_paths[_ACCOUNT_B]
        assert b2_resources["account_scope"].account_id == first_resources[_ACCOUNT_B]["account_scope"].account_id
        owners.append(b2_owner)
        assert not b2_owner.start(), b2_owner.diagnostics()
        b2_diagnostics = b2_owner.diagnostics()
        assert b2_diagnostics["state"] == "failed", b2_diagnostics
        assert b2_diagnostics["resource_error_code"] == "ACCOUNT_POLICY_NOT_EFFECTIVE", b2_diagnostics
        assert b2_diagnostics["host_cleanup"]["start_failure"] == "ACCOUNT_POLICY_NOT_EFFECTIVE", b2_diagnostics
        assert b2_diagnostics["host_cleanup"]["cleanup_failures"] == (), b2_diagnostics
        assert b2_resources["resolved_policy"].policy_ref == _POLICY_REFS[_ACCOUNT_B]["new"]
        b2_owner.close()
        assert not b2_owner._thread.is_alive(), b2_owner.diagnostics()
        owners.remove(b2_owner)

        after_b_snapshot = _snapshot_for_confirmed_policy(
            resolver=resolver,
            policy_ref=_POLICY_REFS[_ACCOUNT_B]["old"],
            account_ref=_ACCOUNT_B,
            risk_path=risk_paths[_ACCOUNT_B],
        )
        assert after_b_snapshot == persisted_b_snapshot

        b1_restart_endpoint = _endpoint()
        offline_resolver = PolicyCatalogAccountAdmissionResolver(None, confirmations)
        b1_restart_owner, b1_restart_resources, b1_restart_risk_path = _account_owner(
            account_ref=_ACCOUNT_B,
            policy_ref=_POLICY_REFS[_ACCOUNT_B]["old"],
            endpoint=b1_restart_endpoint,
            root=tmp_path,
            resolver=offline_resolver,
            keys=keys,
        )
        assert b1_restart_risk_path == risk_paths[_ACCOUNT_B]
        assert b1_restart_owner.start(), b1_restart_owner.diagnostics()
        owners.append(b1_restart_owner)
        b1_observation = b1_restart_owner.observe()
        b1_resolved = b1_restart_resources["resolved_policy"]
        assert b1_observation["policy_id"] == _POLICY_REFS[_ACCOUNT_B]["old"]
        assert b1_observation["policy_fingerprint"] == b1_resolved.risk_policy.fingerprint

        partial_endpoints = {
            _ACCOUNT_A: a2_endpoint,
            _ACCOUNT_B: b1_restart_endpoint,
        }
        partial_profile = _application_profile(
            subject=maker_subject,
            actor_role="maker",
            owner_subject=maker_subject,
            keys=keys,
            catalog_endpoint=endpoint_catalog,
            order_endpoints=partial_endpoints,
        )
        async with _service_read_lifespan(
            monkeypatch=monkeypatch,
            profiles=[partial_profile, checker_profile],
        ):
            a1_status = await _read_policy(
                client=client,
                headers=maker_headers,
                account_ref=_ACCOUNT_A,
                policy_ref=_POLICY_REFS[_ACCOUNT_A]["old"],
            )
            a2_status = await _read_policy(
                client=client,
                headers=maker_headers,
                account_ref=_ACCOUNT_A,
                policy_ref=_POLICY_REFS[_ACCOUNT_A]["new"],
            )
            b1_status = await _read_policy(
                client=client,
                headers=maker_headers,
                account_ref=_ACCOUNT_B,
                policy_ref=_POLICY_REFS[_ACCOUNT_B]["old"],
            )
            b2_status = await _read_policy(
                client=client,
                headers=maker_headers,
                account_ref=_ACCOUNT_B,
                policy_ref=_POLICY_REFS[_ACCOUNT_B]["new"],
            )
            assert a2_status["owner_confirmed"] is True, a2_status
            assert a2_status["owner_confirmed_version"] == a2_status["policy_version"]
            assert a2_status["owner_document_available"] is True, a2_status
            assert a1_status["state"] == "published", a1_status
            assert a1_status["owner_confirmed"] is False, a1_status
            assert a1_status["owner_confirmed_version"] is None, a1_status
            assert a1_status["owner_document_available"] is False, a1_status
            assert b1_status["owner_confirmed"] is True, b1_status
            assert b1_status["owner_confirmed_version"] == b1_status["policy_version"]
            assert b1_status["owner_document_available"] is True, b1_status
            assert a2_resolved.policy_version == a2_status["policy_version"]
            assert b1_resolved.policy_version == b1_status["policy_version"]
            assert b2_status["state"] == "published", b2_status
            assert b2_status["owner_confirmed"] is False, b2_status
            assert b2_status["owner_confirmed_version"] is None, b2_status
            assert b2_status["owner_document_available"] is False, b2_status

            denied = await _submit_manual_order(
                client=client,
                headers=maker_headers,
                account_ref=_ACCOUNT_A,
                idempotency_key="afi-ordinary-a-v2-over-limit",
                quantity="2",
                price="7",
            )
            assert denied["service_code"] == "ADMISSION_DENIED", denied
            assert denied["record"]["state"] == "REJECTED", denied
            after_a_denied = a2_owner.observe()
            assert after_a_denied["increase_count"] == 0, after_a_denied
            assert after_a_denied["provider_writes"] == (), after_a_denied

            allowed = await _submit_manual_order(
                client=client,
                headers=maker_headers,
                account_ref=_ACCOUNT_A,
                idempotency_key="afi-ordinary-a-v2-within-limit",
                quantity="1",
                price="7",
            )
            assert allowed["service_code"] == "OK", allowed
            assert allowed["record"]["state"] == "ACKED_TRACKED", allowed
            after_a_allowed = a2_owner.observe()
            assert after_a_allowed["policy_id"] == _POLICY_REFS[_ACCOUNT_A]["new"]
            assert after_a_allowed["policy_fingerprint"] == a2_resolved.risk_policy.fingerprint
            assert after_a_allowed["increase_count"] == 1, after_a_allowed
            assert Decimal(after_a_allowed["increase_notional"]) == Decimal("7")
            assert len(after_a_allowed["provider_writes"]) == 1

            allowed_old_b = await _submit_manual_order(
                client=client,
                headers=maker_headers,
                account_ref=_ACCOUNT_B,
                idempotency_key="afi-ordinary-b-v1-remains-live",
                quantity="1",
                price="2",
            )
            assert allowed_old_b["service_code"] == "OK", allowed_old_b
            assert allowed_old_b["record"]["state"] == "ACKED_TRACKED", allowed_old_b
            after_b_allowed = b1_restart_owner.observe()
            assert after_b_allowed["policy_id"] == _POLICY_REFS[_ACCOUNT_B]["old"]
            assert after_b_allowed["policy_fingerprint"] == b1_resolved.risk_policy.fingerprint
            assert after_b_allowed["increase_count"] == 2, after_b_allowed
            assert Decimal(after_b_allowed["increase_notional"]) == Decimal("12")
            assert len(after_b_allowed["provider_writes"]) == 1
        for owner in reversed(owners):
            owner.close()
            assert owner.state == "closed", owner.diagnostics()
            assert owner.error is None, owner.diagnostics()
        owners.clear()
    finally:
        active_error = sys.exception()
        cleanup_errors: list[BaseException] = []
        for owner in reversed(owners):
            try:
                owner.close()
            except BaseException as error:
                cleanup_errors.append(error)
        if catalog_attempted:
            try:
                catalog_host.close(require_success=catalog_host.error is None)
            except BaseException as error:
                cleanup_errors.append(error)
        for resource in (catalog, confirmations):
            try:
                resource.close()
            except BaseException as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            cleanup_codes = tuple(type(error).__name__ for error in cleanup_errors)
            if active_error is not None:
                active_error.add_note(f"policy-host cleanup failures: {cleanup_codes!r}")
            else:
                raise AssertionError(
                    f"policy-host cleanup failures: {cleanup_codes!r}"
                ) from cleanup_errors[0]
