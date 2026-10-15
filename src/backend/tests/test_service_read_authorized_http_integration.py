"""Real HTTP, SDK-worker, and service-grant isolation for service reads.

The local execution service and its SQLite journal run in an independent
process.  Orders are submitted only to a synthetic provider leaf; two verified
JWT subjects read their own durable records through separate owner-thread SDK
sessions and the production service-read router.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import ntpath
import os
import sys
import tempfile
import threading
import time
from contextlib import suppress
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic_settings import BaseSettings as _BaseSettings

_JWT_SECRET = "service-read-integration-synthetic-jwt-key-0123456789"
_JWT_ALGORITHM = "HS256"
_SYNTHETIC_LOG_DIR = tempfile.mkdtemp(prefix="afi_service_read_integration_")
_SYNTHETIC_ENV = {
    "DEBUG": "false",
    "DATABASE_URL": "sqlite+aiosqlite://",
    "SECRET_KEY": "service-read-integration-synthetic-secret-0123456789",
    "ADMIN_PASSWORD": "IntegrationSyntheticAdmin!98765",
    "JWT_SECRET_KEY": _JWT_SECRET,
    "JWT_ALGORITHM": _JWT_ALGORITHM,
    "LOG_LEVEL": "CRITICAL",
    "LOG_DIR": _SYNTHETIC_LOG_DIR,
    "BT_API_LOG_DIR": _SYNTHETIC_LOG_DIR,
    "SQL_ECHO": "false",
    "AI_CHAT_ENABLED": "false",
    "AI_CHAT_BASE_URL": "",
    "AI_CHAT_API_KEY": "",
    "AI_CHAT_MODEL": "",
}

_COMMAND_GUARD_STATE = {"active": True}


def _deny_cmd_autorun(event: str, audit_args: tuple[Any, ...]) -> None:
    """Block only cmd.exe/os.system AutoRun paths in this integration process."""

    if not _COMMAND_GUARD_STATE["active"]:
        return
    if event == "os.system":
        raise PermissionError("os.system is disabled by the service-read integration test")
    if event != "subprocess.Popen":
        return

    executable = audit_args[0] if audit_args else None
    if executable is None and len(audit_args) > 1:
        command = audit_args[1]
        if isinstance(command, (str, bytes)):
            text = os.fsdecode(command).lstrip()
            if text.startswith('"') and '"' in text[1:]:
                executable = text[1:].split('"', 1)[0]
            else:
                executable = text.split(None, 1)[0] if text else None
        elif isinstance(command, (list, tuple)) and command:
            executable = command[0]
    if executable is None:
        return
    try:
        basename = ntpath.basename(os.fsdecode(executable)).lower()
    except (TypeError, ValueError):
        return
    if basename in {"cmd", "cmd.exe"}:
        raise PermissionError("cmd.exe is disabled by the service-read integration test")


sys.addaudithook(_deny_cmd_autorun)


def _deny_environment_file_read(event: str, audit_args: tuple[Any, ...]) -> None:
    """Keep deployment and spawned ServiceHost imports away from dotenv files."""

    if event != "open" or not audit_args:
        return
    path = audit_args[0]
    if not isinstance(path, (str, bytes, os.PathLike)):
        return
    normalized = os.fsdecode(path).replace("\\", "/")
    if any(
        part.casefold() == ".slowapi.env"
        or part.casefold() == ".env"
        or part.casefold().startswith(".env.")
        for part in normalized.split("/")
    ):
        raise PermissionError("dotenv reads are disabled by the service-read integration test")


sys.addaudithook(_deny_environment_file_read)

# app/__init__.py eagerly imports application modules and initializes settings.
# Constrain BaseSettings' dotenv input and temporarily expose only synthetic
# settings while those real modules load; no repository/user .env or ambient
# provider credential is consulted.  Restore both process inputs immediately
# afterward so spawned interpreter and sibling tests retain their environment.
_ORIGINAL_ENV = os.environ
_ORIGINAL_BASE_SETTINGS_INIT = _BaseSettings.__init__


def _settings_init_without_dotenv(self: Any, *args: Any, **kwargs: Any) -> None:
    kwargs["_env_file"] = None
    _ORIGINAL_BASE_SETTINGS_INIT(self, *args, **kwargs)


_BaseSettings.__init__ = _settings_init_without_dotenv
os.environ = dict(_SYNTHETIC_ENV)  # noqa: B003 - isolate Python settings, preserve native spawn env
try:
    import app.config as _app_config  # noqa: E402

    pytest.importorskip("bt_api_py")
    pytest.importorskip("bt_api_execution")
    zmq = pytest.importorskip("zmq")

    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402, I001
    from tests import test_service_read_order_local_process as _order  # noqa: E402

    assert _app_config.get_settings().JWT_SECRET_KEY == _JWT_SECRET
    assert _app_config.get_settings().DATABASE_URL == "sqlite+aiosqlite://"
    assert _app_config.get_settings().DEBUG is False
finally:
    _BaseSettings.__init__ = _ORIGINAL_BASE_SETTINGS_INIT
    os.environ = _ORIGINAL_ENV  # noqa: B003 - restore the original environment mapping

if multiprocessing.current_process().name == "MainProcess":
    _COMMAND_GUARD_STATE["active"] = False


_DOMAIN = "paper:afi-authorized-http"
_SERVICE_ID = _order._SERVICE_ID
_SERVICE_PRINCIPAL = _order._SERVICE_PRINCIPAL
_INSTANCE_ID = _order._INSTANCE_ID
_SERVER_SECURITY_REF = _order._SERVER_SECURITY_REF
_APP_PRINCIPAL = "afi-http-read-principal"
_STRATEGY_A_PRINCIPAL = "afi-http-strategy-a-principal"
_STRATEGY_B_PRINCIPAL = "afi-http-strategy-b-principal"

_SUBJECT_A = "afi-user-a"
_SUBJECT_B = "afi-user-b"
_DELEGATE_A = "afi-dashboard-delegate-a"
_DELEGATE_B = "afi-dashboard-delegate-b"
_ACCOUNT_A = "afi-account-a"
_ACCOUNT_B = "afi-account-b"
_STRATEGY_A = "afi-strategy-a"
_STRATEGY_B = "afi-strategy-b"
_ENTRY_SCOPE_A = "afi-order-entry-a-v1"
_ENTRY_SCOPE_B = "afi-order-entry-b-v1"
_QUERY_SCOPE_A = "afi-order-query-a-v1"
_QUERY_SCOPE_B = "afi-order-query-b-v1"
_BOOK_QUERY_SCOPE = "afi-account-books-query-a-v1"
_BOOK_ACCOUNT_SCOPE = WireScope(_DOMAIN, account_ref=_ACCOUNT_A)
_BOOK_WIRE_SCOPE_A = WireScope(_DOMAIN, account_ref=_ACCOUNT_A, strategy_ref=_STRATEGY_A)
_BOOK_WIRE_SCOPE_B = WireScope(_DOMAIN, account_ref=_ACCOUNT_A, strategy_ref=_STRATEGY_B)
_INTENT_A = "afi-user-a-order-1"
_INTENT_B = "afi-user-b-order-1"

_SCOPE_A = WireScope(_DOMAIN, account_ref=_ACCOUNT_A, strategy_ref=_STRATEGY_A)
_SCOPE_B = WireScope(_DOMAIN, account_ref=_ACCOUNT_B, strategy_ref=_STRATEGY_B)
_SERVICE_IDENTITY = WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID)
_APPLICATION_IDENTITY_A = WireIdentity(
    WireRole.APPLICATION_CLIENT, _APP_PRINCIPAL, _SUBJECT_A, _DELEGATE_A
)
_APPLICATION_IDENTITY_B = WireIdentity(
    WireRole.APPLICATION_CLIENT, _APP_PRINCIPAL, _SUBJECT_B, _DELEGATE_B
)
_REQUEST_TIMEOUT_MS = _order._REQUEST_TIMEOUT_MS
_MAX_MESSAGE_BYTES = _order._MAX_MESSAGE_BYTES


class _ObservedSession:
    """Record the thread used by a real SDK session without replacing it."""

    def __init__(
        self,
        session: Any,
        subject: str,
        owner_ident: int,
        events: list[tuple[str, str, int]],
        lock: threading.Lock,
    ) -> None:
        self._session = session
        self._subject = subject
        self._owner_ident = owner_ident
        self._events = events
        self._lock = lock

    def _record(self, operation: str) -> None:
        ident = threading.get_ident()
        with self._lock:
            self._events.append((self._subject, operation, ident))
        assert ident == self._owner_ident

    def start(self) -> None:
        self._record("start")
        self._session.start()

    def maintain(self) -> None:
        self._record("maintain")
        self._session.maintain()

    def read_account(self, account_ref: str, *, currency: str | None = None) -> Any:
        self._record("read_account")
        return self._session.read_account(account_ref, currency=currency)

    def read_order(self, scope_ref: str, intent_id: str) -> Any:
        self._record("read_order")
        return self._session.read_order(scope_ref, intent_id)

    def read_strategy_health(self, scope_ref: str) -> Any:
        self._record("read_strategy_health")
        return self._session.read_strategy_health(scope_ref)

    def close(self) -> None:
        self._record("close")
        self._session.close()


class _CountingProvider:
    """Synthetic provider leaf with stable per-submit IDs for read assertions."""

    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, intent: Any) -> Any:
        from bt_api_execution import ProviderObservation

        self.submitted.append(intent.intent_id)
        return ProviderObservation.accepted(
            intent.intent_id, f"provider-order-{len(self.submitted)}"
        )

    def cancel(self, _intent: Any) -> Any:
        raise AssertionError("cancellation is outside this read-only integration")


def _multiuser_service_process(
    control: Any,
    raw_config: dict[str, Any],
    registry_path: str,
    keys: dict[str, bytes],
    store_path: str,
) -> None:
    """Run the actual execution ServiceHost with exact per-identity grants."""

    from bt_api_execution import ExecutionScope, SqliteExecutionStore
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

    config = parse_service_config(raw_config)
    provider = _CountingProvider()
    gate = _order._Gate()
    execution_store = None
    host = None
    try:
        strategy_identity_a = WireIdentity(
            WireRole.STRATEGY_CLIENT, _STRATEGY_A_PRINCIPAL, _STRATEGY_A
        )
        strategy_identity_b = WireIdentity(
            WireRole.STRATEGY_CLIENT, _STRATEGY_B_PRINCIPAL, _STRATEGY_B
        )
        authority = TrustedServiceAuthority(
            identity=_SERVICE_IDENTITY,
            scope=WireScope(_DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="afi-http-execution-scope-v1",
            security_ref=_SERVER_SECURITY_REF,
            security_version="curve-key-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="afi-http-execution-policy-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="afi-http-execution-requirements-v1",
            curve_public_key=keys["server_public"],
            curve_secret_key=keys["server_secret"],
            principals={
                keys["strategy_a_public"]: _STRATEGY_A_PRINCIPAL,
                keys["strategy_b_public"]: _STRATEGY_B_PRINCIPAL,
                keys["application_public"]: _APP_PRINCIPAL,
            },
            grants={
                _STRATEGY_A_PRINCIPAL: (
                    PrincipalGrant(
                        strategy_identity_a,
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_entry",
                                _ENTRY_SCOPE_A,
                                _SCOPE_A,
                                frozenset({"orders.submit", "orders.cancel"}),
                            ),
                        ),
                    ),
                ),
                _STRATEGY_B_PRINCIPAL: (
                    PrincipalGrant(
                        strategy_identity_b,
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_entry",
                                _ENTRY_SCOPE_B,
                                _SCOPE_B,
                                frozenset({"orders.submit", "orders.cancel"}),
                            ),
                        ),
                    ),
                ),
                _APP_PRINCIPAL: (
                    PrincipalGrant(
                        _APPLICATION_IDENTITY_A,
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_query",
                                _QUERY_SCOPE_A,
                                _SCOPE_A,
                                frozenset({"orders.query"}),
                            ),
                        ),
                    ),
                    PrincipalGrant(
                        _APPLICATION_IDENTITY_B,
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_query",
                                _QUERY_SCOPE_B,
                                _SCOPE_B,
                                frozenset({"orders.query"}),
                            ),
                        ),
                    ),
                ),
            },
        )
        execution_store = SqliteExecutionStore(store_path)
        targets = {
            _SCOPE_A: ExecutionScope("PAPER", "simulation", _ACCOUNT_A, _STRATEGY_A, "run-a"),
            _SCOPE_B: ExecutionScope("PAPER", "simulation", _ACCOUNT_B, _STRATEGY_B, "run-b"),
        }

        def resource_provider(component: str, _instance_id: str, _options: Any, _scope: Any):
            if component != "execution":
                raise AssertionError("unexpected service component")
            return ComponentResources.borrowed(
                {
                    "store": execution_store,
                    "targets": targets,
                    "dispatch": provider,
                    "admission": {"order_gate": gate, "cancel_gate": gate},
                },
                ready=lambda: True,
            )

        host = ServiceHost(config, authority, registry_path, resource_provider)
        host.start()
        control.send(("ready", host.endpoint, host.state))
        while True:
            host.serve_once(timeout_ms=25)
            if not control.poll():
                continue
            command = control.recv()
            if command == ("close",):
                host.close()
                execution_store.close()
                execution_store = None
                control.send(("closed", host.state))
                return
            if command == ("counts",):
                control.send(("counts", tuple(provider.submitted), tuple(gate.reserved)))
                continue
            raise AssertionError("unknown local execution host command")
    except BaseException as error:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        if execution_store is not None:
            with suppress(BaseException):
                execution_store.close()
        with suppress(Exception):
            control.send(("error", getattr(error, "code", type(error).__name__)))
        raise
    finally:
        control.close()


class _SyntheticAccountBookSource:
    """Account-owner facts for the real ExecutionAccountBookService path."""

    def __init__(self, account_key: str, account_scope: WireScope) -> None:
        self.account_key = account_key
        self.account_scope = account_scope
        self.read_count = 0
        self.authorization_facts: list[tuple[str, str, str, str, str, str]] = []
        self.baseline_as_of_ns = time.time_ns()
        self.strategy_a_scope = _BOOK_WIRE_SCOPE_A
        self.strategy_b_scope = _BOOK_WIRE_SCOPE_B

    def authorize_account_view(
        self, *, principal_ref: str, identity: WireIdentity, scope: WireScope, account_key: str
    ) -> bool:
        self.authorization_facts.append(
            (
                principal_ref,
                identity.principal_ref,
                identity.actor_ref,
                identity.delegate_ref or "",
                scope.account_ref or "",
                account_key,
            )
        )
        return (
            principal_ref == _APP_PRINCIPAL
            and identity == _APPLICATION_IDENTITY_A
            and scope == self.account_scope
            and account_key == self.account_key
        )

    def read_inputs(self, *, account_key: str, journal_generation: str, execution_cursor: int):
        from decimal import Decimal

        from bt_api_execution import (
            AllocationOwnerKind,
            CurrencyAmount,
            ExecutionAccountSnapshot,
            ExecutionAllocationBaseline,
            ExecutionOwnerScope,
            ExecutionScope,
            ExecutionScopeDirectory,
            ExternalActivitySnapshot,
            ExternalFillFact,
            ExternalOrderFact,
            OwnerPosition,
            PositionFact,
            Side,
        )
        from bt_api_py.service_execution_account_books import ExecutionAccountBookReadInputsV1

        if account_key != self.account_key or type(execution_cursor) is not int:
            raise AssertionError("the service requested a different trusted account cut")
        self.read_count += 1
        as_of_ns = self.baseline_as_of_ns + 100
        directory_revision = "afi-synthetic-owner-directory-r1"
        provider_generation = "afi-synthetic-provider-generation-r1"
        targets = (
            (
                self.strategy_a_scope,
                ExecutionScope("PAPER", "simulation", _ACCOUNT_A, _STRATEGY_A, "run-a"),
                _STRATEGY_A,
            ),
            (
                self.strategy_b_scope,
                ExecutionScope("PAPER", "simulation", _ACCOUNT_A, _STRATEGY_B, "run-b"),
                _STRATEGY_B,
            ),
        )
        directory = ExecutionScopeDirectory(
            account_key=account_key,
            source="afi-synthetic-owner-directory",
            source_ref="afi-directory-r1",
            revision=directory_revision,
            covers_from_ns=self.baseline_as_of_ns,
            as_of_ns=as_of_ns,
            scopes=tuple(
                ExecutionOwnerScope(
                    execution_scope,
                    AllocationOwnerKind.STRATEGY,
                    owner_ref,
                    wire_scope,
                )
                for wire_scope, execution_scope, owner_ref in targets
            ),
        )
        instrument = "PAPER:SIM:AFI-SYNTHETIC"
        baseline_snapshot = ExecutionAccountSnapshot(
            account_key=account_key,
            source="afi-synthetic-account-snapshot",
            source_ref="afi-baseline-r1",
            generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=self.baseline_as_of_ns,
            execution_cursor=0,
            position_mode="NET",
            positions=(PositionFact(instrument, Decimal("3")),),
            cumulative_fees=(CurrencyAmount("USDT", Decimal("0.10")),),
            fee_coverage_start_ns=self.baseline_as_of_ns,
        )
        current_snapshot = ExecutionAccountSnapshot(
            account_key=account_key,
            source="afi-synthetic-account-snapshot",
            source_ref="afi-current-r1",
            generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=as_of_ns,
            execution_cursor=execution_cursor,
            position_mode="NET",
            positions=(PositionFact(instrument, Decimal("3.5")),),
            cumulative_fees=(CurrencyAmount("USDT", Decimal("0.13")),),
            fee_coverage_start_ns=self.baseline_as_of_ns,
        )
        allocation_baseline = ExecutionAllocationBaseline(
            account_key=account_key,
            source="afi-synthetic-allocation-baseline",
            source_ref="afi-allocation-r1",
            revision="afi-allocation-revision-r1",
            scope_directory_revision=directory_revision,
            provider_generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=self.baseline_as_of_ns,
            execution_cursor=0,
            positions=(
                OwnerPosition(AllocationOwnerKind.STRATEGY, _STRATEGY_A, instrument, Decimal("2")),
                OwnerPosition(AllocationOwnerKind.STRATEGY, _STRATEGY_B, instrument, Decimal("1")),
            ),
        )
        order_ref = "afi-synthetic-owner-a-order"
        external_activity = ExternalActivitySnapshot(
            account_key=account_key,
            source="afi-synthetic-account-activity",
            source_ref="afi-activity-r1",
            generation=provider_generation,
            coverage_start_ns=self.baseline_as_of_ns,
            coverage_end_ns=as_of_ns,
            fills=(
                ExternalFillFact(
                    "afi-synthetic-owner-a-fill",
                    instrument,
                    Side.BUY,
                    Decimal("0.5"),
                    Decimal("100"),
                    self.baseline_as_of_ns + 1,
                    fee=Decimal("0.03"),
                    fee_currency="USDT",
                    provider_order_ref=order_ref,
                ),
            ),
            orders=(
                ExternalOrderFact(
                    order_ref,
                    instrument,
                    Side.BUY,
                    Decimal("1"),
                    Decimal("0.5"),
                    "PARTIALLY_FILLED",
                    self.baseline_as_of_ns + 1,
                    owner_kind=AllocationOwnerKind.STRATEGY,
                    owner_ref=_STRATEGY_A,
                ),
            ),
        )
        return ExecutionAccountBookReadInputsV1(
            directory,
            baseline_snapshot,
            current_snapshot,
            allocation_baseline,
            external_activity,
        )


def _account_book_service_process(
    control: Any,
    raw_config: dict[str, Any],
    registry_path: str,
    keys: dict[str, bytes],
    store_path: str,
) -> None:
    """Run a real account-owner ServiceHost for synthetic book facts only."""

    from bt_api_execution import ExecutionScope, SqliteExecutionStore
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

    config = parse_service_config(raw_config)
    store = SqliteExecutionStore(store_path)
    targets = {
        _BOOK_WIRE_SCOPE_A: ExecutionScope("PAPER", "simulation", _ACCOUNT_A, _STRATEGY_A, "run-a"),
        _BOOK_WIRE_SCOPE_B: ExecutionScope("PAPER", "simulation", _ACCOUNT_A, _STRATEGY_B, "run-b"),
    }
    source = _SyntheticAccountBookSource(
        next(iter(targets.values())).account_key, _BOOK_ACCOUNT_SCOPE
    )
    provider = _CountingProvider()
    gate = _order._Gate()
    app_identity = _APPLICATION_IDENTITY_A
    strategy_identity_a = WireIdentity(WireRole.STRATEGY_CLIENT, _STRATEGY_A_PRINCIPAL, _STRATEGY_A)
    strategy_identity_b = WireIdentity(WireRole.STRATEGY_CLIENT, _STRATEGY_B_PRINCIPAL, _STRATEGY_B)
    book_operations = frozenset({"orders.query", "execution.account_books.query"})
    strategy_grants = {
        _STRATEGY_A_PRINCIPAL: (
            PrincipalGrant(
                strategy_identity_a,
                (
                    ResourceGrant(
                        _INSTANCE_ID,
                        "service.order_entry",
                        _ENTRY_SCOPE_A,
                        _BOOK_WIRE_SCOPE_A,
                        frozenset({"orders.submit", "orders.cancel"}),
                    ),
                    ResourceGrant(
                        _INSTANCE_ID,
                        "service.order_query",
                        _QUERY_SCOPE_A,
                        _BOOK_WIRE_SCOPE_A,
                        book_operations,
                    ),
                ),
            ),
        ),
        _STRATEGY_B_PRINCIPAL: (
            PrincipalGrant(
                strategy_identity_b,
                (
                    ResourceGrant(
                        _INSTANCE_ID,
                        "service.order_entry",
                        _ENTRY_SCOPE_B,
                        _BOOK_WIRE_SCOPE_B,
                        frozenset({"orders.submit", "orders.cancel"}),
                    ),
                    ResourceGrant(
                        _INSTANCE_ID,
                        "service.order_query",
                        _QUERY_SCOPE_B,
                        _BOOK_WIRE_SCOPE_B,
                        book_operations,
                    ),
                ),
            ),
        ),
        _APP_PRINCIPAL: (
            PrincipalGrant(
                app_identity,
                (
                    ResourceGrant(
                        _INSTANCE_ID,
                        "service.order_query",
                        _BOOK_QUERY_SCOPE,
                        _BOOK_ACCOUNT_SCOPE,
                        frozenset({"execution.account_books.query"}),
                    ),
                ),
            ),
        ),
    }
    authority = TrustedServiceAuthority(
        identity=_SERVICE_IDENTITY,
        scope=WireScope(_DOMAIN),
        scope_ref=config.scope_ref,
        scope_version="afi-books-service-scope-r1",
        security_ref=_SERVER_SECURITY_REF,
        security_version="curve-key-v1",
        registration_policy_ref=config.registration_policy_ref,
        registration_policy_version="afi-books-registration-policy-r1",
        service_requirements_ref=config.service_requirements_ref,
        service_requirements_version="afi-books-requirements-r1",
        curve_public_key=keys["server_public"],
        curve_secret_key=keys["server_secret"],
        principals={
            keys["strategy_a_public"]: _STRATEGY_A_PRINCIPAL,
            keys["strategy_b_public"]: _STRATEGY_B_PRINCIPAL,
            keys["application_public"]: _APP_PRINCIPAL,
        },
        grants=strategy_grants,
    )

    def resource_provider(component: str, instance_id: str, _options: Any, _scope: Any):
        if component != "execution" or instance_id != _INSTANCE_ID:
            raise AssertionError("unexpected execution component resource request")
        return ComponentResources.borrowed(
            {
                "store": store,
                "targets": targets,
                "dispatch": provider,
                "admission": {"order_gate": gate, "cancel_gate": gate},
                "account_books": source,
            },
            ready=lambda: True,
        )

    host = None
    host_started = False
    try:
        host = ServiceHost(config, authority, registry_path, resource_provider)
        host.start()
        host_started = True
        control.send(("ready", host.endpoint, host.state))
        while True:
            if control.poll(0.01):
                command = control.recv()
                if command == ("close",):
                    host.close()
                    store.close()
                    control.send(("closed", host.state))
                    return
                if command == ("metrics",):
                    control.send(("metrics", source.read_count))
                    continue
                if command == ("authorization_facts",):
                    control.send(("authorization_facts", tuple(source.authorization_facts)))
                    continue
                if command == ("write_counts",):
                    control.send(("write_counts", tuple(provider.submitted), tuple(gate.reserved)))
                    continue
                raise AssertionError("unknown account-book host command")
            host.serve_once(timeout_ms=20)
    except BaseException as error:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(BaseException):
            store.close()
        with suppress(Exception):
            chain_types: list[str] = []
            seen_errors: set[int] = set()
            current_error: BaseException | None = error
            while current_error is not None and len(chain_types) < 5:
                if id(current_error) in seen_errors:
                    break
                seen_errors.add(id(current_error))
                error_type = type(current_error).__name__
                safe_type = (
                    error_type
                    if error_type.isidentifier() and len(error_type) <= 64
                    else "OtherError"
                )
                error_code = getattr(current_error, "code", None)
                safe_code = (
                    error_code
                    if type(error_code) is str
                    and error_code.isidentifier()
                    and len(error_code) <= 64
                    else None
                )
                chain_types.append((safe_type, safe_code))
                current_error = current_error.__cause__ or current_error.__context__

            summary = host.summary if host is not None else {}
            start_failure = summary.get("start_failure")
            cleanup_failures = summary.get("cleanup_failures", ())
            cleanup_history = summary.get("cleanup_history", ())
            public_code = (
                _safe_diagnostic_code(getattr(error, "code", type(error).__name__)) or "OtherError"
            )
            host_state = (
                _safe_diagnostic_code(host.state if host is not None else "not_created")
                or "unknown"
            )
            control.send(
                (
                    "error",
                    public_code,
                    {
                        "host_state": host_state,
                        "start_failure": _safe_diagnostic_code(start_failure),
                        "cleanup_failures": _safe_diagnostic_codes(cleanup_failures),
                        "cleanup_history": _safe_diagnostic_codes(cleanup_history),
                        "exception_chain": tuple(chain_types),
                    },
                )
            )
        if not host_started:
            return
        raise
    finally:
        control.close()


def _client_runtime(
    endpoint: str,
    *,
    role: str,
    security_ref: str,
    server_public: bytes,
    client_public: bytes,
    client_secret: bytes,
    identity: WireIdentity,
    scope_ref: str,
    scope: WireScope,
) -> Any:
    from bt_api_py.service_config import parse_client_config
    from bt_api_py.service_runtime import (
        ClientCurveKeys,
        ServiceClientRuntime,
        ZmqTransportFactory,
    )

    if role == "strategy_client":
        raw = _order._client_config(endpoint, role, security_ref, strategy=identity.actor_ref)
    else:
        raw = _order._client_config(endpoint, role, security_ref, application=identity.actor_ref)
    binding = raw["clients"]["execution"]["settings"]["bindings"][0]
    binding["scope_ref"] = scope_ref
    binding["account_ref"] = scope.account_ref
    return ServiceClientRuntime(
        parse_client_config(raw),
        identity=identity,
        scope_resolver=lambda requested_ref: (
            scope if requested_ref == scope_ref else _raise_unknown_scope()
        ),
        peer_resolver=lambda _service: _SERVICE_IDENTITY,
        transport_factory=ZmqTransportFactory(
            {security_ref: ClientCurveKeys(server_public, client_public, client_secret)}
        ),
    )


def _raise_unknown_scope() -> Any:
    raise KeyError("scope reference was not included in the trusted client profile")


def _new_runtime(
    endpoint: str,
    *,
    role: str,
    security_ref: str,
    keys: dict[str, bytes],
    identity: WireIdentity,
    scope_ref: str,
    scope: WireScope,
) -> Any:
    return _client_runtime(
        endpoint,
        role=role,
        security_ref=security_ref,
        server_public=keys["server_public"],
        client_public=keys[f"{security_ref}_public"],
        client_secret=keys[f"{security_ref}_secret"],
        identity=identity,
        scope_ref=scope_ref,
        scope=scope,
    )


def _make_token(subject: str, key: str, *, expires_at: int | None = None) -> str:
    import jwt

    return jwt.encode(
        {
            "sub": subject,
            "username": subject,
            "token_type": "access",
            "exp": expires_at if expires_at is not None else int(time.time()) + 600,
        },
        key,
        algorithm=_JWT_ALGORITHM,
    )


def _assert_access_denied(response: Any) -> None:
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVICE_READ_ACCESS_DENIED"


def _close_runtime(runtime: Any) -> None:
    if runtime is None:
        return
    runtime.close()
    assert runtime.cleanup_failures == 0
    assert runtime.unregister_uncertainties == 0


def _run_authorized_http_integration(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise subject isolation through HTTP, worker, SDK, and remote grants."""

    import httpx  # noqa: I001 - retain the verified application import order
    from fastapi import FastAPI

    from app.api.service_read import configure_service_read, router
    from app.services.service_read.access import ReadAccess, ServiceReadAccessDirectory
    from app.services.service_read.client import OrderBinding
    from app.services.service_read.session import SdkServiceReadSession
    from app.services.service_read.worker import ServiceReadWorker
    from app.utils import security

    from bt_api_py.service_execution import ServiceExecutionClient

    monkeypatch.setattr(
        security,
        "settings",
        SimpleNamespace(JWT_SECRET_KEY=_JWT_SECRET, JWT_ALGORITHM=_JWT_ALGORITHM),
    )
    configure_service_read(None)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    context = multiprocessing.get_context("spawn")
    endpoint = _order._endpoint()
    server_public, server_secret = zmq.curve_keypair()
    keypairs = {
        name: zmq.curve_keypair()
        for name in (
            "strategy_a",
            "strategy_b",
            "application",
        )
    }
    keys: dict[str, bytes] = {"server_public": server_public, "server_secret": server_secret}
    for name, (public_key, secret_key) in keypairs.items():
        keys[f"{name}_public"] = public_key
        keys[f"{name}_secret"] = secret_key
    service_keys = {
        key: value
        for key, value in keys.items()
        if key.endswith("_public") or key == "server_secret"
    }

    host = None
    producer_runtimes: list[Any] = []
    workers: list[ServiceReadWorker] = []
    owner_threads: dict[str, threading.Thread] = {}
    session_events: list[tuple[str, str, int]] = []
    events_lock = threading.Lock()
    main_thread_ident = threading.get_ident()
    try:
        host = _order._start_process(
            context,
            _multiuser_service_process,
            (
                _order._service_config(endpoint),
                str(tmp_path / "afi-http-service-registry.sqlite3"),
                service_keys,
                str(tmp_path / "afi-http-execution.sqlite3"),
            ),
            "afi-authorized-http-execution-host",
        )
        ready = _order._receive(host["pipe"])
        assert ready[0] == "ready", ready

        strategy_profiles = (
            (
                "strategy_a",
                _STRATEGY_A_PRINCIPAL,
                _STRATEGY_A,
                _ENTRY_SCOPE_A,
                _SCOPE_A,
                "afi-strategy-a-curve-v1",
                _INTENT_A,
                "signal-user-a",
            ),
            (
                "strategy_b",
                _STRATEGY_B_PRINCIPAL,
                _STRATEGY_B,
                _ENTRY_SCOPE_B,
                _SCOPE_B,
                "afi-strategy-b-curve-v1",
                _INTENT_B,
                "signal-user-b",
            ),
        )
        for (
            key_name,
            principal,
            actor,
            scope_ref,
            scope,
            security_ref,
            intent,
            signal,
        ) in strategy_profiles:
            identity = WireIdentity(WireRole.STRATEGY_CLIENT, principal, actor)
            runtime = _new_runtime(
                endpoint,
                role="strategy_client",
                security_ref=security_ref,
                keys={
                    **keys,
                    f"{security_ref}_public": keys[f"{key_name}_public"],
                    f"{security_ref}_secret": keys[f"{key_name}_secret"],
                },
                identity=identity,
                scope_ref=scope_ref,
                scope=scope,
            )
            producer_runtimes.append(runtime)
            assert runtime.start().degraded_count == 0
            submitter = ServiceExecutionClient(runtime, "broker.orders", scope_ref=scope_ref)
            _order._submit(submitter, intent, signal, "1")

        users = (
            (
                _SUBJECT_A,
                _APPLICATION_IDENTITY_A,
                _ACCOUNT_A,
                _QUERY_SCOPE_A,
                _SCOPE_A,
                "application",
            ),
            (
                _SUBJECT_B,
                _APPLICATION_IDENTITY_B,
                _ACCOUNT_B,
                _QUERY_SCOPE_B,
                _SCOPE_B,
                "application",
            ),
        )

        async def _exercise_http_body() -> None:
            access_by_subject = {}
            for subject, identity, account_ref, query_scope, wire_scope, key_name in users:
                security_ref = f"afi-{subject}-dashboard-curve-v1"

                def make_session_factory(
                    *,
                    subject: str = subject,
                    identity: WireIdentity = identity,
                    query_scope: str = query_scope,
                    wire_scope: WireScope = wire_scope,
                    security_ref: str = security_ref,
                    key_name: str = key_name,
                ):
                    def factory() -> _ObservedSession:
                        owner = threading.current_thread()
                        owner_threads[subject] = owner

                        def runtime_factory() -> Any:
                            with events_lock:
                                session_events.append(
                                    (subject, "runtime_factory", threading.get_ident())
                                )
                            assert threading.current_thread() is owner
                            return _new_runtime(
                                endpoint,
                                role="application_client",
                                security_ref=security_ref,
                                keys={
                                    **keys,
                                    f"{security_ref}_public": keys[f"{key_name}_public"],
                                    f"{security_ref}_secret": keys[f"{key_name}_secret"],
                                },
                                identity=identity,
                                scope_ref=query_scope,
                                scope=wire_scope,
                            )

                        session = SdkServiceReadSession(
                            runtime_factory,
                            identity,
                            account_bindings={},
                            order_bindings={
                                query_scope: OrderBinding("application.order_query", query_scope)
                            },
                        )
                        return _ObservedSession(
                            session,
                            subject,
                            owner.ident,
                            session_events,
                            events_lock,
                        )

                    return factory

                worker = ServiceReadWorker(
                    make_session_factory(),
                    max_queue_size=8,
                    maintenance_interval_seconds=30.0,
                    name=f"afi-http-service-read-{subject}",
                )
                workers.append(worker)
                await worker.start()
                access_by_subject[subject] = ReadAccess(
                    worker,
                    allow_account_refs=frozenset({account_ref}),
                    allow_order_scope_refs=frozenset({query_scope}),
                )

            directory = ServiceReadAccessDirectory(access_by_subject)
            configure_service_read(directory)
            token_a = _make_token(_SUBJECT_A, _JWT_SECRET)
            token_b = _make_token(_SUBJECT_B, _JWT_SECRET)

            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://service-read.test",
                ) as client:
                    own_a = await client.get(
                        f"/api/v1/service-read/orders/{_INTENT_A}",
                        params={
                            "scope_ref": _QUERY_SCOPE_A,
                            "sub": _SUBJECT_B,
                            "actor_ref": _SUBJECT_B,
                            "principal_ref": "forged-principal",
                            "delegate_ref": _DELEGATE_B,
                        },
                        headers={
                            "Authorization": f"Bearer {token_a}",
                            "X-User-Id": _SUBJECT_B,
                            "X-Actor-Ref": _SUBJECT_B,
                            "X-Principal-Ref": "forged-principal",
                            "X-Delegate-Ref": _DELEGATE_B,
                        },
                    )
                    own_b = await client.get(
                        f"/api/v1/service-read/orders/{_INTENT_B}",
                        params={"scope_ref": _QUERY_SCOPE_B},
                        headers={"Authorization": f"Bearer {token_b}"},
                    )
                    assert own_a.status_code == own_b.status_code == 200
                    assert own_a.json()["intent_id"] == _INTENT_A
                    assert own_a.json()["state"] == "ACKED"
                    assert own_a.json()["provider_order_id"] == "provider-order-1"
                    assert own_b.json()["intent_id"] == _INTENT_B
                    assert own_b.json()["state"] == "ACKED"
                    assert own_b.json()["provider_order_id"] == "provider-order-2"

                    reads_before_denials = sum(
                        event[1] in {"read_order", "read_account", "read_strategy_health"}
                        for event in session_events
                    )
                    denied_requests = (
                        await client.get(
                            f"/api/v1/service-read/orders/{_INTENT_B}",
                            params={
                                "scope_ref": _QUERY_SCOPE_B,
                                "sub": _SUBJECT_B,
                                "actor_ref": _SUBJECT_B,
                                "principal_ref": _APP_PRINCIPAL,
                                "delegate_ref": _DELEGATE_B,
                            },
                            headers={
                                "Authorization": f"Bearer {token_a}",
                                "X-User-Id": _SUBJECT_B,
                                "X-Actor-Ref": _SUBJECT_B,
                                "X-Principal-Ref": _APP_PRINCIPAL,
                                "X-Delegate-Ref": _DELEGATE_B,
                            },
                        ),
                        await client.get(
                            f"/api/v1/service-read/accounts/{_ACCOUNT_B}",
                            headers={"Authorization": f"Bearer {token_a}"},
                        ),
                        await client.get(
                            f"/api/v1/service-read/orders/{_INTENT_A}",
                            params={
                                "scope_ref": _QUERY_SCOPE_A,
                                "sub": _SUBJECT_A,
                            },
                            headers={
                                "Authorization": f"Bearer {token_b}",
                                "X-User-Id": _SUBJECT_A,
                                "X-Actor-Ref": _SUBJECT_A,
                                "X-Delegate-Ref": _DELEGATE_A,
                            },
                        ),
                    )
                    for response in denied_requests:
                        _assert_access_denied(response)
                    reads_after_denials = sum(
                        event[1] in {"read_order", "read_account", "read_strategy_health"}
                        for event in session_events
                    )
                    assert reads_after_denials == reads_before_denials
            finally:
                configure_service_read(None)
                close_errors: list[BaseException] = []
                closing_workers = tuple(workers)
                workers.clear()
                for worker in closing_workers:
                    try:
                        await worker.aclose()
                    except BaseException as error:
                        close_errors.append(error)
                assert not close_errors, [type(error).__name__ for error in close_errors]

        async def exercise_http() -> None:
            try:
                await _exercise_http_body()
            finally:
                configure_service_read(None)
                close_errors: list[BaseException] = []
                closing_workers = tuple(workers)
                workers.clear()
                for worker in closing_workers:
                    try:
                        await worker.aclose()
                    except BaseException as error:
                        close_errors.append(error)
                assert not close_errors, [type(error).__name__ for error in close_errors]

        asyncio.run(exercise_http())

        assert len(owner_threads) == 2
        assert owner_threads[_SUBJECT_A].ident != main_thread_ident
        assert owner_threads[_SUBJECT_B].ident != main_thread_ident
        for subject in (_SUBJECT_A, _SUBJECT_B):
            owner_ident = owner_threads[subject].ident
            subject_events = [event for event in session_events if event[0] == subject]
            assert any(event[1] == "runtime_factory" for event in subject_events)
            assert any(event[1] == "read_order" for event in subject_events)
            assert any(event[1] == "close" for event in subject_events)
            assert all(event[2] == owner_ident for event in subject_events)
            assert not owner_threads[subject].is_alive()

        def denied_service_registration(
            identity: WireIdentity,
            *,
            scope_ref: str,
            scope: WireScope,
            key_name: str,
            security_ref: str,
            expected_code: str,
        ) -> None:
            from bt_api_py.service_runtime import ServiceRuntimeError

            runtime = _new_runtime(
                endpoint,
                role="application_client",
                security_ref=security_ref,
                keys={
                    **keys,
                    f"{security_ref}_public": keys[f"{key_name}_public"],
                    f"{security_ref}_secret": keys[f"{key_name}_secret"],
                },
                identity=identity,
                scope_ref=scope_ref,
                scope=scope,
            )
            try:
                with pytest.raises(ServiceRuntimeError) as denied:
                    runtime.start()
                assert denied.value.code == expected_code
            finally:
                _close_runtime(runtime)

        forged_identity = WireIdentity(
            WireRole.APPLICATION_CLIENT,
            _APP_PRINCIPAL,
            "afi-user-ungranted",
            "afi-ungranted-delegate",
        )
        denied_service_registration(
            forged_identity,
            scope_ref=_QUERY_SCOPE_A,
            scope=_SCOPE_A,
            key_name="application",
            security_ref="afi-ungranted-curve-v1",
            expected_code="DENIED",
        )
        denied_service_registration(
            _APPLICATION_IDENTITY_A,
            scope_ref=_QUERY_SCOPE_B,
            scope=_SCOPE_B,
            key_name="application",
            security_ref="afi-cross-scope-curve-v1",
            expected_code="SCOPE_DENIED",
        )

        counts = _order._command(host, "counts")
        assert counts[1] == (_INTENT_A, _INTENT_B)
        assert counts[2] == (_INTENT_A, _INTENT_B)
    finally:
        configure_service_read(None)
        for runtime in reversed(producer_runtimes):
            _close_runtime(runtime)
        if host is not None:
            process = host["process"]
            pipe = host["pipe"]
            if process.is_alive():
                with suppress(Exception):
                    pipe.send(("close",))
                    closed = _order._receive(pipe, timeout=10.0)
                    assert closed[0] == "closed", closed
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(10)
                raise AssertionError("synthetic execution service did not exit normally")
            assert process.exitcode == 0
            pipe.close()
            process.close()


