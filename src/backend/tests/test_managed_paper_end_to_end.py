"""One normal HTTP-to-SDK integration for the E-only managed paper path.

This test starts the real application lifespan and authorized SDK worker, then
uses a separate Execution ServiceHost with its real SQLite journal, admission
gate, paper matcher, and a deterministic in-process quote leaf.  It also runs
the cutover Alembic revision against a file-backed SQLite application database.
No provider, Risk, Monitor, legacy matcher, or mocked ``orders.submit`` path is
used.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import multiprocessing
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import suppress
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("bt_api_py")
pytest.importorskip("bt_api_execution")
zmq = pytest.importorskip("zmq")

from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
from tests import managed_paper_service_read_support as _order  # noqa: E402


_JWT_SECRET = "afi-managed-paper-synthetic-jwt-secret-20261016"
_JWT_ALGORITHM = "HS256"
_SUBMIT_SCOPE_REF = "afi-managed-paper-submit-v1"
_QUERY_SCOPE_REF = "afi-managed-paper-query-v1"
_SECOND_SUBJECT_SCOPE_REF = "afi-managed-paper-unrelated-query-v1"
_APPLICATION_SECURITY_REF = "afi-managed-paper-application-curve-v1"
_APPLICATION_PRINCIPAL = "afi-managed-paper-application-principal"
_APPLICATION_ACTOR = "afi-managed-paper-application"
_SECOND_APPLICATION_PRINCIPAL = "afi-managed-paper-second-principal"
_SECOND_APPLICATION_ACTOR = "afi-managed-paper-second-application"
_DOMAIN_REF = "afi-managed-paper-domain-v1"
_ACCOUNT_REF = "afi-managed-paper-simulation-account-v1"
_STRATEGY_REF = "afi-managed-paper-strategy-v1"
_LEGACY_ACCOUNT_CASH = 100.0
_FEE_RATE = 0.001
_INSTRUMENT = "BTC-USDT"
_INSTRUMENT_VERSION = "afi-paper-instrument-v1"
_MAX_MESSAGE_BYTES = 65_536


def _paper_domain():
    from bt_api_execution import PAPER_MODEL_REF, PaperInstrumentV1, PaperOwnerDomainV1

    return PaperOwnerDomainV1(
        execution_domain_ref=_DOMAIN_REF,
        simulation_account_ref=_ACCOUNT_REF,
        experiment_ref="afi-managed-paper-experiment-v1",
        strategy_ref=_STRATEGY_REF,
        model_ref=PAPER_MODEL_REF,
        model_version="1",
        quote_source_ref="afi-managed-paper-synthetic-quotes-v1",
        cash_currency="USDT",
        initial_cash=Decimal("100"),
        initial_fees=Decimal("0"),
        fee_rate=Decimal(str(_FEE_RATE)),
        fee_quantum=Decimal("0.0001"),
        max_quote_age_ns=30_000_000_000,
        instruments=(
            PaperInstrumentV1(
                _INSTRUMENT,
                _INSTRUMENT_VERSION,
                "BTC",
                "USDT",
                Decimal("0.25"),
                Decimal("0.01"),
            ),
        ),
        opening_positions=(),
    )


class _SyntheticPaperQuoteSource:
    """Return one fixed, versioned quote from the trusted test composition."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def read_quote(self, instrument: str):
        from bt_api_execution import PaperQuoteV1

        self.calls.append(instrument)
        if instrument != _INSTRUMENT:
            return None
        return PaperQuoteV1(
            source_ref="afi-managed-paper-synthetic-quotes-v1",
            generation="afi-managed-paper-quote-generation-v1",
            cursor=1,
            instrument=instrument,
            metadata_version=_INSTRUMENT_VERSION,
            quote_currency="USDT",
            bid=Decimal("10.00"),
            ask=Decimal("10.02"),
            bid_quantity=Decimal("5"),
            ask_quantity=Decimal("5"),
            as_of_ns=time.time_ns(),
        )


