"""AFI REDUCE HTTP path through the real SDK owner and Risk ledger.

The provider is an in-process synthetic leaf. This test proves the persisted
AFI approval, HTTP identity/grant, ServiceHost owner.reduce route, Execution
order journal and Risk close reservation compose locally; it proves no venue
connectivity or provider account position.
"""

from __future__ import annotations

import json
import queue
import socket
import threading
import time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import jwt
import pytest
import zmq
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_execution import (
    ExecutionAdmissionValidatorRegistry,
    ExecutionBasicAdmissionGate,
    ExecutionProviderValidatorV1,
    ExecutionScope,
    OrderType,
    PositionEffect,
    Side,
    SqliteExecutionStore,
    TimeInForce,
)
from bt_api_execution.approved_target import (
    ApprovedTargetOwnerBindingV1,
)
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_client_config, parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_py.service_runtime import (
    ClientCurveKeys,
    ServiceClientRuntime,
    ZmqTransportFactory,
)
from bt_api_risk import (
    AccountScope,
    DurableRiskAdmissionAdapter,
    DurableRiskGate,
    RiskPolicy,
)
from pydantic import SecretStr
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 - register the complete ORM model set

_SUBJECT = "afi-reduction-http-owner"
_PRINCIPAL = "afi-reduction-http-principal"
_ACTOR = "afi-reduction-http-actor"
_DELEGATE = "afi-reduction-http-delegate"
_DOMAIN = "paper:afi-reduction-http-v1"
_ACCOUNT = "account.afi-reduction"
_STRATEGY = "strategy.afi-reduction"
_RUN = "run.afi-reduction"
_SELECTOR = "afi-reduction-selector"
_APPROVAL_SCOPE = "afi-reduction-approved-scope"
_OWNER_SCOPE = "afi-reduction-owner-run-scope"
_STRATEGY_SCOPE = "afi-reduction-strategy-run-scope"
_OWNER_SERVICE = "afi-reduction-paper-owner"
_OWNER_INSTANCE = "afi-reduction-paper-account-owner"
_RISK_INSTANCE = "afi-reduction-risk-account-owner"
_RISK_POLICY = "afi-reduction-risk-policy-v1"
_INSTRUMENT = "BTC-USDT"
_MAX_MESSAGE_BYTES = 65_536

_WIRE_SCOPE = WireScope(
    _DOMAIN,
    account_ref=_ACCOUNT,
    strategy_ref=_STRATEGY,
    run_id=_RUN,
)
_TEMPLATE_SCOPE = WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY)
_APP_IDENTITY = WireIdentity(WireRole.APPLICATION_CLIENT, _PRINCIPAL, _ACTOR, _DELEGATE)
_SERVICE_IDENTITY = WireIdentity(WireRole.SERVICE, _PRINCIPAL, _ACTOR, _DELEGATE)
_HOST_IDENTITY = WireIdentity(
    WireRole.SERVICE, "afi-reduction-host-principal", _OWNER_SERVICE, "afi-reduction-host"
)
_STRATEGY_IDENTITY = WireIdentity(
    WireRole.STRATEGY_CLIENT, "afi-reduction-strategy-principal", _STRATEGY
)


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _scope_payload(scope: WireScope) -> dict[str, object]:
    return {
        "execution_domain_ref": scope.execution_domain_ref,
        "account_ref": scope.account_ref,
        "account_refs": [],
        "strategy_ref": scope.strategy_ref,
        "run_id": scope.run_id,
        "manual_book_ref": None,
        "portfolio_ref": None,
        "group_id": None,
        "leg_id": None,
    }


def _owner_config(endpoint: str) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _OWNER_SERVICE,
        "scope_ref": "afi-reduction-owner-root-v1",
        "transport_ref": "afi-reduction-owner-listener-v1",
        "registration_policy_ref": "afi-reduction-owner-registration-v1",
        "service_requirements_ref": "afi-reduction-owner-requirements-v1",
        "components": {
            "execution": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _OWNER_INSTANCE,
                    "bind_ports": ["service.order_entry", "service.owner_control"],
                    "options": {
                        "role": "account_owner",
                        "paper_composition": "execution_risk",
                        "approved_target_required": True,
                    },
                },
            },
            "risk": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _RISK_INSTANCE,
                    "bind_ports": ["service.order_entry"],
                    "options": {
                        "role": "account_owner",
                        "account_policy_ref": _RISK_POLICY,
                    },
                },
            },
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "afi-reduction-owner-listener-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": "afi-reduction-owner-server-curve-v1",
                    "options": {"high_water_mark": 32, "max_message_bytes": _MAX_MESSAGE_BYTES},
                }
            },
        },
    }