def test_authorized_http_reads_use_per_subject_owner_threads_and_service_grants(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run imports and requests while the test-specific command guard is active."""

    _COMMAND_GUARD_STATE["active"] = True
    try:
        _run_authorized_http_integration(tmp_path, monkeypatch)
    finally:
        _COMMAND_GUARD_STATE["active"] = False


def _default_order_read_profile(
    *,
    endpoint: str,
    subject: str,
    identity: WireIdentity,
    account_ref: str,
    scope_ref: str,
    scope: WireScope,
    security_ref: str,
    keys: dict[str, bytes],
) -> dict[str, Any]:
    """Return deployment-owned config for one synthetic read-only subject."""

    client_config = _order._client_config(
        endpoint,
        "application_client",
        security_ref,
        application=identity.actor_ref,
    )
    binding = client_config["clients"]["execution"]["settings"]["bindings"][0]
    binding["scope_ref"] = scope_ref
    binding["account_ref"] = account_ref
    return {
        "subject": subject,
        "identity": {
            "principal_ref": identity.principal_ref,
            "actor_ref": identity.actor_ref,
            "delegate_ref": identity.delegate_ref,
        },
        "client_config": client_config,
        "scope_claims": {
            scope_ref: {
                "execution_domain_ref": scope.execution_domain_ref,
                "account_ref": scope.account_ref,
                "strategy_ref": scope.strategy_ref,
            }
        },
        "peer_identities": {
            _SERVICE_ID: {"principal_ref": _SERVICE_PRINCIPAL, "actor_ref": _SERVICE_ID}
        },
        "curve_keys": {
            security_ref: {
                "server_key": keys["server_public"].decode("ascii"),
                "public_key": keys["application_public"].decode("ascii"),
                "secret_key": keys["application_secret"].decode("ascii"),
            }
        },
        "grants": {
            "account_refs": [],
            "order_scope_refs": [scope_ref],
            "monitor_scope_refs": [],
        },
        "account_bindings": {},
        "order_bindings": {scope_ref: {"mount": "application.order_query"}},
        "monitor_bindings": {},
        "worker": {"max_queue_size": 8, "maintenance_interval_seconds": 30.0},
    }


def _close_default_deployment_service_host(host: dict[str, Any]) -> None:
    """Attempt graceful close, join, pipe close, and process close on every path."""

    process = host["process"]
    pipe = host["pipe"]
    failures: list[BaseException] = []
    graceful_close = "not_attempted"
    join_attempted = False
    termination_attempted = False
    pipe_closed = False
    process_closed = False
    if process.is_alive() and not host.get("startup_failed", False):
        graceful_close = "failed"
        try:
            pipe.send(("close",))
            closed = _order._receive(pipe, timeout=10.0)
            assert closed[0] == "closed", closed
            graceful_close = "succeeded"
        except BaseException as error:
            failures.append(error)

    try:
        join_attempted = True
        process.join(10.0)
    except BaseException as error:
        failures.append(error)

    try:
        alive = process.is_alive()
        if alive:
            try:
                termination_attempted = True
                process.terminate()
                process.join(10.0)
            except BaseException as error:
                failures.append(error)
            if process.is_alive():
                failures.append(AssertionError("synthetic execution service did not exit"))
        exit_code = process.exitcode
    except BaseException as error:
        failures.append(error)
        exit_code = None

    try:
        pipe.close()
        pipe_closed = True
    except BaseException as error:
        failures.append(error)
    try:
        process.close()
        process_closed = True
    except BaseException as error:
        failures.append(error)

    if exit_code != 0:
        failures.append(AssertionError(f"synthetic execution service exit code was {exit_code!r}"))
    diagnostic = host.get("account_book_diagnostic")
    if isinstance(diagnostic, dict):
        diagnostic["cleanup"] = {
            "graceful_close": graceful_close,
            "join_attempted": join_attempted,
            "termination_attempted": termination_attempted,
            "exit_code": exit_code if type(exit_code) is int else None,
            "pipe_closed": pipe_closed,
            "process_closed": process_closed,
            "failure_count": len(failures),
            "failure_chain": tuple(
                (
                    type(error).__name__
                    if type(error).__name__.isidentifier() and len(type(error).__name__) <= 64
                    else "OtherError",
                    _safe_diagnostic_code(getattr(error, "code", None)),
                )
                for error in failures[:8]
            ),
        }
        try:
            _write_account_book_diagnostic(host["diagnostic_path"], diagnostic)
        except BaseException as error:
            failures.append(error)
    if failures:
        raise AssertionError(
            f"synthetic ServiceHost cleanup had {len(failures)} failure(s)"
        ) from failures[0]


def _write_account_book_diagnostic(path: Any, diagnostic: dict[str, Any]) -> None:
    """Write only the finite, test-generated ServiceHost lifecycle projection."""

    import json

    path.write_text(
        json.dumps(diagnostic, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _safe_diagnostic_code(value: Any) -> str | None:
    if type(value) is not str or not value.isidentifier() or len(value) > 64:
        return None
    return value


def _safe_diagnostic_codes(value: Any) -> tuple[str, ...]:
    if type(value) not in (tuple, list):
        return ()
    return tuple(code for item in value[:8] if (code := _safe_diagnostic_code(item)))


def _run_default_deployment_lifespan_integration(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise trusted deployment JSON through the real app, workers, SDK, and ServiceHost."""

    import json

    import httpx
    from bt_api_py.service_execution import ServiceExecutionClient
    from pydantic import SecretStr

    import app.main as main_module
    from app.api.service_read import configure_service_read
    from app.utils import security

    monkeypatch.setattr(
        security,
        "settings",
        SimpleNamespace(JWT_SECRET_KEY=_JWT_SECRET, JWT_ALGORITHM=_JWT_ALGORITHM),
    )

    async def _no_startup(*_args: Any, **_kwargs: Any) -> None:
        return None

    class _NoopShutdownManager:
        async def initiate(self, _app: Any) -> None:
            return None

    import app.services.quote_service as quote_service

    monkeypatch.setattr(main_module, "run_startup", _no_startup)
    monkeypatch.setattr(main_module, "run_shutdown", _no_startup)
    monkeypatch.setattr(main_module, "GracefulShutdownManager", _NoopShutdownManager)
    monkeypatch.setattr(main_module.settings, "RAG_VECTOR_ENABLED", False)
    monkeypatch.setattr(
        quote_service,
        "get_quote_service",
        lambda: SimpleNamespace(shutdown=lambda: None),
    )

    context = multiprocessing.get_context("spawn")
    endpoint = _order._endpoint()
    server_public, server_secret = zmq.curve_keypair()
    keypairs = {name: zmq.curve_keypair() for name in ("strategy_a", "strategy_b", "application")}
    keys: dict[str, bytes] = {"server_public": server_public, "server_secret": server_secret}
    for name, (public_key, secret_key) in keypairs.items():
        keys[f"{name}_public"] = public_key
        keys[f"{name}_secret"] = secret_key
    service_keys = {
        key: value
        for key, value in keys.items()
        if key.endswith("_public") or key == "server_secret"
    }

    host = None
    producer_runtimes: list[Any] = []
    deployment = None
    owner_threads: tuple[threading.Thread, ...] = ()
    app = main_module.app
    main_thread = threading.current_thread()
    configure_service_read(None)
    try:
        host = _order._start_process(
            context,
            _multiuser_service_process,
            (
                _order._service_config(endpoint),
                str(tmp_path / "afi-default-deployment-registry.sqlite3"),
                service_keys,
                str(tmp_path / "afi-default-deployment-execution.sqlite3"),
            ),
            "afi-default-deployment-execution-host",
        )
        assert host["process"].name == "afi-default-deployment-execution-host"
        assert endpoint.startswith("tcp://127.0.0.1:")
        ready = _order._receive(host["pipe"], timeout=20.0)
        assert ready[0] == "ready", ready
        assert host["process"].is_alive()

        strategy_profiles = (
            (
                "strategy_a",
                _STRATEGY_A_PRINCIPAL,
                _STRATEGY_A,
                _ENTRY_SCOPE_A,
                _SCOPE_A,
                "afi-strategy-a-curve-v1",
                _INTENT_A,
                "signal-user-a",
            ),
            (
                "strategy_b",
                _STRATEGY_B_PRINCIPAL,
                _STRATEGY_B,
                _ENTRY_SCOPE_B,
                _SCOPE_B,
                "afi-strategy-b-curve-v1",
                _INTENT_B,
                "signal-user-b",
            ),
        )
        for (
            key_name,
            principal,
            actor,
            scope_ref,
            scope,
            security_ref,
            intent,
            signal,
        ) in strategy_profiles:
            identity = WireIdentity(WireRole.STRATEGY_CLIENT, principal, actor)
            runtime = _new_runtime(
                endpoint,
                role="strategy_client",
                security_ref=security_ref,
                keys={
                    **keys,
                    f"{security_ref}_public": keys[f"{key_name}_public"],
                    f"{security_ref}_secret": keys[f"{key_name}_secret"],
                },
                identity=identity,
                scope_ref=scope_ref,
                scope=scope,
            )
            producer_runtimes.append(runtime)
            assert runtime.start().degraded_count == 0
            submitter = ServiceExecutionClient(runtime, "broker.orders", scope_ref=scope_ref)
            _order._submit(submitter, intent, signal, "1")

        profiles = [
            _default_order_read_profile(
                endpoint=endpoint,
                subject=subject,
                identity=identity,
                account_ref=account_ref,
                scope_ref=scope_ref,
                scope=scope,
                security_ref=f"afi-{subject}-dashboard-curve-v1",
                keys=keys,
            )
            for subject, identity, account_ref, scope_ref, scope in (
                (_SUBJECT_A, _APPLICATION_IDENTITY_A, _ACCOUNT_A, _QUERY_SCOPE_A, _SCOPE_A),
                (_SUBJECT_B, _APPLICATION_IDENTITY_B, _ACCOUNT_B, _QUERY_SCOPE_B, _SCOPE_B),
            )
        ]
        deployment_config = json.dumps({"schema_version": 1, "subjects": profiles})
        monkeypatch.setattr(
            main_module.settings,
            "SERVICE_READ_DEPLOYMENT_JSON",
            SecretStr(deployment_config),
        )

        async def _exercise_http() -> None:
            nonlocal deployment, owner_threads
            async with main_module.lifespan(app):
                deployment = app.state.service_read_deployment
                assert deployment is not None
                workers = deployment._workers
                assert len(workers) == 2
                owner_threads = tuple(worker._thread for worker in workers)
                assert all(thread is not None and thread.is_alive() for thread in owner_threads)
                assert len({thread.ident for thread in owner_threads}) == 2
                assert all(thread is not main_thread for thread in owner_threads)

                token_a = _make_token(_SUBJECT_A, _JWT_SECRET)
                token_b = _make_token(_SUBJECT_B, _JWT_SECRET)
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://service-read.default-deployment.test",
                ) as client:
                    own_a = await client.get(
                        f"/api/v1/service-read/orders/{_INTENT_A}",
                        params={"scope_ref": _QUERY_SCOPE_A, "sub": _SUBJECT_B},
                        headers={
                            "Authorization": f"Bearer {token_a}",
                            "X-User-Id": _SUBJECT_B,
                        },
                    )
                    own_b = await client.get(
                        f"/api/v1/service-read/orders/{_INTENT_B}",
                        params={"scope_ref": _QUERY_SCOPE_B},
                        headers={"Authorization": f"Bearer {token_b}"},
                    )
                    assert own_a.status_code == own_b.status_code == 200
                    assert own_a.json()["intent_id"] == _INTENT_A
                    assert own_a.json()["state"] == "ACKED"
                    assert own_a.json()["provider_order_id"] == "provider-order-1"
                    assert own_b.json()["intent_id"] == _INTENT_B
                    assert own_b.json()["state"] == "ACKED"
                    assert own_b.json()["provider_order_id"] == "provider-order-2"

                    denied_a_on_b = await client.get(
                        f"/api/v1/service-read/orders/{_INTENT_B}",
                        params={"scope_ref": _QUERY_SCOPE_B},
                        headers={"Authorization": f"Bearer {token_a}"},
                    )
                    denied_a_scope_b = await client.get(
                        f"/api/v1/service-read/orders/{_INTENT_A}",
                        params={"scope_ref": _QUERY_SCOPE_B},
                        headers={"Authorization": f"Bearer {token_a}"},
                    )
                    denied_b_scope_a = await client.get(
                        f"/api/v1/service-read/orders/{_INTENT_A}",
                        params={"scope_ref": _QUERY_SCOPE_A},
                        headers={"Authorization": f"Bearer {token_b}"},
                    )
                    for denied_response in (denied_a_on_b, denied_a_scope_b, denied_b_scope_a):
                        assert denied_response.status_code == 403
                        denied_payload = denied_response.json()
                        assert denied_payload["error"] == "HTTP_403"
                        assert denied_payload["details"]["code"] == "SERVICE_READ_ACCESS_DENIED"

            assert deployment is not None and deployment.closed
            assert deployment.close_failures == ()
            assert app.state.service_read_deployment is None
            assert all(not thread.is_alive() for thread in owner_threads)
            assert all(not worker._close_failed for worker in deployment._workers)

        asyncio.run(_exercise_http())
        counts = _order._command(host, "counts")
        assert counts[1] == (_INTENT_A, _INTENT_B)
        assert counts[2] == (_INTENT_A, _INTENT_B)
    finally:
        try:
            configure_service_read(None)
        finally:
            runtime_close_errors: list[BaseException] = []
            try:
                for runtime in reversed(producer_runtimes):
                    try:
                        _close_runtime(runtime)
                    except BaseException as error:
                        runtime_close_errors.append(error)
            finally:
                if host is not None:
                    _close_default_deployment_service_host(host)
            if runtime_close_errors:
                raise AssertionError(
                    f"{len(runtime_close_errors)} synthetic producer runtime(s) failed to close"
                ) from runtime_close_errors[0]