def _execution_host_process(
    control: Any,
    raw_config: dict[str, Any],
    registry_path: str,
    store_path: str,
    keys: dict[str, bytes],
) -> None:
    """Run the real Execution paper owner with synthetic quote input only."""
    host: Any | None = None
    store: Any | None = None
    close_calls = [0]
    try:
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
        from bt_api_py.service_components import ComponentResources
        from bt_api_py.service_config import parse_service_config
        from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
        from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

        service_config = parse_service_config(raw_config)
        wire_scope = WireScope(
            _DOMAIN_REF,
            account_ref=_ACCOUNT_REF,
            strategy_ref=_STRATEGY_REF,
        )
        execution_scope = ExecutionScope(
            PAPER_PROVIDER,
            PAPER_ENVIRONMENT,
            _ACCOUNT_REF,
            _STRATEGY_REF,
            "afi-managed-paper-trading-day-v1",
        )
        application_identity = WireIdentity(
            WireRole.APPLICATION_CLIENT,
            _APPLICATION_PRINCIPAL,
            _APPLICATION_ACTOR,
        )
        second_identity = WireIdentity(
            WireRole.APPLICATION_CLIENT,
            _SECOND_APPLICATION_PRINCIPAL,
            _SECOND_APPLICATION_ACTOR,
        )
        service_identity = WireIdentity(
            WireRole.SERVICE,
            _order._SERVICE_PRINCIPAL,
            _order._SERVICE_ID,
        )
        grants = {
            _APPLICATION_PRINCIPAL: (
                PrincipalGrant(
                    application_identity,
                    (
                        ResourceGrant(
                            _order._INSTANCE_ID,
                            "service.order_entry",
                            _SUBMIT_SCOPE_REF,
                            wire_scope,
                            frozenset({"orders.submit"}),
                        ),
                        ResourceGrant(
                            _order._INSTANCE_ID,
                            "service.order_query",
                            _QUERY_SCOPE_REF,
                            wire_scope,
                            frozenset({"orders.query"}),
                        ),
                    ),
                ),
            ),
            _SECOND_APPLICATION_PRINCIPAL: (
                PrincipalGrant(
                    second_identity,
                    (
                        ResourceGrant(
                            _order._INSTANCE_ID,
                            "service.order_query",
                            _SECOND_SUBJECT_SCOPE_REF,
                            WireScope(
                                "afi-managed-paper-unrelated-domain-v1",
                                account_ref="afi-managed-paper-unrelated-account-v1",
                                strategy_ref="afi-managed-paper-unrelated-strategy-v1",
                            ),
                            frozenset({"orders.query"}),
                        ),
                    ),
                ),
            ),
        }
        authority = TrustedServiceAuthority(
            identity=service_identity,
            scope=WireScope(_DOMAIN_REF),
            scope_ref=service_config.scope_ref,
            scope_version="afi-managed-paper-service-scope-v1",
            security_ref=_order._SERVER_SECURITY_REF,
            security_version="curve-key-v1",
            registration_policy_ref=service_config.registration_policy_ref,
            registration_policy_version="afi-managed-paper-registration-v1",
            service_requirements_ref=service_config.service_requirements_ref,
            service_requirements_version="afi-managed-paper-requirements-v1",
            curve_public_key=keys["server_public"],
            curve_secret_key=keys["server_secret"],
            principals={
                keys["application_public"]: _APPLICATION_PRINCIPAL,
                keys["second_application_public"]: _SECOND_APPLICATION_PRINCIPAL,
            },
            grants=grants,
        )

        domain = _paper_domain()
        quote_source = _SyntheticPaperQuoteSource()
        dispatch = PaperMatchingPort(domain, quote_source)
        validator = ExecutionProviderValidatorV1(
            provider_id=PAPER_PROVIDER,
            validator_id="afi-managed-paper-market-policy-v1",
            version="1",
            dispatch_port=dispatch,
            instrument_map={_INSTRUMENT: _INSTRUMENT},
            quantity_steps={_INSTRUMENT: Decimal("0.25")},
            max_quantities={_INSTRUMENT: Decimal("10")},
            price_ticks={_INSTRUMENT: Decimal("0.01")},
            supported_order_types=(OrderType.MARKET,),
            supported_time_in_force=(TimeInForce.FOK,),
            supported_actions=((Side.BUY, PositionEffect.OPEN),),
            supports_reduce_only=False,
        )
        store = SqliteExecutionStore(store_path)
        admission = ExecutionBasicAdmissionGate(
            store,
            ExecutionAdmissionValidatorRegistry((validator,)),
            permit_ttl_ns=60_000_000_000,
        )
        close_calls = [0]
        host: Any | None = None

        def close_resources() -> None:
            store.close()
            close_calls[0] += 1

        def resource_provider(component: str, _instance: str, _options: Any, _scope: Any):
            if component != "execution":
                raise AssertionError("unexpected ServiceHost component")
            return ComponentResources.owned(
                {
                    "store": store,
                    "targets": {wire_scope: execution_scope},
                    "dispatch": dispatch,
                    "admission": {"basic_admission_gate": admission},
                    "paper_owner_domain": domain,
                },
                ready=lambda: True,
                close=close_resources,
            )

        host = ServiceHost(
            service_config,
            authority,
            registry_path,
            resource_provider,
        )
        host.start()
        control.send(("ready", host.endpoint, host.state))
        while True:
            if control.poll(0.02):
                command = control.recv()
                if command == ("close",):
                    host.close()
                    control.send(
                        (
                            "closed",
                            host.state,
                            tuple(host.summary["cleanup_failures"]),
                            close_calls[0],
                            tuple(quote_source.calls),
                        )
                    )
                    return
                if isinstance(command, tuple) and len(command) == 2 and command[0] == "metrics":
                    intent_id = command[1]
                    record = store.get(intent_id, scope=execution_scope)
                    receipt = store.get_paper_match_receipt(intent_id, scope=execution_scope)
                    book = store.read_paper_book(execution_scope)
                    events = store.read_outbox(
                        scope=execution_scope, after_sequence=0, limit=100
                    )
                    provider_events = tuple(
                        event for event in events if event.event_type == "provider_observation"
                    )
                    result = {
                        "record_state": None if record is None else record.state.value,
                        "dispatch_attempts": None
                        if record is None
                        else record.dispatch_attempts,
                        "filled_quantity": None
                        if record is None
                        else format(record.filled_quantity, "f"),
                        "receipt_state": None if receipt is None else receipt.state.value,
                        "receipt_price": None
                        if receipt is None
                        else format(receipt.fill_price, "f"),
                        "receipt_fee": None
                        if receipt is None
                        else format(receipt.fee_amount, "f"),
                        "book_cash": format(book.cash, "f"),
                        "book_currency": book.cash_currency,
                        "book_fees": format(book.cumulative_fees, "f"),
                        "book_positions": tuple(
                (
                    row.instrument,
                    format(row.quantity, "f"),
                    format(row.average_cost, "f"),
                )
                            for row in book.positions
                        ),
                        "book_receipts": book.receipt_count,
                        "quote_calls": tuple(quote_source.calls),
                        "provider_event_count": len(provider_events),
                        "provider_event_matches_receipt": (
                            receipt is not None
                            and len(provider_events) == 1
                            and provider_events[0].event_id == receipt.event_id
                            and provider_events[0].sequence == receipt.event_sequence
                        ),
                    }
                    control.send(("metrics", result))
                    continue
                raise AssertionError("unknown synthetic Execution host command")
            host.serve_once(timeout_ms=20)
    except BaseException as error:
        if host is not None:
            with suppress(BaseException):
                if host.state == "started":
                    host.close()
        if store is not None and close_calls[0] == 0:
            try:
                store.close()
            except BaseException:
                pass
            finally:
                close_calls[0] += 1
        code = getattr(error, "code", None)
        if type(code) is not str or not code.isidentifier() or len(code) > 64:
            code = "UNCLASSIFIED"
        with suppress(BaseException):
            control.send(("host_error", type(error).__name__, code))
        raise
    finally:
        with suppress(BaseException):
            control.close()


