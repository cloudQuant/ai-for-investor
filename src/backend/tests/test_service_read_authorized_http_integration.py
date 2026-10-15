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