def test_default_deployment_lifespan_uses_production_sdk_workers_and_enforces_subject_grants(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the default production composition with synthetic loopback services only."""

    _COMMAND_GUARD_STATE["active"] = True
    try:
        _run_default_deployment_lifespan_integration(tmp_path, monkeypatch)
    finally:
        _COMMAND_GUARD_STATE["active"] = False


def _run_live_composition_projection(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    authorization_matrix: bool,
) -> None:
    """Use the normal HTTP and AFI worker path for synthetic SDK account-book facts."""

    import json
    from pathlib import Path

    import httpx
    from bt_api_base.account_protocol import AccountKey
    from bt_api_execution import ExecutionScope
    from pydantic import SecretStr
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    original_is_file = Path.is_file
    original_path_isfile = os.path.isfile

    def _without_optional_slowapi_config(path: Path) -> bool:
        basename = ntpath.basename(os.fsdecode(path)).casefold()
        if basename == ".slowapi.env" or basename == ".env" or basename.startswith(".env."):
            return False
        return original_is_file(path)

    def _without_optional_dotenv_file_probe(path: Any) -> bool:
        basename = ntpath.basename(os.fsdecode(path)).casefold()
        if basename == ".env" or basename.startswith(".env."):
            return False
        return original_path_isfile(path)

    monkeypatch.setattr(Path, "is_file", _without_optional_slowapi_config)
    monkeypatch.setattr(os.path, "isfile", _without_optional_dotenv_file_probe)
    import app.api.portfolio.api as portfolio_api
    import app.main as main_module
    from app.db.database import get_db
    from app.models.portfolio_composition import PortfolioCompositionVersion
    from app.services.service_read.deployment import ServiceReadDeployment

    _COMMAND_GUARD_STATE["active"] = True
    monkeypatch.setattr(
        portfolio_api,
        "_get_manager",
        lambda: (_ for _ in ()).throw(
            AssertionError("a versioned composition must not instantiate the legacy manager")
        ),
    )
    monkeypatch.setattr(main_module.settings, "DB_AUTO_CREATE_SCHEMA", True)
    monkeypatch.setattr(main_module.settings, "RAG_VECTOR_ENABLED", False)
    server_public, server_secret = zmq.curve_keypair()
    keypairs = {name: zmq.curve_keypair() for name in ("strategy_a", "strategy_b", "application")}
    keys: dict[str, bytes] = {"server_public": server_public, "server_secret": server_secret}
    for name, (public_key, secret_key) in keypairs.items():
        keys[f"{name}_public"] = public_key
        keys[f"{name}_secret"] = secret_key
    service_keys = {
        key: value
        for key, value in keys.items()
        if key.endswith("_public") or key == "server_secret"
    }
    context = multiprocessing.get_context("spawn")
    endpoint = _order._endpoint()
    app = main_module.app
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    app_db = async_sessionmaker(engine, expire_on_commit=False)

    async def _create_tables() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(PortfolioCompositionVersion.__table__.create)

    asyncio.run(_create_tables())

    async def _override_db():
        async with app_db() as session:
            yield session

    prior_db_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_db
    host = None
    deployment: ServiceReadDeployment | None = None
    owner_threads: tuple[threading.Thread, ...] = ()
    account_key = AccountKey(
        provider="PAPER",
        venue="synthetic-venue",
        environment="simulation",
        account_id="synthetic-provider-account-id",
        subaccount_id=None,
    )
    expected_service_account_key = ExecutionScope(
        "PAPER", "simulation", _ACCOUNT_A, _STRATEGY_A, "run-a"
    ).account_key
    profile = _default_order_read_profile(
        endpoint=endpoint,
        subject=_SUBJECT_A,
        identity=_APPLICATION_IDENTITY_A,
        account_ref=_ACCOUNT_A,
        scope_ref=_BOOK_QUERY_SCOPE,
        scope=_BOOK_ACCOUNT_SCOPE,
        security_ref="afi-account-books-app-curve-v1",
        keys=keys,
    )
    profile["account_bindings"] = {}
    profile["account_book_bindings"] = {
        _ACCOUNT_A: {
            "mount": "application.order_query",
            "scope_ref": _BOOK_QUERY_SCOPE,
            "account_key": account_key.to_dict(),
        }
    }
    profile["strategy_book_bindings"] = {
        "strategy-owner-a": {"account_ref": _ACCOUNT_A, "owner_ref": _STRATEGY_A}
    }
    profile["order_bindings"] = {}
    profile["monitor_bindings"] = {}
    profile["grants"] = {
        "account_refs": [],
        "account_book_refs": [_ACCOUNT_A],
        "strategy_book_refs": ["strategy-owner-a"],
        "order_scope_refs": [],
        "monitor_scope_refs": [],
    }

    try:
        host = _order._start_process(
            context,
            _account_book_service_process,
            (
                _order._service_config(endpoint),
                str(tmp_path / "afi-account-books-registry.sqlite3"),
                service_keys,
                str(tmp_path / "afi-account-books-execution.sqlite3"),
            ),
            "afi-account-books-execution-host",
        )
        diagnostic_path = tmp_path / "account-book-service-host-diagnostic.json"
        host["diagnostic_path"] = diagnostic_path
        ready = _order._receive(host["pipe"], timeout=20.0)
        raw = ready[2] if len(ready) > 2 and isinstance(ready[2], dict) else {}
        raw_state = (
            raw.get("host_state") if ready[0] == "error" else (ready[2] if len(ready) > 2 else None)
        )
        allowed_states = {"new", "started", "closed", "failed", "close_failed", "not_created"}
        chain = raw.get("exception_chain", ())
        exception_chain = (
            tuple(
                {"type": _safe_diagnostic_code(item[0]), "code": _safe_diagnostic_code(item[1])}
                for item in chain[:5]
                if type(item) in (tuple, list) and len(item) == 2
            )
            if type(chain) in (tuple, list)
            else ()
        )
        diagnostic = {
            "schema_version": 1,
            "startup": {
                "status": "error"
                if ready[0] == "error"
                else ("ready" if ready[0] == "ready" else "unexpected"),
                "code": _safe_diagnostic_code(
                    ready[1] if ready[0] == "error" and len(ready) > 1 else None
                ),
                "host_state": (
                    raw_state
                    if type(raw_state) is str and raw_state in allowed_states
                    else "unknown"
                ),
                "start_failure": _safe_diagnostic_code(raw.get("start_failure")),
                "cleanup_failures": _safe_diagnostic_codes(raw.get("cleanup_failures")),
                "cleanup_history": _safe_diagnostic_codes(raw.get("cleanup_history")),
                "exception_chain": exception_chain,
                "loopback_endpoint": (
                    ready[1].startswith("tcp://127.0.0.1:")
                    if ready[0] == "ready" and len(ready) > 1 and type(ready[1]) is str
                    else False
                ),
            },
        }
        host["account_book_diagnostic"] = diagnostic
        _write_account_book_diagnostic(diagnostic_path, diagnostic)
        if ready[0] == "error":
            host["startup_failed"] = True
            pytest.fail(
                f"bounded account-book ServiceHost startup diagnostic saved: {diagnostic_path}",
                pytrace=False,
            )
        assert ready[0] == "ready", ready
        assert host["process"].is_alive()
        monkeypatch.setattr(
            main_module.settings,
            "SERVICE_READ_DEPLOYMENT_JSON",
            SecretStr(json.dumps({"schema_version": 1, "subjects": [profile]})),
        )

        async def _exercise_http() -> None:
            nonlocal deployment, owner_threads
            async with main_module.lifespan(app):
                deployment = app.state.service_read_deployment
                assert deployment is not None
                assert len(deployment._workers) == 1
                worker = deployment._workers[0]
                assert worker._thread is not None and worker._thread.is_alive()
                owner_threads = (worker._thread,)
                assert worker._thread is not threading.current_thread()

                token_a = _make_token(_SUBJECT_A, _JWT_SECRET)
                token_b = _make_token(_SUBJECT_B, _JWT_SECRET)
                headers_a = {"Authorization": f"Bearer {token_a}"}
                headers_b = {"Authorization": f"Bearer {token_b}"}
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://afi-account-books.synthetic.test",
                ) as client:
                    created = await client.post(
                        "/api/v1/portfolio/compositions",
                        headers=headers_a,
                        json={
                            "portfolio_ref": "execution-books-view",
                            "source_type": "live",
                            "base_currency": "USDT",
                            "members": [
                                {"kind": "account", "ref": _ACCOUNT_A},
                                {"kind": "strategy", "ref": "strategy-owner-a"},
                            ],
                        },
                    )
                    assert created.status_code == 201, created.text
                    assert created.json()["membership_version"] == 1

                    projection_response = await client.get(
                        "/api/v1/portfolio/overview",
                        params={
                            "portfolio_ref": "execution-books-view",
                            "membership_version": 1,
                        },
                        headers=headers_a,
                    )
                    assert projection_response.status_code == 200, projection_response.text
                    projection = projection_response.json()
                    assert projection["account_total"] == {
                        "status": "not_collected",
                        "currency": "USDT",
                        "value": None,
                    }
                    assert projection["accounts"] == []
                    strategy = projection["strategies"][0]
                    assert strategy["strategy_ref"] == "strategy-owner-a"
                    assert strategy["attribution_status"] == "available"
                    assert strategy["positions"] == [
                        {"instrument": "PAPER:SIM:AFI-SYNTHETIC", "net_quantity": "2.5"}
                    ]
                    assert strategy["fees_since_baseline"] == [
                        {"currency": "USDT", "amount": "0.03"}
                    ]
                    assert strategy["source_cursor"] == 0
                    assert strategy["source_state"] == "BALANCED"
                    assert projection["strategy_attribution"] == {
                        "status": "execution_account_books_current",
                        "strategy_count": 1,
                        "mapped_strategy_count": 1,
                        "attributed_value": None,
                        "unattributed_account_value": None,
                        "residual_basis": (
                            "Execution owner-book positions and fees only; "
                            "cash, account value, and FX are not calculated"
                        ),
                    }
                    assert projection["coverage"]["strategy_attribution_complete"] is True
                    assert projection["coverage"]["account_facts_complete"] is False
                    assert projection["coverage"]["complete"] is False
                    assert projection["coverage"]["code"] == "ACCOUNT_FACT_COVERAGE_INCOMPLETE"
                    assert (
                        projection["account_book_sources"][0]["coverage"][
                            "current_execution_cursor"
                        ]
                        == 0
                    )
                    assert projection["account_book_sources"][0]["position_residual"] == []
                    assert projection["account_book_sources"][0]["fee_residual"] == []
                    assert _STRATEGY_B not in projection_response.text
                    assert account_key.account_id not in projection_response.text
                    assert account_key.account_key_id not in projection_response.text
                    assert "cash" not in strategy and "value" not in strategy
                    assert projection["creditable"] is False
                    assert projection["overlap_policy"] == "non_additive_display_only"

                    if authorization_matrix:
                        forged_headers = {
                            **headers_a,
                            "X-User-Id": _SUBJECT_B,
                            "X-Actor-Ref": _SUBJECT_B,
                            "X-Principal-Ref": "forged-principal",
                            "X-Delegate-Ref": _DELEGATE_B,
                            "X-Approver-Ref": _SUBJECT_B,
                        }
                        repeated_read = await client.get(
                            "/api/v1/portfolio/overview",
                            params={
                                "portfolio_ref": "execution-books-view",
                                "membership_version": 1,
                                "actor_ref": _SUBJECT_B,
                                "principal_ref": "forged-principal",
                                "delegate_ref": _DELEGATE_B,
                                "approver_ref": _SUBJECT_B,
                            },
                            headers=forged_headers,
                        )
                        assert repeated_read.status_code == 200, repeated_read.text
                        assert repeated_read.json() == projection

                        expired_read = await client.get(
                            "/api/v1/portfolio/overview",
                            params={
                                "portfolio_ref": "execution-books-view",
                                "membership_version": 1,
                            },
                            headers={
                                "Authorization": (
                                    "Bearer "
                                    + _make_token(
                                        _SUBJECT_A,
                                        _JWT_SECRET,
                                        expires_at=int(time.time()) - 60,
                                    )
                                )
                            },
                        )
                        assert expired_read.status_code == 401

                        forged_scope = await client.get(
                            f"/api/v1/service-read/orders/{_INTENT_A}",
                            params={
                                "scope_ref": _BOOK_QUERY_SCOPE,
                                "actor_ref": _SUBJECT_A,
                                "approver_ref": _SUBJECT_B,
                            },
                            headers=forged_headers,
                        )
                        assert forged_scope.status_code == 403
                        assert (
                            forged_scope.json()["details"]["code"] == "SERVICE_READ_ACCESS_DENIED"
                        )

                        cross_account_read = await client.get(
                            f"/api/v1/service-read/accounts/{_ACCOUNT_B}",
                            headers=forged_headers,
                        )
                        assert cross_account_read.status_code == 403
                        assert (
                            cross_account_read.json()["details"]["code"]
                            == "SERVICE_READ_ACCESS_DENIED"
                        )

                        read_write_method = await client.post(
                            f"/api/v1/service-read/orders/{_INTENT_A}",
                            headers=forged_headers,
                            json={"approver_ref": _SUBJECT_B, "scope_ref": _BOOK_QUERY_SCOPE},
                        )
                        assert read_write_method.status_code == 405

                        forged_approver_membership = await client.post(
                            "/api/v1/portfolio/compositions",
                            headers=headers_a,
                            json={
                                "portfolio_ref": "forged-approver-view",
                                "source_type": "live",
                                "base_currency": "USDT",
                                "members": [
                                    {"kind": "account", "ref": _ACCOUNT_A},
                                    {"kind": "strategy", "ref": "strategy-owner-a"},
                                ],
                                "approver_ref": _SUBJECT_B,
                            },
                        )
                        assert forged_approver_membership.status_code == 422

                    unbound_owner = await client.post(
                        "/api/v1/portfolio/compositions",
                        headers=headers_a,
                        json={
                            "portfolio_ref": "unbound-owner-view",
                            "source_type": "live",
                            "base_currency": "USDT",
                            "members": [
                                {"kind": "account", "ref": _ACCOUNT_A},
                                {"kind": "strategy", "ref": _STRATEGY_B},
                            ],
                        },
                    )
                    assert unbound_owner.status_code == 201, unbound_owner.text
                    unbound_response = await client.get(
                        "/api/v1/portfolio/overview",
                        params={"portfolio_ref": "unbound-owner-view", "membership_version": 1},
                        headers=headers_a,
                    )
                    assert unbound_response.status_code == 200
                    unbound_projection = unbound_response.json()
                    assert unbound_projection["strategies"] == [
                        {
                            "strategy_ref": _STRATEGY_B,
                            "attribution_status": "execution_attribution_not_collected",
                            "attributed_value": None,
                        }
                    ]
                    assert unbound_projection["account_book_sources"] == []
                    assert _STRATEGY_A not in unbound_response.text

                    cross_account = await client.post(
                        "/api/v1/portfolio/compositions",
                        headers=headers_a,
                        json={
                            "portfolio_ref": "cross-account-view",
                            "source_type": "live",
                            "base_currency": "USDT",
                            "members": [
                                {"kind": "account", "ref": _ACCOUNT_B},
                                {"kind": "strategy", "ref": "strategy-owner-a"},
                            ],
                        },
                    )
                    assert cross_account.status_code == 403
                    assert cross_account.json()["details"]["code"] == "SERVICE_READ_ACCESS_DENIED"

                    cross_owner = await client.get(
                        "/api/v1/portfolio/overview",
                        params={
                            "portfolio_ref": "execution-books-view",
                            "membership_version": 1,
                        },
                        headers=headers_b,
                    )
                    assert cross_owner.status_code == 404

            assert deployment is not None and deployment.closed
            assert deployment.close_failures == ()
            assert app.state.service_read_deployment is None
            assert all(not thread.is_alive() for thread in owner_threads)
            assert not deployment._workers[0]._close_failed

        from app.services.service_read.session import SdkServiceReadSession

        session_method_phases = {
            SdkServiceReadSession.__init__.__code__: "constructed",
            SdkServiceReadSession.start.__code__: "started",
            SdkServiceReadSession.read_account_book.__code__: "read_account_book",
            SdkServiceReadSession.close.__code__: "closed",
        }
        session_owner_events: list[tuple[str, int]] = []
        session_events_lock = threading.Lock()

        def _observe_session_owner(frame: Any, event: str, _argument: Any) -> None:
            if event != "call":
                return
            phase = session_method_phases.get(frame.f_code)
            if phase is not None:
                with session_events_lock:
                    session_owner_events.append((phase, threading.get_ident()))

        prior_thread_profile = threading.getprofile()
        try:
            threading.setprofile(_observe_session_owner)
            asyncio.run(_exercise_http())
        finally:
            threading.setprofile(prior_thread_profile)
            owner_thread_diagnostic = {
                "phases": tuple(phase for phase, _thread_id in session_owner_events),
                "thread_ids": tuple(thread_id for _phase, thread_id in session_owner_events),
            }
            host["account_book_diagnostic"]["afi_session_owner"] = owner_thread_diagnostic
            _write_account_book_diagnostic(host["diagnostic_path"], host["account_book_diagnostic"])

        assert {phase for phase, _thread_id in session_owner_events} == {
            "constructed",
            "started",
            "read_account_book",
            "closed",
        }
        assert owner_threads and owner_threads[0].ident is not None
        assert {thread_id for _phase, thread_id in session_owner_events} == {owner_threads[0].ident}
        assert owner_threads[0].ident != threading.get_ident()

        metrics = _order._command(host, "metrics")
        assert metrics == ("metrics", 2 if authorization_matrix else 1)
        if authorization_matrix:
            assert _order._command(host, "authorization_facts") == (
                "authorization_facts",
                (
                    (
                        _APP_PRINCIPAL,
                        _APPLICATION_IDENTITY_A.principal_ref,
                        _SUBJECT_A,
                        _DELEGATE_A,
                        _ACCOUNT_A,
                        expected_service_account_key,
                    ),
                    (
                        _APP_PRINCIPAL,
                        _APPLICATION_IDENTITY_A.principal_ref,
                        _SUBJECT_A,
                        _DELEGATE_A,
                        _ACCOUNT_A,
                        expected_service_account_key,
                    ),
                ),
            )
            assert _order._command(host, "write_counts") == ("write_counts", (), ())
    finally:
        app.dependency_overrides.pop(get_db, None)
        if prior_db_override is not None:
            app.dependency_overrides[get_db] = prior_db_override
        try:
            if host is not None:
                _close_default_deployment_service_host(host)
        finally:
            asyncio.run(engine.dispose())
            _COMMAND_GUARD_STATE["active"] = False


def test_live_composition_projects_only_trusted_strategy_books_from_sdk_host(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run_live_composition_projection(tmp_path, monkeypatch, authorization_matrix=False)


def test_afi01_read_authorization_matrix_keeps_http_identity_scope_and_replay_boundaries(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run_live_composition_projection(tmp_path, monkeypatch, authorization_matrix=True)


_DUAL_LIVE_DOMAIN = "paper:afi-dual-live-composition"
_DUAL_LIVE_PRINCIPAL = "afi-dual-live-application-principal"
_DUAL_LIVE_APPLICATION_IDENTITY = WireIdentity(
    WireRole.APPLICATION_CLIENT, _DUAL_LIVE_PRINCIPAL, _SUBJECT_A, _DELEGATE_A
)
_DUAL_LIVE_VALUES = {
    # Cash totals exclude holdings; the synthetic position mark is 10 USDT
    # per unit, so reported equity includes the marked position value.
    _ACCOUNT_A: {
        "total": "100",
        "cash": "80",
        "locked": "20",
        "position_quantity": "6",
        "average_price": "10",
        "position_mark": "10",
    },
    _ACCOUNT_B: {
        "total": "700",
        "cash": "650",
        "locked": "50",
        "position_quantity": "9",
        "average_price": "10",
        "position_mark": "10",
    },
}


class _DualLiveSyntheticAccountProvider:
    """One synthetic Gateway-owned account snapshot with finite lifecycle counts."""

    def __init__(self, account_key: Any, account_ref: str) -> None:
        self.account_key = account_key
        self.account_ref = account_ref
        self.generation: str | None = None
        self.connect_calls = 0
        self.read_calls = 0
        self.close_calls = 0

    def connect(self, *, account_key: Any, generation: str, timeout: float) -> None:
        if account_key != self.account_key or not generation or timeout <= 0 or self.generation:
            raise AssertionError("invalid synthetic account-session connect")
        self.connect_calls += 1
        self.generation = generation

    def read_account(self, *, generation: str, timeout: float) -> Any:
        from datetime import UTC, datetime
        from decimal import Decimal

        from bt_api_base.account_protocol import (
            AccountBalance,
            AccountObservation,
            AccountPosition,
            AccountResourceKey,
            AccountValuation,
        )
        from bt_api_base.market_protocol import MarketInstrumentKey

        if generation != self.generation or timeout <= 0:
            raise AssertionError("synthetic account read used a stale session")
        self.read_calls += 1
        values = _DUAL_LIVE_VALUES[self.account_ref]
        observed_at = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        resource = AccountResourceKey("spot", "cash")
        suffix = self.account_ref[-1].upper()
        instrument_id = f"PAPER:SIM:AFI-DUAL-{suffix}"
        position_quantity = values["position_quantity"]
        average_price = values["average_price"]
        position_mark = Decimal(values["position_mark"])
        equity = Decimal(values["total"]) + Decimal(position_quantity) * position_mark
        return AccountObservation(
            account_key=self.account_key,
            observation_id=f"{self.account_ref}-snapshot-{self.read_calls}",
            coverage=(resource,),
            balances=(
                AccountBalance(
                    resource=resource,
                    currency="USDT",
                    total=values["total"],
                    available=values["cash"],
                    locked=values["locked"],
                    observed_at_utc=observed_at,
                ),
            ),
            positions=(
                AccountPosition(
                    resource=resource,
                    instrument=MarketInstrumentKey(
                        provider=self.account_key.provider,
                        venue=self.account_key.venue,
                        environment=self.account_key.environment,
                        product_type=resource.product_type,
                        instrument_id=instrument_id,
                        native_symbol=f"AFI-DUAL-{suffix}",
                    ),
                    side="net",
                    quantity=position_quantity,
                    qty_unit="unit",
                    average_price=average_price,
                    price_currency="USDT",
                    observed_at_utc=observed_at,
                ),
            ),
            valuation=AccountValuation(
                currency="USDT",
                available_cash=values["cash"],
                equity=format(equity, "f"),
                observed_at_utc=observed_at,
            ),
            started_at_utc=observed_at,
            completed_at_utc=observed_at,
            consistency="provider_atomic",
            balances_complete=True,
            positions_complete=True,
        )

    def close(self) -> bool:
        self.close_calls += 1
        self.generation = None
        return True


class _DualLiveSyntheticAccountBookSource:
    """Synthetic source facts consumed by the real Execution account-book adapter."""

    def __init__(self, account_ref: str, strategy_ref: str) -> None:
        from bt_api_base.service_protocol import WireScope
        from bt_api_execution import ExecutionScope

        self.account_ref = account_ref
        self.strategy_ref = strategy_ref
        self.execution_scope = ExecutionScope(
            "PAPER", "simulation", account_ref, strategy_ref, f"run-{account_ref}"
        )
        self.wire_scope = WireScope(
            _DUAL_LIVE_DOMAIN, account_ref=account_ref, strategy_ref=strategy_ref
        )
        self.account_key = self.execution_scope.account_key
        self.baseline_as_of_ns = time.time_ns()
        self.read_count = 0

    def authorize_account_view(
        self, *, principal_ref: str, identity: Any, scope: Any, account_key: str
    ) -> bool:
        from bt_api_base.service_protocol import WireScope

        return (
            principal_ref == _DUAL_LIVE_PRINCIPAL
            and identity == _DUAL_LIVE_APPLICATION_IDENTITY
            and scope == WireScope(_DUAL_LIVE_DOMAIN, account_ref=self.account_ref)
            and account_key == self.account_key
        )

    def read_inputs(
        self, *, account_key: str, journal_generation: str, execution_cursor: int
    ) -> Any:
        from decimal import Decimal

        from bt_api_execution import (
            AllocationOwnerKind,
            CurrencyAmount,
            ExecutionAccountSnapshot,
            ExecutionAllocationBaseline,
            ExecutionOwnerScope,
            ExecutionScopeDirectory,
            ExternalActivitySnapshot,
            ExternalFillFact,
            ExternalOrderFact,
            OwnerPosition,
            PositionFact,
            Side,
        )
        from bt_api_py.service_execution_account_books import ExecutionAccountBookReadInputsV1

        if account_key != self.account_key or type(execution_cursor) is not int:
            raise AssertionError("execution account-book source crossed its trusted account")
        self.read_count += 1
        suffix = self.account_ref[-1].upper()
        strategy_ref = self.strategy_ref
        baseline_ns = self.baseline_as_of_ns
        as_of_ns = baseline_ns + 100
        revision = f"afi-dual-directory-{suffix}-r1"
        generation = f"afi-dual-provider-generation-{suffix}-r1"
        instrument = f"PAPER:SIM:AFI-DUAL-{suffix}"
        baseline_quantity = Decimal("5") if self.account_ref == _ACCOUNT_A else Decimal("7")
        current_quantity = Decimal(_DUAL_LIVE_VALUES[self.account_ref]["position_quantity"])
        allocated_quantity = Decimal("2") if self.account_ref == _ACCOUNT_A else Decimal("3")
        fill_quantity = Decimal("0.5") if self.account_ref == _ACCOUNT_A else Decimal("1")
        baseline_fee = Decimal("0.10") if self.account_ref == _ACCOUNT_A else Decimal("0.20")
        current_fee = Decimal("0.20") if self.account_ref == _ACCOUNT_A else Decimal("0.40")
        fill_fee = Decimal("0.06") if self.account_ref == _ACCOUNT_A else Decimal("0.13")
        directory = ExecutionScopeDirectory(
            account_key=account_key,
            source="afi-dual-synthetic-owner-directory",
            source_ref=f"afi-dual-directory-source-{suffix}-r1",
            revision=revision,
            covers_from_ns=baseline_ns,
            as_of_ns=as_of_ns,
            scopes=(
                ExecutionOwnerScope(
                    self.execution_scope,
                    AllocationOwnerKind.STRATEGY,
                    strategy_ref,
                    self.wire_scope,
                ),
            ),
        )
        baseline = ExecutionAccountSnapshot(
            account_key=account_key,
            source="afi-dual-synthetic-account-snapshot",
            source_ref=f"afi-dual-baseline-{suffix}-r1",
            generation=generation,
            journal_generation=journal_generation,
            as_of_ns=baseline_ns,
            execution_cursor=0,
            position_mode="NET",
            positions=(PositionFact(instrument, baseline_quantity),),
            cumulative_fees=(CurrencyAmount("USDT", baseline_fee),),
            fee_coverage_start_ns=baseline_ns,
        )
        current = ExecutionAccountSnapshot(
            account_key=account_key,
            source="afi-dual-synthetic-account-snapshot",
            source_ref=f"afi-dual-current-{suffix}-r1",
            generation=generation,
            journal_generation=journal_generation,
            as_of_ns=as_of_ns,
            execution_cursor=execution_cursor,
            position_mode="NET",
            positions=(PositionFact(instrument, current_quantity),),
            cumulative_fees=(CurrencyAmount("USDT", current_fee),),
            fee_coverage_start_ns=baseline_ns,
        )
        allocation = ExecutionAllocationBaseline(
            account_key=account_key,
            source="afi-dual-synthetic-allocation-baseline",
            source_ref=f"afi-dual-allocation-{suffix}-r1",
            revision=f"afi-dual-allocation-revision-{suffix}-r1",
            scope_directory_revision=revision,
            provider_generation=generation,
            journal_generation=journal_generation,
            as_of_ns=baseline_ns,
            execution_cursor=0,
            positions=(
                OwnerPosition(
                    AllocationOwnerKind.STRATEGY,
                    strategy_ref,
                    instrument,
                    allocated_quantity,
                ),
            ),
        )
        order_ref = f"afi-dual-synthetic-order-{suffix}"
        activity = ExternalActivitySnapshot(
            account_key=account_key,
            source="afi-dual-synthetic-account-activity",
            source_ref=f"afi-dual-activity-{suffix}-r1",
            generation=generation,
            coverage_start_ns=baseline_ns,
            coverage_end_ns=as_of_ns,
            fills=(
                ExternalFillFact(
                    f"afi-dual-synthetic-fill-{suffix}",
                    instrument,
                    Side.BUY,
                    fill_quantity,
                    Decimal("100"),
                    baseline_ns + 10,
                    fee=fill_fee,
                    fee_currency="USDT",
                    provider_order_ref=order_ref,
                ),
            ),
            orders=(
                ExternalOrderFact(
                    order_ref,
                    instrument,
                    Side.BUY,
                    fill_quantity,
                    fill_quantity,
                    "FILLED",
                    baseline_ns + 10,
                    owner_kind=AllocationOwnerKind.STRATEGY,
                    owner_ref=strategy_ref,
                ),
            ),
        )
        return ExecutionAccountBookReadInputsV1(directory, baseline, current, allocation, activity)


def _dual_gateway_service_config(
    endpoint: str,
    account_ref: str,
    service_id: str,
    instance_id: str,
    scope_ref: str,
    transport_ref: str,
    security_ref: str,
) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": service_id,
        "scope_ref": scope_ref,
        "transport_ref": transport_ref,
        "registration_policy_ref": f"{account_ref}-gateway-policy-v1",
        "service_requirements_ref": f"{account_ref}-gateway-requirements-v1",
        "components": {
            "gateway": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": instance_id,
                    "bind_ports": ["service.account_read", "service.provider_session"],
                    "options": {
                        "role": "account_session_worker",
                        "account_session_ref": f"{account_ref}-session-v1",
                    },
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                transport_ref: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": security_ref,
                    "options": {"high_water_mark": 32, "max_message_bytes": _MAX_MESSAGE_BYTES},
                }
            },
        },
    }


def _dual_execution_service_config(
    endpoint: str,
    account_ref: str,
    service_id: str,
    instance_id: str,
    scope_ref: str,
    transport_ref: str,
    security_ref: str,
) -> dict[str, Any]:
    raw = _order._service_config(endpoint)
    old_transport_ref = raw["transport_ref"]
    raw["service_id"] = service_id
    raw["scope_ref"] = scope_ref
    raw["transport_ref"] = transport_ref
    raw["registration_policy_ref"] = f"{account_ref}-execution-policy-v1"
    raw["service_requirements_ref"] = f"{account_ref}-execution-requirements-v1"
    settings = raw["components"]["execution"]["settings"]
    settings["instance_id"] = instance_id
    profile = raw["communication"]["profiles"].pop(old_transport_ref)
    profile["endpoints"] = {"rpc_bind": endpoint}
    profile["security_profile_ref"] = security_ref
    raw["communication"]["profiles"][transport_ref] = profile
    return raw


def _dual_gateway_service_process(
    control: Any,
    raw_config: dict[str, Any],
    registry_path: str,
    journal_path: str,
    guard_directory: str,
    account_ref: str,
    client_scope_ref: str,
    account_key_values: dict[str, Any],
    service_keys: dict[str, bytes],
) -> None:
    """Spawn target: one actual Gateway ServiceHost and one synthetic account session."""

    from pathlib import Path

    from bt_api_base.account_protocol import AccountKey, AccountResourceKey
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_gateway import GatewayEventJournal
    from bt_api_gateway.account_session_worker import GatewayAccountSessionWorker
    from bt_api_gateway.router import GatewayCommandKind, GatewayPrincipal
    from bt_api_gateway.service_component import GatewayServiceAccountScope
    from bt_api_gateway.session_guard import LocalAccountSessionGuard
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

    config = parse_service_config(raw_config)
    account_key = AccountKey.from_dict(account_key_values)
    journal = GatewayEventJournal(journal_path)
    provider = _DualLiveSyntheticAccountProvider(account_key, account_ref)
    journal_scope = f"afi-dual-journal:{account_ref}"
    state_scope = f"afi-dual-state:{account_ref}"
    account_scope = GatewayServiceAccountScope(
        account_ref=account_ref,
        execution_domain_ref=_DUAL_LIVE_DOMAIN,
        journal_account_scope=journal_scope,
        account_read_strategy_scope=state_scope,
        shared_account_facts_scope=state_scope,
    )
    principal = GatewayPrincipal(
        principal_id=_DUAL_LIVE_PRINCIPAL,
        account_scopes=frozenset({journal_scope}),
        strategy_scopes=frozenset({state_scope}),
        allowed_kinds=frozenset({GatewayCommandKind.READ}),
    )
    holder: dict[str, Any] = {}

    def resource_provider(component: str, _instance_id: str, options: Any, _scope: Any):
        if component != "gateway" or options.get("role") != "account_session_worker":
            raise AssertionError("unexpected dual-live Gateway resource request")
        worker = GatewayAccountSessionWorker(
            provider,
            journal,
            account_key=account_key,
            journal_account_scope=journal_scope,
            state_scope=state_scope,
            guard=LocalAccountSessionGuard(
                Path(guard_directory), account_key.account_key_id, owner_ref=f"afi-{account_ref}"
            ),
            required_coverage=(AccountResourceKey("spot", "cash"),),
            refresh_interval_seconds=3600,
            max_staleness_seconds=7200,
            request_timeout_seconds=2,
        )
        holder["worker"] = worker
        return ComponentResources.owned(
            {
                "journal": journal,
                "accounts": {account_ref: account_scope},
                "principals": {_DUAL_LIVE_PRINCIPAL: principal},
            },
            ready=lambda: True,
            close=worker.close,
            internal_ports={"service.provider_session": worker},
        )

    identity = _DUAL_LIVE_APPLICATION_IDENTITY
    app_grant = ResourceGrant(
        config.components["gateway"]["settings"]["instance_id"],
        "service.account_read",
        client_scope_ref,
        WireScope(_DUAL_LIVE_DOMAIN, account_ref=account_ref),
        frozenset({"account.snapshot"}),
    )
    host = None
    try:
        host = ServiceHost(
            config,
            TrustedServiceAuthority(
                identity=WireIdentity(
                    WireRole.SERVICE, f"{config.service_id}-principal", config.service_id
                ),
                scope=WireScope(_DUAL_LIVE_DOMAIN),
                scope_ref=config.scope_ref,
                scope_version=f"{account_ref}-gateway-scope-v1",
                security_ref=service_keys["security_ref"],
                security_version="curve-key-v1",
                registration_policy_ref=config.registration_policy_ref,
                registration_policy_version=f"{account_ref}-gateway-policy-v1",
                service_requirements_ref=config.service_requirements_ref,
                service_requirements_version=f"{account_ref}-gateway-requirements-v1",
                curve_public_key=service_keys["server_public"],
                curve_secret_key=service_keys["server_secret"],
                principals={service_keys["application_public"]: _DUAL_LIVE_PRINCIPAL},
                grants={_DUAL_LIVE_PRINCIPAL: (PrincipalGrant(identity, (app_grant,)),)},
            ),
            registry_path,
            resource_provider,
        )
        host.start()
        worker = holder["worker"]
        control.send(
            (
                "ready",
                host.endpoint,
                host.state,
                {
                    "worker_state": worker.state,
                    "worker_ready": worker.ready,
                    "connect_calls": provider.connect_calls,
                    "read_calls": provider.read_calls,
                    "close_calls": provider.close_calls,
                    "account_key_id": account_key.account_key_id,
                },
            )
        )
        while True:
            host.serve_once(timeout_ms=10)
            if not control.poll():
                continue
            command = control.recv()
            if command == ("close",):
                host.close()
                control.send(
                    (
                        "closed",
                        host.state,
                        provider.connect_calls,
                        provider.read_calls,
                        provider.close_calls,
                        worker.state,
                    )
                )
                return
            if command == ("status",):
                worker = holder["worker"]
                control.send(
                    (
                        "status",
                        provider.connect_calls,
                        provider.read_calls,
                        provider.close_calls,
                        worker.ready,
                    )
                )
                continue
            raise AssertionError("unknown synthetic Gateway host command")
    except BaseException as error:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(Exception):
            control.send(("error", getattr(error, "code", type(error).__name__)))
        raise
    finally:
        control.close()


def _dual_execution_service_process(
    control: Any,
    raw_config: dict[str, Any],
    registry_path: str,
    store_path: str,
    account_ref: str,
    strategy_ref: str,
    client_scope_ref: str,
    service_keys: dict[str, bytes],
) -> None:
    """Spawn target: one actual Execution ServiceHost with one trusted owner book."""

    from bt_api_execution import SqliteExecutionStore
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

    config = parse_service_config(raw_config)
    store = SqliteExecutionStore(store_path)
    provider = _CountingProvider()
    gate = _order._Gate()
    source = _DualLiveSyntheticAccountBookSource(account_ref, strategy_ref)
    scope = WireScope(_DUAL_LIVE_DOMAIN, account_ref=account_ref, strategy_ref=strategy_ref)
    account_scope = WireScope(_DUAL_LIVE_DOMAIN, account_ref=account_ref)
    execution_scope = source.execution_scope
    targets = {scope: execution_scope}
    instance_id = config.components["execution"]["settings"]["instance_id"]
    app_identity = _DUAL_LIVE_APPLICATION_IDENTITY
    app_grant = ResourceGrant(
        instance_id,
        "service.order_query",
        client_scope_ref,
        account_scope,
        frozenset({"execution.account_books.query"}),
    )

    def resource_provider(component: str, requested_instance: str, _options: Any, _scope: Any):
        if component != "execution" or requested_instance != instance_id:
            raise AssertionError("unexpected dual-live Execution resource request")
        return ComponentResources.borrowed(
            {
                "store": store,
                "targets": targets,
                "dispatch": provider,
                "admission": {"order_gate": gate, "cancel_gate": gate},
                "account_books": source,
            },
            ready=lambda: True,
        )

    host = None
    try:
        host = ServiceHost(
            config,
            TrustedServiceAuthority(
                identity=WireIdentity(
                    WireRole.SERVICE, f"{config.service_id}-principal", config.service_id
                ),
                scope=WireScope(_DUAL_LIVE_DOMAIN),
                scope_ref=config.scope_ref,
                scope_version=f"{account_ref}-execution-scope-v1",
                security_ref=service_keys["security_ref"],
                security_version="curve-key-v1",
                registration_policy_ref=config.registration_policy_ref,
                registration_policy_version=f"{account_ref}-execution-policy-v1",
                service_requirements_ref=config.service_requirements_ref,
                service_requirements_version=f"{account_ref}-execution-requirements-v1",
                curve_public_key=service_keys["server_public"],
                curve_secret_key=service_keys["server_secret"],
                principals={service_keys["application_public"]: _DUAL_LIVE_PRINCIPAL},
                grants={_DUAL_LIVE_PRINCIPAL: (PrincipalGrant(app_identity, (app_grant,)),)},
            ),
            registry_path,
            resource_provider,
        )
        host.start()
        control.send(("ready", host.endpoint, host.state))
        while True:
            host.serve_once(timeout_ms=10)
            if not control.poll():
                continue
            command = control.recv()
            if command == ("close",):
                host.close()
                store.close()
                control.send(("closed", host.state, source.read_count))
                return
            if command == ("status",):
                control.send(("status", source.read_count))
                continue
            raise AssertionError("unknown synthetic Execution host command")
    except BaseException as error:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(BaseException):
            store.close()
        with suppress(Exception):
            control.send(("error", getattr(error, "code", type(error).__name__)))
        raise
    finally:
        control.close()


def _stop_dual_live_service_host(host: dict[str, Any]) -> tuple[Any, ...]:
    """Gracefully stop one test-owned process and always release its pipe/handle."""

    process, pipe = host["process"], host["pipe"]
    failures: list[BaseException] = []
    close_reply: tuple[Any, ...] = ()
    exit_code: int | None = None
    try:
        if process.is_alive() and not host.get("startup_failed", False):
            pipe.send(("close",))
            close_reply = _order._receive(pipe, timeout=15.0)
            if not close_reply or close_reply[0] != "closed":
                failures.append(AssertionError("synthetic ServiceHost did not confirm close"))
    except BaseException as error:
        failures.append(error)
    try:
        process.join(15.0)
        if process.is_alive():
            process.terminate()
            process.join(10.0)
            failures.append(AssertionError("synthetic ServiceHost required termination"))
        exit_code = process.exitcode
    except BaseException as error:
        failures.append(error)
    try:
        pipe.close()
    except BaseException as error:
        failures.append(error)
    try:
        process.close()
    except BaseException as error:
        failures.append(error)
    if exit_code != 0:
        failures.append(AssertionError(f"synthetic ServiceHost exit code was {exit_code!r}"))
    host["shutdown"] = {
        "reply": close_reply,
        "exit_code": exit_code,
        "failure_count": len(failures),
    }
    if failures:
        raise AssertionError(
            f"synthetic ServiceHost cleanup had {len(failures)} failure(s)"
        ) from failures[0]
    return close_reply


def _run_dual_live_composition_projection(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise two real SDK Gateway and Execution hosts through the production AFI HTTP path."""

    import json
    import re
    from pathlib import Path

    import httpx
    from bt_api_base.account_protocol import AccountKey, AccountResourceKey
    from pydantic import SecretStr
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    original_is_file = Path.is_file
    original_path_isfile = os.path.isfile

    def no_private_dotenv_path_probe(path: Any) -> bool:
        basename = ntpath.basename(os.fsdecode(path)).casefold()
        if basename == ".slowapi.env" or basename == ".env" or basename.startswith(".env."):
            return False
        return original_is_file(path)

    def no_private_dotenv_open(path: Any) -> bool:
        basename = ntpath.basename(os.fsdecode(path)).casefold()
        if basename == ".env" or basename.startswith(".env."):
            return False
        return original_path_isfile(path)

    monkeypatch.setattr(Path, "is_file", no_private_dotenv_path_probe)
    monkeypatch.setattr(os.path, "isfile", no_private_dotenv_open)
    import app.api.portfolio.api as portfolio_api
    import app.main as main_module
    from app.db.database import get_db
    from app.models.portfolio_composition import PortfolioCompositionVersion
    from app.services.service_read.deployment import (
        ServiceReadDeployment,
        _load_sdk_types,
        _parse_profile,
    )

    monkeypatch.setattr(
        portfolio_api,
        "_get_manager",
        lambda: (_ for _ in ()).throw(
            AssertionError("versioned composition must not instantiate the legacy manager")
        ),
    )
    monkeypatch.setattr(main_module.settings, "DB_AUTO_CREATE_SCHEMA", True)
    monkeypatch.setattr(main_module.settings, "RAG_VECTOR_ENABLED", False)
    app = main_module.app

    context = multiprocessing.get_context("spawn")
    preflight_only = os.environ.get("AFI_DUAL_LIVE_PREFLIGHT_ONLY") == "1"
    next_preflight_port = 45100

    def endpoint() -> str:
        nonlocal next_preflight_port
        if preflight_only:
            value = f"tcp://127.0.0.1:{next_preflight_port}"
            next_preflight_port += 1
            return value
        return _order._endpoint()

    account_refs = {"account-a": _ACCOUNT_A, "account-b": _ACCOUNT_B}
    strategy_refs = {"account-a": _STRATEGY_A, "account-b": _STRATEGY_B}
    account_keys = {
        name: AccountKey("PAPER", "synthetic-venue", "simulation", f"afi-{name}-id")
        for name in account_refs
    }
    assert account_keys["account-a"].account_key_id != account_keys["account-b"].account_key_id
    app_public, app_secret = zmq.curve_keypair()
    services: dict[str, dict[str, Any]] = {}
    for name in account_refs:
        gateway_endpoint = endpoint()
        gateway_server_public, gateway_server_secret = zmq.curve_keypair()
        gateway_security_ref = f"afi-dual-{name}-gateway-curve-v1"
        gateway_transport_ref = f"afi-dual-{name}-gateway-connect-v1"
        gateway_service_id = f"afi-dual-{name}-gateway-service"
        gateway_instance_id = f"afi-dual-{name}-gateway-instance"
        gateway_scope_ref = f"afi-dual-{name}-gateway-scope-v1"
        execution_endpoint = endpoint()
        execution_server_public, execution_server_secret = zmq.curve_keypair()
        execution_security_ref = f"afi-dual-{name}-execution-curve-v1"
        execution_transport_ref = f"afi-dual-{name}-execution-connect-v1"
        execution_service_id = f"afi-dual-{name}-execution-service"
        execution_instance_id = f"afi-dual-{name}-execution-instance"
        execution_service_scope_ref = f"afi-dual-{name}-execution-service-scope-v1"
        gateway_client_scope_ref = f"afi-dual-{name}-account-snapshot-v1"
        books_client_scope_ref = f"afi-dual-{name}-account-books-v1"
        services[name] = {
            "account_ref": account_refs[name],
            "strategy_ref": strategy_refs[name],
            "account_key": account_keys[name],
            "gateway": {
                "endpoint": gateway_endpoint,
                "server_public": gateway_server_public,
                "server_secret": gateway_server_secret,
                "security_ref": gateway_security_ref,
                "transport_ref": gateway_transport_ref,
                "service_id": gateway_service_id,
                "instance_id": gateway_instance_id,
                "service_scope_ref": gateway_scope_ref,
                "client_scope_ref": gateway_client_scope_ref,
                "config": _dual_gateway_service_config(
                    gateway_endpoint,
                    account_refs[name],
                    gateway_service_id,
                    gateway_instance_id,
                    gateway_scope_ref,
                    gateway_transport_ref,
                    gateway_security_ref,
                ),
            },
            "execution": {
                "endpoint": execution_endpoint,
                "server_public": execution_server_public,
                "server_secret": execution_server_secret,
                "security_ref": execution_security_ref,
                "transport_ref": execution_transport_ref,
                "service_id": execution_service_id,
                "instance_id": execution_instance_id,
                "service_scope_ref": execution_service_scope_ref,
                "client_scope_ref": books_client_scope_ref,
                "config": _dual_execution_service_config(
                    execution_endpoint,
                    account_refs[name],
                    execution_service_id,
                    execution_instance_id,
                    execution_service_scope_ref,
                    f"afi-dual-{name}-execution-listener-v1",
                    execution_security_ref,
                ),
            },
        }

    identity = _DUAL_LIVE_APPLICATION_IDENTITY
    gateway_bindings = []
    execution_bindings = []
    scope_claims: dict[str, dict[str, Any]] = {}
    peers: dict[str, dict[str, str]] = {}
    curve_keys: dict[str, dict[str, str]] = {}
    communication_profiles: dict[str, dict[str, Any]] = {}
    account_bindings: dict[str, dict[str, Any]] = {}
    account_book_bindings: dict[str, dict[str, Any]] = {}
    strategy_book_bindings: dict[str, dict[str, str]] = {}
    for _name, service in services.items():
        account_ref, strategy_ref, account_key = (
            service["account_ref"],
            service["strategy_ref"],
            service["account_key"],
        )
        for role in ("gateway", "execution"):
            endpoint = service[role]["endpoint"]
            transport_ref = service[role]["transport_ref"]
            security_ref = service[role]["security_ref"]
            peer_service_id = service[role]["service_id"]
            peer_principal = f"{peer_service_id}-principal"
            peers[peer_service_id] = {"principal_ref": peer_principal, "actor_ref": peer_service_id}
            curve_keys[security_ref] = {
                "server_key": service[role]["server_public"].decode("ascii"),
                "public_key": app_public.decode("ascii"),
                "secret_key": app_secret.decode("ascii"),
            }
            communication_profiles[transport_ref] = {
                "backend": "zmq",
                "config_schema_version": 1,
                "endpoints": {"rpc_connect": endpoint},
                "security_profile_ref": security_ref,
                "options": {
                    "request_timeout_ms": _REQUEST_TIMEOUT_MS,
                    "high_water_mark": 32,
                    "max_message_bytes": _MAX_MESSAGE_BYTES,
                },
            }
            client_scope_ref = service[role]["client_scope_ref"]
            scope_claims[client_scope_ref] = {
                "execution_domain_ref": _DUAL_LIVE_DOMAIN,
                "account_ref": account_ref,
                "strategy_ref": None,
            }
            if role == "gateway":
                gateway_bindings.append(
                    {
                        "mount": "application.account",
                        "service_id": peer_service_id,
                        "instance_id": service[role]["instance_id"],
                        "scope_ref": client_scope_ref,
                        "transport_ref": transport_ref,
                        "account_ref": account_ref,
                    }
                )
                account_bindings[account_ref] = {
                    "mount": "application.account",
                    "scope_ref": client_scope_ref,
                    "currency": "USDT",
                    "account_key": account_key.to_dict(),
                    "coverage": [AccountResourceKey("spot", "cash").to_dict()],
                    "require_open_orders": False,
                }
            else:
                execution_bindings.append(
                    {
                        "mount": "application.order_query",
                        "service_id": peer_service_id,
                        "instance_id": service[role]["instance_id"],
                        "scope_ref": client_scope_ref,
                        "transport_ref": transport_ref,
                        "account_ref": account_ref,
                    }
                )
                account_book_bindings[account_ref] = {
                    "mount": "application.order_query",
                    "scope_ref": client_scope_ref,
                    "account_key": account_key.to_dict(),
                }
                strategy_book_bindings[strategy_ref] = {
                    "account_ref": account_ref,
                    "owner_ref": strategy_ref,
                }

    client_config = {
        "client_config_schema_version": 1,
        "process_role": "application_client",
        "registration": {"application_ref": identity.actor_ref},
        "clients": {
            "gateway": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": gateway_bindings,
                    "options": {"request_timeout_ms": _REQUEST_TIMEOUT_MS},
                },
            },
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": execution_bindings,
                    "options": {"request_timeout_ms": _REQUEST_TIMEOUT_MS},
                },
            },
        },
        "communication": {"config_schema_version": 1, "profiles": communication_profiles},
    }
    profile = {
        "subject": _SUBJECT_A,
        "identity": {
            "principal_ref": identity.principal_ref,
            "actor_ref": identity.actor_ref,
            "delegate_ref": identity.delegate_ref,
        },
        "client_config": client_config,
        "scope_claims": scope_claims,
        "peer_identities": peers,
        "curve_keys": curve_keys,
        "grants": {
            "account_refs": list(account_bindings),
            "account_book_refs": list(account_book_bindings),
            "strategy_book_refs": list(strategy_book_bindings),
            "order_scope_refs": [],
            "monitor_scope_refs": [],
        },
        "account_bindings": account_bindings,
        "account_book_bindings": account_book_bindings,
        "strategy_book_bindings": strategy_book_bindings,
        "order_bindings": {},
        "monitor_bindings": {},
        "worker": {"max_queue_size": 16, "maintenance_interval_seconds": 30.0},
    }

    # Parse every component/profile before creating any process or runtime.
    from bt_api_py.service_config import parse_client_config, parse_service_config

    assert len(parse_client_config(client_config).clients) == 2
    for service in services.values():
        parse_service_config(service["gateway"]["config"])
        parse_service_config(service["execution"]["config"])
    parsed_profile = _parse_profile(profile, _load_sdk_types())
    assert parsed_profile.identity == _DUAL_LIVE_APPLICATION_IDENTITY
    assert set(parsed_profile.account_bindings) == {_ACCOUNT_A, _ACCOUNT_B}
    assert set(parsed_profile.account_book_bindings) == {_ACCOUNT_A, _ACCOUNT_B}
    assert set(parsed_profile.strategy_book_bindings) == {_STRATEGY_A, _STRATEGY_B}
    gateway_client_bindings = client_config["clients"]["gateway"]["settings"]["bindings"]
    execution_client_bindings = client_config["clients"]["execution"]["settings"]["bindings"]
    for name in account_refs:
        account_ref = account_refs[name]
        service = services[name]
        assert parsed_profile.account_bindings[account_ref].account_key == account_keys[name]
        assert parsed_profile.account_book_bindings[account_ref].account_key == account_keys[name]
        gateway = service["gateway"]
        assert parsed_profile.account_bindings[account_ref].scope_ref == (
            gateway["client_scope_ref"]
        )
        gateway_binding = next(
            binding
            for binding in gateway_client_bindings
            if binding["service_id"] == gateway["service_id"]
        )
        assert gateway_binding["scope_ref"] == gateway["client_scope_ref"]
        assert gateway_binding["transport_ref"] == gateway["transport_ref"]
        assert gateway_binding["instance_id"] == gateway["config"]["components"]["gateway"][
            "settings"
        ]["instance_id"]
        assert peers[gateway["service_id"]] == {
            "principal_ref": f"{gateway['service_id']}-principal",
            "actor_ref": gateway["service_id"],
        }
        gateway_profile = communication_profiles[gateway["transport_ref"]]
        assert gateway_profile["endpoints"]["rpc_connect"] == gateway["endpoint"]
        assert gateway_profile["security_profile_ref"] == gateway["security_ref"]
        assert gateway["security_ref"] in curve_keys
        assert scope_claims[gateway["client_scope_ref"]] == {
            "execution_domain_ref": _DUAL_LIVE_DOMAIN,
            "account_ref": account_ref,
            "strategy_ref": None,
        }
        execution = service["execution"]
        execution_binding = next(
            binding
            for binding in execution_client_bindings
            if binding["service_id"] == execution["service_id"]
        )
        assert execution_binding["scope_ref"] == execution["client_scope_ref"]
        assert execution_binding["transport_ref"] == execution["transport_ref"]
        assert execution_binding["instance_id"] == execution["config"]["components"][
            "execution"
        ]["settings"]["instance_id"]
        assert peers[execution["service_id"]] == {
            "principal_ref": f"{execution['service_id']}-principal",
            "actor_ref": execution["service_id"],
        }
        execution_profile = communication_profiles[execution["transport_ref"]]
        assert execution_profile["endpoints"]["rpc_connect"] == execution["endpoint"]
        assert execution_profile["security_profile_ref"] == execution["security_ref"]
        assert execution["security_ref"] in curve_keys
        assert scope_claims[execution["client_scope_ref"]] == {
            "execution_domain_ref": _DUAL_LIVE_DOMAIN,
            "account_ref": account_ref,
            "strategy_ref": None,
        }
        assert parsed_profile.account_book_bindings[account_ref].scope_ref == (
            execution["client_scope_ref"]
        )
        strategy_binding = parsed_profile.strategy_book_bindings[service["strategy_ref"]]
        assert strategy_binding.account_ref == account_ref
        assert strategy_binding.owner_ref == service["strategy_ref"]

    if preflight_only:
        return

    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    app_db = async_sessionmaker(engine, expire_on_commit=False)

    async def _create_tables() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(PortfolioCompositionVersion.__table__.create)

    asyncio.run(_create_tables())

    async def _override_db():
        async with app_db() as session:
            yield session

    prior_db_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_db
    hosts: list[dict[str, Any]] = []
    deployment: ServiceReadDeployment | None = None
    owner_threads: tuple[threading.Thread, ...] = ()
    cleanup_failures: list[BaseException] = []
    primary_error: BaseException | None = None
    primary_traceback = None
    root = tmp_path / "afi-dual-live"
    root.mkdir(parents=True, exist_ok=True)
    _COMMAND_GUARD_STATE["active"] = True
    startup_trace_phases = {
        ("app.services.service_read.deployment", "_create_runtime"): "runtime_factory",
        (
            "app.services.service_read.session",
            "SdkServiceReadSession.__init__",
        ): "session_construct",
        ("app.services.service_read.session", "SdkServiceReadSession.start"): "session_start",
        ("app.services.service_read.worker", "ServiceReadWorker._run_owner"): "owner_thread_start",
        ("bt_api_py.service_runtime", "ServiceClientRuntime.__init__"): "sdk_runtime_construct",
        ("bt_api_py.service_runtime", "ServiceClientRuntime.start"): "sdk_runtime_start",
        (
            "bt_api_py.service_runtime",
            "ServiceClientRuntime._register_port",
        ): "sdk_port_register",
        ("bt_api_py.service_runtime", "ServiceClientRuntime._rpc"): "sdk_control_rpc",
    }
    startup_rpc_operation_labels = {
        "service.discover": "discover",
        "service.register": "register",
        "service.renew": "renew",
        "service.unregister": "unregister",
        "account.snapshot": "account_snapshot",
        "execution.account_books.query": "account_book_query",
    }
    startup_rpc_services = {
        "afi-dual-account-a-gateway-service": (
            "account_a_gateway",
            frozenset(
                {
                    "service.discover",
                    "service.register",
                    "service.renew",
                    "service.unregister",
                    "account.snapshot",
                }
            ),
        ),
        "afi-dual-account-a-execution-service": (
            "account_a_execution",
            frozenset(
                {
                    "service.discover",
                    "service.register",
                    "service.renew",
                    "service.unregister",
                    "execution.account_books.query",
                }
            ),
        ),
        "afi-dual-account-b-gateway-service": (
            "account_b_gateway",
            frozenset(
                {
                    "service.discover",
                    "service.register",
                    "service.renew",
                    "service.unregister",
                    "account.snapshot",
                }
            ),
        ),
        "afi-dual-account-b-execution-service": (
            "account_b_execution",
            frozenset(
                {
                    "service.discover",
                    "service.register",
                    "service.renew",
                    "service.unregister",
                    "execution.account_books.query",
                }
            ),
        ),
    }
    startup_rpc_stages = {
        (service_id, operation): f"{service_label}_{startup_rpc_operation_labels[operation]}"
        for service_id, (service_label, operations) in startup_rpc_services.items()
        for operation in operations
    }
    coded_startup_errors = {
        ("app.services.service_read.deployment", "ServiceReadDeploymentError"),
        ("app.services.service_read.session", "ServiceReadSessionError"),
        ("app.services.service_read.session", "ServiceReadUnavailableError"),
        ("app.services.service_read.worker", "ServiceReadWorkerError"),
        ("bt_api_py.service_runtime", "ServiceRuntimeError"),
        ("bt_api_py.service_runtime", "ServiceRuntimeStartupCleanupError"),
        ("bt_api_py.service_runtime", "ServiceRuntimeRequestNotSentError"),
        ("bt_api_py.service_runtime", "ServiceCallOutcomeUnknownError"),
    }
    startup_exception_events: list[dict[str, str | None]] = []
    startup_exception_overflow = False
    startup_exception_lock = threading.Lock()

    def safe_exception_type(error_type: type[BaseException]) -> str:
        module_name = getattr(error_type, "__module__", None)
        qualified_name = getattr(error_type, "__qualname__", None)
        if (
            type(module_name) is not str
            or type(qualified_name) is not str
            or len(module_name) + len(qualified_name) > 192
            or not module_name
            or not qualified_name
            or any(
                not part.isidentifier()
                for part in (*module_name.split("."), *qualified_name.split("."))
            )
        ):
            return "unclassified"
        return f"{module_name}.{qualified_name}"

    def safe_exception_code(
        error_type: type[BaseException], error: BaseException
    ) -> str | None:
        if (error_type.__module__, error_type.__name__) not in coded_startup_errors:
            return None
        return _safe_diagnostic_code(getattr(error, "code", None))

    def observe_startup_exceptions(frame: Any, event: str, _argument: Any) -> Any:
        if event != "call" or not threading.current_thread().name.startswith(
            "afi-service-read-"
        ):
            return None
        phase = startup_trace_phases.get(
            (frame.f_globals.get("__name__"), frame.f_code.co_qualname)
        )
        if phase is None:
            return None
        rpc_stage = None
        if phase == "sdk_control_rpc":
            rpc_stage = startup_rpc_stages.get(
                (frame.f_locals.get("service_id"), frame.f_locals.get("operation")),
                "unclassified_synthetic_rpc",
            )

        def observe_phase(_frame: Any, phase_event: str, phase_argument: Any) -> Any:
            nonlocal startup_exception_overflow
            if phase_event == "exception" and type(phase_argument) is tuple:
                try:
                    error_type, error, _traceback = phase_argument
                    if isinstance(error_type, type) and isinstance(error, BaseException):
                        record = {
                            "phase": phase,
                            "type": safe_exception_type(error_type),
                            "code": safe_exception_code(error_type, error),
                        }
                        if rpc_stage is not None:
                            record["service_operation"] = rpc_stage
                        with startup_exception_lock:
                            if len(startup_exception_events) < 8:
                                startup_exception_events.append(record)
                            else:
                                startup_exception_overflow = True
                except BaseException:
                    with startup_exception_lock:
                        startup_exception_overflow = True
            return observe_phase

        return observe_phase

    try:
        guard_directories: dict[str, str] = {}
        for name in account_refs:
            guard_directory = root / f"{name}-session-guard"
            guard_directory.mkdir(exist_ok=False)
            guard_directories[name] = str(guard_directory)
        for name, service in services.items():
            for role, target, arguments, process_name in (
                (
                    "gateway",
                    _dual_gateway_service_process,
                    (
                        service["gateway"]["config"],
                        str(root / f"{name}-gateway-registry.sqlite3"),
                        str(root / f"{name}-gateway-journal.sqlite3"),
                        guard_directories[name],
                        service["account_ref"],
                        service["gateway"]["client_scope_ref"],
                        service["account_key"].to_dict(),
                        {
                            "server_public": service["gateway"]["server_public"],
                            "server_secret": service["gateway"]["server_secret"],
                            "application_public": app_public,
                            "security_ref": service["gateway"]["security_ref"],
                        },
                    ),
                    f"afi-dual-{name}-gateway-host",
                ),
                (
                    "execution",
                    _dual_execution_service_process,
                    (
                        service["execution"]["config"],
                        str(root / f"{name}-execution-registry.sqlite3"),
                        str(root / f"{name}-execution-store.sqlite3"),
                        service["account_ref"],
                        service["strategy_ref"],
                        service["execution"]["client_scope_ref"],
                        {
                            "server_public": service["execution"]["server_public"],
                            "server_secret": service["execution"]["server_secret"],
                            "application_public": app_public,
                            "security_ref": service["execution"]["security_ref"],
                        },
                    ),
                    f"afi-dual-{name}-execution-host",
                ),
            ):
                host = _order._start_process(context, target, arguments, process_name)
                hosts.append(host)
                host["role"] = role
                host["account_ref"] = service["account_ref"]
                diagnostic_path = root / f"{name}-{role}-startup.json"
                host["diagnostic_path"] = diagnostic_path
                host["account_book_diagnostic"] = {"schema_version": 1, "role": role}
                try:
                    ready = _order._receive(host["pipe"], timeout=20.0)
                except BaseException:
                    host["startup_failed"] = True
                    raise
                if ready[0] == "error":
                    host["startup_failed"] = True
                    _write_account_book_diagnostic(
                        diagnostic_path,
                        {
                            "schema_version": 1,
                            "role": role,
                            "status": "error",
                            "code": _safe_diagnostic_code(ready[1] if len(ready) > 1 else None),
                        },
                    )
                    pytest.fail(
                        f"synthetic {role} ServiceHost startup failed; "
                        f"finite record at {diagnostic_path}",
                        pytrace=False,
                    )
                assert ready[0] == "ready", ready
                assert ready[2] == "started", ready
                if role == "gateway":
                    assert ready[3]["worker_ready"] is True
                    assert ready[3]["connect_calls"] == ready[3]["read_calls"] == 1
                    assert ready[3]["close_calls"] == 0
                    assert ready[3]["account_key_id"] == service["account_key"].account_key_id
                    host["startup_facts"] = ready[3]
                else:
                    host["startup_facts"] = ready[2]

        monkeypatch.setattr(
            main_module.settings,
            "SERVICE_READ_DEPLOYMENT_JSON",
            SecretStr(json.dumps({"schema_version": 1, "subjects": [profile]})),
        )

        async def _exercise_http() -> None:
            nonlocal deployment, owner_threads
            async with main_module.lifespan(app):
                deployment = app.state.service_read_deployment
                assert deployment is not None
                assert len(deployment._workers) == 1
                worker = deployment._workers[0]
                assert worker._thread is not None and worker._thread.is_alive()
                owner_threads = (worker._thread,)
                assert owner_threads[0] is not threading.current_thread()
                headers_a = {"Authorization": f"Bearer {_make_token(_SUBJECT_A, _JWT_SECRET)}"}
                headers_b = {"Authorization": f"Bearer {_make_token(_SUBJECT_B, _JWT_SECRET)}"}
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://afi-dual-live.synthetic.test",
                ) as client:
                    base_members = [
                        {"kind": "account", "ref": _ACCOUNT_A},
                        {"kind": "account", "ref": _ACCOUNT_B},
                        {"kind": "strategy", "ref": _STRATEGY_A},
                        {"kind": "strategy", "ref": _STRATEGY_B},
                    ]
                    created = await client.post(
                        "/api/v1/portfolio/compositions",
                        headers=headers_a,
                        json={
                            "portfolio_ref": "afi-dual-live-overlap-one",
                            "source_type": "live",
                            "base_currency": "USDT",
                            "members": base_members,
                        },
                    )
                    assert created.status_code == 201, created.text
                    assert created.json()["membership_version"] == 1
                    create_overlap = await client.post(
                        "/api/v1/portfolio/compositions",
                        headers=headers_a,
                        json={
                            "portfolio_ref": "afi-dual-live-overlap-two",
                            "source_type": "live",
                            "base_currency": "USDT",
                            "members": [
                                {"kind": "account", "ref": _ACCOUNT_A},
                                {"kind": "strategy", "ref": _STRATEGY_A},
                            ],
                        },
                    )
                    assert create_overlap.status_code == 201, create_overlap.text

                    async def projection(portfolio_ref: str) -> dict[str, Any]:
                        response = await client.get(
                            "/api/v1/portfolio/overview",
                            params={"portfolio_ref": portfolio_ref, "membership_version": 1},
                            headers=headers_a,
                        )
                        assert response.status_code == 200, response.text
                        return response.json()

                    combined = await projection("afi-dual-live-overlap-one")
                    overlapping = await projection("afi-dual-live-overlap-two")
                    assert combined["source_type"] == "live"
                    assert combined["membership_version"] == 1
                    assert combined["account_total"] == {
                        "status": "current",
                        "currency": "USDT",
                        "value": "950",
                    }
                    assert [row["member_ref"] for row in combined["accounts"]] == [
                        _ACCOUNT_A,
                        _ACCOUNT_B,
                    ]
                    assert {row["member_ref"]: row["cash"] for row in combined["accounts"]} == {
                        _ACCOUNT_A: "80",
                        _ACCOUNT_B: "650",
                    }
                    assert {row["member_ref"]: row["value"] for row in combined["accounts"]} == {
                        _ACCOUNT_A: "160",
                        _ACCOUNT_B: "790",
                    }
                    assert all(row["included_in_total"] is True for row in combined["accounts"])
                    assert all(row["duplicate_of_ref"] is None for row in combined["accounts"])
                    assert {row["strategy_ref"] for row in combined["strategies"]} == {
                        _STRATEGY_A,
                        _STRATEGY_B,
                    }
                    assert all(
                        row["attribution_status"] == "available_with_residuals"
                        for row in combined["strategies"]
                    )
                    assert all(
                        "cash" not in row and "value" not in row and row["attributed_value"] is None
                        for row in combined["strategies"]
                    )
                    assert {
                        row["strategy_ref"]: row["positions"]
                        for row in combined["strategies"]
                    } == {
                        _STRATEGY_A: [
                            {"instrument": "PAPER:SIM:AFI-DUAL-A", "net_quantity": "2.5"}
                        ],
                        _STRATEGY_B: [
                            {"instrument": "PAPER:SIM:AFI-DUAL-B", "net_quantity": "4"}
                        ],
                    }
                    assert {
                        row["strategy_ref"]: row["fees_since_baseline"]
                        for row in combined["strategies"]
                    } == {
                        _STRATEGY_A: [{"currency": "USDT", "amount": "0.06"}],
                        _STRATEGY_B: [{"currency": "USDT", "amount": "0.13"}],
                    }
                    assert {
                        row["strategy_ref"]: row["source_cursor"] for row in combined["strategies"]
                    } == {_STRATEGY_A: 0, _STRATEGY_B: 0}
                    books_by_account = {
                        row["account_ref"]: row for row in combined["account_book_sources"]
                    }
                    coverage_by_account = {
                        account_ref: row["coverage"]
                        for account_ref, row in books_by_account.items()
                    }
                    journal_generations = []
                    for account_ref, suffix in ((_ACCOUNT_A, "A"), (_ACCOUNT_B, "B")):
                        coverage = coverage_by_account[account_ref]
                        assert coverage["scope_directory_revision"] == (
                            f"afi-dual-directory-{suffix}-r1"
                        )
                        assert re.fullmatch(r"[0-9a-f]{32}", coverage["journal_generation"])
                        journal_generations.append(coverage["journal_generation"])
                        assert coverage["baseline_execution_cursor"] == 0
                        assert coverage["current_execution_cursor"] == 0
                        assert coverage["complete"] is True
                        assert coverage["reasons"] == []
                        assert coverage["scanned_outbox_events"] == 0
                        assert coverage["outbox_history_contiguous"] is True
                        assert coverage["outbox_scan_complete"] is True
                        assert coverage["continuations"] == []
                        assert coverage["input_continuations"] == []
                        assert coverage["quarantined_intents"] == []
                    assert len(set(journal_generations)) == 2
                    strategy_cursors = {
                        row["strategy_ref"]: row["source_cursor"] for row in combined["strategies"]
                    }
                    assert (
                        strategy_cursors[_STRATEGY_A]
                        == coverage_by_account[_ACCOUNT_A]["current_execution_cursor"]
                    )
                    assert (
                        strategy_cursors[_STRATEGY_B]
                        == coverage_by_account[_ACCOUNT_B]["current_execution_cursor"]
                    )
                    assert {
                        row["account_ref"]: row["state"] for row in combined["account_book_sources"]
                    } == {_ACCOUNT_A: "RESIDUAL", _ACCOUNT_B: "RESIDUAL"}
                    assert {
                        row["account_ref"]: row["provider_position_change"]
                        for row in combined["account_book_sources"]
                    } == {
                        _ACCOUNT_A: [
                            {"instrument": "PAPER:SIM:AFI-DUAL-A", "net_quantity": "1"}
                        ],
                        _ACCOUNT_B: [
                            {"instrument": "PAPER:SIM:AFI-DUAL-B", "net_quantity": "2"}
                        ],
                    }
                    assert {
                        row["account_ref"]: row["position_residual"]
                        for row in combined["account_book_sources"]
                    } == {
                        _ACCOUNT_A: [{"instrument": "PAPER:SIM:AFI-DUAL-A", "net_quantity": "0.5"}],
                        _ACCOUNT_B: [{"instrument": "PAPER:SIM:AFI-DUAL-B", "net_quantity": "1"}],
                    }
                    assert {
                        row["account_ref"]: row["unallocated_book"]
                        for row in combined["account_book_sources"]
                    } == {
                        _ACCOUNT_A: {
                            "owner_kind": "UNALLOCATED",
                            "owner_ref": "UNALLOCATED",
                            "current_positions": [
                                {
                                    "instrument": "PAPER:SIM:AFI-DUAL-A",
                                    "net_quantity": "3.5",
                                }
                            ],
                            "fees_since_baseline": [{"currency": "USDT", "amount": "0.04"}],
                        },
                        _ACCOUNT_B: {
                            "owner_kind": "UNALLOCATED",
                            "owner_ref": "UNALLOCATED",
                            "current_positions": [
                                {
                                    "instrument": "PAPER:SIM:AFI-DUAL-B",
                                    "net_quantity": "5",
                                }
                            ],
                            "fees_since_baseline": [{"currency": "USDT", "amount": "0.07"}],
                        },
                    }
                    assert {
                        row["account_ref"]: row["fee_residual"]
                        for row in combined["account_book_sources"]
                    } == {
                        _ACCOUNT_A: [{"currency": "USDT", "amount": "0.04"}],
                        _ACCOUNT_B: [{"currency": "USDT", "amount": "0.07"}],
                    }
                    assert combined["strategy_attribution"]["attributed_value"] is None
                    assert combined["coverage"]["account_facts_complete"] is True
                    assert combined["coverage"]["strategy_attribution_complete"] is False
                    assert combined["coverage"]["complete"] is False
                    assert combined["creditable"] is False
                    assert combined["overlap_policy"] == "non_additive_display_only"

                    assert overlapping["account_total"]["value"] == "160"
                    assert overlapping["accounts"][0]["value"] == "160"
                    assert overlapping["creditable"] is False
                    assert overlapping["overlap_policy"] == "non_additive_display_only"
                    assert overlapping["account_book_sources"][0]["account_ref"] == _ACCOUNT_A
                    assert combined["membership_sha256"] != overlapping["membership_sha256"]
                    cross_owner = await client.get(
                        "/api/v1/portfolio/overview",
                        params={
                            "portfolio_ref": "afi-dual-live-overlap-one",
                            "membership_version": 1,
                        },
                        headers=headers_b,
                    )
                    assert cross_owner.status_code == 404

        from app.services.service_read.session import SdkServiceReadSession

        session_phases = {
            SdkServiceReadSession.__init__.__code__: "constructed",
            SdkServiceReadSession.start.__code__: "started",
            SdkServiceReadSession.read_account.__code__: "read_account",
            SdkServiceReadSession.read_account_book.__code__: "read_account_book",
            SdkServiceReadSession.close.__code__: "closed",
        }
        session_events: list[tuple[str, int]] = []
        events_lock = threading.Lock()

        def observe_owner_thread(frame: Any, event: str, _argument: Any) -> None:
            if event == "call" and frame.f_code in session_phases:
                with events_lock:
                    session_events.append((session_phases[frame.f_code], threading.get_ident()))

        prior_profile = threading.getprofile()
        prior_trace = threading.gettrace()
        try:
            threading.setprofile(observe_owner_thread)
            threading.settrace(observe_startup_exceptions)
            asyncio.run(_exercise_http())
        finally:
            threading.setprofile(prior_profile)
            threading.settrace(prior_trace)
        assert {phase for phase, _thread_id in session_events} == {
            "constructed",
            "started",
            "read_account",
            "read_account_book",
            "closed",
        }
        assert len({thread_id for _phase, thread_id in session_events}) == 1
        assert owner_threads and owner_threads[0].ident in {
            thread_id for _phase, thread_id in session_events
        }
        assert owner_threads[0].ident != threading.get_ident()
        assert deployment is not None and deployment.closed
        assert deployment.close_failures == ()
        assert app.state.service_read_deployment is None
        assert all(not thread.is_alive() for thread in owner_threads)
        for host in hosts:
            if host["role"] == "gateway":
                status = _order._command(host, "status")
                assert status[0] == "status" and status[1:4] == (1, 1, 0)
            else:
                status = _order._command(host, "status")
                expected_reads = 2 if host["account_ref"] == _ACCOUNT_A else 1
                assert status[0] == "status" and status[1] == expected_reads
    except BaseException as error:
        primary_error = error
        primary_traceback = error.__traceback__
    finally:
        try:
            try:
                app.dependency_overrides.pop(get_db, None)
                if prior_db_override is not None:
                    app.dependency_overrides[get_db] = prior_db_override
            except BaseException as error:
                cleanup_failures.append(error)
            for host in reversed(hosts):
                try:
                    receipt = _stop_dual_live_service_host(host)
                    if host["role"] == "gateway":
                        assert len(receipt) == 6 and receipt[1] == receipt[5] == "closed", receipt
                    else:
                        assert len(receipt) == 3 and receipt[1] == "closed", receipt
                except BaseException as error:
                    cleanup_failures.append(error)
                try:
                    _write_account_book_diagnostic(
                        host["diagnostic_path"],
                        {
                            "schema_version": 1,
                            "role": host.get("role"),
                            "account_ref": host.get("account_ref"),
                            "startup": host.get("startup_facts"),
                            "shutdown": host.get("shutdown"),
                        },
                    )
                except BaseException as error:
                    cleanup_failures.append(error)
            try:
                asyncio.run(engine.dispose())
            except BaseException as error:
                cleanup_failures.append(error)
        finally:
            _COMMAND_GUARD_STATE["active"] = False

    startup_diagnostic = {
        "schema_version": 1,
        "events": list(startup_exception_events),
        "events_overflow": startup_exception_overflow,
        "outer_failure": (
            {
                "phase": "integration_body",
                "type": safe_exception_type(type(primary_error)),
                "code": safe_exception_code(type(primary_error), primary_error),
            }
            if primary_error is not None
            else None
        ),
    }
    try:
        _write_account_book_diagnostic(
            root / "service-read-startup-diagnostic.json", startup_diagnostic
        )
    except BaseException as error:
        cleanup_failures.append(error)

    if primary_error is not None:
        import json

        primary_error.add_note(
            "service-read-startup-diagnostic="
            + json.dumps(startup_diagnostic, sort_keys=True, separators=(",", ":"))
        )
        if cleanup_failures:
            primary_error.__dict__["dual_live_cleanup_failures"] = tuple(cleanup_failures)
            primary_error.add_note(
                f"synthetic ServiceHost cleanup also reported {len(cleanup_failures)} failure(s)"
            )
        raise primary_error.with_traceback(primary_traceback)
    if cleanup_failures:
        raise AssertionError(
            f"dual-live integration cleanup had {len(cleanup_failures)} failure(s)"
        ) from cleanup_failures[0]