def _deployment_profile(
    *,
    endpoint: str,
    subject: str,
    principal: str,
    actor: str,
    security_ref: str,
    public_key: bytes,
    secret_key: bytes,
    server_key: bytes,
    legacy_account_id: str | None,
) -> dict[str, Any]:
    from bt_api_base.service_protocol import WireScope

    identity = WireIdentity(WireRole.APPLICATION_CLIENT, principal, actor)
    if legacy_account_id is None:
        scope_ref = _SECOND_SUBJECT_SCOPE_REF
        account_ref = "afi-managed-paper-unrelated-account-v1"
        domain_ref = "afi-managed-paper-unrelated-domain-v1"
        strategy_ref = "afi-managed-paper-unrelated-strategy-v1"
        binding_mount = "application.order_query"
        binding_scope_ref = scope_ref
        client_config = _order._client_config(
            endpoint,
            "application_client",
            security_ref,
            application=actor,
        )
        client_config["clients"]["execution"]["settings"]["bindings"][0].update(
            {"scope_ref": scope_ref, "account_ref": account_ref}
        )
        paper_bindings: dict[str, Any] = {}
        paper_grants: list[str] = []
        order_bindings = {scope_ref: {"mount": "application.order_query"}}
    else:
        domain = _paper_domain()
        scope_ref = _SUBMIT_SCOPE_REF
        query_scope_ref = _QUERY_SCOPE_REF
        account_ref = _ACCOUNT_REF
        domain_ref = _DOMAIN_REF
        strategy_ref = _STRATEGY_REF
        binding_mount = "application.orders"
        binding_scope_ref = scope_ref
        client_config = _order._client_config(
            endpoint,
            "application_client",
            security_ref,
            application=actor,
        )
        bindings = client_config["clients"]["execution"]["settings"]["bindings"]
        bindings[0].update(
            {
                "mount": "application.orders",
                "scope_ref": scope_ref,
                "account_ref": account_ref,
            }
        )
        bindings.append(
            {
                "mount": "application.order_query",
                "service_id": _order._SERVICE_ID,
                "instance_id": _order._INSTANCE_ID,
                "scope_ref": query_scope_ref,
                "transport_ref": "afi-execution-connect-v1",
                "account_ref": account_ref,
            }
        )
        paper_bindings = {
            legacy_account_id: {
                "control_mode": "execution_only",
                "mount": "application.orders",
                "scope_ref": scope_ref,
                "query_scope_ref": query_scope_ref,
                "account_ref": account_ref,
                "execution_domain_ref": domain_ref,
                "strategy_ref": strategy_ref,
                "paper_owner_domain": domain.to_payload(),
                "execution_scope": {
                    "provider": "paper",
                    "environment": "paper",
                    "account_ref": account_ref,
                    "strategy_id": strategy_ref,
                    "trading_day": "afi-managed-paper-trading-day-v1",
                },
            }
        }
        paper_grants = [legacy_account_id]
        order_bindings = {query_scope_ref: {"mount": "application.order_query"}}

    client_config["clients"]["execution"]["settings"]["bindings"][0].update(
        {"mount": binding_mount, "scope_ref": binding_scope_ref, "account_ref": account_ref}
    )
    scopes = {
        scope_ref: {
            "execution_domain_ref": domain_ref,
            "account_ref": account_ref,
            "strategy_ref": strategy_ref,
        }
    }
    if legacy_account_id is not None:
        scopes[_QUERY_SCOPE_REF] = {
            "execution_domain_ref": domain_ref,
            "account_ref": account_ref,
            "strategy_ref": strategy_ref,
        }
    return {
        "subject": subject,
        "identity": {
            "principal_ref": identity.principal_ref,
            "actor_ref": identity.actor_ref,
            "delegate_ref": identity.delegate_ref,
        },
        "client_config": client_config,
        "scope_claims": scopes,
        "peer_identities": {
            _order._SERVICE_ID: {
                "principal_ref": _order._SERVICE_PRINCIPAL,
                "actor_ref": _order._SERVICE_ID,
            }
        },
        "curve_keys": {
            security_ref: {
                "server_key": server_key.decode("ascii"),
                "public_key": public_key.decode("ascii"),
                "secret_key": secret_key.decode("ascii"),
            }
        },
        "grants": {
            "account_refs": [],
            "order_scope_refs": list(order_bindings),
            "monitor_scope_refs": [],
            "paper_submit_account_ids": paper_grants,
        },
        "account_bindings": {},
        "order_bindings": order_bindings,
        "monitor_bindings": {},
        "paper_submit_bindings": paper_bindings,
        "worker": {"max_queue_size": 8, "maintenance_interval_seconds": 30.0},
    }


