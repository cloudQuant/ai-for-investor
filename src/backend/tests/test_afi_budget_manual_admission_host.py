"""Authenticated AFI manual orders consume the Risk-owned budget generation."""

from __future__ import annotations

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
import zmq
from sqlalchemy import insert
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
    RiskPolicy,
)
from bt_api_risk.budget_admission import (
    BudgetAdmissionResolutionError,
    PolicyCatalogBudgetAdmissionResolver,
)
from bt_api_risk.service_component import (
    ConfirmedPolicyStore,
    PolicyCatalogService,
    PolicyCatalogStore,
)
from bt_api_py.bt_api import BtApi
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_service_config
from bt_api_py.service_host import ServiceHost, ServiceHostError, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_py.service_risk_order_entry import RiskBtApiProviderContract, RiskOrderTarget
from bt_api_py.service_risk_order_journal import RiskOrderJournal
from pydantic import SecretStr

from app.api.service_read import configure_service_read
import app.main as main_module
from app.db.database import async_session_maker
from app.models.permission import Role, user_roles
from app.utils.security import decode_access_token

_DOMAIN = "paper:afi-budget-manual"
_ACCOUNT = "afi-account-a"
_PROVIDER_ACCOUNT_KEY = AccountKey(
    provider="PAPER",
    venue="synthetic-venue",
    environment="simulation",
    account_id="synthetic-provider-account-id",
)
_PROVIDER_ACCOUNT = _PROVIDER_ACCOUNT_KEY.account_key_id
_PORTFOLIO = "afi-portfolio-a"
_MANUAL_BOOK = "afi-manual-book-a"
_SELECTOR = "afi-budget-manual-a-v1"
_POOL = "afi-budget-pool-v1"
_GENERATION = "afi-budget-generation-v1"
_POLICY_REF_A = "afi-budget-account-a-v1"
_POLICY_REF_B = "afi-budget-account-b-v1"
_MAKER = "afi-budget-maker"
_CHECKER = "afi-budget-checker"
_APP_PRINCIPAL = "afi-budget-application-principal"
_APP_ACTOR = "afi-budget-application"
_APP_DELEGATE = "afi-budget-human-delegate"
_SERVICE_ID = "afi-budget-risk-owner"
_SERVICE_PRINCIPAL = "afi-budget-risk-owner-principal"
_INSTANCE = "afi-budget-risk-owner-instance"
_SERVICE_SCOPE_REF = "afi-budget-risk-owner-scope-v1"
_SERVICE_SECURITY_REF = "afi-budget-risk-server-curve-v1"
_APP_SECURITY_REF = "afi-budget-application-curve-v1"
_SERVICE_TRANSPORT_REF = "afi-budget-risk-listener-v1"
_APP_TRANSPORT_REF = "afi-budget-application-connect-v1"
_EXCHANGE = "PAPER___SPOT"
_INSTRUMENT = "BTC-USDT"
_METADATA_VERSION = "afi-budget-risk-metadata-v1"
_CURRENCY = "USD"
_METRIC = "max_increase_notional"
_MEMBERSHIP_SHA256 = "1" * 64
_MEMBERSHIP_VERSION = 1
_ALLOCATIONS: tuple[dict[str, object], ...] = (
    {
        "account_ref": _ACCOUNT,
        "policy_ref": _POLICY_REF_A,
        "amount": "25",
        "max_increase_count": 7,
    },
    {
        "account_ref": "afi-account-b",
        "policy_ref": _POLICY_REF_B,
        "amount": "15",
        "max_increase_count": 4,
    },
)


async def _register_manual_order_user(client: Any) -> tuple[str, dict[str, str]]:
    """Create a real USER role assignment before issuing the test bearer token."""
    username = f"afi_budget_http_{uuid.uuid4().hex[:12]}"
    password = "Test12345678"
    email = f"{username}@test.com"
    registration = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert registration.status_code == 200, registration.text
    subject = str(registration.json()["id"])
    async with async_session_maker() as db:
        await db.execute(
            insert(user_roles).values(user_id=subject, role=Role.USER.value)
        )
        await db.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return subject, {"Authorization": f"Bearer {token}"}