def test_afi02_dual_live_projection_uses_gateway_and_execution_service_hosts(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run_dual_live_composition_projection(tmp_path, monkeypatch)


def test_default_service_read_runtime_assembly_limits_gateway_to_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.service_read.deployment import _create_runtime
    import bt_api_py.service_runtime as service_runtime
    from bt_api_py.service_config import parse_client_config

    real_runtime_type = service_runtime.ServiceClientRuntime
    requested_operations: list[Any] = []

    def observe_real_runtime_constructor(config: Any, **kwargs: Any) -> Any:
        requested_operations.append(kwargs.get("requested_operations"))
        return real_runtime_type(config, **kwargs)

    monkeypatch.setattr(
        service_runtime, "ServiceClientRuntime", observe_real_runtime_constructor
    )
    profile = SimpleNamespace(
        curve_keys={},
        account_bindings={_ACCOUNT_A: object(), _ACCOUNT_B: object()},
        account_book_bindings={_ACCOUNT_A: object(), _ACCOUNT_B: object()},
        order_bindings={},
        client_config=parse_client_config({}),
        identity=_DUAL_LIVE_APPLICATION_IDENTITY,
        scopes={},
        peer_identities={},
    )

    runtime = _create_runtime(profile)
    expected = {
        "application.account": frozenset({"account.snapshot"}),
        "application.order_query": frozenset({"execution.account_books.query"}),
    }
    assert requested_operations == [expected]
    assert type(runtime) is real_runtime_type
    assert runtime._requested_operations == expected
    assert runtime.state == "new"
    runtime.close()


_MANUAL_SUBMIT_SELECTOR = "afi-manual-order-current-v1"
_MANUAL_BOOK_A = "afi-manual-book-a-v1"
_MANUAL_BOOK_B = "afi-manual-book-b-v1"
_MANUAL_SCOPE_A = WireScope(
    _DOMAIN, account_ref=_ACCOUNT_A, manual_book_ref=_MANUAL_BOOK_A
)
_MANUAL_SCOPE_B = WireScope(
    _DOMAIN, account_ref=_ACCOUNT_B, manual_book_ref=_MANUAL_BOOK_B
)
_MANUAL_HTTP_PHASES = frozenset(
    {
        "first-owner-A-submit",
        "same-key-owner-A-replay",
        "same-key-owner-B-submit",
        "changed-terms-idempotency-conflict",
        "client-supplied-actor-ref-refusal",
        "unknown-server-scope-ref-refusal",
        "post-lifespan-restart-owner-A-replay",
    }
)


def _manual_order_http_response_fact(
    phase: str, status_code: int, payload: object
) -> tuple[str, int, str | None, str | None]:
    """Project only a fixed phase, status and safe error codes from HTTP JSON."""

    if phase not in _MANUAL_HTTP_PHASES or type(status_code) is not int:
        raise AssertionError("manual-order HTTP diagnostic input is not bounded")
    if not isinstance(payload, dict):
        return phase, status_code, None, None
    details = payload.get("details", payload.get("detail"))
    outer_error = payload.get("error")
    detail_code = details.get("code") if isinstance(details, dict) else None

    def finite_code(value: Any) -> str | None:
        if (
            type(value) is str
            and 1 <= len(value) <= 64
            and value[0].isalpha()
            and value[0].isascii()
            and value.isascii()
            and all(char.isupper() or char.isdigit() or char == "_" for char in value)
        ):
            return value
        return None

    return phase, status_code, finite_code(outer_error), finite_code(detail_code)


def _manual_order_http_response_fact_from_response(
    phase: str, response: Any
) -> tuple[str, int, str | None, str | None]:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = None
    return _manual_order_http_response_fact(phase, response.status_code, payload)


def test_manual_order_http_error_diagnostic_uses_real_exception_handler() -> None:
    """Check the finite response projection against the application's handlers."""

    import json

    from fastapi.exceptions import RequestValidationError
    from starlette.requests import Request

    from app.api.service_orders import _map_service_error
    from app.middleware.exception_handling import (
        handle_http_exception,
        handle_request_validation_error,
    )

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/service-orders/manual",
            "raw_path": b"/api/v1/service-orders/manual",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 32100),
            "server": ("manual-order.synthetic.test", 80),
            "root_path": "",
        }
    )

    async def _response_for_service_code(code: str):
        return await handle_http_exception(request, _map_service_error(code))

    for phase, service_code, status_code in (
        ("client-supplied-actor-ref-refusal", "SCOPE_DENIED", 403),
        ("changed-terms-idempotency-conflict", "INTENT_CONFLICT", 409),
        ("first-owner-A-submit", "SERVICE_READ_FAILED", 503),
    ):
        response = asyncio.run(_response_for_service_code(service_code))
        payload = json.loads(response.body)
        assert _manual_order_http_response_fact(
            phase, response.status_code, payload
        ) == (f"{phase}", status_code, f"HTTP_{status_code}", service_code)

    validation = RequestValidationError(
        [
            {
                "loc": ("body", "actor_ref"),
                "msg": "Extra inputs are not permitted",
                "type": "extra_forbidden",
            }
        ],
        body={"actor_ref": "synthetic-forged-actor"},
    )
    validation_response = asyncio.run(handle_request_validation_error(request, validation))
    validation_payload = json.loads(validation_response.body)
    assert _manual_order_http_response_fact(
        "client-supplied-actor-ref-refusal",
        validation_response.status_code,
        validation_payload,
    ) == ("client-supplied-actor-ref-refusal", 422, "VALIDATION_ERROR", None)


