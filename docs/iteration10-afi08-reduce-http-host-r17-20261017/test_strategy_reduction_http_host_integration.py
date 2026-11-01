"""AFI REDUCE HTTP path through the real SDK owner and Risk ledger.

The provider is an in-process synthetic leaf. This test proves the persisted
AFI approval, HTTP identity/grant, ServiceHost owner.reduce route, Execution
order journal and Risk close reservation compose locally; it proves no venue
connectivity or provider account position.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import hashlib
import json
import os
import queue
import re
import socket
import sqlite3
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import zmq
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_execution import (
    ExecutionAdmissionValidatorRegistry,
    ExecutionBasicAdmissionGate,
    ExecutionProviderValidatorV1,
    ExecutionScope,
    ExecutionState,
    OrderType,
    PositionEffect,
    ProviderObservation,
    Side,
    SqliteExecutionStore,
    TimeInForce,
)
from bt_api_execution.approved_target import (
    ApprovedTargetOwnerBindingV1,
    ApprovedTargetOwnerBindingsV1,
    ProtectedApprovedTargetScopesV1,
)
from bt_api_risk import (
    AccountScope,
    DurableRiskAdmissionAdapter,
    DurableRiskGate,
    IntentAction,
    RiskIntent,
    RiskPolicy,
)
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_client_config, parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_py.service_runtime import (
    ClientCurveKeys,
    ServiceClientRuntime,
    ServiceRuntimeError,
    ZmqTransportFactory,
)

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
_PAPER_POLICY_PRINCIPAL = "afi-reduction-unused-paper-policy"
_PAPER_POLICY_ACTOR = "afi-reduction-unused-paper-policy-actor"
_INSTRUMENT = "BTC-USDT"
_MAX_MESSAGE_BYTES = 65_536

_RUNTIME_RECEIPT_MODULES = (
    "app.main",
    "app.api.router",
    "app.api.strategy_reduction",
    "app.services.service_read.client",
    "app.services.service_read.approved_target_authority",
    "bt_api_execution.strategy_reduction",
    "bt_api_base.service_protocol",
    "bt_api_execution",
    "bt_api_execution.approved_target",
    "bt_api_execution.paper_risk",
    "bt_api_execution.paper_execution_risk",
    "bt_api_execution.strategy_cancel",
    "bt_api_execution.service_component",
    "bt_api_execution.service_order_entry",
    "bt_api_execution.contracts",
    "bt_api_py.service_components",
    "bt_api_py.service_execution_account_books",
    "bt_api_py.service_host",
    "bt_api_py.service_registry",
    "bt_api_py.service_runtime",
    "bt_api_risk",
    "bt_api_risk.core.admission",
    "bt_api_risk.order_admission",
    "bt_api_gateway.account_position_snapshot",
)


def _runtime_module_origin_receipt(owner_thread: threading.Thread) -> dict[str, Any]:
    modules: dict[str, Any] = {}
    for name in _RUNTIME_RECEIPT_MODULES:
        module = sys.modules.get(name)
        filename = getattr(module, "__file__", None) if module is not None else None
        path = Path(filename) if filename else None
        raw = path.read_bytes() if path is not None and path.is_file() else None
        modules[name] = {
            "loaded": module is not None,
            "origin": str(path.resolve()) if path is not None and path.is_file() else None,
            "bytes": len(raw) if raw is not None else None,
            "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
        }
    required = (
        "app.main",
        "app.api.router",
        "app.api.strategy_reduction",
        "bt_api_py.service_components",
        "bt_api_py.service_execution_account_books",
        "bt_api_py.service_host",
        "bt_api_execution.approved_target",
        "bt_api_execution.paper_risk",
        "bt_api_execution.service_order_entry",
    "bt_api_execution.contracts",
        "bt_api_execution.paper_execution_risk",
        "bt_api_risk.core.admission",
        "bt_api_risk.order_admission",
    )
    missing_required = [name for name in required if not modules[name]["loaded"]]
    return {
        "schema": "afi08.reduce.runtime-module-origins.v1",
        "status": "CAPTURED" if not missing_required else "REQUIRED_MODULES_MISSING",
        "python_pid": os.getpid(),
        "python_version": sys.version.split()[0],
        "python_executable": str(Path(sys.executable).resolve()),
        "working_directory": str(Path.cwd().resolve()),
        "test_source": {
            "path": str(Path(__file__).resolve()),
            "bytes": Path(__file__).stat().st_size,
            "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "owner_thread": {
            "name": owner_thread.name,
            "ident": owner_thread.ident,
            "native_id": owner_thread.native_id,
            "same_process": isinstance(owner_thread, threading.Thread),
            "observed_from_thread_ident": threading.get_ident(),
            "is_alive_at_capture": owner_thread.is_alive(),
        },
        "source_manifest_sha256": os.environ.get(
            "AFI08_REDUCE_SOURCE_MANIFEST_SHA256"
        ),
        "sdk_overlay_manifest_sha256": os.environ.get(
            "AFI08_REDUCE_SDK_OVERLAY_MANIFEST_SHA256"
        ),
        "execution_overlay_manifest_sha256": os.environ.get(
            "AFI08_REDUCE_EXECUTION_OVERLAY_MANIFEST_SHA256"
        ),
        "required_modules_missing": missing_required,
        "modules": modules,
    }


def _write_runtime_receipt(filename: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    receipt_dir = os.environ.get("AFI08_REDUCE_RECEIPT_DIR")
    if not receipt_dir:
        return None
    path = Path(receipt_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    return {"path": str(path.resolve()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _safe_startup_error_facts(error: BaseException) -> dict[str, str | None]:
    """Return only finite type/code labels; never inspect exception text or args."""

    error_type = f"{type(error).__module__}.{type(error).__qualname__}"
    if not re.fullmatch(r"[A-Za-z0-9_.]{1,160}", error_type, flags=re.ASCII):
        error_type = "UNSAFE_EXCEPTION_TYPE"
    try:
        code = error.code
    except BaseException:
        code = None
    if (
        type(code) is not str
        or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code, flags=re.ASCII)
    ):
        code = None
    return {"error_type": error_type, "error_code": code}


def _safe_mapping_result_facts(value: Any) -> dict[str, Any]:
    """Project only bounded protocol fields; never serialize reply contents."""

    result_type = f"{type(value).__module__}.{type(value).__qualname__}"
    if not re.fullmatch(r"[A-Za-z0-9_.]{1,160}", result_type, flags=re.ASCII):
        result_type = "UNSAFE_RESULT_TYPE"
    facts: dict[str, Any] = {
        "result_is_mapping": isinstance(value, Mapping),
        "result_type": result_type,
        "ok": None,
        "code": None,
        "reason_code": None,
    }
    if not isinstance(value, Mapping):
        return facts
    try:
        ok = value.get("ok")
        facts["ok"] = ok if type(ok) is bool else None
        code = value.get("code")
        reason_code = value.get("reason_code")
        nested = value.get("result")
        if isinstance(nested, Mapping):
            if code is None:
                code = nested.get("code")
            if reason_code is None:
                reason_code = nested.get("reason_code")
        execution = value.get("execution")
        if isinstance(execution, Mapping) and reason_code is None:
            reason_code = execution.get("reason_code")
    except BaseException:
        return facts
    code_pattern = r"[A-Z][A-Z0-9_]{0,63}"
    if type(code) is str and re.fullmatch(code_pattern, code, flags=re.ASCII):
        facts["code"] = code
    if type(reason_code) is str and re.fullmatch(
        code_pattern, reason_code, flags=re.ASCII
    ):
        facts["reason_code"] = reason_code
    return facts


def close_was_observed(result: dict[str, Any]) -> bool:
    """Accept only an observed close or an explicit not-created resource."""

    if result.get("created") is True:
        return result.get("attempted") is True and result.get("status") == "CLOSED"
    return (
        result.get("created") is False
        and result.get("attempted") is False
        and result.get("status") == "NOT_CREATED"
    )


def test_close_was_observed_covers_ready_and_startup_failure_cleanup() -> None:
    assert close_was_observed(
        {"created": False, "attempted": False, "status": "NOT_CREATED"}
    ) is True
    assert close_was_observed(
        {"created": True, "attempted": True, "status": "CLOSED"}
    ) is True
    assert close_was_observed(
        {"created": True, "attempted": True, "status": "FAILED"}
    ) is False
    assert close_was_observed(
        {"created": True, "attempted": False, "status": "NOT_ATTEMPTED_BY_HOST"}
    ) is False

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
        ExecutionAdmissionValidatorRegistry,
        ExecutionBasicAdmissionGate,
        ExecutionProviderValidatorV1,
        ExecutionScope,
        OrderType,
        PaperMatchingPort,
        PositionEffect,
        Side,
        SqliteExecutionStore,
        TimeInForce,
    )
    from bt_api_execution.paper_execution import (
        PAPER_MODEL_REF,
        PaperInstrumentV1,
        PaperOpeningPositionV1,
        PaperOwnerDomainV1,
    )
    from bt_api_execution.paper_execution_risk import PaperExecutionCloseAuthority
    from bt_api_execution.paper_risk import PaperRiskAdmissionAdapter
    from bt_api_risk import (
        AccountScope,
        DurableRiskAdmissionAdapter,
        DurableRiskGate,
        InstrumentRiskAdmissionMapper,
        InstrumentRiskMetadata,
        InstrumentRiskRegistry,
        RiskPolicy,
    )
    from bt_api_py import bt_api as bt_api_module
    from bt_api_py.service_components import TrustedRiskPolicyBinding
    from bt_api_py.service_risk_order_entry import (
        RiskBtApiProviderContract,
        RiskOrderJournal,
        RiskOrderTarget,
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
        provider_status_mapping=(
            ("cancelled", "canceled"),
            ("expired", "expired"),
            ("filled", "completed"),
            ("open", "accepted"),
            ("partial", "partial"),
            ("rejected", "rejected"),
        ),
        supported_order_types=("LIMIT",),
        supported_time_in_force=("GTC",),
        supported_position_effects=("OPEN",),
        normalizer_schema="bt-api-order-source-provenance-v2",
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
    for name in ("gate", "store", "bt_api"):
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
    from bt_api_execution.approved_target import (
        ApprovedTargetOwnerBindingV1,
        ProtectedApprovedTargetScopesV1,
    )
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
    from app.services.service_read.approved_target_authority import (
        create_execution_approved_target_resources,
    )

    service_config = parse_service_config(_owner_config(endpoint))
    authority, _paper_policy_identity = _build_owner_authority(
        config=service_config,
        server_public=keys["server_public"],
        server_secret=keys["server_secret"],
        owner_public=keys["owner_public"],
        strategy_public=keys["strategy_public"],
        scope_version="afi-reduction-owner-scope-v1",
        registration_policy_version="afi-reduction-registration-v1",
        service_requirements_version="afi-reduction-requirements-v1",
        application_policy_grant=True,
    )
    commands: queue.Queue[tuple[str, str | None]] = queue.Queue()
    ready: queue.Queue[tuple[str, str | None]] = queue.Queue(maxsize=1)
    results: queue.Queue[tuple[str, Any]] = queue.Queue()
    stop = threading.Event()
    cleanup_facts: dict[str, Any] = {
        "schema": "afi08.reduce.owner-thread-cleanup.v1",
        "python_pid": os.getpid(),
        "owner_thread_model": "same-process-thread",
        "owner_thread_name": "afi-reduction-service-owner",
        "owner_thread_ident": None,
        "host_constructed": False,
        "host_started": False,
        "host_state_after_start": None,
        "resource_close_results": {},
        "cleanup_errors": [],
    }
    approved_resource_close_results: list[dict[str, str]] = []

    def run() -> None:
        host = None
        resources: dict[str, ComponentResources] = {}
        graph = None
        approved_resource = None
        cleanup_facts["owner_thread_ident"] = threading.get_ident()

        def close_fact(name: str, resource: Any, close: Any) -> None:
            if resource is None:
                cleanup_facts["resource_close_results"][name] = {
                    "created": False,
                    "attempted": False,
                    "status": "NOT_CREATED",
                }
                return
            result: dict[str, Any] = {"created": True, "attempted": True}
            try:
                close()
            except BaseException as error:  # cleanup receipts contain type labels only
                error_type = f"{type(error).__module__}.{type(error).__qualname__}"
                result.update({"status": "FAILED", "error_type": error_type})
                cleanup_facts["cleanup_errors"].append({"resource": name, "error_type": error_type})
                results.put(("cleanup_error", error_type))
            else:
                result["status"] = "CLOSED"
            cleanup_facts["resource_close_results"][name] = result

        try:
            execution_values, risk_resource, graph = _paper_graph(paths)
            resources["risk"] = risk_resource
            cleanup_facts["paper_graph_created"] = graph is not None

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
                        protected_scopes=(_WIRE_SCOPE,),
                    )
                    approved_authority = approved_resource.values["approved_target_authority"]
                    assert approved_authority.requires_approval(_WIRE_SCOPE) is True
                    assert approved_authority.requires_approval(
                        WireScope(
                            _DOMAIN,
                            account_ref=_ACCOUNT,
                            strategy_ref="afi-unrelated-protected-strategy",
                        )
                    ) is False

                def close_approved_resource() -> None:
                    try:
                        approved_resource.close()
                    except BaseException as error:
                        result = {
                            "status": "FAILED",
                            "error_type": f"{type(error).__module__}.{type(error).__qualname__}",
                        }
                        approved_resource_close_results.append(result)
                        raise
                    else:
                        approved_resource_close_results.append({"status": "CLOSED"})

                values = dict(execution_values)
                values.update(approved_resource.values)
                return ComponentResources.owned(
                    values,
                    ready=lambda: approved_resource.ready(),
                    close=close_approved_resource,
                )

            host = ServiceHost(
                service_config,
                authority,
                paths["registry"],
                resource_provider,
                service_directory={_OWNER_SERVICE: service_config},
            )
            cleanup_facts["host_constructed"] = True
            host.start()
            cleanup_facts["host_started"] = True
            cleanup_facts["host_state_after_start"] = host.state
            cleanup_facts["approved_target_resource_created"] = approved_resource is not None
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
            cleanup_facts["owner_loop_error_type"] = f"{type(error).__module__}.{type(error).__qualname__}"
            try:
                ready.put_nowait(("error", getattr(error, "code", type(error).__name__)))
            except queue.Full:
                results.put(("owner_error", getattr(error, "code", type(error).__name__)))
        finally:
            try:
                cleanup_facts["host_state_before_close"] = host.state if host is not None else None
            except BaseException:
                cleanup_facts["host_state_before_close"] = "UNAVAILABLE"
            close_fact(
                "service_host",
                host,
                host.close if host is not None else lambda: None,
            )
            try:
                cleanup_facts["host_state_after_close"] = host.state if host is not None else None
            except BaseException:
                cleanup_facts["host_state_after_close"] = "UNAVAILABLE"
            cleanup_facts["resource_close_results"]["approved_target_resource"] = (
                {
                    "created": False,
                    "attempted": False,
                    "status": "NOT_CREATED",
                }
                if approved_resource is None
                else {
                    "created": True,
                    "attempted": bool(approved_resource_close_results),
                    "status": (
                        approved_resource_close_results[-1]["status"]
                        if approved_resource_close_results
                        else "NOT_ATTEMPTED_BY_HOST"
                    ),
                    "close_attempt_count": len(approved_resource_close_results),
                    "error_type": (
                        approved_resource_close_results[-1].get("error_type")
                        if approved_resource_close_results
                        else None
                    ),
                }
            )
            close_fact(
                "paper_graph",
                graph,
                (lambda: _close_graph(graph)) if graph is not None else lambda: None,
            )
            cleanup_facts["owner_thread_cleanup_completed"] = True
            results.put(("closed", "closed"))

    thread = threading.Thread(target=run, name="afi-reduction-service-owner", daemon=True)
    thread.start()
    return thread, ready, commands, results, stop, cleanup_facts


async def _seed_approved_close_target(factory):
    from sqlalchemy import insert

    from app.models.permission import Role, user_roles
    from app.models.strategy import Strategy
    from app.models.strategy_target_approval import StrategyTargetApproval
    from app.models.strategy_version import StrategyVersion, VersionBranch
    from app.models.user import User
    from app.services.strategy_approval_authority import (
        approve_strategy_order_target,
        publish_strategy_order_approval_policy,
    )
    from app.services.strategy_target_approvals import canonical_target_sha256

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
    from app.api import strategy_reduction as reduction_api
    from app.db import database as database_module
    from app.db.database import Base
    from app.models.approved_target_http_operation import ApprovedTargetHttpOperation
    from app.services.service_read.access import ReadAccess, ServiceReadAccessDirectory
    from app.services.service_read.client import ApprovedTargetSubmitBinding
    from app.services.service_read import approved_target_authority as target_authority_module
    from app.api import service_read as service_read_api
    from app.utils import security as security_module
    from app.main import app as afi_app

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
    owner_thread, ready, commands, owner_results, owner_stop, cleanup_facts = _start_owner_thread(
        endpoint=owner_endpoint,
        keys=keys,
        paths=paths,
        database_url=db_url,
        authority_module=target_authority_module,
    )
    strategy_runtime = None
    client_cleanup_facts: dict[str, Any] = {
        "strategy_runtime_close": {
            "created": False,
            "attempted": False,
            "status": "NOT_CREATED",
        },
        "service_read_reset": {"status": "NOT_ATTEMPTED"},
        "test_database_engine_dispose": {"status": "NOT_ATTEMPTED"},
    }
    primary_test_error: BaseException | None = None
    try:
        state, detail = ready.get(timeout=10)
        assert state == "ready", detail
        assert detail == "started"
        owner_client_identity = WireIdentity(WireRole.SERVICE, _PRINCIPAL, _ACTOR, _DELEGATE)
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
            run_id=_RUN,
            requested_operations={"broker.orders": frozenset({"orders.submit"})},
        )
        client_cleanup_facts["strategy_runtime_close"] = {
            "created": True,
            "attempted": False,
            "status": "NOT_ATTEMPTED",
        }
        registered = strategy_runtime.start()
        assert registered.degraded_count == 0
        assert len(registered.bindings) == 1
        assert registered.bindings[0].scope == _WIRE_SCOPE
        assert registered.bindings[0].scope.run_id == _RUN

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

        host_scope = _TEMPLATE_SCOPE
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
                JWT_EXPIRE_MINUTES=5,
            ),
        )

        async def _get_db():
            async with sessions() as db:
                yield db

        afi_app.dependency_overrides[database_module.get_db] = _get_db
        token = security_module.create_access_token(
            {
                "sub": _SUBJECT,
                "username": "afi-reduction-synthetic-owner",
            }
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
        startup_events: list[dict[str, Any]] = []
        owner_call_events: list[dict[str, Any]] = []
        owner_rpc_events: list[dict[str, Any]] = []
        owner_start_facts: dict[str, Any] = {
            "schema": "afi08.reduce.owner-client-call-diagnostic.v1",
            "start_call_count": 0,
            "events": startup_events,
            "owner_call_events": owner_call_events,
            "owner_rpc_events": owner_rpc_events,
        }
        expected_owner_operations = {
            "upstream.owner_control": frozenset({"owner.reduce"})
        }
        expected_owner_binding = allowlisted_client_config["clients"]["execution"][
            "settings"
        ]["bindings"][0]
        expected_owner_transport_ref = expected_owner_binding["transport_ref"]
        original_runtime_start = ServiceClientRuntime.start
        original_runtime_call = ServiceClientRuntime.call
        original_runtime_rpc = ServiceClientRuntime._rpc
        active_start_runtime_ids: set[int] = set()
        reduction_runtime_ids: set[int] = set()
        capture_one_start = [True]
        capture_one_owner_call = [True]
        capture_one_owner_rpc = [True]

        def is_reduction_runtime(runtime: Any) -> bool:
            identity = getattr(runtime, "identity", None)
            return (
                type(identity) is WireIdentity
                and identity.role is WireRole.SERVICE
                and getattr(runtime, "_requested_operations", None)
                == expected_owner_operations
            )

        def observed_rpc(
            runtime: ServiceClientRuntime,
            service_id: str,
            transport_ref: str,
            scope: WireScope,
            operation: str,
            payload: Any,
            *args: Any,
            **kwargs: Any,
        ):
            is_startup_control = (
                id(runtime) in active_start_runtime_ids
                and operation
                in {
                    "service.discover",
                    "service.register",
                    "service.renew",
                    "service.unregister",
                }
            )
            is_owner_reduce = (
                id(runtime) in reduction_runtime_ids
                and operation == "owner.reduce"
                and capture_one_owner_rpc[0]
            )
            if not is_startup_control and not is_owner_reduce:
                return original_runtime_rpc(
                    runtime,
                    service_id,
                    transport_ref,
                    scope,
                    operation,
                    payload,
                    *args,
                    **kwargs,
                )
            if is_owner_reduce:
                capture_one_owner_rpc[0] = False
            event: dict[str, Any] = {
                "phase": "owner.reduce.rpc" if is_owner_reduce else operation,
                "operation": "owner.reduce" if is_owner_reduce else operation,
                "service_id_matches_expected": service_id == _OWNER_SERVICE,
                "transport_ref_matches_expected": (
                    transport_ref == expected_owner_transport_ref
                ),
                "scope_matches_expected": scope == _WIRE_SCOPE,
                "outcome": "PENDING",
            }
            destination = owner_rpc_events if is_owner_reduce else startup_events
            try:
                result = original_runtime_rpc(
                    runtime,
                    service_id,
                    transport_ref,
                    scope,
                    operation,
                    payload,
                    *args,
                    **kwargs,
                )
            except BaseException as error:
                event["outcome"] = "EXCEPTION"
                event.update(_safe_startup_error_facts(error))
                destination.append(event)
                raise
            event["outcome"] = "REPLIED"
            event.update(_safe_mapping_result_facts(result))
            if operation == "service.discover":
                capabilities = (
                    result.get("capabilities")
                    if isinstance(result, Mapping)
                    else None
                )
                owner_caps = (
                    [
                        item
                        for item in capabilities
                        if isinstance(item, Mapping)
                        and item.get("instance_id") == _OWNER_INSTANCE
                        and item.get("port") == "service.owner_control"
                    ]
                    if type(capabilities) in (list, tuple)
                    else []
                )
                known_ops = {
                    "owner.session",
                    "owner.stop_new",
                    "owner.cancel",
                    "owner.reduce",
                }
                advertised_ops = {
                    operation_name
                    for item in owner_caps
                    for operation_name in (
                        item.get("operations")
                        if type(item.get("operations")) in (list, tuple)
                        else ()
                    )
                    if type(operation_name) is str and operation_name in known_ops
                }
                event.update(
                    {
                        "discovery_protocol_v2": (
                            isinstance(result, Mapping)
                            and result.get("protocol_version") == 2
                        ),
                        "discovery_service_id_matches": (
                            isinstance(result, Mapping)
                            and result.get("service_id") == _OWNER_SERVICE
                        ),
                        "discovery_ready": (
                            isinstance(result, Mapping)
                            and result.get("ready") is True
                        ),
                        "owner_control_capability_count": min(len(owner_caps), 9),
                        "owner_reduce_advertised": "owner.reduce" in advertised_ops,
                        "owner_control_operations": sorted(advertised_ops),
                    }
                )
            elif operation == "service.register":
                event["registration_reply_received"] = isinstance(result, Mapping)
            destination.append(event)
            return result

        def observed_call(
            runtime: ServiceClientRuntime,
            mount: str,
            operation: str,
            arguments: Any,
            *args: Any,
            **kwargs: Any,
        ):
            account_ref = kwargs.get("account_ref")
            scope_ref = kwargs.get("scope_ref")
            if (
                id(runtime) not in reduction_runtime_ids
                or not capture_one_owner_call[0]
            ):
                return original_runtime_call(
                    runtime, mount, operation, arguments, *args, **kwargs
                )
            capture_one_owner_call[0] = False
            event: dict[str, Any] = {
                "phase": "runtime.call",
                "operation": "owner.reduce"
                if operation == "owner.reduce"
                else "UNEXPECTED",
                "mount_matches_expected": mount == "upstream.owner_control",
                "operation_matches_expected": operation == "owner.reduce",
                "account_ref_matches_expected": (account_ref == _ACCOUNT),
                "scope_ref_matches_expected": (scope_ref == _OWNER_SCOPE),
                "outcome": "PENDING",
            }
            try:
                result = original_runtime_call(
                    runtime, mount, operation, arguments, *args, **kwargs
                )
            except BaseException as error:
                event["outcome"] = "EXCEPTION"
                event.update(_safe_startup_error_facts(error))
                owner_call_events.append(event)
                raise
            event["outcome"] = "RETURNED"
            event.update(_safe_mapping_result_facts(result))
            owner_call_events.append(event)
            return result

        def observed_start(runtime: ServiceClientRuntime):
            if not capture_one_start[0] or not is_reduction_runtime(runtime):
                return original_runtime_start(runtime)
            capture_one_start[0] = False
            owner_start_facts["start_call_count"] += 1
            reduction_runtime_ids.add(id(runtime))
            start_event: dict[str, Any] = {
                "phase": "runtime.start",
                "requested_owner_reduce_exactly": True,
                "identity_role_service": True,
                "outcome": "PENDING",
            }
            startup_events.append(start_event)
            active_start_runtime_ids.add(id(runtime))
            try:
                summary = original_runtime_start(runtime)
            except BaseException as error:
                start_event["outcome"] = "EXCEPTION"
                start_event.update(_safe_startup_error_facts(error))
                try:
                    runtime_state = runtime.state
                except BaseException:
                    runtime_state = None
                start_event["runtime_state_after"] = (
                    runtime_state
                    if type(runtime_state) is str
                    and runtime_state in {
                        "new",
                        "starting",
                        "registered",
                        "closing",
                        "closed",
                    }
                    else "UNAVAILABLE"
                )
                try:
                    start_event["registered_binding_count"] = len(runtime.bindings)
                    start_event["degraded_count"] = runtime.degraded_count
                except BaseException:
                    start_event["post_failure_runtime_counts_available"] = False
                raise
            else:
                start_event["outcome"] = "RETURNED"
                try:
                    runtime_state = runtime.state
                except BaseException:
                    runtime_state = None
                start_event["runtime_state_after"] = (
                    runtime_state
                    if type(runtime_state) is str
                    and runtime_state in {
                        "new",
                        "starting",
                        "registered",
                        "closing",
                        "closed",
                    }
                    else "UNAVAILABLE"
                )
                start_event["registered_binding_count"] = len(summary.bindings)
                start_event["degraded_count"] = summary.degraded_count
                return summary
            finally:
                active_start_runtime_ids.discard(id(runtime))

        monkeypatch.setattr(ServiceClientRuntime, "_rpc", observed_rpc)
        monkeypatch.setattr(ServiceClientRuntime, "call", observed_call)
        monkeypatch.setattr(ServiceClientRuntime, "start", observed_start)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=afi_app),
            base_url="http://afi-reduction.synthetic.test",
        ) as client:
            try:
                first = await client.post(
                    "/api/v1/service-orders/approved-targets/reduce",
                    json=request_json,
                    headers=headers,
                )
            finally:
                first_status = (
                    first.status_code
                    if "first" in locals() and type(first.status_code) is int
                    else None
                )
                body_code = None
                if first_status is not None:
                    try:
                        body = first.json()
                        candidate_code = body.get("code") if isinstance(body, Mapping) else None
                        if type(candidate_code) is str and re.fullmatch(
                            r"[A-Z][A-Z0-9_]{0,63}", candidate_code, flags=re.ASCII
                        ):
                            body_code = candidate_code
                    except BaseException:
                        body_code = None
                owner_start_facts["http_status"] = first_status
                owner_start_facts["http_error_code"] = body_code
                try:
                    _write_runtime_receipt(
                        "reduction-owner-call-diagnostic.json", owner_start_facts
                    )
                except BaseException as error:
                    owner_start_facts["diagnostic_receipt_write_error_type"] = (
                        _safe_startup_error_facts(error)["error_type"]
                    )
                monkeypatch.setattr(ServiceClientRuntime, "_rpc", original_runtime_rpc)
                monkeypatch.setattr(ServiceClientRuntime, "call", original_runtime_call)
                monkeypatch.setattr(ServiceClientRuntime, "start", original_runtime_start)
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
            mapping = await db.scalar(
                select(ApprovedTargetHttpOperation).where(
                    ApprovedTargetHttpOperation.intent_id == first_body["intent_id"]
                )
            )
            assert mapping is not None
            assert mapping.intent_id == first_body["intent_id"]
            assert mapping.approval_ref == approval_ref
            assert mapping.scope_ref == _APPROVAL_SCOPE
            assert mapping.account_ref == _ACCOUNT
            assert mapping.strategy_ref == _STRATEGY
    except BaseException as error:
        primary_test_error = error
        cleanup_facts["primary_test_error_type"] = (
            f"{type(error).__module__}.{type(error).__qualname__}"
        )
        raise
    finally:
        try:
            service_read_api.configure_service_read(None)
        except BaseException as error:
            client_cleanup_facts["service_read_reset"] = {
                "status": "FAILED",
                "error_type": f"{type(error).__module__}.{type(error).__qualname__}",
            }
        else:
            client_cleanup_facts["service_read_reset"] = {"status": "RESET"}
        if strategy_runtime is not None:
            client_cleanup_facts["strategy_runtime_close"] = {
                "created": True,
                "attempted": True,
                "status": "CLOSING",
            }
            try:
                strategy_runtime.close()
            except BaseException as error:
                client_cleanup_facts["strategy_runtime_close"] = {
                    "created": True,
                    "attempted": True,
                    "status": "FAILED",
                    "error_type": f"{type(error).__module__}.{type(error).__qualname__}",
                }
            else:
                client_cleanup_facts["strategy_runtime_close"] = {
                    "created": True,
                    "attempted": True,
                    "status": "CLOSED",
                }
        owner_stop.set()
        commands.put(("stop", None))
        owner_thread.join(timeout=10)
        cleanup_facts.update(
            {
                "owner_thread_started": True,
                "owner_thread_finished": not owner_thread.is_alive(),
                "owner_thread_alive_after_join": owner_thread.is_alive(),
                "owner_thread_ident_after_join": owner_thread.ident,
                "join_timeout_seconds": 10,
                "stop_requested": owner_stop.is_set(),
                "client_cleanup": client_cleanup_facts,
            }
        )
        observed_messages: list[dict[str, str]] = []
        closed = None
        message_deadline = time.monotonic() + 5
        while time.monotonic() < message_deadline:
            try:
                message = owner_results.get(timeout=max(0.001, message_deadline - time.monotonic()))
            except queue.Empty:
                break
            if message == ("closed", "closed"):
                closed = message
                break
            kind, value = message
            observed_messages.append(
                {
                    "kind": str(kind),
                    "value_type": f"{type(value).__module__}.{type(value).__qualname__}",
                }
            )
        cleanup_facts["owner_thread_messages_before_close"] = observed_messages
        cleanup_facts["owner_closed_message_received"] = closed == ("closed", "closed")
        try:
            await engine.dispose()
        except BaseException as error:
            client_cleanup_facts["test_database_engine_dispose"] = {
                "status": "FAILED",
                "error_type": f"{type(error).__module__}.{type(error).__qualname__}",
            }
        else:
            client_cleanup_facts["test_database_engine_dispose"] = {"status": "DISPOSED"}
        try:
            runtime_receipt = _runtime_module_origin_receipt(owner_thread)
            runtime_receipt_ref = _write_runtime_receipt("module-origins.json", runtime_receipt)
        except BaseException as error:
            runtime_receipt = {
                "status": "FAILED",
                "error_type": f"{type(error).__module__}.{type(error).__qualname__}",
            }
            runtime_receipt_ref = None
            cleanup_facts["module_origin_receipt_error_type"] = runtime_receipt["error_type"]
            if primary_test_error is None:
                raise
        cleanup_facts["module_origin_receipt"] = runtime_receipt_ref
        try:
            cleanup_receipt = _write_runtime_receipt(
                "cleanup-receipt.json",
                {
                    "schema": "afi08.reduce.test-cleanup-receipt.v1",
                    "status": (
                        "CLEANUP_OBSERVED"
                        if cleanup_facts.get("owner_thread_cleanup_completed")
                        and cleanup_facts.get("owner_thread_finished")
                        and cleanup_facts.get("owner_closed_message_received")
                        and not cleanup_facts.get("cleanup_errors")
                        and cleanup_facts.get("resource_close_results", {}).get(
                            "service_host", {}
                        ).get("status")
                        == "CLOSED"
                        and close_was_observed(
                            cleanup_facts.get("resource_close_results", {}).get(
                                "approved_target_resource", {}
                            )
                        )
                        and cleanup_facts.get("resource_close_results", {}).get(
                            "paper_graph", {}
                        ).get("status")
                        == "CLOSED"
                        and client_cleanup_facts.get("service_read_reset", {}).get("status")
                        == "RESET"
                        and close_was_observed(
                            client_cleanup_facts.get("strategy_runtime_close", {})
                        )
                        and client_cleanup_facts.get(
                            "test_database_engine_dispose", {}
                        ).get("status")
                        == "DISPOSED"
                        and runtime_receipt.get("status") == "CAPTURED"
                        and runtime_receipt.get("owner_thread", {}).get("same_process") is True
                        and runtime_receipt.get("owner_thread", {}).get("ident")
                        == cleanup_facts.get("owner_thread_ident")
                        else "CLEANUP_INCOMPLETE_OR_FAILED"
                    ),
                    "owner": cleanup_facts,
                    "receipt_file_refs": {"module_origins": runtime_receipt_ref},
                },
            )
        except BaseException as error:
            cleanup_receipt = None
            cleanup_facts["cleanup_receipt_error_type"] = (
                f"{type(error).__module__}.{type(error).__qualname__}"
            )
            if primary_test_error is None:
                raise
        cleanup_facts["cleanup_receipt_ref"] = cleanup_receipt
        if os.environ.get("AFI08_REDUCE_REQUIRE_RECEIPTS") == "1":
            if primary_test_error is None:
                assert runtime_receipt_ref is not None, "module-origin receipt was not written"
                assert cleanup_receipt is not None, "cleanup receipt was not written"
        if primary_test_error is None:
            assert not owner_thread.is_alive(), "owner thread did not close normally"
            assert closed == ("closed", "closed"), cleanup_facts
            assert not cleanup_facts.get("cleanup_errors"), cleanup_facts
            assert runtime_receipt["status"] == "CAPTURED", runtime_receipt
            assert runtime_receipt["owner_thread"]["same_process"] is True
            assert runtime_receipt["owner_thread"]["ident"] == cleanup_facts["owner_thread_ident"]
            assert cleanup_facts["owner_thread_ident"] == owner_thread.ident
            assert cleanup_facts["resource_close_results"]["service_host"]["status"] == "CLOSED"
            assert close_was_observed(cleanup_facts["resource_close_results"]["approved_target_resource"])
            assert cleanup_facts["resource_close_results"]["paper_graph"]["status"] == "CLOSED"
            assert client_cleanup_facts["service_read_reset"]["status"] == "RESET"
            assert close_was_observed(client_cleanup_facts["strategy_runtime_close"])
            assert client_cleanup_facts["test_database_engine_dispose"]["status"] == "DISPOSED"


def _unexpected_scope() -> WireScope:
    raise AssertionError("unconfigured service scope")


def _unexpected_peer() -> WireIdentity:
    raise AssertionError("unconfigured peer identity")


def _build_owner_authority(
    *,
    config,
    server_public: bytes,
    server_secret: bytes,
    owner_public: bytes,
    strategy_public: bytes,
    scope_version: str,
    registration_policy_version: str,
    service_requirements_version: str,
    application_policy_grant: bool,
):
    """Use one exact grant composition for both listener and no-listener paths."""

    owner_grant = ResourceGrant(
        _OWNER_INSTANCE,
        "service.owner_control",
        _OWNER_SCOPE,
        _WIRE_SCOPE,
        frozenset({"owner.reduce"}),
    )
    strategy_grant = ResourceGrant(
        _OWNER_INSTANCE,
        "service.order_entry",
        _STRATEGY_SCOPE,
        _TEMPLATE_SCOPE,
        frozenset({"orders.submit"}),
    )
    paper_policy_identity = WireIdentity(
        WireRole.APPLICATION_CLIENT,
        _PAPER_POLICY_PRINCIPAL,
        _PAPER_POLICY_ACTOR,
    )
    paper_policy_grant = ResourceGrant(
        _OWNER_INSTANCE,
        "service.order_entry",
        _STRATEGY_SCOPE,
        _TEMPLATE_SCOPE,
        frozenset({"orders.submit"}),
    )
    paper_policy_public, _paper_policy_secret = zmq.curve_keypair()
    principal_grants = {
        _PRINCIPAL: (PrincipalGrant(_SERVICE_IDENTITY, (owner_grant,)),),
        _STRATEGY_IDENTITY.principal_ref: (
            PrincipalGrant(_STRATEGY_IDENTITY, (strategy_grant,)),
        ),
        _PAPER_POLICY_PRINCIPAL: (
            (PrincipalGrant(paper_policy_identity, (paper_policy_grant,)),)
            if application_policy_grant
            else ()
        ),
    }
    principals = {
        owner_public: _PRINCIPAL,
        strategy_public: _STRATEGY_IDENTITY.principal_ref,
        paper_policy_public: _PAPER_POLICY_PRINCIPAL,
    }
    authority = TrustedServiceAuthority(
        identity=_HOST_IDENTITY,
        scope=WireScope(_DOMAIN),
        scope_ref=config.scope_ref,
        scope_version=scope_version,
        security_ref="afi-reduction-owner-server-curve-v1",
        security_version="curve-key-v1",
        registration_policy_ref=config.registration_policy_ref,
        registration_policy_version=registration_policy_version,
        service_requirements_ref=config.service_requirements_ref,
        service_requirements_version=service_requirements_version,
        curve_public_key=server_public,
        curve_secret_key=server_secret,
        principals=principals,
        grants=principal_grants,
    )
    return authority, paper_policy_identity


def test_paper_risk_graph_builds_and_closes_without_host(tmp_path):
    """Exercise the full trusted Paper/Risk graph before any Host is created."""
    from bt_api_execution.paper_risk import PaperRiskAdmissionAdapter
    from bt_api_execution.paper_execution import PaperOwnerDomainV1
    from bt_api_execution.service_order_entry import ExecutionOrderEntryService
    from bt_api_py import bt_api as bt_api_module
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_risk_order_entry import RiskOrderEntryService

    original_plugin_loader = bt_api_module._ensure_plugins_loaded

    paths = {
        "execution": str(tmp_path / "paper-graph-execution.sqlite3"),
        "risk": str(tmp_path / "paper-graph-risk.sqlite3"),
        "journal": str(tmp_path / "paper-graph-journal.sqlite3"),
    }
    graph = None
    primary_error = None
    try:
        execution_values, risk_resource, graph = _paper_graph(paths)
        paper_gate = execution_values["admission"]["order_gate"]
        assert type(paper_gate) is PaperRiskAdmissionAdapter
        assert paper_gate.is_bound_to(graph["gate"]) is True
        assert paper_gate.is_bound_to_composition(
            graph["gate"],
            execution_values["paper_owner_domain"],
            execution_values["dispatch"],
            store=execution_values["store"],
            execution_scope=graph["scope"],
        ) is True
        assert type(risk_resource) is ComponentResources
        assert risk_resource.ready() is True
        assert risk_resource.values["gate"] is graph["gate"]
        assert risk_resource.values["journal"] is graph["journal"]
        contract = risk_resource.values["provider_contracts"][_TEMPLATE_SCOPE]
        assert contract.provider_status_mapping == (
            ("cancelled", "canceled"),
            ("expired", "expired"),
            ("filled", "completed"),
            ("open", "accepted"),
            ("partial", "partial"),
            ("rejected", "rejected"),
        )
        # The Risk account-owner contract is independent of E's Paper
        # MARKET/FOK validator and must retain its own LIMIT/GTC semantics.
        assert contract.supported_order_types == ("LIMIT",)
        assert contract.supported_time_in_force == ("GTC",)
        assert contract.supported_position_effects == ("OPEN",)
        assert graph["gate"].get_strategy_allocation(
            graph["risk_scope"], _STRATEGY
        ).strategy_id == _STRATEGY
        assert type(execution_values["paper_owner_domain"]) is PaperOwnerDomainV1
        e_owner = ExecutionOrderEntryService(
            execution_values["store"],
            execution_values["targets"],
            execution_values["dispatch"],
            admission_gate=paper_gate,
            basic_admission_gate=execution_values["admission"]["basic_admission_gate"],
            paper_owner_domain=execution_values["paper_owner_domain"],
        )
        assert "orders.submit" in e_owner.supported_operations
        risk_owner = RiskOrderEntryService(
            graph["bt_api"],
            risk_resource.values["targets"],
            risk_resource.values["admission"],
            graph["journal"],
            graph["gate"],
            risk_resource.values["provider_contracts"],
        )
        assert type(risk_owner) is RiskOrderEntryService
        assert risk_owner.ready is True
        assert graph["quotes"].calls == []
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            if graph is not None:
                _close_graph(graph)
        except BaseException as cleanup_error:
            if primary_error is None:
                raise
            primary_error.add_note(
                f"Paper/Risk graph cleanup also failed: {type(cleanup_error).__name__}"
            )
        finally:
            bt_api_module._ensure_plugins_loaded = original_plugin_loader


@pytest.mark.asyncio
async def test_prepared_paper_owner_uses_exact_application_policy_grant_without_starting_host(
    tmp_path, monkeypatch
) -> None:
    """Build the real Paper owner and bind both grants without opening a listener."""

    from app.db.database import Base
    from app.services.service_read import approved_target_authority as authority_module
    from app.services.service_read.approved_target_authority import (
        create_execution_approved_target_resources,
    )
    from bt_api_execution.approved_target import ApprovedTargetOwnerBindingV1
    from bt_api_py.service_components import (
        ComponentResources,
        build_component,
        component_specs,
        validate_components,
    )
    from bt_api_py.service_host import ServiceHost, ServiceHostError, TrustedServiceAuthority

    app_policy_identity = WireIdentity(
        WireRole.APPLICATION_CLIENT,
        _PAPER_POLICY_PRINCIPAL,
        _PAPER_POLICY_ACTOR,
    )
    database_path = tmp_path / "afi-reduction-policy-binding.sqlite3"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    engine = create_async_engine(database_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(
        authority_module,
        "get_settings",
        lambda: SimpleNamespace(DATABASE_URL=database_url),
    )

    def construct_without_listener() -> None:
        from bt_api_py import bt_api as bt_api_module

        original_plugin_loader = bt_api_module._ensure_plugins_loaded
        graph = None
        component = None
        approved_resource = None
        resources = None
        resource_passed_to_builder = False
        try:
            execution_values, _risk_resource, graph = _paper_graph(
                {
                    "execution": str(tmp_path / "paper-owner-execution.sqlite3"),
                    "risk": str(tmp_path / "paper-owner-risk.sqlite3"),
                    "journal": str(tmp_path / "paper-owner-journal.sqlite3"),
                }
            )
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
                        strategy_ref="afi-reduction-protected-strategy",
                    ),
                ),
            )

            config = parse_service_config(_owner_config("tcp://127.0.0.1:1"))
            prepared = validate_components(component_specs(config.components))
            owner_prepared = next(
                item
                for item in prepared
                if item.spec.component == "execution"
                and item.spec.instance_id == _OWNER_INSTANCE
            )
            resources = ComponentResources.owned(
                {**execution_values, **approved_resource.values},
                ready=approved_resource.ready,
                close=approved_resource.close,
            )

            def resource_provider(component_name, instance_id, _options, _scope):
                assert (component_name, instance_id) == ("execution", _OWNER_INSTANCE)
                return resources

            authority_public, authority_secret = zmq.curve_keypair()
            owner_public, _owner_secret = zmq.curve_keypair()
            strategy_public, _strategy_secret = zmq.curve_keypair()
            def make_authority(*, application_policy_grant: bool) -> TrustedServiceAuthority:
                authority, _policy_identity = _build_owner_authority(
                    config=config,
                    server_public=authority_public,
                    server_secret=authority_secret,
                    owner_public=owner_public,
                    strategy_public=strategy_public,
                    scope_version="afi-reduction-nohost-scope-v1",
                    registration_policy_version="afi-reduction-nohost-registration-v1",
                    service_requirements_version="afi-reduction-nohost-requirements-v1",
                    application_policy_grant=application_policy_grant,
                )
                return authority

            authority_without_policy = make_authority(application_policy_grant=False)
            host_without_policy = ServiceHost(
                config,
                authority_without_policy,
                tmp_path / "unused-service-registry-missing-policy.sqlite3",
                resource_provider,
                service_directory={_OWNER_SERVICE: config},
            )
            with pytest.raises(ServiceHostError) as failure:
                host_without_policy._paper_owner_write_policies(owner_prepared, resources)
            assert failure.value.code == "PAPER_OWNER_SUBMIT_GRANT_INVALID"
            assert host_without_policy.state == "new"
            assert host_without_policy.endpoint is None

            authority = make_authority(application_policy_grant=True)
            host = ServiceHost(
                config,
                authority,
                tmp_path / "unused-service-registry-with-policy.sqlite3",
                resource_provider,
                service_directory={_OWNER_SERVICE: config},
            )
            resource_passed_to_builder = True
            component = build_component(
                owner_prepared,
                scope=authority.scope,
                resource_provider=resource_provider,
                service_identity=authority.identity,
            )
            policy = host._paper_owner_write_policies(owner_prepared, resources)
            assert len(policy) == 1
            assert policy[0].identity == app_policy_identity
            assert policy[0].scope_ref == _STRATEGY_SCOPE
            assert policy[0].scope == _TEMPLATE_SCOPE
            assert component.instance_id == _OWNER_INSTANCE
            assert "owner.reduce" in next(
                capability.operations
                for capability in component.capabilities
                if capability.port == "service.owner_control"
            )
            assert host.state == "new"
            assert host.endpoint is None
        finally:
            try:
                if component is not None:
                    component.close()
                elif approved_resource is not None and not resource_passed_to_builder:
                    approved_resource.close()
            finally:
                if graph is not None:
                    _close_graph(graph)
                bt_api_module._ensure_plugins_loaded = original_plugin_loader

    try:
        await asyncio.to_thread(construct_without_listener)
    finally:
        await engine.dispose()