def _reduction_client_config(endpoint: str) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": "afi-reduction-client-process",
        "scope_ref": "afi-reduction-client-registration-v1",
        "transport_ref": "afi-reduction-client-listener-v1",
        "registration_policy_ref": "afi-reduction-client-policy-v1",
        "service_requirements_ref": "afi-reduction-client-requirements-v1",
        "components": {
            "execution": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _OWNER_INSTANCE,
                    "bind_ports": ["service.owner_control"],
                    "options": {"role": "account_owner"},
                },
            }
        },
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "upstream.owner_control",
                            "service_id": _OWNER_SERVICE,
                            "instance_id": _OWNER_INSTANCE,
                            "scope_ref": _OWNER_SCOPE,
                            "transport_ref": "afi-reduction-owner-connect-v1",
                            "account_ref": _ACCOUNT,
                        }
                    ],
                    "options": {"request_timeout_ms": 3_000},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "afi-reduction-client-listener-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": "afi-reduction-client-server-curve-v1",
                },
                "afi-reduction-owner-connect-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": endpoint},
                    "security_profile_ref": "afi-reduction-client-curve-v1",
                    "options": {
                        "request_timeout_ms": 3_000,
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                },
            },
        },
    }


def _strategy_client_config(endpoint: str):
    return parse_client_config(
        {
            "client_config_schema_version": 1,
            "process_role": "strategy_client",
            "registration": {"strategy_ref": _STRATEGY},
            "clients": {
                "execution": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": "broker.orders",
                                "service_id": _OWNER_SERVICE,
                                "instance_id": _OWNER_INSTANCE,
                                "scope_ref": _STRATEGY_SCOPE,
                                "transport_ref": "afi-reduction-strategy-connect-v1",
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
                    "afi-reduction-strategy-connect-v1": {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_connect": endpoint},
                        "security_profile_ref": "afi-reduction-strategy-curve-v1",
                        "options": {
                            "request_timeout_ms": 2_000,
                            "high_water_mark": 32,
                            "max_message_bytes": _MAX_MESSAGE_BYTES,
                        },
                    }
                },
            },
        }
    )


class _SyntheticPaperQuotes:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.cursor = 0

    def read_quote(self, instrument: str):
        from bt_api_execution.paper_execution import PaperQuoteV1

        self.calls.append(instrument)
        if instrument != _INSTRUMENT:
            return None
        self.cursor += 1
        return PaperQuoteV1(
            source_ref="afi-reduction-local-quotes-v1",
            generation="afi-reduction-local-quotes-generation-v1",
            cursor=self.cursor,
            instrument=instrument,
            metadata_version="afi-reduction-instrument-v1",
            quote_currency="USDT",
            bid=Decimal("10.00"),
            ask=Decimal("10.02"),
            bid_quantity=Decimal("5"),
            ask_quantity=Decimal("5"),
            as_of_ns=time.time_ns(),
        )