def _manual_order_service_process(
    control: Any,
    raw_config: dict[str, Any],
    registry_path: str,
    keys: dict[str, bytes],
    store_path: str,
) -> None:
    """Run the normal account-owner Host and observe its real submit handler."""

    import sys

    from bt_api_execution import ExecutionScope, SqliteExecutionStore
    from bt_api_execution.service_order_entry import ExecutionOrderEntryService
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

    config = parse_service_config(raw_config)
    provider = _CountingProvider()
    gate = _order._Gate()
    execution_store = None
    host = None
    identity_facts: list[tuple[str, str, str, str, str, str]] = []
    submit_code = ExecutionOrderEntryService.handle.__code__

    def observe_submit(frame: Any, event: str, _argument: Any) -> Any:
        if event != "call" or frame.f_code is not submit_code:
            return None
        local = frame.f_locals
        if local.get("operation") != "orders.submit":
            return None
        identity = local.get("identity")
        scope = local.get("scope")
        if type(identity) is WireIdentity and type(scope) is WireScope:
            identity_facts.append(
                (
                    identity.principal_ref,
                    identity.actor_ref,
                    identity.delegate_ref or "",
                    scope.account_ref or "",
                    scope.manual_book_ref or "",
                    local["operation"],
                )
            )
        return None

    sys.settrace(observe_submit)
    try:
        authority = TrustedServiceAuthority(
            identity=_SERVICE_IDENTITY,
            scope=WireScope(_DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="afi-manual-order-scope-v1",
            security_ref=_SERVER_SECURITY_REF,
            security_version="afi-manual-order-curve-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="afi-manual-order-policy-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="afi-manual-order-requirements-v1",
            curve_public_key=keys["server_public"],
            curve_secret_key=keys["server_secret"],
            principals={keys["application_public"]: _APP_PRINCIPAL},
            grants={
                _APP_PRINCIPAL: (
                    PrincipalGrant(
                        _APPLICATION_IDENTITY_A,
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_entry",
                                _MANUAL_SUBMIT_SELECTOR,
                                _MANUAL_SCOPE_A,
                                frozenset({"orders.submit"}),
                            ),
                        ),
                    ),
                    PrincipalGrant(
                        _APPLICATION_IDENTITY_B,
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_entry",
                                _MANUAL_SUBMIT_SELECTOR,
                                _MANUAL_SCOPE_B,
                                frozenset({"orders.submit"}),
                            ),
                        ),
                    ),
                )
            },
        )
        execution_store = SqliteExecutionStore(store_path)
        targets = {
            _MANUAL_SCOPE_A: ExecutionScope(
                "afi-synthetic-provider", "simulation", _ACCOUNT_A, _MANUAL_BOOK_A, "20261016"
            ),
            _MANUAL_SCOPE_B: ExecutionScope(
                "afi-synthetic-provider", "simulation", _ACCOUNT_B, _MANUAL_BOOK_B, "20261016"
            ),
        }

        def resource_provider(component: str, _instance: str, _options: Any, _scope: Any):
            if component != "execution":
                raise AssertionError("unexpected component in manual-order Host")
            return ComponentResources.borrowed(
                {
                    "store": execution_store,
                    "targets": targets,
                    "dispatch": provider,
                    "admission": {"order_gate": gate, "cancel_gate": gate},
                },
                ready=lambda: True,
            )

        host = ServiceHost(config, authority, registry_path, resource_provider)
        host.start()
        control.send(("ready", host.endpoint, host.state))
        while True:
            host.serve_once(timeout_ms=25)
            if not control.poll():
                continue
            command = control.recv()
            if command == ("close",):
                host.close()
                execution_store.close()
                execution_store = None
                control.send(("closed", host.state))
                return
            if command == ("facts",):
                control.send(
                    (
                        "facts",
                        tuple(provider.submitted),
                        tuple(gate.reserved),
                        tuple(identity_facts),
                    )
                )
                continue
            raise AssertionError("unknown manual-order Host command")
    except BaseException as error:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        if execution_store is not None:
            with suppress(BaseException):
                execution_store.close()
        with suppress(Exception):
            control.send(("error", getattr(error, "code", type(error).__name__)))
        raise
    finally:
        sys.settrace(None)
        control.close()