def _safe_close_execution_host(host: dict[str, Any]) -> tuple[Any, ...]:
    process = host["process"]
    pipe = host["pipe"]
    failures: list[str] = []
    forced = False
    reply: tuple[Any, ...] | None = None
    is_ready = host.get("ready") is True
    try:
        if process.is_alive():
            if is_ready:
                pipe.send(("close",))
                reply = _order._receive(pipe, timeout=15.0)
                if not reply or reply[0] != "closed":
                    failures.append("normal_close_reply_missing")
            else:
                startup_reply = host.get("startup_reply")
                if startup_reply is None:
                    if pipe.poll(0.1):
                        startup_reply = pipe.recv()
                    else:
                        pipe.send(("close",))
                        if pipe.poll(2.0):
                            startup_reply = pipe.recv()
                if isinstance(startup_reply, tuple) and startup_reply[:1] == ("ready",):
                    pipe.send(("close",))
                    reply = _order._receive(pipe, timeout=15.0)
                    if not reply or reply[0] != "closed":
                        failures.append("normal_close_reply_missing")
                elif (
                    isinstance(startup_reply, tuple)
                    and startup_reply
                    and startup_reply[0] in {"closed", "host_error"}
                ):
                    reply = startup_reply
                elif startup_reply is None:
                    failures.append("startup_reply_missing")
                else:
                    failures.append("unexpected_startup_reply")
    except BaseException as error:
        failures.append(type(error).__name__)
    try:
        process.join(15.0 if is_ready else 2.0)
    except BaseException as error:
        failures.append(type(error).__name__)
    try:
        if process.is_alive():
            forced = True
            process.terminate()
    except BaseException as error:
        failures.append(type(error).__name__)
    try:
        process.join(5.0)
    except BaseException as error:
        failures.append(type(error).__name__)
    try:
        if process.is_alive():
            forced = True
            process.kill()
    except BaseException as error:
        failures.append(type(error).__name__)
    try:
        process.join(5.0)
    except BaseException as error:
        failures.append(type(error).__name__)
    try:
        if process.is_alive():
            failures.append("process_still_alive")
        elif process.exitcode != 0:
            failures.append("nonzero_exit")
    except BaseException as error:
        failures.append(type(error).__name__)
    finally:
        try:
            pipe.close()
        except BaseException as error:
            failures.append(f"pipe_close:{type(error).__name__}")
        process_stopped = False
        try:
            process_stopped = not process.is_alive()
        except BaseException as error:
            failures.append(f"is_alive_after_cleanup:{type(error).__name__}")
        if process_stopped:
            try:
                process.close()
            except BaseException as error:
                failures.append(f"process_close:{type(error).__name__}")
    if forced:
        failures.append("forced_cleanup_used")
    if failures:
        error = AssertionError(f"synthetic paper owner cleanup failed: {tuple(failures)}")
        _order._record_cleanup_failures(error, tuple(failures))
        raise error
    return reply or ()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_http_lifespan_managed_paper_cutover_submit_query_and_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise one paper BUY through HTTP, the authorized SDK owner, and Execution."""

    import httpx
    import jwt
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from pydantic import SecretStr
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import app.main as main_module
    import app.services.quote_service as quote_service
    import app.services.service_read.deployment as service_read_deployment
    import app.utils.security as security
    from app.db import database, sql_repository
    from app.models.legacy_paper_cutover import LegacyPaperCutoverReceipt
    from app.models.user import User

    # ServiceReadWorker intentionally turns owner-thread startup exceptions
    # into the finite START_FAILED code.  Keep the real worker/runtime path,
    # while observing only the first underlying startup exception at this
    # integration-test seam.  The public record below contains type/code only;
    # exception text and deployment configuration are never emitted.
    startup_failure_lock = threading.Lock()
    startup_failure: dict[str, Any] | None = None
    startup_failure_error: BaseException | None = None
    worker_ordinal = 0
    service_thread_ordinals: dict[str, int] = {}
    public_exception_kinds = {
        ("builtins", "AttributeError"): "attribute_error",
        ("builtins", "ConnectionError"): "connection_error",
        ("builtins", "ImportError"): "import_error",
        ("builtins", "KeyError"): "key_error",
        ("builtins", "ModuleNotFoundError"): "module_not_found",
        ("builtins", "OSError"): "os_error",
        ("builtins", "RuntimeError"): "runtime_error",
        ("builtins", "TimeoutError"): "timeout_error",
        ("builtins", "TypeError"): "type_error",
        ("builtins", "ValueError"): "value_error",
        (
            "app.services.service_read.deployment",
            "ServiceReadDeploymentError",
        ): "service_read_deployment_error",
        ("app.services.service_read.worker", "ServiceReadWorkerError"):
            "service_read_worker_error",
    }

    def public_exception_kind(error: BaseException) -> str:
        try:
            error_type = type(error)
            module = error_type.__module__
            name = error_type.__name__
            if (
                type(module) is not str
                or type(name) is not str
                or len(module) > 80
                or len(name) > 80
            ):
                return "unknown_exception"
            return public_exception_kinds.get(
                (module, name), "unknown_exception"
            )
        except BaseException:
            return "unknown_exception"

    original_build_worker = service_read_deployment._build_worker
    original_thread_start = threading.Thread.start

    def diagnostic_thread_start(
        thread: threading.Thread, *args: Any, **kwargs: Any
    ) -> Any:
        ordinal = service_thread_ordinals.get(thread.name)
        if ordinal is None:
            return original_thread_start(thread, *args, **kwargs)
        try:
            return original_thread_start(thread, *args, **kwargs)
        except BaseException as error:
            record_startup_failure(ordinal, "thread_start", error)
            raise

    monkeypatch.setattr(threading.Thread, "start", diagnostic_thread_start)

    def record_startup_failure(
        ordinal: int, phase: str, error: BaseException
    ) -> None:
        nonlocal startup_failure, startup_failure_error
        exception_chain: list[dict[str, Any]] = []
        current: BaseException | None = error
        seen_errors: set[int] = set()
        while current is not None and len(exception_chain) < 4:
            if id(current) in seen_errors:
                break
            seen_errors.add(id(current))
            try:
                code = getattr(current, "code", None)
            except BaseException:
                code = None
            if (
                type(code) is not str
                or not code
                or len(code) > 80
                or not code.isascii()
                or any(
                    character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
                    for character in code
                )
            ):
                code = None
            exception_chain.append(
                {
                    "exception_kind": public_exception_kind(current),
                    "code": code,
                }
            )
            cause = current.__cause__
            current = cause if cause is not None else current.__context__
        record = {
            "worker_index": ordinal,
            "phase": phase,
            "exception_chain": exception_chain,
        }
        with startup_failure_lock:
            if startup_failure is None:
                startup_failure = record
                startup_failure_error = error

    def build_diagnostic_worker(profile: Any) -> Any:
        nonlocal worker_ordinal
        ordinal = worker_ordinal
        worker_ordinal += 1
        try:
            worker = original_build_worker(profile)
        except BaseException as error:
            record_startup_failure(ordinal, "worker_build", error)
            raise
        worker_name = getattr(worker, "_name", None)
        if type(worker_name) is str:
            service_thread_ordinals[worker_name] = ordinal
        session_factory = worker._factory

        def diagnostic_session_factory() -> Any:
            try:
                session = session_factory()
            except BaseException as error:
                record_startup_failure(ordinal, "session_factory", error)
                raise
            try:
                session_start = session.start
            except BaseException as error:
                record_startup_failure(ordinal, "session_start_binding", error)
                raise

            def diagnostic_session_start() -> None:
                try:
                    session_start()
                except BaseException as error:
                    record_startup_failure(ordinal, "session_start", error)
                    raise

            try:
                session.start = diagnostic_session_start
            except BaseException as error:
                record_startup_failure(ordinal, "session_start_binding", error)
                raise
            return session

        worker._factory = diagnostic_session_factory
        original_worker_start = worker.start

        async def diagnostic_worker_start() -> None:
            try:
                await original_worker_start()
            except BaseException as error:
                record_startup_failure(ordinal, "worker_start", error)
                raise

        worker.start = diagnostic_worker_start
        return worker

    monkeypatch.setattr(
        service_read_deployment, "_build_worker", build_diagnostic_worker
    )
    original_start_service_read_deployment = main_module.start_service_read_deployment

    async def start_service_read_deployment_with_diagnostic(value: Any) -> Any:
        nonlocal worker_ordinal, startup_failure, startup_failure_error
        worker_ordinal = 0
        with startup_failure_lock:
            startup_failure = None
            startup_failure_error = None
        try:
            return await original_start_service_read_deployment(value)
        except BaseException as error:
            if getattr(error, "code", None) == "START_FAILED":
                with startup_failure_lock:
                    first_failure = startup_failure
                    first_failure_error = startup_failure_error
                    # Retain the original worker exception until the safe
                    # public projection has been written, then release it.
                    startup_failure_error = None
                payload = {
                    "event": "afi13_paper_service_read_startup_failure_v1",
                    "deployment_code": "START_FAILED",
                    "deployment_exception_kind": public_exception_kind(error),
                    "first_worker_failure": first_failure,
                    "first_worker_failure_observed": (
                        first_failure is not None and first_failure_error is not None
                    ),
                }
                try:
                    stream = sys.__stderr__
                    if stream is not None:
                        stream.write(
                            "AFI13_PAPER_SERVICE_READ_STARTUP_DIAGNOSTIC "
                            + json.dumps(
                                payload, sort_keys=True, separators=(",", ":")
                            )
                            + "\n"
                        )
                        stream.flush()
                except BaseException:
                    # Diagnostic output must never replace the startup error.
                    pass
            raise

    monkeypatch.setattr(
        main_module,
        "start_service_read_deployment",
        start_service_read_deployment_with_diagnostic,
    )

    owner_subject = str(uuid.uuid4())
    second_subject = str(uuid.uuid4())
    account_db_path = tmp_path / "afi-managed-paper-application.sqlite3"
    execution_db_path = tmp_path / "afi-managed-paper-execution.sqlite3"
    registry_path = tmp_path / "afi-managed-paper-service-registry.sqlite3"
    account_db_url = f"sqlite+aiosqlite:///{account_db_path.as_posix()}"
    account_engine = create_async_engine(
        account_db_url,
        connect_args={"check_same_thread": False},
    )
    account_sessions = async_sessionmaker(
        account_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    monkeypatch.setattr(database, "_engine", account_engine)
    monkeypatch.setattr(database, "_async_session_maker", account_sessions)
    monkeypatch.setattr(database, "engine", account_engine)
    monkeypatch.setattr(database, "async_session_maker", account_sessions)
    monkeypatch.setattr(sql_repository, "async_session_maker", account_sessions)

    async with account_engine.begin() as connection:
        await connection.run_sync(database.Base.metadata.create_all)

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20261016_legacy_paper_cutover.py"
    )
    migration_spec = importlib.util.spec_from_file_location(
        "afi_test_legacy_paper_cutover_migration", migration_path
    )
    assert migration_spec is not None and migration_spec.loader is not None
    migration = importlib.util.module_from_spec(migration_spec)
    migration_spec.loader.exec_module(migration)
    import_migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20261016_legacy_paper_import.py"
    )
    import_migration_spec = importlib.util.spec_from_file_location(
        "afi_test_legacy_paper_import_migration", import_migration_path
    )
    assert import_migration_spec is not None and import_migration_spec.loader is not None
    import_migration = importlib.util.module_from_spec(import_migration_spec)
    import_migration_spec.loader.exec_module(import_migration)
    imported_cutover_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20261017_legacy_paper_import_cutover.py"
    )
    imported_cutover_spec = importlib.util.spec_from_file_location(
        "afi_test_legacy_paper_import_cutover_migration", imported_cutover_path
    )
    assert imported_cutover_spec is not None and imported_cutover_spec.loader is not None
    imported_cutover_migration = importlib.util.module_from_spec(imported_cutover_spec)
    imported_cutover_spec.loader.exec_module(imported_cutover_migration)

    def apply_cutover_migration(sync_connection: Any) -> None:
        # create_all includes the ORM tables; exercise the actual revision DDL.
        sync_connection.exec_driver_sql("DROP TABLE legacy_paper_cutover_receipts")
        sync_connection.exec_driver_sql("DROP TABLE legacy_paper_writer_leases")
        sync_connection.exec_driver_sql("DROP TABLE legacy_paper_import_receipts")
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            migration.upgrade()
            import_migration.upgrade()
            imported_cutover_migration.upgrade()

    async with account_engine.begin() as connection:
        await connection.run_sync(apply_cutover_migration)
        trigger_result = await connection.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        )
        trigger_names = {str(row[0]) for row in trigger_result.all()}
    assert "trg_lpc_receipt_no_update" in trigger_names
    assert "trg_lpc_account_update" in trigger_names
    assert any(
        name.startswith("trg_lpc_") and name.endswith("_insert") for name in trigger_names
    )

    async with account_sessions() as session:
        session.add_all(
            [
                User(
                    id=owner_subject,
                    username=f"paper-owner-{owner_subject[:8]}",
                    email=f"paper-owner-{owner_subject[:8]}@example.test",
                    hashed_password="synthetic-test-only-unused",
                ),
                User(
                    id=second_subject,
                    username=f"paper-reader-{second_subject[:8]}",
                    email=f"paper-reader-{second_subject[:8]}@example.test",
                    hashed_password="synthetic-test-only-unused",
                ),
            ]
        )
        await session.commit()

    monkeypatch.setattr(
        security,
        "settings",
        SimpleNamespace(JWT_SECRET_KEY=_JWT_SECRET, JWT_ALGORITHM=_JWT_ALGORITHM),
    )

    def token_for(subject: str) -> str:
        return jwt.encode(
            {
                "sub": subject,
                "username": subject,
                "token_type": "access",
                "exp": int(time.time()) + 600,
            },
            _JWT_SECRET,
            algorithm=_JWT_ALGORITHM,
        )

    owner_headers = {"Authorization": f"Bearer {token_for(owner_subject)}"}
    second_headers = {"Authorization": f"Bearer {token_for(second_subject)}"}

    async def no_startup(*_args: Any, **_kwargs: Any) -> None:
        return None

    class NoopShutdownManager:
        async def initiate(self, _app: Any) -> None:
            return None

    monkeypatch.setattr(main_module, "run_startup", no_startup)
    monkeypatch.setattr(main_module, "run_shutdown", no_startup)
    monkeypatch.setattr(main_module, "GracefulShutdownManager", NoopShutdownManager)
    monkeypatch.setattr(main_module.settings, "RAG_VECTOR_ENABLED", False)
    monkeypatch.setattr(
        quote_service,
        "get_quote_service",
        lambda: SimpleNamespace(shutdown=lambda: None),
    )

    endpoint = _order._endpoint()
    server_public, server_secret = zmq.curve_keypair()
    owner_public, owner_secret = zmq.curve_keypair()
    second_public, second_secret = zmq.curve_keypair()
    service_keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "application_public": owner_public,
        "second_application_public": second_public,
    }
    context = multiprocessing.get_context("spawn")
    owner_host: dict[str, Any] | None = None
    app = main_module.app
    main_thread = __import__("threading").current_thread()

    def start_execution_owner() -> dict[str, Any]:
        nonlocal owner_host
        host = _order._start_process(
            context,
            _execution_host_process,
            (
                _order._service_config(endpoint),
                str(registry_path),
                str(execution_db_path),
                service_keys,
            ),
            "afi-managed-paper-execution-owner",
        )
        host["ready"] = False
        owner_host = host
        ready = _order._receive(host["pipe"], timeout=20.0)
        host["startup_reply"] = ready
        host["ready"] = isinstance(ready, tuple) and ready[:1] == ("ready",)
        assert ready == ("ready", endpoint, "started")
        return host

    def execution_metrics(host: dict[str, Any], intent_id: str) -> dict[str, Any]:
        host["pipe"].send(("metrics", intent_id))
        reply = _order._receive(host["pipe"], timeout=10.0)
        assert reply and reply[0] == "metrics", reply
        return reply[1]

    def assert_one_paper_fill(
        metrics: dict[str, Any], *, expected_quote_calls: tuple[str, ...]
    ) -> None:
        assert metrics["record_state"] == "FILLED"
        assert metrics["dispatch_attempts"] == 1
        assert Decimal(metrics["filled_quantity"]) == Decimal("0.25")
        assert metrics["receipt_state"] == "FILLED"
        assert Decimal(metrics["receipt_price"]) == Decimal("10.02")
        assert Decimal(metrics["receipt_fee"]) == Decimal("0.0025")
        assert Decimal(metrics["book_cash"]) == Decimal("97.4925")
        assert metrics["book_currency"] == "USDT"
        assert Decimal(metrics["book_fees"]) == Decimal("0.0025")
        assert metrics["book_positions"] == ((_INSTRUMENT, "0.25", "10.02"),)
        assert metrics["book_receipts"] == 1
        assert metrics["quote_calls"] == expected_quote_calls
        assert metrics["provider_event_count"] == 1
        assert metrics["provider_event_matches_receipt"] is True

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://afi-managed-paper.integration",
        ) as client:
            # Create the selector account through the normal HTTP/API path before
            # binding a deployment-owned execution scope to its real ID.
            monkeypatch.setattr(main_module.settings, "SERVICE_READ_DEPLOYMENT_JSON", None)
            async with main_module.lifespan(app):
                assert app.state.service_read_deployment is None
                created = await client.post(
                    "/api/v1/paper-trading/accounts",
                    headers=owner_headers,
                    json={
                        "name": "managed paper empty cutover",
                        "initial_cash": _LEGACY_ACCOUNT_CASH,
                        "commission_rate": _FEE_RATE,
                        "slippage_rate": 0,
                    },
                )
                assert created.status_code == 200, created.text
                legacy_account_id = created.json()["id"]
                assert created.headers["X-Paper-Data-Source"] == "legacy"
                assert created.json()["current_cash"] == _LEGACY_ACCOUNT_CASH

            profile_owner = _deployment_profile(
                endpoint=endpoint,
                subject=owner_subject,
                principal=_APPLICATION_PRINCIPAL,
                actor=_APPLICATION_ACTOR,
                security_ref=_APPLICATION_SECURITY_REF,
                public_key=owner_public,
                secret_key=owner_secret,
                server_key=server_public,
                legacy_account_id=legacy_account_id,
            )
            profile_second = _deployment_profile(
                endpoint=endpoint,
                subject=second_subject,
                principal=_SECOND_APPLICATION_PRINCIPAL,
                actor=_SECOND_APPLICATION_ACTOR,
                security_ref="afi-managed-paper-second-curve-v1",
                public_key=second_public,
                secret_key=second_secret,
                server_key=server_public,
                legacy_account_id=None,
            )
            deployment_json = json.dumps(
                {"schema_version": 1, "subjects": [profile_owner, profile_second]},
                sort_keys=True,
                separators=(",", ":"),
            )
            deployment_value = SecretStr(deployment_json)
            monkeypatch.setattr(
                main_module.settings, "SERVICE_READ_DEPLOYMENT_JSON", deployment_value
            )

            owner_host = start_execution_owner()
            intent_id: str | None = None
            operation_key = f"afi13-managed-paper-{uuid.uuid4()}"
            order_body = {
                "account_id": legacy_account_id,
                "symbol": _INSTRUMENT,
                "order_type": "market",
                "side": "buy",
                "size": 0.25,
            }

            async with main_module.lifespan(app):
                deployment = app.state.service_read_deployment
                assert deployment is not None
                assert len(deployment._workers) == 2
                owner_threads = tuple(worker._thread for worker in deployment._workers)
                assert all(thread is not None and thread.is_alive() for thread in owner_threads)
                assert len({thread.ident for thread in owner_threads}) == 2
                assert all(thread is not main_thread for thread in owner_threads)

                cutover = await client.post(
                    f"/api/v1/paper-trading/accounts/{legacy_account_id}/managed-cutover",
                    headers=owner_headers,
                    json={"confirmed": True},
                )
                assert cutover.status_code == 200, cutover.text
                cutover_body = cutover.json()
                assert cutover.headers["X-Paper-Data-Source"] == "managed_paper"
                assert cutover_body["state"] == "ACTIVE"
                assert cutover_body["data_migrated"] is False
                assert cutover_body["legacy_ledger_retained_read_only"] is True
                assert cutover_body["source_counts"] == {
                    "orders": 0,
                    "positions": 0,
                    "trades": 0,
                }
                assert len(cutover_body["source_inventory_sha256"]) == 64
                assert len(cutover_body["binding_sha256"]) == 64
                assert len(cutover_body["paper_domain_sha256"]) == 64

                async with account_sessions() as session:
                    receipt_result = await session.execute(
                        select(LegacyPaperCutoverReceipt).where(
                            LegacyPaperCutoverReceipt.legacy_account_id == legacy_account_id
                        )
                    )
                    persisted_receipt = receipt_result.scalar_one()
                    assert persisted_receipt.owner_subject == owner_subject
                    assert persisted_receipt.source_order_count == 0
                    assert persisted_receipt.source_position_count == 0
                    assert persisted_receipt.source_trade_count == 0
                    assert persisted_receipt.source_inventory_sha256 == cutover_body[
                        "source_inventory_sha256"
                    ]

                # The compatibility endpoints still expose only the old ledger.
                legacy_orders = await client.get(
                    "/api/v1/paper-trading/orders",
                    headers=owner_headers,
                    params={"account_id": legacy_account_id},
                )
                assert legacy_orders.status_code == 200, legacy_orders.text
                assert legacy_orders.headers["X-Paper-Data-Source"] == "legacy"
                assert legacy_orders.json() == {"total": 0, "items": []}
                legacy_account = await client.get(
                    f"/api/v1/paper-trading/accounts/{legacy_account_id}",
                    headers=owner_headers,
                )
                assert legacy_account.status_code == 200, legacy_account.text
                assert legacy_account.headers["X-Paper-Data-Source"] == "legacy"
                assert legacy_account.json()["current_cash"] == _LEGACY_ACCOUNT_CASH

                unsupported_limit = await client.post(
                    "/api/v1/paper-trading/orders",
                    headers={**owner_headers, "Idempotency-Key": f"{operation_key}-limit"},
                    json={
                        **order_body,
                        "order_type": "limit",
                        "price": 10.0,
                    },
                )
                assert unsupported_limit.status_code == 422
                assert (
                    unsupported_limit.json()["details"]["code"]
                    == "UNSUPPORTED_PAPER_ORDER_TYPE"
                )

                denied_submit = await client.post(
                    "/api/v1/paper-trading/orders",
                    headers={**second_headers, "Idempotency-Key": f"{operation_key}-denied"},
                    json=order_body,
                )
                assert denied_submit.status_code == 403
                assert denied_submit.headers.get("X-Paper-Data-Source") is None

                async def submit_same_manual_order():
                    return await client.post(
                        "/api/v1/paper-trading/orders",
                        headers={**owner_headers, "Idempotency-Key": operation_key},
                        json=order_body,
                    )

                first_submit, duplicate_submit = await asyncio.gather(
                    submit_same_manual_order(),
                    submit_same_manual_order(),
                )
                assert first_submit.status_code == 200, first_submit.text
                assert duplicate_submit.status_code == 200, duplicate_submit.text
                assert first_submit.headers["X-Paper-Data-Source"] == "managed_paper"
                assert duplicate_submit.headers["X-Paper-Data-Source"] == "managed_paper"
                first_body = first_submit.json()
                duplicate_body = duplicate_submit.json()
                intent_id = first_body["intent_id"]
                assert duplicate_body["intent_id"] == intent_id
                assert first_body["state"] == "FILLED"
                assert duplicate_body["state"] == "FILLED"
                assert first_body["status"] == "filled"
                assert duplicate_body["status"] == "filled"
                assert first_body["submission_acknowledged"] is True
                assert first_body["filled_size"] == 0.25
                assert first_body["avg_fill_price"] == 10.02
                assert first_body["commission"] == 0.0025

                conflicting_replay = await client.post(
                    "/api/v1/paper-trading/orders",
                    headers={**owner_headers, "Idempotency-Key": operation_key},
                    json={**order_body, "size": 0.5},
                )
                assert conflicting_replay.status_code == 409
                assert (
                    conflicting_replay.json()["details"]["code"]
                    == "PAPER_IDEMPOTENCY_CONFLICT"
                )
                assert conflicting_replay.json()["details"]["intent_id"] == intent_id

                authorized_read = await client.get(
                    f"/api/v1/paper-trading/managed-orders/{intent_id}",
                    headers=owner_headers,
                    params={"account_id": legacy_account_id},
                )
                assert authorized_read.status_code == 200, authorized_read.text
                assert authorized_read.headers["X-Paper-Data-Source"] == "managed_paper"
                assert authorized_read.json()["intent_id"] == intent_id
                assert authorized_read.json()["state"] == "FILLED"
                assert authorized_read.json()["filled_size"] == 0.25

                legacy_orders_after_submit = await client.get(
                    "/api/v1/paper-trading/orders",
                    headers=owner_headers,
                    params={"account_id": legacy_account_id},
                )
                assert legacy_orders_after_submit.status_code == 200
                assert legacy_orders_after_submit.headers["X-Paper-Data-Source"] == "legacy"
                assert legacy_orders_after_submit.json() == {"total": 0, "items": []}
                legacy_account_after_submit = await client.get(
                    f"/api/v1/paper-trading/accounts/{legacy_account_id}",
                    headers=owner_headers,
                )
                assert legacy_account_after_submit.status_code == 200
                assert legacy_account_after_submit.headers["X-Paper-Data-Source"] == "legacy"
                assert legacy_account_after_submit.json()["current_cash"] == _LEGACY_ACCOUNT_CASH

                denied_read = await client.get(
                    f"/api/v1/paper-trading/managed-orders/{intent_id}",
                    headers=second_headers,
                    params={"account_id": legacy_account_id},
                )
                assert denied_read.status_code == 403
                assert denied_read.headers.get("X-Paper-Data-Source") is None

                fenced_delete = await client.delete(
                    f"/api/v1/paper-trading/accounts/{legacy_account_id}",
                    headers=owner_headers,
                )
                assert fenced_delete.status_code == 409
                assert (
                    fenced_delete.json()["details"]["code"]
                    == "MANAGED_PAPER_LEGACY_ACCOUNT_FENCED"
                )

                account_connection = sqlite3.connect(str(account_db_path))
                try:
                    with pytest.raises(
                        sqlite3.IntegrityError,
                        match="MANAGED_PAPER_LEGACY_ACCOUNT_FENCED",
                    ):
                        account_connection.execute(
                            "UPDATE paper_trading_accounts SET current_cash = current_cash "
                            "WHERE id = ?",
                            (legacy_account_id,),
                        )
                finally:
                    account_connection.close()

                metrics_before_restart = execution_metrics(owner_host, intent_id)
                assert_one_paper_fill(
                    metrics_before_restart,
                    expected_quote_calls=(_INSTRUMENT,),
                )

            assert deployment.closed is True

            close_reply = _safe_close_execution_host(owner_host)
            owner_host = None
            assert close_reply[0] == "closed"
            assert close_reply[1] == "closed"
            assert close_reply[2] == ()
            assert close_reply[3] == 1
            assert close_reply[4] == (_INSTRUMENT,)

            # The closed owner released SQLite cleanly; the journal and match
            # receipt survive reopening the same durable Execution database.
            from bt_api_execution import (
                PAPER_ENVIRONMENT,
                PAPER_PROVIDER,
                ExecutionScope,
                SqliteExecutionStore,
            )

            execution_scope = ExecutionScope(
                PAPER_PROVIDER,
                PAPER_ENVIRONMENT,
                _ACCOUNT_REF,
                _STRATEGY_REF,
                "afi-managed-paper-trading-day-v1",
            )
            reopened_store = SqliteExecutionStore(str(execution_db_path))
            try:
                persisted_order = reopened_store.get(intent_id, scope=execution_scope)
                persisted_match = reopened_store.get_paper_match_receipt(
                    intent_id, scope=execution_scope
                )
                persisted_book = reopened_store.read_paper_book(execution_scope)
                persisted_events = reopened_store.read_outbox(
                    scope=execution_scope, after_sequence=0, limit=100
                )
                assert persisted_order is not None
                assert persisted_order.state.value == "FILLED"
                assert persisted_order.dispatch_attempts == 1
                assert persisted_match is not None
                assert persisted_match.state.value == "FILLED"
                assert persisted_book.receipt_count == 1
                assert len(persisted_events) >= 1
            finally:
                reopened_store.close()

            owner_host = start_execution_owner()
            async with main_module.lifespan(app):
                deployment_after_restart = app.state.service_read_deployment
                assert deployment_after_restart is not None
                assert len(deployment_after_restart._workers) == 2
                restarted_threads = tuple(
                    worker._thread for worker in deployment_after_restart._workers
                )
                assert all(thread is not None and thread.is_alive() for thread in restarted_threads)
                assert len({thread.ident for thread in restarted_threads}) == 2
                assert all(thread is not main_thread for thread in restarted_threads)

                replay_after_restart = await client.post(
                    "/api/v1/paper-trading/orders",
                    headers={**owner_headers, "Idempotency-Key": operation_key},
                    json=order_body,
                )
                assert replay_after_restart.status_code == 200, replay_after_restart.text
                assert replay_after_restart.headers["X-Paper-Data-Source"] == "managed_paper"
                assert replay_after_restart.json()["intent_id"] == intent_id
                assert replay_after_restart.json()["state"] == "FILLED"

                read_after_restart = await client.get(
                    f"/api/v1/paper-trading/managed-orders/{intent_id}",
                    headers=owner_headers,
                    params={"account_id": legacy_account_id},
                )
                assert read_after_restart.status_code == 200, read_after_restart.text
                assert read_after_restart.json()["intent_id"] == intent_id
                assert read_after_restart.json()["state"] == "FILLED"
                assert read_after_restart.json()["filled_size"] == 0.25

                replay_metrics = execution_metrics(owner_host, intent_id)
                assert_one_paper_fill(replay_metrics, expected_quote_calls=())
                assert deployment_after_restart.closed is False

            assert deployment_after_restart.closed is True
            restarted_close_reply = _safe_close_execution_host(owner_host)
            owner_host = None
            assert restarted_close_reply[0] == "closed"
            assert restarted_close_reply[1] == "closed"
            assert restarted_close_reply[2] == ()
            assert restarted_close_reply[3] == 1
            assert restarted_close_reply[4] == ()
    finally:
        pending_error = sys.exc_info()[1]
        cleanup_error: BaseException | None = None
        if owner_host is not None:
            try:
                _safe_close_execution_host(owner_host)
            except BaseException as error:
                cleanup_error = error
                if pending_error is not None:
                    failures = getattr(
                        error, "_afi_managed_paper_cleanup_failures", ()
                    )
                    _order._record_cleanup_failures(
                        pending_error,
                        (
                            f"execution_owner:{type(error).__name__}",
                            *(failures if type(failures) is tuple else ()),
                        ),
                    )
        try:
            await account_engine.dispose()
        except BaseException as error:
            if cleanup_error is None:
                cleanup_error = error
            else:
                failures = getattr(
                    error, "_afi_managed_paper_cleanup_failures", ()
                )
                _order._record_cleanup_failures(
                    cleanup_error,
                    (
                        f"account_engine_dispose:{type(error).__name__}",
                        *(failures if type(failures) is tuple else ()),
                    ),
                )
        if pending_error is not None:
            if cleanup_error is not None and cleanup_error is not pending_error:
                failures = getattr(
                    cleanup_error, "_afi_managed_paper_cleanup_failures", ()
                )
                _order._record_cleanup_failures(
                    pending_error,
                    (
                        f"cleanup:{type(cleanup_error).__name__}",
                        *(failures if type(failures) is tuple else ()),
                    ),
                )
        elif cleanup_error is not None:
            raise cleanup_error