def _paper_graph(paths: dict[str, str]):
    from bt_api_execution import (
        PAPER_ENVIRONMENT,
        PAPER_PROVIDER,
        PaperMatchingPort,
    )
    from bt_api_execution.paper_execution import (
        PAPER_MODEL_REF,
        PaperInstrumentV1,
        PaperOpeningPositionV1,
        PaperOwnerDomainV1,
    )
    from bt_api_execution.paper_execution_risk import PaperExecutionCloseAuthority
    from bt_api_execution.paper_risk import PaperRiskAdmissionAdapter
    from bt_api_py import bt_api as bt_api_module
    from bt_api_py.service_components import TrustedRiskPolicyBinding
    from bt_api_py.service_risk_order_entry import (
        RiskBtApiProviderContract,
        RiskOrderJournal,
        RiskOrderTarget,
    )
    from bt_api_risk import (
        InstrumentRiskAdmissionMapper,
        InstrumentRiskMetadata,
        InstrumentRiskRegistry,
    )

    bt_api_module._ensure_plugins_loaded = lambda: None
    bt_api = bt_api_module.BtApi(debug=False)
    store = SqliteExecutionStore(paths["execution"])
    journal = RiskOrderJournal(paths["journal"], writer_id="afi-reduction-local-owner")
    policy = RiskPolicy(
        policy_id=_RISK_POLICY,
        max_increase_notional=Decimal("1000"),
        max_increase_count=10,
        permit_ttl_seconds=60.0,
        require_strategy_allocation=True,
        notional_unit="USDT",
    )
    risk_scope = AccountScope(PAPER_PROVIDER, _ACCOUNT, PAPER_ENVIRONMENT)
    domain = PaperOwnerDomainV1(
        execution_domain_ref=_DOMAIN,
        simulation_account_ref=_ACCOUNT,
        experiment_ref="afi-reduction-local-paper-experiment-v1",
        strategy_ref=_STRATEGY,
        model_ref=PAPER_MODEL_REF,
        model_version="1",
        quote_source_ref="afi-reduction-local-quotes-v1",
        cash_currency="USDT",
        initial_cash=Decimal("100"),
        initial_fees=Decimal("0"),
        fee_rate=Decimal("0.001"),
        fee_quantum=Decimal("0.0001"),
        max_quote_age_ns=30_000_000_000,
        instruments=(
            PaperInstrumentV1(
                _INSTRUMENT,
                "afi-reduction-instrument-v1",
                "BTC",
                "USDT",
                Decimal("0.25"),
                Decimal("0.01"),
            ),
        ),
        opening_positions=(PaperOpeningPositionV1(_INSTRUMENT, Decimal("1"), Decimal("10")),),
    )
    execution_scope = ExecutionScope(
        PAPER_PROVIDER, PAPER_ENVIRONMENT, _ACCOUNT, _STRATEGY, "afi-reduction-trading-day-v1"
    )
    quotes = _SyntheticPaperQuotes()
    dispatch = PaperMatchingPort(domain, quotes)
    metadata = InstrumentRiskMetadata(
        instrument=_INSTRUMENT,
        metadata_version="afi-reduction-instrument-v1",
        as_of_ns=time.time_ns() - 1_000_000,
        expires_at_ns=time.time_ns() + 3_600_000_000_000,
        tick_size=Decimal("0.01"),
        quantity_step=Decimal("0.25"),
        contract_multiplier=Decimal("1"),
        max_gross_notional=Decimal("1000"),
        taker_fee_bps=Decimal("10"),
        quantity_unit="BTC",
        valuation_unit="USDT",
        quote_currency="USDT",
    )
    registry = InstrumentRiskRegistry((metadata,))
    close_authority = PaperExecutionCloseAuthority(
        store, execution_scope, domain, dispatch, risk_scope, registry, journal
    )
    gate = DurableRiskGate(
        paths["risk"],
        policy,
        execution_journal_authority=journal,
        gross_exposure_authority=close_authority,
    )
    gate.set_strategy_allocation(
        risk_scope,
        _STRATEGY,
        "afi-reduction-local-allocation-v1",
        max_notional=Decimal("1000"),
        notional_unit="USDT",
    )
    validator = ExecutionProviderValidatorV1(
        provider_id=PAPER_PROVIDER,
        validator_id="afi-reduction-local-market-policy-v1",
        version="1",
        dispatch_port=dispatch,
        instrument_map={_INSTRUMENT: _INSTRUMENT},
        quantity_steps={_INSTRUMENT: Decimal("0.25")},
        max_quantities={_INSTRUMENT: Decimal("10")},
        price_ticks={_INSTRUMENT: Decimal("0.01")},
        supported_order_types=(OrderType.MARKET,),
        supported_time_in_force=(TimeInForce.FOK,),
        supported_actions=((Side.BUY, PositionEffect.OPEN), (Side.SELL, PositionEffect.CLOSE)),
        supports_reduce_only=True,
    )
    basic_gate = ExecutionBasicAdmissionGate(
        store,
        ExecutionAdmissionValidatorRegistry((validator,)),
        permit_ttl_ns=60_000_000_000,
    )
    paper_gate = PaperRiskAdmissionAdapter(
        gate,
        domain,
        dispatch,
        close_authority=close_authority,
        execution_store=store,
        execution_scope=execution_scope,
    )
    mapper = InstrumentRiskAdmissionMapper(
        risk_scope,
        registry,
        allocation_reader=lambda scope: gate.get_strategy_allocation(risk_scope, scope.strategy_id),
        wire_account_ref=_ACCOUNT,
    )
    risk_target = RiskOrderTarget(
        account_scope=risk_scope,
        strategy_id=_STRATEGY,
        exchange_name="paper___spot",
        provider_account_id=_ACCOUNT,
        registry=registry,
    )
    provider_contract = RiskBtApiProviderContract(
        exchange_name="paper___spot",
        profile_id="afi-reduction-paper-provider-v1",
        order_schema="paper-reduction-order-v1",
        fill_schema="paper-reduction-fill-v1",
        client_order_id_query=True,
        client_order_id_query_unique=True,
        complete_order_snapshot=True,
        complete_fill_history=True,
        provider_accepts_client_order_id=True,
        provider_status_mapping=(("filled", "filled"), ("rejected", "rejected")),
        supported_order_types=("LIMIT",),
        supported_time_in_force=("GTC",),
        supported_position_effects=("OPEN",),
        normalizer_schema="afi-reduction-paper-normalizer-v1",
        order_revision_field="order_revision",
        fill_revision_field="fill_revision",
        fill_watermark_field="fill_watermark",
        fee_amount_field="fee_amount",
        fee_currency_field="fee_currency",
        quote_currency_by_instrument=((_INSTRUMENT, "USDT"),),
    )
    execution_values = {
        "store": store,
        "targets": {_TEMPLATE_SCOPE: execution_scope},
        "dispatch": dispatch,
        "admission": {"basic_admission_gate": basic_gate, "order_gate": paper_gate},
        "paper_owner_domain": domain,
    }
    risk_values = {
        "bt_api": bt_api,
        "targets": {_TEMPLATE_SCOPE: risk_target},
        "admission": {
            _TEMPLATE_SCOPE: DurableRiskAdmissionAdapter(gate, mapper),
        },
        "journal": journal,
        "gate": gate,
        "provider_contracts": {_TEMPLATE_SCOPE: provider_contract},
    }
    risk_resource = ComponentResources.borrowed(
        risk_values,
        ready=lambda: True,
        risk_policy_bindings=(TrustedRiskPolicyBinding(_RISK_POLICY, _TEMPLATE_SCOPE, gate.policy),),
    )
    return execution_values, risk_resource, {
        "bt_api": bt_api,
        "store": store,
        "journal": journal,
        "gate": gate,
        "scope": execution_scope,
        "risk_scope": risk_scope,
        "quotes": quotes,
    }