def _manual_order_deployment_profile(
    *,
    endpoint: str,
    subject: str,
    identity: WireIdentity,
    account_ref: str,
    manual_book_ref: str,
    manual_scope: WireScope,
    security_ref: str,
    keys: dict[str, bytes],
) -> dict[str, Any]:
    """Build one strict server-owned selector to a manual account book."""

    client_config = _order._client_config(
        endpoint,
        "application_client",
        security_ref,
        application=identity.actor_ref,
    )
    client_binding = client_config["clients"]["execution"]["settings"]["bindings"][0]
    client_binding.update(
        mount="application.orders",
        scope_ref=_MANUAL_SUBMIT_SELECTOR,
        account_ref=account_ref,
    )
    return {
        "subject": subject,
        "identity": {
            "principal_ref": identity.principal_ref,
            "actor_ref": identity.actor_ref,
            "delegate_ref": identity.delegate_ref,
        },
        "client_config": client_config,
        "scope_claims": {
            _MANUAL_SUBMIT_SELECTOR: {
                "execution_domain_ref": manual_scope.execution_domain_ref,
                "account_ref": account_ref,
                "manual_book_ref": manual_book_ref,
            }
        },
        "peer_identities": {
            _SERVICE_ID: {"principal_ref": _SERVICE_PRINCIPAL, "actor_ref": _SERVICE_ID}
        },
        "curve_keys": {
            security_ref: {
                "server_key": keys["server_public"].decode("ascii"),
                "public_key": keys["application_public"].decode("ascii"),
                "secret_key": keys["application_secret"].decode("ascii"),
            }
        },
        "grants": {
            "account_refs": [],
            "order_scope_refs": [],
            "order_submit_scope_refs": [_MANUAL_SUBMIT_SELECTOR],
            "monitor_scope_refs": [],
        },
        "account_bindings": {},
        "order_bindings": {},
        "order_submit_bindings": {
            _MANUAL_SUBMIT_SELECTOR: {
                "mount": "application.orders",
                "account_ref": account_ref,
                "manual_book_ref": manual_book_ref,
            }
        },
        "monitor_bindings": {},
        "worker": {"max_queue_size": 8, "maintenance_interval_seconds": 30.0},
    }