def _budget_scope(account_ref: str | None = None) -> WireScope:
    if account_ref is None:
        return WireScope(
            _DOMAIN,
            account_refs=tuple(sorted(str(row["account_ref"]) for row in _ALLOCATIONS)),
            portfolio_ref=_PORTFOLIO,
            group_id="afi-budget-group-v1",
        )
    return WireScope(_DOMAIN, account_ref=account_ref, portfolio_ref=_PORTFOLIO)


def _manual_scope() -> WireScope:
    # The public AFI manual-order contract deliberately carries no portfolio or
    # strategy claim. Catalog membership is resolved separately by the owner.
    return WireScope(_DOMAIN, account_ref=_ACCOUNT, manual_book_ref=_MANUAL_BOOK)


def _sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _catalog_call(
    service: PolicyCatalogService,
    operation: str,
    *,
    principal: str,
    scope: WireScope,
    arguments: dict[str, object],
) -> dict[str, object]:
    reply = service.handle(
        operation,
        principal_ref=principal,
        scope=scope,
        arguments=arguments,
    )
    assert reply["ok"] is True, reply
    assert reply["code"] == "OK", reply
    assert type(reply["result"]) is dict, reply
    return reply["result"]


def _prepare_persisted_budget(
    tmp_path: Path,
) -> tuple[
    PolicyCatalogStore,
    ConfirmedPolicyStore,
    PolicyCatalogService,
    PolicyCatalogBudgetAdmissionResolver,
    ConfirmedPolicyStore,
]:
    catalog = PolicyCatalogStore(
        str(tmp_path / "afi-policy-catalog.sqlite3"),
        trusted_approver_principals=(_CHECKER,),
    )
    confirmations = ConfirmedPolicyStore(str(tmp_path / "afi-confirmed-policy.sqlite3"))
    service = PolicyCatalogService(catalog, confirmation_store=confirmations)
    missing_confirmations = ConfirmedPolicyStore(
        str(tmp_path / "afi-confirmed-policy-missing.sqlite3")
    )
    catalog.configure_budget_pool(
        _POOL,
        capacity_amount="100",
        currency=_CURRENCY,
        metric=_METRIC,
        scale=2,
        portfolio_ref=_PORTFOLIO,
        membership_version=_MEMBERSHIP_VERSION,
        membership_sha256=_MEMBERSHIP_SHA256,
        account_refs=tuple(str(row["account_ref"]) for row in _ALLOCATIONS),
    )
    allocations = [dict(row, metric=_METRIC, currency=_CURRENCY) for row in _ALLOCATIONS]
    total_amount = "50"
    unallocated_amount = "10"
    manifest = {
        "kind": "afi.static_account_budget",
        "schema_version": 1,
        "portfolio_ref": _PORTFOLIO,
        "membership_version": _MEMBERSHIP_VERSION,
        "membership_sha256": _MEMBERSHIP_SHA256,
        "metric": _METRIC,
        "currency": _CURRENCY,
        "total_amount": total_amount,
        "unallocated_amount": unallocated_amount,
        "allocations": sorted(allocations, key=lambda row: row["account_ref"]),
    }
    allocation_digest = _sha256(manifest)
    for allocation in allocations:
        account_ref = str(allocation["account_ref"])
        policy_ref = str(allocation["policy_ref"])
        amount = str(allocation["amount"])
        content = {
            "afi_budget": {
                "kind": "afi.static_account_budget",
                "schema_version": 1,
                "portfolio_ref": _PORTFOLIO,
                "membership_version": _MEMBERSHIP_VERSION,
                "membership_sha256": _MEMBERSHIP_SHA256,
                "allocation_set_sha256": allocation_digest,
                "metric": _METRIC,
                "currency": _CURRENCY,
                "total_amount": total_amount,
                "unallocated_amount": unallocated_amount,
                "account_ref": account_ref,
                "allocated_amount": amount,
            },
            "risk_policy": {
                "policy_id": policy_ref,
                "max_increase_notional": amount,
                "max_increase_count": allocation["max_increase_count"],
                "permit_ttl_seconds": 30.0,
                "require_strategy_allocation": False,
                "notional_unit": _CURRENCY,
            },
        }
        _catalog_call(
            service,
            "policy.draft",
            principal=_MAKER,
            scope=_budget_scope(account_ref),
            arguments={"policy_ref": policy_ref, "content": content},
        )

    proposal = {
        "pool_ref": _POOL,
        "generation_ref": _GENERATION,
        "portfolio_ref": _PORTFOLIO,
        "membership_version": _MEMBERSHIP_VERSION,
        "membership_sha256": _MEMBERSHIP_SHA256,
        "allocation_set_sha256": allocation_digest,
        "currency": _CURRENCY,
        "metric": _METRIC,
        "total_amount": total_amount,
        "unallocated_amount": unallocated_amount,
        "allocations": allocations,
    }
    _catalog_call(
        service,
        "policy.budget.propose",
        principal=_MAKER,
        scope=_budget_scope(),
        arguments=proposal,
    )
    _catalog_call(
        service,
        "policy.budget.approve",
        principal=_CHECKER,
        scope=_budget_scope(),
        arguments={"generation_ref": _GENERATION},
    )
    receipts: dict[str, dict[str, object]] = {}
    for allocation in allocations:
        account_ref = str(allocation["account_ref"])
        published = _catalog_call(
            service,
            "policy.budget.publish_member",
            principal=_CHECKER,
            scope=_budget_scope(),
            arguments={"generation_ref": _GENERATION, "account_ref": account_ref},
        )
        assert published["consumer_effective"] is False, published
        member = published["member"]
        assert type(member) is dict, published
        receipts[account_ref] = member
    for allocation in allocations:
        account_ref = str(allocation["account_ref"])
        confirmations.confirm(receipts[account_ref])
        confirmed = _catalog_call(
            service,
            "policy.budget.confirm_member",
            principal=_MAKER,
            scope=_budget_scope(account_ref),
            arguments={"generation_ref": _GENERATION, "account_ref": account_ref},
        )
        assert confirmed["consumer_effective"] is False, confirmed
    resolver = PolicyCatalogBudgetAdmissionResolver(catalog, confirmations)
    return catalog, confirmations, service, resolver, missing_confirmations


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
            "registration_policy_ref": "afi-budget-registration-v1",
            "service_requirements_ref": "afi-budget-requirements-v1",
            "components": {
                "risk": {
                    "config_schema_version": 2,
                    "settings": {
                        "instance_id": _INSTANCE,
                        "bind_ports": ["service.order_entry"],
                        "options": {
                            "role": "account_owner",
                            "account_policy_ref": _POLICY_REF_A,
                        },
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


def _service_authority(endpoint: str, keys: dict[str, bytes]) -> TrustedServiceAuthority:
    del endpoint
    application = WireIdentity(
        WireRole.APPLICATION_CLIENT,
        _APP_PRINCIPAL,
        _APP_ACTOR,
        _APP_DELEGATE,
    )
    operations = frozenset({"orders.submit"})
    grant = ResourceGrant(_INSTANCE, "service.order_entry", _SELECTOR, _manual_scope(), operations)
    return TrustedServiceAuthority(
        identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID),
        scope=WireScope(_DOMAIN),
        scope_ref=_SERVICE_SCOPE_REF,
        scope_version="afi-budget-service-scope-v1",
        security_ref=_SERVICE_SECURITY_REF,
        security_version="afi-budget-server-curve-v1",
        registration_policy_ref="afi-budget-registration-v1",
        registration_policy_version="afi-budget-registration-policy-v1",
        service_requirements_ref="afi-budget-requirements-v1",
        service_requirements_version="afi-budget-requirements-policy-v1",
        curve_public_key=keys["server_public"],
        curve_secret_key=keys["server_secret"],
        principals={keys["application_public"]: _APP_PRINCIPAL},
        grants={_APP_PRINCIPAL: (PrincipalGrant(application, (grant,)),)},
    )


def _application_profile(
    *, subject: str, endpoint: str, keys: dict[str, bytes]
) -> dict[str, object]:
    return {
        "subject": subject,
        "identity": {
            "principal_ref": _APP_PRINCIPAL,
            "actor_ref": _APP_ACTOR,
            "delegate_ref": _APP_DELEGATE,
        },
        "client_config": {
            "client_config_schema_version": 1,
            "process_role": "application_client",
            "registration": {"application_ref": _APP_ACTOR},
            "clients": {
                "execution": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": "application.orders",
                                "service_id": _SERVICE_ID,
                                "instance_id": _INSTANCE,
                                "scope_ref": _SELECTOR,
                                "transport_ref": _APP_TRANSPORT_REF,
                                "account_ref": _ACCOUNT,
                            }
                        ],
                        "options": {"request_timeout_ms": 2_000},
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
                            "request_timeout_ms": 2_000,
                            "high_water_mark": 16,
                            "max_message_bytes": 65_536,
                        },
                    }
                },
            },
        },
        "scope_claims": {
            _SELECTOR: {
                "execution_domain_ref": _DOMAIN,
                "account_ref": _ACCOUNT,
                "manual_book_ref": _MANUAL_BOOK,
            }
        },
        "peer_identities": {
            _SERVICE_ID: {"principal_ref": _SERVICE_PRINCIPAL, "actor_ref": _SERVICE_ID}
        },
        "curve_keys": {
            _APP_SECURITY_REF: {
                "server_key": keys["server_public"].decode("ascii"),
                "public_key": keys["application_public"].decode("ascii"),
                "secret_key": keys["application_secret"].decode("ascii"),
            }
        },
        "grants": {
            "account_refs": [],
            "order_scope_refs": [],
            "order_submit_scope_refs": [_SELECTOR],
            "monitor_scope_refs": [],
        },
        "account_bindings": {},
        "order_bindings": {},
        "order_submit_bindings": {
            _SELECTOR: {
                "mount": "application.orders",
                "account_ref": _ACCOUNT,
                "manual_book_ref": _MANUAL_BOOK,
                "instrument_metadata_versions": {
                    _INSTRUMENT: _METADATA_VERSION
                },
            }
        },
        "monitor_bindings": {},
        "worker": {"max_queue_size": 8, "maintenance_interval_seconds": 0.05},
    }