def _close_graph(graph: dict[str, Any]) -> None:
    failures: list[str] = []
    for name in ("gate", "journal", "store", "bt_api"):
        try:
            graph[name].close()
        except BaseException as error:  # cleanup facts must stay finite
            failures.append(type(error).__name__)
    if failures:
        raise AssertionError(f"Paper/Risk graph cleanup failed: {failures}")


def _host_snapshot(graph: dict[str, Any], intent_id: str) -> dict[str, Any]:
    record = graph["store"].get(intent_id, scope=graph["scope"])
    receipt = graph["store"].get_paper_match_receipt(intent_id, scope=graph["scope"])
    book = graph["store"].read_paper_book(graph["scope"])
    close = graph["gate"].dispatch_close_resolution_receipt(record.permit_reference)
    closable = graph["gate"].get_closable_position(
        graph["risk_scope"],
        _INSTRUMENT,
        _STRATEGY,
        position_side="NET",
        position_bucket="ALL",
    )
    return {
        "record_state": record.state.value,
        "dispatch_attempts": record.dispatch_attempts,
        "permit_reference": record.permit_reference,
        "receipt_state": receipt.state.value,
        "receipt_event_id": receipt.event_id,
        "receipt_count": book.receipt_count,
        "positions": tuple((item.instrument, str(item.quantity)) for item in book.positions),
        "quote_calls": tuple(graph["quotes"].calls),
        "close_resolution": close.status.value,
        "closable_declared": str(closable.declared_quantity),
        "closable_available": str(closable.available_quantity),
    }