def _run_manual_order_submission_integration(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise manual HTTP submission through a real owner worker and SDK Host."""

    import json
    import threading
    from pathlib import Path

    import httpx
    from pydantic import SecretStr
    from sqlalchemy import insert
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    original_is_file = Path.is_file
    original_path_isfile = os.path.isfile

    def _without_optional_dotenv_file(path: Any) -> bool:
        basename = ntpath.basename(os.fsdecode(path)).casefold()
        if basename == ".slowapi.env" or basename == ".env" or basename.startswith(".env."):
            return False
        return original_is_file(path)

    def _without_optional_dotenv_probe(path: Any) -> bool:
        basename = ntpath.basename(os.fsdecode(path)).casefold()
        if basename == ".env" or basename.startswith(".env."):
            return False
        return original_path_isfile(path)

    monkeypatch.setattr(Path, "is_file", _without_optional_dotenv_file)
    monkeypatch.setattr(os.path, "isfile", _without_optional_dotenv_probe)
    import app.main as main_module
    import app.services.quote_service as quote_service

    from app.api.service_read import configure_service_read
    from app.db import database
    from app.models.permission import Role, user_roles
    from app.models.user import User
    from app.services.service_read.session import SdkServiceReadSession
    from app.utils import security

    monkeypatch.setattr(
        security,
        "settings",
        SimpleNamespace(JWT_SECRET_KEY=_JWT_SECRET, JWT_ALGORITHM=_JWT_ALGORITHM),
    )

    async def _no_startup(*_args: Any, **_kwargs: Any) -> None:
        return None

    class _NoopShutdownManager:
        async def initiate(self, _app: Any) -> None:
            return None

    monkeypatch.setattr(main_module, "run_startup", _no_startup)
    monkeypatch.setattr(main_module, "run_shutdown", _no_startup)
    monkeypatch.setattr(main_module, "GracefulShutdownManager", _NoopShutdownManager)
    monkeypatch.setattr(main_module.settings, "RAG_VECTOR_ENABLED", False)
    monkeypatch.setattr(
        quote_service,
        "get_quote_service",
        lambda: SimpleNamespace(shutdown=lambda: None),
    )

    context = multiprocessing.get_context("spawn")
    endpoint = _order._endpoint()
    server_public, server_secret = zmq.curve_keypair()
    application_public, application_secret = zmq.curve_keypair()
    keys: dict[str, bytes] = {
        "server_public": server_public,
        "server_secret": server_secret,
        "application_public": application_public,
        "application_secret": application_secret,
    }
    host_keys = {
        key: value
        for key, value in keys.items()
        if key.endswith("_public") or key == "server_secret"
    }

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    previous_overrides = dict(main_module.app.dependency_overrides)
    app = main_module.app
    host = None
    primary_error: BaseException | None = None
    primary_traceback: Any = None
    cleanup_failures: list[BaseException] = []
    worker_threads: list[tuple[int, ...]] = []
    session_calls: list[tuple[int, int, str, str]] = []
    old_thread_profile = threading.getprofile()
    profile_code = SdkServiceReadSession.submit_manual_order.__code__
    configure_service_read(None)

    def _observe_owner_call(frame: Any, event: str, _argument: Any) -> None:
        if event != "call" or frame.f_code is not profile_code:
            return
        session = frame.f_locals.get("self")
        if not isinstance(session, SdkServiceReadSession):
            return
        session_calls.append(
            (
                threading.get_ident(),
                session._owner_thread,
                session._expected_identity.actor_ref,
                session._expected_identity.delegate_ref or "",
            )
        )

    threading.setprofile(_observe_owner_call)
    try:
        async def _prepare_database() -> None:
            import app.models  # noqa: F401 - register all mapped models before create_all

            async with engine.begin() as connection:
                await connection.run_sync(database.Base.metadata.create_all)
            async with session_factory() as db:
                db.add_all(
                    [
                        User(
                            id=_SUBJECT_A,
                            username="manual-order-user-a",
                            email="manual-order-user-a@example.invalid",
                            hashed_password="synthetic-only",
                            is_active=True,
                            principal_kind="HUMAN",
                        ),
                        User(
                            id=_SUBJECT_B,
                            username="manual-order-user-b",
                            email="manual-order-user-b@example.invalid",
                            hashed_password="synthetic-only",
                            is_active=True,
                            principal_kind="HUMAN",
                        ),
                    ]
                )
                await db.flush()
                await db.execute(
                    insert(user_roles),
                    [
                        {"user_id": _SUBJECT_A, "role": Role.USER.value},
                        {"user_id": _SUBJECT_B, "role": Role.USER.value},
                    ],
                )
                await db.commit()

        async def _get_db():
            async with session_factory() as db:
                yield db

        asyncio.run(_prepare_database())
        app.dependency_overrides[database.get_db] = _get_db
        host = _order._start_process(
            context,
            _manual_order_service_process,
            (
                _order._service_config(endpoint),
                str(tmp_path / "afi-manual-order-registry.sqlite3"),
                host_keys,
                str(tmp_path / "afi-manual-order-execution.sqlite3"),
            ),
            "afi-manual-order-execution-host",
        )
        host["startup_failed"] = True
        ready = _order._receive(host["pipe"], timeout=20.0)
        if ready[0] == "ready":
            host["startup_failed"] = False
        assert ready[0] == "ready", ready
        assert host["process"].is_alive()

        profiles = [
            _manual_order_deployment_profile(
                endpoint=endpoint,
                subject=subject,
                identity=identity,
                account_ref=account_ref,
                manual_book_ref=manual_book_ref,
                manual_scope=scope,
                security_ref=f"afi-{subject}-manual-order-curve-v1",
                keys=keys,
            )
            for subject, identity, account_ref, manual_book_ref, scope in (
                (
                    _SUBJECT_A,
                    _APPLICATION_IDENTITY_A,
                    _ACCOUNT_A,
                    _MANUAL_BOOK_A,
                    _MANUAL_SCOPE_A,
                ),
                (
                    _SUBJECT_B,
                    _APPLICATION_IDENTITY_B,
                    _ACCOUNT_B,
                    _MANUAL_BOOK_B,
                    _MANUAL_SCOPE_B,
                ),
            )
        ]
        monkeypatch.setattr(
            main_module.settings,
            "SERVICE_READ_DEPLOYMENT_JSON",
            SecretStr(json.dumps({"schema_version": 1, "subjects": profiles})),
        )
        body = {
            "scope_ref": _MANUAL_SUBMIT_SELECTOR,
            "instrument": "BTC-USDT",
            "side": "BUY",
            "position_effect": "OPEN",
            "order_type": "LIMIT",
            "quantity": "1",
            "price": "50000",
            "time_in_force": "DAY",
            "reduce_only": False,
        }
        token_a = _make_token(_SUBJECT_A, _JWT_SECRET)
        token_b = _make_token(_SUBJECT_B, _JWT_SECRET)
        main_thread = threading.get_ident()

        result_a_id = None

        async def _exercise_both_generations() -> None:
            nonlocal result_a_id
            for generation in range(2):
                async with main_module.lifespan(app):
                    deployment = app.state.service_read_deployment
                    assert deployment is not None
                    workers = deployment._workers
                    assert len(workers) == 2
                    current_threads = tuple(worker._thread for worker in workers)
                    assert all(thread is not None and thread.is_alive() for thread in current_threads)
                    thread_ids = tuple(thread.ident for thread in current_threads)
                    assert len(set(thread_ids)) == 2
                    assert all(ident != main_thread for ident in thread_ids)
                    worker_threads.append(thread_ids)

                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app),
                        base_url="http://manual-order.synthetic.test",
                    ) as client:
                        async def submit(token: str, payload: dict[str, Any] = body):
                            return await client.post(
                                "/api/v1/service-orders/manual",
                                json=payload,
                                headers={
                                    "Authorization": f"Bearer {token}",
                                    "Idempotency-Key": "same-manual-business-key",
                                },
                            )

                        if generation == 0:
                            first_a = await submit(token_a)
                            replay_a = await submit(token_a)
                            other_actor = await submit(token_b)
                            changed = await submit(token_a, {**body, "quantity": "2"})
                            forged_actor = await submit(token_a, {**body, "actor_ref": "forged-actor"})
                            unknown_scope = await submit(token_a, {**body, "scope_ref": "manual-other-account"})
                            assert first_a.status_code == replay_a.status_code == 200, (
                                _manual_order_http_response_fact_from_response(
                                    "first-owner-A-submit", first_a
                                ),
                                _manual_order_http_response_fact_from_response(
                                    "same-key-owner-A-replay", replay_a
                                ),
                                _manual_order_http_response_fact_from_response(
                                    "same-key-owner-B-submit", other_actor
                                ),
                            )
                            assert other_actor.status_code == 200, _manual_order_http_response_fact_from_response(
                                "same-key-owner-B-submit", other_actor
                            )
                            result_a = first_a.json()
                            result_b = other_actor.json()
                            assert result_a["intent_id"] == replay_a.json()["intent_id"]
                            assert result_a["intent_id"] != result_b["intent_id"]
                            assert result_a["actor_ref"] == _SUBJECT_A
                            assert result_a["delegate_ref"] == _DELEGATE_A
                            assert result_b["actor_ref"] == _SUBJECT_B
                            assert result_b["delegate_ref"] == _DELEGATE_B
                            assert result_a["account_ref"] == _ACCOUNT_A
                            assert result_b["account_ref"] == _ACCOUNT_B
                            assert result_a["record"]["state"] == "ACKED"
                            assert result_b["record"]["state"] == "ACKED"
                            assert changed.status_code == 409, _manual_order_http_response_fact_from_response(
                                "changed-terms-idempotency-conflict", changed
                            )
                            assert forged_actor.status_code == 422, _manual_order_http_response_fact_from_response(
                                "client-supplied-actor-ref-refusal", forged_actor
                            )
                            assert unknown_scope.status_code == 403, _manual_order_http_response_fact_from_response(
                                "unknown-server-scope-ref-refusal", unknown_scope
                            )
                            result_a_id = result_a["intent_id"]
                        else:
                            restarted_replay = await submit(token_a)
                            assert restarted_replay.status_code == 200, _manual_order_http_response_fact_from_response(
                                "post-lifespan-restart-owner-A-replay", restarted_replay
                            )
                            assert restarted_replay.json()["intent_id"] == result_a_id

                assert deployment.closed
                assert deployment.close_failures == ()
                assert app.state.service_read_deployment is None
                assert all(not thread.is_alive() for thread in current_threads)

        asyncio.run(_exercise_both_generations())
        facts = _order._command(host, "facts")
        assert len(facts[1]) == 2
        assert len(set(facts[1])) == 2
        assert set(facts[2]) == set(facts[1])
        observed = facts[3]
        assert len(observed) == 4
        assert [row[1:3] for row in observed].count((_SUBJECT_A, _DELEGATE_A)) == 3
        assert [row[1:3] for row in observed].count((_SUBJECT_B, _DELEGATE_B)) == 1
        assert all(row[0] == _APP_PRINCIPAL for row in observed)
        assert all(row[-1] == "orders.submit" for row in observed)
        assert {row[3:] for row in observed} == {
            (_ACCOUNT_A, _MANUAL_BOOK_A, "orders.submit"),
            (_ACCOUNT_B, _MANUAL_BOOK_B, "orders.submit"),
        }
        assert len(session_calls) == 4
        assert all(call_thread == owner_thread for call_thread, owner_thread, *_ in session_calls)
        assert all(call_thread != main_thread for call_thread, *_ in session_calls)
        assert [row[2:4] for row in session_calls].count((_SUBJECT_A, _DELEGATE_A)) == 3
        assert [row[2:4] for row in session_calls].count((_SUBJECT_B, _DELEGATE_B)) == 1
        assert len(worker_threads) == 2
    except BaseException as error:
        primary_error = error
        primary_traceback = error.__traceback__
    finally:
        threading.setprofile(old_thread_profile)
        configure_service_read(None)
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        if host is not None:
            try:
                _close_default_deployment_service_host(host)
            except BaseException as error:
                cleanup_failures.append(error)
        async def _dispose_database() -> None:
            async with engine.begin() as connection:
                await connection.run_sync(database.Base.metadata.drop_all)
            await engine.dispose()

        try:
            asyncio.run(_dispose_database())
        except BaseException as error:
            cleanup_failures.append(error)

    if primary_error is not None:
        if cleanup_failures:
            primary_error.__dict__["manual_order_cleanup_failures"] = tuple(cleanup_failures)
            primary_error.add_note(
                f"manual-order integration cleanup reported {len(cleanup_failures)} failure(s)"
            )
        raise primary_error.with_traceback(primary_traceback)
    if cleanup_failures:
        raise AssertionError(
            f"manual-order integration cleanup had {len(cleanup_failures)} failure(s)"
        ) from cleanup_failures[0]


def test_manual_http_submission_reuses_owner_and_durable_execution_intent(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _COMMAND_GUARD_STATE["active"] = True
    try:
        _run_manual_order_submission_integration(tmp_path, monkeypatch)
    finally:
        _COMMAND_GUARD_STATE["active"] = False