class _SyntheticProvider:
    """Provider leaf for the real BtApi/Risk order path; never calls a network."""

    def __init__(self) -> None:
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
            "account_id": _PROVIDER_ACCOUNT,
            "client_order_id": client_order_id,
            "filled": 0,
            "order_id": "provider-" + client_order_id,
            "quantity": volume,
            "side": order_type.split("-", 1)[0],
            "status": "open",
            "symbol": symbol,
        }
        self.rows[client_order_id] = row
        self.writes.append(client_order_id)
        return {
            "account_id": _PROVIDER_ACCOUNT,
            "client_order_id": client_order_id,
            "complete": True,
            "schema_version": "afi.fixture.order.v1",
            "watermark": len(self.writes),
            "data": [dict(row)],
        }

    def query_order(
        self, _symbol: str, order_id: str, **_kwargs: Any
    ) -> dict[str, object]:
        self.order_queries.append(order_id)
        row = self.rows.get(order_id)
        return {
            "account_id": _PROVIDER_ACCOUNT,
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
            "account_id": _PROVIDER_ACCOUNT,
            "client_order_id": client_order_id,
            "complete": True,
            "schema_version": "afi.fixture.fills.v1",
            "watermark": len(self.fill_queries),
            "data": [],
        }


class _HostOwner:
    """Keep the ZMQ ServiceHost on one owner thread and report normal close."""

    def __init__(
        self,
        config: Any,
        authority: TrustedServiceAuthority,
        registry_path: Path,
        resource_provider: Any,
        resources: dict[str, Any],
    ) -> None:
        self._config = config
        self._authority = authority
        self._registry_path = registry_path
        self._resource_provider = resource_provider
        self._resources = resources
        self._commands: queue.Queue[tuple[str, queue.Queue[Any] | None]] = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="afi-budget-risk-host", daemon=False)
        self.error: BaseException | None = None
        self.resource_error_code: str | None = None
        self.close_error_code: str | None = None
        self.host_cleanup: dict[str, object] | None = None
        self.owner_cleanup_failures: list[dict[str, str]] = []
        self.state: str | None = None

    def start(self) -> bool:
        self._thread.start()
        assert self._ready.wait(timeout=10), "Risk Host did not report startup"
        return self.error is None and self.state == "started"

    def observe(self) -> dict[str, object]:
        reply: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._commands.put(("observe", reply))
        value = reply.get(timeout=5)
        assert isinstance(value, dict), value
        return value

    def close(self) -> None:
        if self._thread.is_alive() and self.state == "started":
            reply: queue.Queue[Any] = queue.Queue(maxsize=1)
            self._commands.put(("close", reply))
            reply.get(timeout=10)
        self._thread.join(timeout=10)
        assert not self._thread.is_alive(), "Risk Host owner thread remained alive"

    def diagnostics(self) -> dict[str, object]:
        error = self.error
        code = getattr(error, "code", None) if error is not None else None
        return {
            "state": self.state,
            "error_code": code if type(code) is str else (type(error).__name__ if error is not None else None),
            "resource_error_code": self.resource_error_code,
            "close_error_code": self.close_error_code,
            "thread_alive": self._thread.is_alive(),
            "host_cleanup": self.host_cleanup,
            "owner_cleanup_failures": tuple(self.owner_cleanup_failures),
            "resolution_error_code": self._resources.get("resolution_error_code"),
            "ledger_error_code": self._resources.get("ledger_error_code"),
        }

    def _run(self) -> None:
        host: ServiceHost | None = None
        try:
            host = ServiceHost(
                self._config,
                self._authority,
                str(self._registry_path),
                self._resource_provider,
            )
            host.start()
            self.state = host.state
            self._ready.set()
            while True:
                try:
                    command, reply = self._commands.get(timeout=0.01)
                except queue.Empty:
                    host.serve_once(timeout_ms=20)
                    self.state = host.state
                    continue
                if command == "observe":
                    gate = self._resources.get("gate")
                    account_scope = self._resources.get("account_scope")
                    provider = self._resources.get("provider")
                    assert isinstance(gate, DurableRiskGate)
                    assert isinstance(account_scope, AccountScope)
                    binding = gate.bind_policy(account_scope)
                    assert reply is not None
                    reply.put(
                        {
                            "host_state": host.state,
                            "policy_id": binding.policy_id,
                            "policy_fingerprint": binding.policy_fingerprint,
                            "ledger_identity_ref": binding.ledger_identity_ref,
                            "increase_count": gate.snapshot(account_scope)["increase_count"],
                            "increase_notional": str(
                                gate.snapshot(account_scope)["increase_notional"]
                            ),
                            "provider_writes": tuple(provider.writes),
                            "provider_order_queries": tuple(provider.order_queries),
                            "provider_fill_queries": tuple(provider.fill_queries),
                        }
                    )
                    continue
                if command == "close":
                    assert reply is not None
                    try:
                        host.close()
                    except BaseException as error:
                        self.error = error
                        self.close_error_code = getattr(error, "code", type(error).__name__)
                        self.state = host.state
                        reply.put({
                            "host_state": host.state,
                            "error_code": getattr(error, "code", type(error).__name__),
                        })
                        return
                    self.state = host.state
                    reply.put({"host_state": host.state})
                    return
                raise AssertionError("unknown host control")
        except BaseException as error:
            self.error = error
            if isinstance(error, ServiceHostError):
                self.resource_error_code = error.code
            self.state = None if host is None else host.state
        finally:
            if host is not None:
                self.state = host.state
                try:
                    summary = host.summary
                    self.host_cleanup = {
                        "state": host.state,
                        "start_failure": summary.get("start_failure"),
                        "cleanup_failures": tuple(summary.get("cleanup_failures", ())),
                        "cleanup_history": tuple(summary.get("cleanup_history", ())),
                    }
                except BaseException as error:
                    self.host_cleanup = {
                        "summary_error_code": getattr(error, "code", type(error).__name__)
                    }
            for key in ("gate", "bt_api"):
                resource = self._resources.get(key)
                close = getattr(resource, "close", None)
                if callable(close):
                    try:
                        close()
                    except BaseException as error:
                        self.owner_cleanup_failures.append(
                            {"resource": key, "code": getattr(error, "code", type(error).__name__)}
                        )
                        if self.error is None:
                            self.error = error
            self._ready.set()