def _start_owner_thread(
    *,
    endpoint: str,
    keys: dict[str, bytes],
    paths: dict[str, str],
    database_url: str,
    authority_module: Any,
):
    from app.services.service_read.approved_target_authority import (
        create_execution_approved_target_resources,
    )

    service_config = parse_service_config(_owner_config(endpoint))
    run_grants = (
        PrincipalGrant(
            _SERVICE_IDENTITY,
            (
                ResourceGrant(
                    _OWNER_INSTANCE,
                    "service.owner_control",
                    _OWNER_SCOPE,
                    _WIRE_SCOPE,
                    frozenset({"owner.reduce"}),
                ),
            ),
        ),
        PrincipalGrant(
            _STRATEGY_IDENTITY,
            (
                ResourceGrant(
                    _OWNER_INSTANCE,
                    "service.order_entry",
                    _STRATEGY_SCOPE,
                    _WIRE_SCOPE,
                    frozenset({"orders.submit"}),
                ),
            ),
        ),
    )
    principal_grants = {_PRINCIPAL: (run_grants[0],), _STRATEGY_IDENTITY.principal_ref: (run_grants[1],)}
    authority = TrustedServiceAuthority(
        identity=_HOST_IDENTITY,
        scope=WireScope(_DOMAIN),
        scope_ref=service_config.scope_ref,
        scope_version="afi-reduction-owner-scope-v1",
        security_ref="afi-reduction-owner-server-curve-v1",
        security_version="curve-key-v1",
        registration_policy_ref=service_config.registration_policy_ref,
        registration_policy_version="afi-reduction-registration-v1",
        service_requirements_ref=service_config.service_requirements_ref,
        service_requirements_version="afi-reduction-requirements-v1",
        curve_public_key=keys["server_public"],
        curve_secret_key=keys["server_secret"],
        principals={
            keys["owner_public"]: _PRINCIPAL,
            keys["strategy_public"]: _STRATEGY_IDENTITY.principal_ref,
        },
        grants=principal_grants,
    )
    commands: queue.Queue[tuple[str, str | None]] = queue.Queue()
    ready: queue.Queue[tuple[str, str | None]] = queue.Queue(maxsize=1)
    results: queue.Queue[tuple[str, Any]] = queue.Queue()
    stop = threading.Event()

    def run() -> None:
        host = None
        resources: dict[str, ComponentResources] = {}
        graph = None
        approved_resource = None
        try:
            execution_values, risk_resource, graph = _paper_graph(paths)
            resources["risk"] = risk_resource

            def resource_provider(component, _instance_id, _options, _scope):
                nonlocal approved_resource
                if component == "risk":
                    return resources["risk"]
                if component != "execution":
                    raise AssertionError("unexpected component")
                if approved_resource is None:
                    monkeypatch_settings = SimpleNamespace(DATABASE_URL=database_url)
                    authority_module.get_settings = lambda: monkeypatch_settings
                    approved_resource = create_execution_approved_target_resources(
                        owner_bindings=(
                            ApprovedTargetOwnerBindingV1(
                                principal_ref=_PRINCIPAL,
                                identity=_SERVICE_IDENTITY,
                                wire_scope=_WIRE_SCOPE,
                                owner_subject=_SUBJECT,
                                expected_scope_ref=_APPROVAL_SCOPE,
                            ),
                        ),
                        protected_scopes=(
                            WireScope(
                                _DOMAIN,
                                account_ref=_ACCOUNT,
                                strategy_ref="afi-unrelated-protected-strategy",
                            ),
                        ),
                    )
                values = dict(execution_values)
                values.update(approved_resource.values)
                return ComponentResources.owned(
                    values,
                    ready=lambda: approved_resource.ready(),
                    close=approved_resource.close,
                )

            host = ServiceHost(
                service_config,
                authority,
                paths["registry"],
                resource_provider,
                service_directory={_OWNER_SERVICE: service_config},
            )
            host.start()
            ready.put(("ready", host.state))
            while not stop.is_set():
                try:
                    command, intent_id = commands.get_nowait()
                except queue.Empty:
                    command = ""
                    intent_id = None
                if command == "snapshot":
                    assert intent_id is not None and graph is not None
                    results.put(("snapshot", _host_snapshot(graph, intent_id)))
                    continue
                if command == "stop":
                    break
                host.serve_once(timeout_ms=20)
        except BaseException as error:
            try:
                ready.put_nowait(("error", getattr(error, "code", type(error).__name__)))
            except queue.Full:
                results.put(("owner_error", getattr(error, "code", type(error).__name__)))
        finally:
            if host is not None and host.state == "started":
                try:
                    host.close()
                except BaseException as error:
                    results.put(("cleanup_error", getattr(error, "code", type(error).__name__)))
            if approved_resource is not None:
                try:
                    approved_resource.close()
                except BaseException as error:
                    results.put(("cleanup_error", getattr(error, "code", type(error).__name__)))
            if graph is not None:
                try:
                    _close_graph(graph)
                except BaseException as error:
                    results.put(("cleanup_error", getattr(error, "code", type(error).__name__)))
            results.put(("closed", "closed"))

    thread = threading.Thread(target=run, name="afi-reduction-service-owner", daemon=True)
    thread.start()
    return thread, ready, commands, results, stop


