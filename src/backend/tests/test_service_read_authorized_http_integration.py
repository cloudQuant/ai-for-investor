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


def _make_token(subject: str, key: str) -> str:
    import jwt

    return jwt.encode(
        {
            "sub": subject,
            "username": subject,
            "token_type": "access",
            "exp": int(time.time()) + 600,
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
    if process.is_alive():
        try:
            pipe.send(("close",))
            closed = _order._receive(pipe, timeout=10.0)
            assert closed[0] == "closed", closed
        except BaseException as error:
            failures.append(error)

    try:
        process.join(10.0)
    except BaseException as error:
        failures.append(error)

    try:
        alive = process.is_alive()
        if alive:
            try:
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
    except BaseException as error:
        failures.append(error)
    try:
        process.close()
    except BaseException as error:
        failures.append(error)

    if exit_code != 0:
        failures.append(AssertionError(f"synthetic execution service exit code was {exit_code!r}"))
    if failures:
        raise AssertionError(
            f"synthetic ServiceHost cleanup had {len(failures)} failure(s)"
        ) from failures[0]


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