def _resource_provider_factory(
    *,
    resolver: PolicyCatalogBudgetAdmissionResolver,
    gate_path: Path,
    journal_path: Path,
    provider: _SyntheticProvider,
    resources: dict[str, Any],
) -> Any:
    def provide(component: str, _instance_id: str, _options: Any, _scope: WireScope):
        assert component == "risk", component
        try:
            resolved = resolver.resolve(
                _POOL,
                _ACCOUNT,
                scope=_budget_scope(_ACCOUNT),
            )
        except BudgetAdmissionResolutionError as error:
            resources["resolution_error_code"] = error.code
            raise
        resources["resolved_budget"] = resolved

        now_ns = time.time_ns()
        metadata = InstrumentRiskMetadata(
            instrument=_INSTRUMENT,
            metadata_version=_METADATA_VERSION,
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
        registry = InstrumentRiskRegistry((metadata,))
        account_scope = AccountScope(
            _PROVIDER_ACCOUNT_KEY.provider,
            _PROVIDER_ACCOUNT,
            _PROVIDER_ACCOUNT_KEY.environment,
        )
        target = RiskOrderTarget(
            account_scope=account_scope,
            strategy_id="afi-internal-manual-target-v1",
            exchange_name=_EXCHANGE,
            provider_account_id=_PROVIDER_ACCOUNT,
            registry=registry,
        )
        bt_api = BtApi(debug=False)
        bt_api.exchange_feeds[_EXCHANGE] = provider
        journal = RiskOrderJournal(str(journal_path), writer_id="afi-budget-risk-owner")
        try:
            gate = DurableRiskGate(
                str(gate_path),
                resolved.risk_policy,
                execution_journal_authority=journal,
            )
        except BaseException as error:
            resources["ledger_error_code"] = getattr(error, "code", type(error).__name__)
            bt_api.close()
            raise
        try:
            startup_binding = gate.bind_policy(account_scope)
            if (
                startup_binding.policy_id != resolved.policy_ref
                or startup_binding.policy_fingerprint != resolved.risk_policy.fingerprint
            ):
                raise RuntimeError("durable policy binding differs from the resolved budget")
        except BaseException as error:
            resources["ledger_error_code"] = getattr(error, "code", type(error).__name__)
            gate.close()
            bt_api.close()
            raise
        mapper = InstrumentRiskAdmissionMapper(
            account_scope,
            registry,
            clock_ns=time.time_ns,
        )
        adapter = DurableRiskAdmissionAdapter(gate, mapper)
        contract = RiskBtApiProviderContract(
            exchange_name=_EXCHANGE,
            profile_id="afi-synthetic-provider-contract-v1",
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
        manual_scope = _manual_scope()
        resources.update(
            {
                "bt_api": bt_api,
                "journal": journal,
                "gate": gate,
                "account_scope": account_scope,
                "resolved_budget": resolved,
                "startup_policy_binding": startup_binding,
                "provider": provider,
            }
        )
        return ComponentResources.borrowed(
            {
                "bt_api": bt_api,
                "targets": {manual_scope: target},
                "admission": {manual_scope: adapter},
                "journal": journal,
                "gate": gate,
                "provider_contracts": {manual_scope: contract},
            },
            ready=lambda: True,
        )

    return provide


def _seed_old_reservation(path: Path) -> tuple[RiskPolicy, AccountScope, dict[str, object]]:
    old_policy = RiskPolicy(
        "afi-previous-account-policy-v1",
        Decimal("80"),
        max_increase_count=9,
        permit_ttl_seconds=300.0,
        notional_unit=_CURRENCY,
    )
    scope = AccountScope(
        _PROVIDER_ACCOUNT_KEY.provider,
        _PROVIDER_ACCOUNT,
        _PROVIDER_ACCOUNT_KEY.environment,
    )
    gate = DurableRiskGate(path, old_policy)
    gate.reserve(
        RiskIntent(
            intent_id="afi-prior-active-reservation",
            scope=scope,
            action=IntentAction.INCREASE,
            notional=Decimal("12.5"),
            payload_fingerprint="old-ledger-reservation",
            notional_unit=_CURRENCY,
        )
    )
    before = gate.snapshot(scope)
    gate.close()
    return old_policy, scope, before


@pytest.mark.asyncio
async def test_authenticated_manual_http_order_uses_confirmed_budget_risk_host(
    tmp_path: Path,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject, auth_headers = await _register_manual_order_user(client)
    assert (
        decode_access_token(auth_headers["Authorization"].removeprefix("Bearer "))["sub"]
        == subject
    )
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    application_public, application_secret = zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "application_public": application_public,
        "application_secret": application_secret,
    }
    catalog, confirmations, policy_service, resolver, unused_confirmations = (
        _prepare_persisted_budget(tmp_path)
    )
    resources: dict[str, Any] = {}
    provider = _SyntheticProvider()
    host_owner = _HostOwner(
        _service_config(endpoint),
        _service_authority(endpoint, keys),
        tmp_path / "afi-budget-service-registry.sqlite3",
        _resource_provider_factory(
            resolver=resolver,
            gate_path=tmp_path / "afi-budget-risk.sqlite3",
            journal_path=tmp_path / "afi-budget-risk-journal.sqlite3",
            provider=provider,
            resources=resources,
        ),
        resources,
    )
    deployment = None
    host_started = False
    application = main_module.app
    previous_deployment = getattr(application.state, "service_read_deployment", None)
    assert previous_deployment is None or previous_deployment.closed, previous_deployment
    deployment_json = json.dumps(
        {
            "schema_version": 1,
            "subjects": [_application_profile(subject=subject, endpoint=endpoint, keys=keys)],
        },
        separators=(",", ":"),
    )
    monkeypatch.setattr(main_module.settings, "DB_AUTO_CREATE_SCHEMA", True)
    monkeypatch.setattr(main_module.settings, "RAG_VECTOR_ENABLED", False)
    monkeypatch.setattr(
        main_module.settings,
        "SERVICE_READ_DEPLOYMENT_JSON",
        SecretStr(deployment_json),
    )
    configure_service_read(None)
    try:
        host_started = host_owner.start()
        assert host_started, host_owner.diagnostics()
        assert host_owner.state == "started"
        actual_budget = resources["resolved_budget"]
        assert actual_budget.generation_ref == _GENERATION
        assert actual_budget.account_ref == _ACCOUNT
        assert actual_budget.portfolio_ref == _PORTFOLIO
        assert actual_budget.risk_policy.max_increase_notional == Decimal("25")
        assert actual_budget.risk_policy.require_strategy_allocation is False

        async with main_module.lifespan(application):
            deployment = application.state.service_read_deployment
            assert deployment is not None and not deployment.closed
            oversized_response = await client.post(
                "/api/v1/service-orders/manual",
                json={
                    "scope_ref": _SELECTOR,
                    "instrument": _INSTRUMENT,
                    "side": "BUY",
                    "position_effect": "OPEN",
                    "order_type": "LIMIT",
                    "quantity": "2",
                    "price": "20",
                    "time_in_force": "GTC",
                    "reduce_only": False,
                },
                headers={
                    **auth_headers,
                    "Idempotency-Key": "afi-budget-manual-order-over-limit",
                },
            )
            assert oversized_response.status_code == 200, oversized_response.text
            oversized_payload = oversized_response.json()
            assert oversized_payload["service_code"] == "ADMISSION_DENIED", oversized_payload
            assert oversized_payload["record"]["state"] == "REJECTED", oversized_payload
            assert oversized_payload["outcome"] == "durable_record", oversized_payload
            after_denial = host_owner.observe()
            assert after_denial["increase_count"] == 0, after_denial
            assert Decimal(str(after_denial["increase_notional"])) == Decimal("0"), after_denial
            assert after_denial["provider_writes"] == (), after_denial

            response = await client.post(
                "/api/v1/service-orders/manual",
                json={
                    "scope_ref": _SELECTOR,
                    "instrument": _INSTRUMENT,
                    "side": "BUY",
                    "position_effect": "OPEN",
                    "order_type": "LIMIT",
                    "quantity": "1",
                    "price": "20",
                    "time_in_force": "GTC",
                    "reduce_only": False,
                },
                headers={
                    **auth_headers,
                    "Idempotency-Key": "afi-budget-manual-order-001",
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["operation_kind"] == "manual_order"
            assert payload["account_ref"] == _ACCOUNT
            assert payload["manual_book_ref"] == _MANUAL_BOOK
            assert payload["service_code"] == "OK"
            assert payload["record"]["state"] == "ACKED_TRACKED"
            assert payload["record"]["provider_order_id"].startswith("provider-risk-")
            assert payload["outcome"] == "durable_record"

            observed = host_owner.observe()
            assert observed["host_state"] == "started"
            assert observed["policy_id"] == _POLICY_REF_A
            assert observed["policy_fingerprint"] == actual_budget.risk_policy.fingerprint
            assert observed["ledger_identity_ref"]
            assert observed["increase_count"] == 1, observed
            assert Decimal(str(observed["increase_notional"])) == Decimal("20"), observed
            assert observed["provider_writes"] and len(observed["provider_writes"]) == 1
            assert len(observed["provider_order_queries"]) >= 1
            assert len(observed["provider_fill_queries"]) >= 1
            assert resources["resolved_budget"].generation_ref == _GENERATION
            assert "consumer_effective" not in payload
        assert deployment is not None and deployment.closed
        assert application.state.service_read_deployment is None
    finally:
        configure_service_read(None)
        if deployment is not None and not deployment.closed:
            await deployment.aclose()
        host_owner.close()
        if host_started:
            assert host_owner.state == "closed", host_owner.diagnostics()
            assert host_owner.error is None, host_owner.diagnostics()
        else:
            # Startup failure is already asserted with the full owner/host diagnostic above.
            # Do not let cleanup-state checks replace that first failure.
            assert not host_owner.diagnostics()["thread_alive"], host_owner.diagnostics()
        policy_service.close()
        catalog.close()
        confirmations.close()
        unused_confirmations.close()


def test_budget_activation_refuses_missing_confirmation_and_incompatible_old_ledger(
    tmp_path: Path,
) -> None:
    for blocker in ("missing_confirmation", "occupied_old_ledger"):
        case_root = tmp_path / blocker
        case_root.mkdir()
        _assert_budget_activation_refusal(blocker, case_root)


def _assert_budget_activation_refusal(blocker: str, tmp_path: Path) -> None:
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    application_public, application_secret = zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "application_public": application_public,
        "application_secret": application_secret,
    }
    catalog, confirmations, policy_service, resolver, missing_confirmations = (
        _prepare_persisted_budget(tmp_path)
    )
    gate_path = tmp_path / "afi-budget-risk.sqlite3"
    old_policy, old_scope, old_snapshot = _seed_old_reservation(gate_path)

    resources: dict[str, Any] = {}
    provider = _SyntheticProvider()
    startup_resolver = (
        PolicyCatalogBudgetAdmissionResolver(catalog, missing_confirmations)
        if blocker == "missing_confirmation"
        else resolver
    )
    host_owner = _HostOwner(
        _service_config(endpoint),
        _service_authority(endpoint, keys),
        tmp_path / "afi-budget-service-registry.sqlite3",
        _resource_provider_factory(
            resolver=startup_resolver,
            gate_path=gate_path,
            journal_path=tmp_path / "afi-budget-risk-journal.sqlite3",
            provider=provider,
            resources=resources,
        ),
        resources,
    )
    try:
        assert host_owner.start() is False
        assert host_owner.error is not None
        assert host_owner.state != "started"
        assert provider.writes == []
        if blocker == "missing_confirmation":
            assert resources["resolution_error_code"] == "POLICY_NOT_CONFIRMED"
            assert "gate" not in resources
        else:
            assert resources["ledger_error_code"]
        reopened = DurableRiskGate(gate_path, old_policy)
        try:
            after = reopened.snapshot(old_scope)
            binding = reopened.bind_policy(old_scope)
            assert after["increase_count"] == old_snapshot["increase_count"] == 1
            assert (
                after["increase_notional"]
                == old_snapshot["increase_notional"]
                == Decimal("12.5")
            )
            assert after["policy_fingerprint"] == old_snapshot["policy_fingerprint"]
            assert binding.policy_id == old_policy.policy_id
            assert binding.policy_fingerprint == old_policy.fingerprint
        finally:
            reopened.close()
    finally:
        host_owner.close()
        policy_service.close()
        catalog.close()
        confirmations.close()
        missing_confirmations.close()