async def _seed_approved_close_target(factory):

    from app.models.permission import Role, user_roles
    from app.models.strategy import Strategy
    from app.models.strategy_version import StrategyVersion, VersionBranch
    from app.models.user import User
    from app.services.strategy_approval_authority import (
        approve_strategy_order_target,
        publish_strategy_order_approval_policy,
    )

    now_ns = time.time_ns()
    async with factory() as db:
        async with db.begin():
            db.add(
                User(
                    id=_SUBJECT,
                    username="afi-reduction-synthetic-owner",
                    email="afi-reduction-synthetic-owner@example.invalid",
                    hashed_password="synthetic-test-data-only",
                    is_active=True,
                    principal_kind="HUMAN",
                )
            )
            db.add(
                Strategy(
                    id=_STRATEGY,
                    user_id=_SUBJECT,
                    name="AFI reduction synthetic strategy",
                    code="pass",
                    params={},
                )
            )
            version = StrategyVersion(
                id="afi-reduction-version-v1",
                strategy_id=_STRATEGY,
                version_number=7,
                version_name="v7",
                branch="main",
                status="stable",
                tags=["synthetic"],
                code="pass",
                params={},
                is_active=True,
                is_default=False,
                is_current=True,
                created_by=_SUBJECT,
            )
            db.add(version)
            await db.flush()
            db.add(
                VersionBranch(
                    id="afi-reduction-main-branch",
                    strategy_id=_STRATEGY,
                    branch_name="main",
                    version_count=1,
                    last_version_id=version.id,
                    is_default=True,
                    created_by=_SUBJECT,
                )
            )
            await db.execute(
                insert(user_roles),
                [{"user_id": _SUBJECT, "role": Role.TRADE_OPERATOR.value}],
            )

    policy = {
        "schema_id": "afi.strategy_order_approval_policy",
        "schema_version": 1,
        "allowed_instruments": [_INSTRUMENT],
        "allowed_sides": ["SELL"],
        "allowed_position_effects": ["CLOSE"],
        "allowed_order_types": ["MARKET"],
        "allowed_time_in_force": ["FOK"],
        "limits": {
            "max_quantity": "0.25",
            "max_notional": None,
            "min_price": None,
            "max_price": None,
        },
    }
    async with factory() as db:
        policy_row = await publish_strategy_order_approval_policy(
            db,
            owner_subject=_SUBJECT,
            policy_ref="afi-reduction-approval-policy-v1",
            policy=policy,
            published_by_subject=_SUBJECT,
            published_by_principal_ref="afi-human-approver",
            published_by_actor_ref="afi-human-approval-action",
            published_by_delegate_ref=None,
            published_at_ns=now_ns - 1_000_000,
        )
        await db.commit()

    target = {
        "schema_id": "bt_api.approved_order_target",
        "schema_version": 1,
        "target_ref": "afi-reduction-target-v1",
        "target_version": 1,
        "owner_subject": _SUBJECT,
        "principal_ref": _PRINCIPAL,
        "actor_ref": _ACTOR,
        "delegate_ref": _DELEGATE,
        "scope_ref": _APPROVAL_SCOPE,
        "wire_scope": _scope_payload(_WIRE_SCOPE),
        "strategy_version": 7,
        "membership_version": None,
        "membership_sha256": None,
        "instrument": _INSTRUMENT,
        "metadata_version": "afi-reduction-instrument-v1",
        "side": "SELL",
        "position_effect": "CLOSE",
        "order_type": "MARKET",
        "quantity": "0.25",
        "price": None,
        "time_in_force": "FOK",
        "reduce_only": True,
        "deadline_ns": None,
        "limits": {
            "max_quantity": "0.25",
            "max_notional": None,
            "min_price": None,
            "max_price": None,
        },
        "policy_ref": "afi-reduction-approval-policy-v1",
        "policy_version": policy_row.policy_version,
        "policy_sha256": policy_row.policy_sha256,
    }
    async with factory() as db:
        approval = await approve_strategy_order_target(
            db,
            target=target,
            owner_subject=_SUBJECT,
            expected_scope_ref=_APPROVAL_SCOPE,
            target_identity=_APP_IDENTITY,
            target_wire_scope=_WIRE_SCOPE,
            approved_by_subject=_SUBJECT,
            approved_by_principal_ref="afi-human-approver",
            approved_by_actor_ref="afi-human-approval-action",
            approved_by_delegate_ref=None,
            approved_at_ns=now_ns,
            expires_at_ns=now_ns + 600_000_000_000,
        )
        return approval.approval_ref, approval.approval_version, approval.target_sha256


@pytest.mark.asyncio
async def test_http_reduce_reaches_real_paper_risk_owner_and_replay_is_single_dispatch(
    tmp_path, monkeypatch
) -> None:
    from app.api import service_read as service_read_api
    from app.api import strategy_reduction as reduction_api
    from app.db import database as database_module
    from app.db.database import Base
    from app.main import app as afi_app
    from app.models.approved_target_http_operation import ApprovedTargetHttpOperation
    from app.services.service_read import approved_target_authority as target_authority_module
    from app.services.service_read.access import ReadAccess, ServiceReadAccessDirectory
    from app.services.service_read.client import ApprovedTargetSubmitBinding
    from app.utils import security as security_module

    db_path = tmp_path / "afi-reduction-approval.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    engine = create_async_engine(db_url, poolclass=NullPool, connect_args={"timeout": 15})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    approval_ref, approval_version, target_digest = await _seed_approved_close_target(sessions)

    monkeypatch.setattr(
        target_authority_module,
        "get_settings",
        lambda: SimpleNamespace(DATABASE_URL=db_url),
    )
    owner_endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    owner_public, owner_secret = zmq.curve_keypair()
    strategy_public, strategy_secret = zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "owner_public": owner_public,
        "owner_secret": owner_secret,
        "strategy_public": strategy_public,
        "strategy_secret": strategy_secret,
    }
    paths = {
        "execution": str(tmp_path / "afi-reduction-execution.sqlite3"),
        "risk": str(tmp_path / "afi-reduction-risk.sqlite3"),
        "journal": str(tmp_path / "afi-reduction-risk-journal.sqlite3"),
        "registry": str(tmp_path / "afi-reduction-owner-registry.sqlite3"),
    }
    owner_thread, ready, commands, owner_results, owner_stop = _start_owner_thread(
        endpoint=owner_endpoint,
        keys=keys,
        paths=paths,
        database_url=db_url,
        authority_module=target_authority_module,
    )
    strategy_runtime = None
    try:
        state, detail = ready.get(timeout=10)
        assert state == "ready", detail
        assert detail == "started"
        strategy_runtime = ServiceClientRuntime(
            _strategy_client_config(owner_endpoint),
            identity=_STRATEGY_IDENTITY,
            scope_resolver=lambda scope_ref: (
                _WIRE_SCOPE if scope_ref == _STRATEGY_SCOPE else _unexpected_scope()
            ),
            peer_resolver=lambda service_id: (
                _HOST_IDENTITY if service_id == _OWNER_SERVICE else _unexpected_peer()
            ),
            transport_factory=ZmqTransportFactory(
                {
                    "afi-reduction-strategy-curve-v1": ClientCurveKeys(
                        server_public, strategy_public, strategy_secret
                    )
                }
            ),
            requested_operations={"broker.orders": frozenset({"orders.submit"})},
        )
        registered = strategy_runtime.start()
        assert registered.degraded_count == 0
        assert len(registered.bindings) == 1

        class _UnusedReadWorker:
            async def read_account(self, *_args, **_kwargs):
                raise AssertionError("reduction must not use account-read worker")

            async def read_order(self, *_args, **_kwargs):
                raise AssertionError("reduction must not use order-read worker")

            async def read_strategy_health(self, *_args, **_kwargs):
                raise AssertionError("reduction must not use health-read worker")

            async def submit_approved_target(self, *_args, **_kwargs):
                raise AssertionError("reduction uses the exact owner.reduce client profile")

        access = ReadAccess(
            _UnusedReadWorker(),
            allow_approved_target_scope_refs=frozenset({_SELECTOR}),
            approved_target_bindings={
                _SELECTOR: ApprovedTargetSubmitBinding(
                    mount="application.orders",
                    scope_ref=_SELECTOR,
                    account_ref=_ACCOUNT,
                    strategy_ref=_STRATEGY,
                    expected_scope_ref=_APPROVAL_SCOPE,
                    wire_scope=_WIRE_SCOPE,
                )
            },
            application_identity=_APP_IDENTITY,
        )
        service_read_api.configure_service_read(ServiceReadAccessDirectory({_SUBJECT: access}))

        allowlisted_client_config = _reduction_client_config(owner_endpoint)
        profile = {
            "profile_ref": "afi-reduction-profile-v1",
            "subject": _SUBJECT,
            "selector_ref": _SELECTOR,
            "approved_target_scope_ref": _APPROVAL_SCOPE,
            "account_ref": _ACCOUNT,
            "strategy_ref": _STRATEGY,
            "run_id": _RUN,
            "service_id": _OWNER_SERVICE,
            "instance_id": _OWNER_INSTANCE,
            "scope_ref": _OWNER_SCOPE,
            "not_before_utc": time.time() - 30,
            "expires_at_utc": time.time() + 600,
            "wire_scope": _scope_payload(_WIRE_SCOPE),
            "client_identity": {
                "principal_ref": _PRINCIPAL,
                "actor_ref": _ACTOR,
                "delegate_ref": _DELEGATE,
            },
            "peer_identity": {
                "principal_ref": _HOST_IDENTITY.principal_ref,
                "actor_ref": _HOST_IDENTITY.actor_ref,
                "delegate_ref": _HOST_IDENTITY.delegate_ref,
            },
            "client_config": allowlisted_client_config,
            "curve_keys": {
                "afi-reduction-client-curve-v1": {
                    "server_key_z85": server_public.decode("ascii"),
                    "public_key_z85": owner_public.decode("ascii"),
                    "secret_key_z85": owner_secret.decode("ascii"),
                }
            },
        }
        deployment_json = json.dumps(
            {
                "schema_version": 1,
                "deployment_id": "afi-reduction-deployment-v1",
                "deployment_version": "r1",
                "not_before_utc": time.time() - 30,
                "expires_at_utc": time.time() + 600,
                "profiles": [profile],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        monkeypatch.setattr(
            reduction_api,
            "get_settings",
            lambda: SimpleNamespace(
                SERVICE_STRATEGY_REDUCTION_DEPLOYMENT_JSON=SecretStr(deployment_json)
            ),
        )
        monkeypatch.setattr(
            security_module,
            "settings",
            SimpleNamespace(
                JWT_SECRET_KEY="afi-reduction-local-jwt-signing-key-not-a-secret",
                JWT_ALGORITHM="HS256",
            ),
        )

        async def _get_db():
            async with sessions() as db:
                yield db

        afi_app.dependency_overrides[database_module.get_db] = _get_db
        token = jwt.encode(
            {
                "sub": _SUBJECT,
                "username": "afi-reduction-synthetic-owner",
                "exp": time.time() + 300,
            },
            "afi-reduction-local-jwt-signing-key-not-a-secret",
            algorithm="HS256",
        )
        request_json = {
            "scope_ref": _SELECTOR,
            "approval_ref": approval_ref,
            "approval_version": approval_version,
            "target_sha256": target_digest,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "afi-reduction-http-idempotency-v1",
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=afi_app),
            base_url="http://afi-reduction.synthetic.test",
        ) as client:
            first = await client.post(
                "/api/v1/service-orders/approved-targets/reduce",
                json=request_json,
                headers=headers,
            )
            assert first.status_code == 200, first.text
            first_body = first.json()
            assert first_body["operation_kind"] == "owner_strategy_reduction"
            assert first_body["outcome"] == "filled"
            assert first_body["flatness"] == "not_established"
            assert first_body["execution"]["status"] == "FILLED"
            assert first_body["execution"]["stage"] == "EXECUTION"
            assert first_body["execution"]["filled_quantity"] == "0.25"
            assert first_body["execution"]["review_required"] is False

            replay = await client.post(
                "/api/v1/service-orders/approved-targets/reduce",
                json=request_json,
                headers=headers,
            )
            assert replay.status_code == 200, replay.text
            assert replay.json() == first_body

        commands.put(("snapshot", first_body["intent_id"]))
        snapshot_kind, snapshot = owner_results.get(timeout=5)
        assert snapshot_kind == "snapshot"
        assert snapshot["record_state"] == "FILLED"
        assert snapshot["dispatch_attempts"] == 1
        assert snapshot["receipt_state"] == "FILLED"
        assert snapshot["receipt_event_id"]
        assert snapshot["close_resolution"] == "TERMINAL_CLOSE_RESOLVED"
        assert snapshot["positions"] == ((_INSTRUMENT, "0.75"),)
        assert snapshot["closable_declared"] == "0.75"
        assert snapshot["closable_available"] == "0.75"
        assert snapshot["quote_calls"].count(_INSTRUMENT) == 1

        async with sessions() as db:
            mapping = await db.get(ApprovedTargetHttpOperation, first_body["intent_id"])
            assert mapping is not None
            assert mapping.approval_ref == approval_ref
            assert mapping.scope_ref == _APPROVAL_SCOPE
            assert mapping.account_ref == _ACCOUNT
            assert mapping.strategy_ref == _STRATEGY
    finally:
        service_read_api.configure_service_read(None)
        if strategy_runtime is not None:
            strategy_runtime.close()
        owner_stop.set()
        commands.put(("stop", None))
        owner_thread.join(timeout=10)
        assert not owner_thread.is_alive(), "owner thread did not close normally"
        closed = owner_results.get(timeout=5)
        assert closed == ("closed", "closed")
        await engine.dispose()


def _unexpected_scope() -> WireScope:
    raise AssertionError("unconfigured service scope")


def _unexpected_peer() -> WireIdentity:
    raise AssertionError("unconfigured peer identity")

