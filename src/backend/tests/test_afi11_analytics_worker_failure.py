"""AFI11 analytics-worker startup failure isolation over the accepted R236 HTTP path.

The test runs the R236 AFI route against its fixed Risk source export. The first
V2 worker is a real spawn child held before the worker-entry frame until the
production ten-second startup deadline expires. The host must terminate and
reap that child, then run a second task. An independent Strategy owner remains
registered and executes through the same durable policy throughout.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import json
import multiprocessing
import os
import socket
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import zmq

_AFI_BACKEND_ROOT_ENV = "AFI11_BACKEND_ROOT"
_SDK_SOURCE_ROOT_ENV = "AFI11_SDK_EXPORT_ROOT"
_RISK_SOURCE_ROOT_ENV = "AFI11_RISK_EXPORT_ROOT"
_R236_RISK_SOURCE_ROOT_ENV = "AFI11_R236_RISK_EXPORT_ROOT"
_R236_HTTP_TEST_SHA256 = "f2680d4db91331cac35d77fad37e88144d51876255f3c3198d1ddfc8455321f1"
_R236_RISK_ANALYTICS_SHA256 = "1b148a4a923081302e507829d540aa9e45fc8ae3aac37eeb8f7f8dd3f1bda9c8"
_R236_RISK_ANALYTICS_BYTES = 80_802
_EXPECTED_PYTHON_ENV = "AFI11_EXPECTED_PYTHON"
_TERMINAL_STATES = frozenset({"succeeded", "unavailable", "failed", "cancelled", "expired"})
_MAX_WIRE_MESSAGE_BYTES = 1_048_576
_WORKER_STARTUP_SECONDS = 10.0

_OWNER_DOMAIN = "afi11:analytics-worker-owner"
_OWNER_SERVICE_ID = "afi11-execution-service"
_OWNER_SERVICE_PRINCIPAL = "afi11-execution-principal"
_OWNER_INSTANCE_ID = "afi11-execution-owner"
_OWNER_SCOPE_REF = "afi11-execution-root-v1"
_OWNER_REGISTRATION = "afi11-execution-registration-v1"
_OWNER_REQUIREMENTS = "afi11-execution-requirements-v1"
_OWNER_SECURITY_REF = "afi11-execution-server-curve-v1"
_OWNER_ACCOUNT = "afi11-account-owner"
_OWNER_STRATEGY = "afi11-strategy-owner"
_OWNER_STRATEGY_PRINCIPAL = "afi11-strategy-principal"
_OWNER_ENTRY_SCOPE_REF = "afi11-order-entry-v1"
_OWNER_QUERY_SCOPE_REF = "afi11-order-query-v1"
_OWNER_TRANSPORT = "afi11-execution-connect-v1"
_OWNER_SECURITY_CLIENT = "afi11-strategy-client-curve-v1"
_OWNER_POLICY_ID = "afi11-owner-risk-policy-v1"


def _required_python() -> None:
    expected = os.environ.get(_EXPECTED_PYTHON_ENV)
    assert type(expected) is str and expected.strip(), "Root must set the fixed AFI Python"
    assert Path(sys.executable).resolve() == Path(expected).resolve()
    assert sys.version_info[:2] == (3, 12)


def _required_directory(variable: str) -> Path:
    raw = os.environ.get(variable)
    assert type(raw) is str and raw.strip(), f"Root must set {variable} to a fixed source export"
    path = Path(raw).resolve()
    assert path.is_dir(), f"{variable} does not name a source directory"
    return path


def _r236_support() -> ModuleType:
    backend_root = _required_directory(_AFI_BACKEND_ROOT_ENV)
    source = backend_root / "tests" / "test_service_read_portfolio_analytics_process.py"
    assert source.is_file()
    raw = source.read_bytes()
    assert len(raw) == 43_115
    assert hashlib.sha256(raw).hexdigest() == _R236_HTTP_TEST_SHA256
    spec = importlib.util.spec_from_file_location("afi11_r236_http_test_support", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert Path(module.__file__).resolve() == source.resolve()
    return module


def _assert_r236_sources() -> dict[str, Path]:
    sdk_export = _required_directory(_SDK_SOURCE_ROOT_ENV)
    risk_export = _required_directory(_RISK_SOURCE_ROOT_ENV)
    r236_risk_export = _required_directory(_R236_RISK_SOURCE_ROOT_ENV)
    root_by_name = {
        "bt_api_base": (sdk_export / "base" / "src").resolve(),
        "bt_api_execution": (sdk_export / "execution" / "src").resolve(),
        "bt_api_py": (sdk_export / "root").resolve(),
        "bt_api_risk": (risk_export / "src").resolve(),
        "bt_api_transport_zmq": (sdk_export / "transport" / "src").resolve(),
    }
    for package, root in root_by_name.items():
        package_path = root / package
        assert (package_path / "__init__.py").is_file(), (package, "fixed package missing")

    analytics_path = (
        r236_risk_export / "src" / "bt_api_risk" / "service_analytics.py"
    ).resolve()
    analytics_bytes = analytics_path.read_bytes()
    assert len(analytics_bytes) == _R236_RISK_ANALYTICS_BYTES
    assert hashlib.sha256(analytics_bytes).hexdigest() == _R236_RISK_ANALYTICS_SHA256
    analytics_source = analytics_bytes.decode("utf-8")
    assert "multiprocessing.get_context(\"spawn\")" in analytics_source
    assert "TASK_WORKER_START_TIMEOUT" in analytics_source
    assert "_WORKER_STARTUP_TIMEOUT_NS: Final[int] = 10_000_000_000" in analytics_source

    from bt_api_base.service_protocol import WireIdentity
    from bt_api_execution import ExecutionScope, ProviderObservation, SqliteExecutionStore
    from bt_api_execution.service_order_entry import ExecutionOrderEntryService
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
        INSTRUMENT_METADATA_DIGEST_TAG,
        AccountScope,
        DurableRiskAdmissionAdapter,
        DurableRiskGate,
        ExposureAccountingMode,
        InstrumentRiskMetadata,
        InstrumentRiskRegistry,
        RiskDeniedError,
        RiskPolicy,
    )

    module_paths = (
        (WireIdentity, root_by_name["bt_api_base"] / "bt_api_base" / "service_protocol.py"),
        (ExecutionScope, root_by_name["bt_api_execution"] / "bt_api_execution" / "contracts.py"),
        (ProviderObservation, root_by_name["bt_api_execution"] / "bt_api_execution" / "contracts.py"),
        (SqliteExecutionStore, root_by_name["bt_api_execution"] / "bt_api_execution" / "store.py"),
        (ExecutionOrderEntryService, root_by_name["bt_api_execution"] / "bt_api_execution" / "service_order_entry.py"),
        (AccountScope, root_by_name["bt_api_risk"] / "bt_api_risk" / "core" / "admission.py"),
        (DurableRiskGate, root_by_name["bt_api_risk"] / "bt_api_risk" / "core" / "admission.py"),
        (RiskPolicy, root_by_name["bt_api_risk"] / "bt_api_risk" / "core" / "admission.py"),
        (RiskDeniedError, root_by_name["bt_api_risk"] / "bt_api_risk" / "core" / "admission.py"),
        (InstrumentRiskMetadata, root_by_name["bt_api_risk"] / "bt_api_risk" / "core" / "instrument.py"),
        (InstrumentRiskRegistry, root_by_name["bt_api_risk"] / "bt_api_risk" / "core" / "instrument.py"),
        (ComponentResources, root_by_name["bt_api_py"] / "bt_api_py" / "service_components.py"),
        (ServiceHost, root_by_name["bt_api_py"] / "bt_api_py" / "service_host.py"),
        (TrustedServiceAuthority, root_by_name["bt_api_py"] / "bt_api_py" / "service_host.py"),
        (PrincipalGrant, root_by_name["bt_api_py"] / "bt_api_py" / "service_registry.py"),
        (ResourceGrant, root_by_name["bt_api_py"] / "bt_api_py" / "service_registry.py"),
        (ServiceClientRuntime, root_by_name["bt_api_py"] / "bt_api_py" / "service_runtime.py"),
        (ClientCurveKeys, root_by_name["bt_api_py"] / "bt_api_py" / "service_runtime.py"),
        (ZmqTransportFactory, root_by_name["bt_api_py"] / "bt_api_py" / "service_runtime.py"),
        (parse_client_config, root_by_name["bt_api_py"] / "bt_api_py" / "service_config.py"),
        (parse_service_config, root_by_name["bt_api_py"] / "bt_api_py" / "service_config.py"),
    )
    import inspect

    for symbol, expected in module_paths:
        actual = inspect.getsourcefile(symbol)
        assert type(actual) is str and Path(actual).resolve() == expected.resolve(), (
            getattr(symbol, "__name__", type(symbol).__name__),
            "SDK source origin mismatch",
        )
    assert type(INSTRUMENT_METADATA_DIGEST_TAG) is str
    assert DurableRiskAdmissionAdapter is not None
    assert ExposureAccountingMode is not None
    assert root_by_name["bt_api_base"] == (sdk_export / "base" / "src").resolve()
    return {
        **root_by_name,
        "afi_backend": _required_directory(_AFI_BACKEND_ROOT_ENV),
        "r236_risk": (r236_risk_export / "src").resolve(),
    }


def _owner_service_config(endpoint: str) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _OWNER_SERVICE_ID,
        "scope_ref": _OWNER_SCOPE_REF,
        "transport_ref": _OWNER_TRANSPORT,
        "registration_policy_ref": _OWNER_REGISTRATION,
        "service_requirements_ref": _OWNER_REQUIREMENTS,
        "components": {
            "execution": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _OWNER_INSTANCE_ID,
                    "bind_ports": ["service.order_entry", "service.order_query"],
                    "options": {"role": "account_owner"},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _OWNER_TRANSPORT: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _OWNER_SECURITY_REF,
                    "options": {
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_WIRE_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _owner_client_config(endpoint: str) -> dict[str, Any]:
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": _OWNER_STRATEGY},
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "broker.orders",
                            "service_id": _OWNER_SERVICE_ID,
                            "instance_id": _OWNER_INSTANCE_ID,
                            "scope_ref": _OWNER_ENTRY_SCOPE_REF,
                            "transport_ref": _OWNER_TRANSPORT,
                            "account_ref": _OWNER_ACCOUNT,
                        },
                        {
                            "mount": "broker.order_query",
                            "service_id": _OWNER_SERVICE_ID,
                            "instance_id": _OWNER_INSTANCE_ID,
                            "scope_ref": _OWNER_QUERY_SCOPE_REF,
                            "transport_ref": _OWNER_TRANSPORT,
                            "account_ref": _OWNER_ACCOUNT,
                        },
                    ],
                    "options": {"request_timeout_ms": 5_000},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _OWNER_TRANSPORT: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": endpoint},
                    "security_profile_ref": _OWNER_SECURITY_CLIENT,
                    "options": {
                        "request_timeout_ms": 5_000,
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_WIRE_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _owner_process(
    control: Any,
    config_raw: dict[str, Any],
    registry_path: str,
    execution_store_path: str,
    risk_store_path: str,
    material: dict[str, Any],
) -> None:
    """Spawn target for the independent, real execution and risk owner."""

    from bt_api_base.service_protocol import WireScope
    from bt_api_execution import ProviderObservation, SqliteExecutionStore
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant
    from bt_api_risk import (
        DurableRiskAdmissionAdapter,
        DurableRiskGate,
        InstrumentRiskAdmissionMapper,
        InstrumentRiskRegistry,
        RiskDeniedError,
    )

    config = parse_service_config(config_raw)
    store = None
    gate = None
    host = None
    provider = None
    denial_reasons: list[str] = []
    provider_construction_count = 0
    try:
        class SyntheticProvider:
            def __init__(self) -> None:
                nonlocal provider_construction_count
                provider_construction_count += 1
                self.session_id = f"afi11-synthetic-owner-session-{provider_construction_count}"
                self.session_open_count = provider_construction_count
                self.submitted: list[str] = []

            def submit(self, intent: Any) -> Any:
                self.submitted.append(intent.intent_id)
                return ProviderObservation.accepted(
                    intent.intent_id, f"afi11-synthetic-owner-order-{len(self.submitted)}"
                )

            def cancel(self, _intent: Any) -> Any:
                raise AssertionError("this AFI11 node does not authorize cancellation")

        provider = SyntheticProvider()
        account_scope = material["account_scope"]
        wire_scope = material["wire_scope"]
        execution_scope = material["execution_scope"]
        metadata = material["metadata"]
        gate = DurableRiskGate(
            risk_store_path,
            material["risk_policy"],
        )
        gate.set_strategy_allocation(
            account_scope,
            execution_scope.strategy_id,
            "afi11-owner-allocation-v1",
            max_notional=Decimal("1000"),
            notional_unit="USD",
        )
        registry = InstrumentRiskRegistry((metadata,))
        mapper = InstrumentRiskAdmissionMapper(
            account_scope,
            registry,
            clock_ns=time.time_ns,
            allocation_reader=lambda selected_scope: gate.get_strategy_allocation(
                account_scope, selected_scope.strategy_id
            ),
            wire_account_ref=wire_scope.account_ref,
        )

        def observe_mapper(intent: Any) -> Any:
            try:
                return mapper(intent)
            except RiskDeniedError as error:
                if type(error.code) is str:
                    denial_reasons.append(error.code)
                raise

        admission = DurableRiskAdmissionAdapter(gate, observe_mapper)
        store = SqliteExecutionStore(execution_store_path)
        principals = dict(material["principal_keys"])
        grants: dict[str, tuple[PrincipalGrant, ...]] = {}
        for principal_ref, identity, resource_grants in material["grant_rows"]:
            grants[principal_ref] = grants.get(principal_ref, ()) + (
                PrincipalGrant(identity, resource_grants),
            )
        authority = TrustedServiceAuthority(
            identity=material["service_identity"],
            scope=WireScope(_OWNER_DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="afi11-owner-scope-v1",
            security_ref=_OWNER_SECURITY_REF,
            security_version="afi11-owner-curve-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="afi11-owner-registration-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="afi11-owner-requirements-v1",
            curve_public_key=material["server_public"],
            curve_secret_key=material["server_secret"],
            principals=principals,
            grants=grants,
        )

        def resource_provider(
            component: str, instance_id: str, _options: Any, _scope: Any
        ) -> Any:
            if component != "execution" or instance_id != _OWNER_INSTANCE_ID:
                raise AssertionError("unexpected execution owner resource request")
            return ComponentResources.borrowed(
                {
                    "store": store,
                    "targets": {wire_scope: execution_scope},
                    "dispatch": provider,
                    "admission": {"order_gate": admission, "cancel_gate": None},
                },
                ready=lambda: True,
            )

        host = ServiceHost(config, authority, registry_path, resource_provider)
        host.start()
        control.send(("ready", os.getpid(), host.endpoint, host.state))
        while True:
            host.serve_once(timeout_ms=25)
            if not control.poll():
                continue
            command = control.recv()
            if command == ("counts",):
                binding = admission.policy_binding
                control.send(
                    (
                        "counts",
                        os.getpid(),
                        host.state,
                        provider.session_id,
                        provider.session_open_count,
                        tuple(provider.submitted),
                        tuple(denial_reasons),
                        binding.policy_id,
                        binding.policy_fingerprint,
                        provider_construction_count,
                    )
                )
                continue
            if command == ("close",):
                host.close()
                gate.close()
                store.close()
                gate = None
                store = None
                control.send(("closed", os.getpid(), host.state))
                return
            raise AssertionError("unknown execution owner command")
    except BaseException as error:
        if host is not None and host.state not in {"closed", "failed", "close_failed"}:
            try:
                host.close()
            except BaseException:
                pass
        if gate is not None:
            try:
                gate.close()
            except BaseException:
                pass
        if store is not None:
            try:
                store.close()
            except BaseException:
                pass
        try:
            control.send(("error", getattr(error, "code", type(error).__name__)))
        except BaseException:
            pass
        raise
    finally:
        control.close()


def _owner_order_arguments(
    intent_id: str, metadata: Any, instrument: str, metadata_digest_tag: str
) -> dict[str, Any]:
    return {
        "intent_id": intent_id,
        "signal_id": f"signal-{intent_id}",
        "instrument": instrument,
        "side": "BUY",
        "position_effect": "OPEN",
        "order_type": "LIMIT",
        "quantity": "1",
        "price": "100",
        "time_in_force": "GTC",
        "reduce_only": False,
        "metadata_version": metadata.metadata_version,
        "deadline_ns": None,
        "tags": {metadata_digest_tag: metadata.digest},
    }


def _blocked_before_worker_entry(
    target: Any, args: tuple[Any, ...], entered_path: str, release_receiver: Any
) -> None:
    """Real spawn child that cannot emit the V2 worker's startup frame."""

    try:
        Path(entered_path).write_text("entered", encoding="ascii")
        command = release_receiver.recv_bytes(maxlength=16)
    except (EOFError, OSError):
        return
    finally:
        release_receiver.close()
    if command == b"run":
        target(*args)


class _ObservedBarrierProcess:
    def __init__(self, process: Any, child_ends: tuple[Any, Any], marker: Path) -> None:
        self._process = process
        self._child_ends = child_ends
        self._marker = marker
        self._record: dict[str, Any] = {"events": [], "schema": "afi11-v2-startup-child-v1"}

    def _save(self, event: str) -> None:
        events = self._record["events"]
        events.append(event)
        temporary = self._marker.with_name(self._marker.name + ".tmp")
        temporary.write_text(json.dumps(self._record, sort_keys=True), encoding="ascii")
        temporary.replace(self._marker)

    def start(self) -> None:
        assert self._process.daemon is True
        self._record["daemon"] = self._process.daemon
        self._record["parent_pid"] = os.getpid()
        self._record["start_monotonic_ns"] = time.monotonic_ns()
        self._process.start()
        self._record["pid"] = self._process.pid
        self._record["started"] = True
        self._save("start")
        for connection in self._child_ends:
            if not connection.closed:
                connection.close()

    def terminate(self) -> None:
        self._process.terminate()
        self._save("terminate")

    def join(self, timeout: float | None = None) -> None:
        self._process.join(timeout)
        self._record["alive_after_join"] = self._process.is_alive()
        self._record["exitcode_after_join"] = self._process.exitcode
        self._save("join")

    def close(self) -> None:
        self._record["alive_before_close"] = self._process.is_alive()
        self._record["exitcode_before_close"] = self._process.exitcode
        self._process.close()
        self._record["closed"] = True
        self._save("close")

    @property
    def daemon(self) -> bool:
        return self._process.daemon

    @daemon.setter
    def daemon(self, value: bool) -> None:
        self._process.daemon = value

    def __getattr__(self, name: str) -> Any:
        return getattr(self._process, name)


class _StartupBarrierContext:
    def __init__(self, context: Any, entered_path: Path, event_path: Path) -> None:
        self._context = context
        self._entered_path = entered_path
        self._event_path = event_path
        self._blocked = False
        self._parent_connections: list[Any] = []

    def Pipe(self, *, duplex: bool) -> Any:
        return self._context.Pipe(duplex=duplex)

    def Process(self, *, target: Any, args: tuple[Any, ...], **kwargs: Any) -> Any:
        if self._blocked:
            return self._context.Process(target=target, args=args, **kwargs)
        self._blocked = True
        release_receiver, release_sender = self._context.Pipe(duplex=False)
        self._parent_connections.append(release_sender)
        process = self._context.Process(
            target=_blocked_before_worker_entry,
            args=(target, args, str(self._entered_path), release_receiver),
            **kwargs,
        )
        return _ObservedBarrierProcess(
            process, (release_receiver,), self._event_path
        )

    def close(self) -> None:
        for connection in self._parent_connections:
            if not connection.closed:
                connection.close()


def _risk_host_entry(config_path: Path) -> int:
    _required_python()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    Path(config["host_pid"]).write_text(str(os.getpid()), encoding="ascii")
    support = _r236_support()
    service_module = importlib.import_module("bt_api_risk.service_analytics")
    r236_risk_export = _required_directory(_R236_RISK_SOURCE_ROOT_ENV)
    expected_analytics = (
        r236_risk_export / "src" / "bt_api_risk" / "service_analytics.py"
    ).resolve()
    assert Path(service_module.__file__).resolve() == expected_analytics
    barrier = _StartupBarrierContext(
        multiprocessing.get_context("spawn"),
        Path(config["worker_entered"]),
        Path(config["worker_events"]),
    )
    service_module.multiprocessing = SimpleNamespace(
        get_context=lambda method: barrier
        if method == "spawn"
        else multiprocessing.get_context(method)
    )
    try:
        return support._host_worker(config_path)
    finally:
        barrier.close()


def _child_entry() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--risk-host":
        return 2
    return _risk_host_entry(Path(sys.argv[2]))


def _wait_for_host(
    process: subprocess.Popen[bytes], ready: Path, failure: Path, timeout_seconds: float
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if ready.is_file():
            return
        if failure.is_file() or process.poll() is not None:
            break
        time.sleep(0.025)
    failure_detail: Any = None
    if failure.is_file():
        raw = failure.read_bytes()
        if len(raw) <= 16_384:
            try:
                failure_detail = json.loads(raw.decode("ascii"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                failure_detail = "invalid_failure_marker"
        else:
            failure_detail = "oversize_failure_marker"
    raise AssertionError(
        json.dumps(
            {"host_exit": process.poll(), "failure": failure_detail},
            sort_keys=True,
            separators=(",", ":"),
        )
    )


async def _wait_terminal(client: Any, headers: dict[str, str], url: str) -> dict[str, Any]:
    deadline = time.monotonic() + 20.0
    latest: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        response = await client.get(url, headers=headers)
        assert response.status_code == 200, response.text
        latest = response.json()
        if latest.get("state") in _TERMINAL_STATES:
            return latest
        await asyncio.sleep(0.05)
    raise AssertionError({"last_state": latest.get("state") if latest else None})


def _wait_marker(path: Path, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.01)
    raise AssertionError("real V2 spawn child did not reach the startup barrier")


def _owner_receive(connection: Any, timeout: float = 25.0) -> Any:
    if not connection.poll(timeout):
        raise AssertionError("execution owner did not answer its bounded control request")
    message = connection.recv()
    if isinstance(message, tuple) and message and message[0] == "error":
        raise AssertionError(("execution owner startup failure", message[1:]))
    return message


def _owner_command(owner: dict[str, Any], *command: Any) -> tuple[Any, ...]:
    owner["control"].send(command)
    result = _owner_receive(owner["control"])
    assert result[0] != "error", result
    return result


def _strategy_facts(runtime: Any) -> tuple[Any, ...]:
    return (
        runtime.client_session_id,
        runtime.run_id,
        runtime.state,
        tuple(sorted((key, id(transport)) for key, transport in runtime._transports.items())),
        tuple(
            (binding.mount, binding.scope_ref, binding.registration_id, binding.active)
            for binding in runtime.bindings
        ),
    )


def _close_owner(owner: dict[str, Any]) -> None:
    process = owner["process"]
    failures: list[str] = []
    if process.is_alive():
        try:
            closed = _owner_command(owner, "close")
            assert closed[0] == "closed" and closed[1] == owner["pid"] and closed[2] == "closed"
        except BaseException as error:
            failures.append("close_" + type(error).__name__)
    try:
        process.join(20.0)
        if process.is_alive():
            assert process.pid == owner["pid"] and type(owner["pid"]) is int
            process.terminate()
            process.join(10.0)
            failures.append("owner_required_termination")
    except BaseException as error:
        failures.append("join_" + type(error).__name__)
    if process.is_alive():
        failures.append("owner_not_reaped")
    elif process.exitcode != 0:
        failures.append("owner_exit_not_zero")
    try:
        owner["control"].close()
    except BaseException as error:
        failures.append("control_close_" + type(error).__name__)
    if not process.is_alive():
        try:
            process.close()
        except BaseException as error:
            failures.append("process_close_" + type(error).__name__)
    if failures:
        raise AssertionError("execution owner cleanup: " + ",".join(failures))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_http_analytics_startup_timeout_reaps_only_worker_and_preserves_owner(
    client: Any, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _required_python()
    support = _r236_support()
    source_roots = _assert_r236_sources()
    backend_root = source_roots["afi_backend"]

    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_execution import ExecutionScope
    from bt_api_py.service_config import parse_client_config
    from bt_api_py.service_registry import ResourceGrant
    from bt_api_py.service_runtime import ClientCurveKeys, ServiceClientRuntime, ZmqTransportFactory
    from bt_api_risk import (
        INSTRUMENT_METADATA_DIGEST_TAG,
        AccountScope,
        ExposureAccountingMode,
        InstrumentRiskMetadata,
        RiskPolicy,
    )
    from pydantic import SecretStr

    from app import main as main_module
    from app.api.portfolio import analytics_tasks as analytics_routes
    from app.config import get_settings
    from app.db import database as database_module
    from app.db.database import async_session_maker
    from app.models.portfolio_ledger import PortfolioLedgerImportModel, PortfolioLedgerModel
    from app.services import portfolio_analytics_tasks as analytics_service
    from app.services.service_read import deployment as service_read_deployment
    from app.services.service_read import worker as service_read_worker
    from app.utils.security import decode_access_token

    app_module_origins = (
        (main_module, backend_root / "app" / "main.py"),
        (analytics_routes, backend_root / "app" / "api" / "portfolio" / "analytics_tasks.py"),
        (analytics_service, backend_root / "app" / "services" / "portfolio_analytics_tasks.py"),
        (service_read_deployment, backend_root / "app" / "services" / "service_read" / "deployment.py"),
        (service_read_worker, backend_root / "app" / "services" / "service_read" / "worker.py"),
    )
    for module, expected in app_module_origins:
        assert Path(module.__file__).resolve() == expected.resolve(), (
            module.__name__,
            "AFI source origin mismatch",
        )

    assert main_module.settings is database_module.settings is get_settings()
    monkeypatch.setattr(main_module.settings, "DB_AUTO_CREATE_SCHEMA", True)
    token = auth_headers["Authorization"].split(" ", 1)[1]
    claims = decode_access_token(token)
    assert type(claims) is dict and type(claims.get("sub")) is str
    subject = claims["sub"]
    subject_tag = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16]
    app_principal = f"afi04-user-{subject_tag}"
    app_delegate = f"afi04-delegate-{subject_tag}"
    async with async_session_maker() as db:
        db.add(
            PortfolioLedgerModel(
                id="afi11-analytics-worker-ledger",
                owner_id=subject,
                name="AFI11 synthetic analytics source",
                base_currency="USD",
                source_type="imported",
            )
        )
        db.add(
            PortfolioLedgerImportModel(
                id="afi11-analytics-worker-import",
                portfolio_id="afi11-analytics-worker-ledger",
                import_format="json",
                idempotency_key="afi11-analytics-worker-membership-v1",
                imported_count=0,
            )
        )
        await db.commit()

    # Build a real independent Strategy owner while the AFI/Risk HTTP chain runs.
    multiprocessing.set_executable(sys.executable)
    owner_context = multiprocessing.get_context("spawn")
    owner_endpoint = _loopback_endpoint()
    server_public, server_secret = zmq.curve_keypair()
    strategy_public, strategy_secret = zmq.curve_keypair()
    account_scope = AccountScope("PAPER", _OWNER_ACCOUNT, "simulation")
    wire_scope = WireScope(_OWNER_DOMAIN, account_ref=_OWNER_ACCOUNT, strategy_ref=_OWNER_STRATEGY)
    execution_scope = ExecutionScope(
        "PAPER", "simulation", _OWNER_ACCOUNT, _OWNER_STRATEGY, "afi11-worker-failure-run"
    )
    metadata_now_ns = time.time_ns()
    metadata = InstrumentRiskMetadata(
        instrument="BTC-USDT",
        metadata_version="afi11-worker-failure-instrument-v1",
        as_of_ns=metadata_now_ns - 1_000_000_000,
        expires_at_ns=metadata_now_ns + 3_600_000_000_000,
        tick_size=Decimal("0.01"),
        quantity_step=Decimal("0.001"),
        contract_multiplier=Decimal("1"),
        max_gross_notional=Decimal("500000"),
        taker_fee_bps=Decimal("0"),
        fixed_fee=Decimal("0"),
        max_slippage_bps=Decimal("0"),
        quantity_unit="BTC",
        valuation_unit="USD",
    )
    service_identity = WireIdentity(WireRole.SERVICE, _OWNER_SERVICE_PRINCIPAL, _OWNER_SERVICE_ID)
    strategy_identity = WireIdentity(
        WireRole.STRATEGY_CLIENT, _OWNER_STRATEGY_PRINCIPAL, _OWNER_STRATEGY
    )
    owner_resources = (
        ResourceGrant(
            _OWNER_INSTANCE_ID,
            "service.order_entry",
            _OWNER_ENTRY_SCOPE_REF,
            wire_scope,
            frozenset({"orders.submit"}),
        ),
        ResourceGrant(
            _OWNER_INSTANCE_ID,
            "service.order_query",
            _OWNER_QUERY_SCOPE_REF,
            wire_scope,
            frozenset({"orders.query"}),
        ),
    )
    owner_config_raw = _owner_service_config(owner_endpoint)
    owner_client_raw = _owner_client_config(owner_endpoint)
    owner_client_config = parse_client_config(owner_client_raw)
    owner_peer_identity = service_identity
    owner_runtime = ServiceClientRuntime(
        owner_client_config,
        identity=strategy_identity,
        scope_resolver=lambda scope_ref: {
            _OWNER_ENTRY_SCOPE_REF: wire_scope,
            _OWNER_QUERY_SCOPE_REF: wire_scope,
        }[scope_ref],
        peer_resolver=lambda _service_id: owner_peer_identity,
        transport_factory=ZmqTransportFactory(
            {
                _OWNER_SECURITY_CLIENT: ClientCurveKeys(
                    server_public, strategy_public, strategy_secret
                )
            }
        ),
        requested_operations={
            "broker.orders": frozenset({"orders.submit"}),
            "broker.order_query": frozenset({"orders.query"}),
        },
    )
    owner_material = {
        "account_scope": account_scope,
        "wire_scope": wire_scope,
        "execution_scope": execution_scope,
        "metadata": metadata,
        "risk_policy": RiskPolicy(
            _OWNER_POLICY_ID,
            Decimal("5000"),
            max_increase_count=10,
            permit_ttl_seconds=60.0,
            require_strategy_allocation=True,
            notional_unit="USD",
            exposure_accounting_mode=ExposureAccountingMode.RESERVATIONS_ONLY,
        ),
        "service_identity": service_identity,
        "grant_rows": ((_OWNER_STRATEGY_PRINCIPAL, strategy_identity, owner_resources),),
        "principal_keys": {strategy_public: _OWNER_STRATEGY_PRINCIPAL},
        "server_public": server_public,
        "server_secret": server_secret,
    }
    owner_parent, owner_child = owner_context.Pipe(duplex=True)
    owner_process = owner_context.Process(
        target=_owner_process,
        args=(
            owner_child,
            owner_config_raw,
            str(tmp_path / "afi11-execution-owner-registry.sqlite3"),
            str(tmp_path / "afi11-execution-owner-store.sqlite3"),
            str(tmp_path / "afi11-execution-owner-risk.sqlite3"),
            owner_material,
        ),
        name="afi11-independent-execution-owner",
    )
    owner = {"control": owner_parent, "pid": None, "process": owner_process}

    analytics_endpoint = support._endpoint()
    analytics_keys = support._wire_keys()
    host_config_path = tmp_path / "afi11-analytics-risk-host.json"
    deployment_path = tmp_path / "afi11-analytics-deployment.json"
    host_markers = {
        "ready": tmp_path / "afi11-risk-host-ready.marker",
        "host_pid": tmp_path / "afi11-risk-host-pid.marker",
        "stop": tmp_path / "afi11-risk-host-stop.marker",
        "closed": tmp_path / "afi11-risk-host-closed.marker",
        "failure": tmp_path / "afi11-risk-host-failure.marker",
        "worker_entered": tmp_path / "afi11-v2-worker-entered.marker",
        "worker_events": tmp_path / "afi11-v2-worker-events.json",
    }
    host_config_path.write_text(
        json.dumps(
            {
                "closed": str(host_markers["closed"]),
                "database": str(tmp_path / "afi11-risk-analysis.sqlite3"),
                "endpoint": analytics_endpoint,
                "failure": str(host_markers["failure"]),
                "host_pid": str(host_markers["host_pid"]),
                "keys": analytics_keys,
                "principal_ref": app_principal,
                "delegate_ref": app_delegate,
                "ready": str(host_markers["ready"]),
                "registry": str(tmp_path / "afi11-risk-registry.sqlite3"),
                "stop": str(host_markers["stop"]),
                "worker_entered": str(host_markers["worker_entered"]),
                "worker_events": str(host_markers["worker_events"]),
            }
        ),
        encoding="utf-8",
    )
    deployment_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "subjects": [support._deployment_profile(subject, analytics_endpoint, analytics_keys)],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    host_log_path = tmp_path / "afi11-risk-host.log"
    host_process: subprocess.Popen[bytes] | None = None
    deployment = None
    owner_started = False
    strategy_started = False
    owner_baseline: tuple[Any, ...] | None = None
    synthetic_home = tmp_path / "afi11-process-home"
    synthetic_home.mkdir()
    synthetic_temp = tmp_path / "afi11-process-temp"
    synthetic_temp.mkdir()
    home_tail = str(synthetic_home)[len(synthetic_home.drive) :]
    child_env = {
        key: os.environ[key]
        for key in (
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "SYSTEMDRIVE",
            "OS",
            "PROCESSOR_ARCHITECTURE",
            "PROCESSOR_IDENTIFIER",
            "NUMBER_OF_PROCESSORS",
            "PROCESSOR_LEVEL",
            "PROCESSOR_REVISION",
            "TEMP",
            "TMP",
        )
        if key in os.environ
    }
    child_env.update(
        {
            "HOME": str(synthetic_home),
            "HOMEDRIVE": synthetic_home.drive,
            "HOMEPATH": home_tail,
            "USERPROFILE": str(synthetic_home),
            "TEMP": str(synthetic_temp),
            "TMP": str(synthetic_temp),
            _EXPECTED_PYTHON_ENV: os.environ[_EXPECTED_PYTHON_ENV],
            _AFI_BACKEND_ROOT_ENV: str(backend_root),
            _SDK_SOURCE_ROOT_ENV: str(_required_directory(_SDK_SOURCE_ROOT_ENV)),
            _RISK_SOURCE_ROOT_ENV: str(_required_directory(_RISK_SOURCE_ROOT_ENV)),
            _R236_RISK_SOURCE_ROOT_ENV: str(_required_directory(_R236_RISK_SOURCE_ROOT_ENV)),
            "PYTHONPATH": os.pathsep.join(
                [
                    str(backend_root),
                    str(source_roots["bt_api_base"]),
                    str(source_roots["bt_api_execution"]),
                    str(source_roots["bt_api_py"]),
                    str(source_roots["bt_api_transport_zmq"]),
                    str(source_roots["r236_risk"]),
                ]
            ),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPYCACHEPREFIX": str(tmp_path / "afi11-risk-host-pycache"),
            "BT_API_LOG_DIR": str(tmp_path / "afi11-risk-host-logs"),
        }
    )
    Path(child_env["BT_API_LOG_DIR"]).mkdir(parents=True, exist_ok=True)

    try:
        owner_process.start()
        owner_started = True
        owner_child.close()
        owner["pid"] = owner_process.pid
        owner_ready = _owner_receive(owner_parent)
        assert owner_ready[0] == "ready" and owner_ready[1] == owner_process.pid
        assert owner_ready[2] == owner_endpoint and owner_ready[3] == "started"
        strategy_started = True
        startup = owner_runtime.start()
        assert startup.degraded_count == 0
        session_before = _strategy_facts(owner_runtime)
        assert session_before[2] == "registered" and len(session_before[3]) == 1
        owner_baseline = _owner_command(owner, "counts")
        assert owner_baseline[1] == owner_process.pid
        assert owner_baseline[2] == "started"
        assert owner_baseline[3] == "afi11-synthetic-owner-session-1"
        assert owner_baseline[4] == owner_baseline[9] == 1
        assert owner_baseline[5:7] == ((), ())
        assert owner_baseline[7] == _OWNER_POLICY_ID

        with host_log_path.open("wb") as host_log:
            host_process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--risk-host", str(host_config_path)],
                cwd=str(backend_root),
                env=child_env,
                stdout=host_log,
                stderr=subprocess.STDOUT,
            )
            await asyncio.to_thread(
                _wait_for_host, host_process, host_markers["ready"], host_markers["failure"], 20.0
            )
            risk_host_pid = int(host_markers["host_pid"].read_text(encoding="ascii"))
            assert risk_host_pid > 0 and risk_host_pid != os.getpid()

            monkeypatch.setattr(
                main_module.settings,
                "SERVICE_READ_DEPLOYMENT_JSON",
                SecretStr(deployment_path.read_text(encoding="utf-8")),
            )
            monkeypatch.setattr(main_module.settings, "RAG_VECTOR_ENABLED", False)
            async with main_module.lifespan(main_module.app):
                deployment = main_module.app.state.service_read_deployment
                assert deployment is not None and not deployment.closed
                created = await client.post(
                    "/api/v1/portfolio/compositions",
                    headers=auth_headers,
                    json={
                        "portfolio_ref": support._PORTFOLIO,
                        "source_type": "imported",
                        "base_currency": "USD",
                        "members": [
                            {"kind": "imported_ledger", "ref": "afi11-analytics-worker-import"}
                        ],
                    },
                )
                assert created.status_code == 201, created.text
                membership = created.json()
                task_root = (
                    f"/api/v1/portfolio/compositions/{support._PORTFOLIO}/versions/"
                    f"{membership['membership_version']}/analytics-tasks"
                )

                first_submitted_ns = time.monotonic_ns()
                first = await client.post(
                    task_root,
                    headers=auth_headers,
                    json={
                        "idempotency_key": "afi11-startup-timeout-v1",
                        "facts": support._available_facts(),
                        "request": support._request(),
                    },
                )
                assert first.status_code == 202, first.text
                first_ref = first.json()["task_ref"]
                first_url = f"{task_root}/{first_ref}"
                await _wait_terminal_running(client, auth_headers, first_url)
                await asyncio.to_thread(
                    _wait_marker,
                    host_markers["worker_entered"],
                    _WORKER_STARTUP_SECONDS + 10.0,
                )
                failure_task = await _wait_terminal(client, auth_headers, first_url)
                failure_observed_ns = time.monotonic_ns()
                assert failure_task["state"] == "failed"
                assert failure_task["detail_code"] == "TASK_WORKER_START_TIMEOUT"
                assert failure_task["result"] is None
                assert failure_observed_ns - first_submitted_ns >= 9_000_000_000
                assert host_process.poll() is None
                assert host_markers["worker_entered"].read_text(encoding="ascii") == "entered"

                worker_events = json.loads(host_markers["worker_events"].read_text(encoding="ascii"))
                assert worker_events["schema"] == "afi11-v2-startup-child-v1"
                assert type(worker_events["pid"]) is int and worker_events["pid"] > 0
                assert worker_events["pid"] != risk_host_pid
                assert worker_events["parent_pid"] == risk_host_pid
                assert type(worker_events["start_monotonic_ns"]) is int
                assert worker_events["start_monotonic_ns"] > 0
                assert worker_events["started"] is True
                assert worker_events["daemon"] is True
                assert worker_events["events"].count("start") == 1
                assert worker_events["events"].index("start") < worker_events["events"].index("terminate")
                assert worker_events["events"].index("terminate") < worker_events["events"].index("join")
                assert worker_events["events"].index("join") < worker_events["events"].index("close")
                assert worker_events["alive_after_join"] is False
                assert worker_events["alive_before_close"] is False
                assert worker_events["closed"] is True
                assert type(worker_events["exitcode_after_join"]) is int
                assert worker_events["exitcode_after_join"] != 0

                # The same Risk Host and quota continue after the failed worker.
                second = await client.post(
                    task_root,
                    headers=auth_headers,
                    json={
                        "idempotency_key": "afi11-startup-recovery-v1",
                        "facts": support._available_facts(),
                        "request": support._request(),
                    },
                )
                assert second.status_code == 202, second.text
                success_task = await _wait_terminal(
                    client, auth_headers, f"{task_root}/{second.json()['task_ref']}"
                )
                assert success_task["state"] == "succeeded"
                assert success_task["result"]["status"] == "AVAILABLE"
                assert host_process.poll() is None
                assert _strategy_facts(owner_runtime) == session_before

            assert deployment is not None and deployment.closed
            assert deployment.close_failures == ()
            assert main_module.app.state.service_read_deployment is None

        # The original authorized owner still has the same session and policy,
        # and its normal Risk-admitted synthetic order path remains usable.
        counts_after_fault = _owner_command(owner, "counts")
        assert counts_after_fault == owner_baseline
        assert _strategy_facts(owner_runtime) == session_before
        denied_id = "afi11-after-analytics-worker-startup-failure-missing-facts"
        denied = owner_runtime.call(
            "broker.orders",
            "orders.submit",
            _owner_order_arguments(
                denied_id, metadata, "UNREGISTERED-ASSET", INSTRUMENT_METADATA_DIGEST_TAG
            ),
            scope_ref=_OWNER_ENTRY_SCOPE_REF,
        )
        assert denied["code"] == "OK"
        denied_record = denied["result"]["record"]
        assert denied_record["state"] == "REJECTED"
        assert denied_record["unknown_reason"] == "admission_denied"
        assert denied_record["dispatch_attempts"] == 0
        assert denied_record["provider_order_id"] is None
        assert _strategy_facts(owner_runtime) == session_before
        counts_after_denial = _owner_command(owner, "counts")
        assert counts_after_denial[1] == owner_process.pid
        assert counts_after_denial[2] == "started"
        assert counts_after_denial[3] == "afi11-synthetic-owner-session-1"
        assert counts_after_denial[4] == counts_after_denial[9] == 1
        assert counts_after_denial[5] == ()
        assert counts_after_denial[6] == ("INSTRUMENT_UNREGISTERED",)
        assert counts_after_denial[7:9] == owner_baseline[7:9]

        order_id = "afi11-after-analytics-worker-startup-failure"
        submitted = owner_runtime.call(
            "broker.orders",
            "orders.submit",
            _owner_order_arguments(
                order_id, metadata, metadata.instrument, INSTRUMENT_METADATA_DIGEST_TAG
            ),
            scope_ref=_OWNER_ENTRY_SCOPE_REF,
        )
        assert submitted["code"] == "OK"
        record = submitted["result"]["record"]
        assert record["state"] == "ACKED" and record["dispatch_attempts"] == 1
        counts_after_order = _owner_command(owner, "counts")
        assert counts_after_order[1] == owner_process.pid
        assert counts_after_order[2] == "started"
        assert counts_after_order[3] == "afi11-synthetic-owner-session-1"
        assert counts_after_order[4] == counts_after_order[9] == 1
        assert counts_after_order[5] == (order_id,)
        assert counts_after_order[6] == ("INSTRUMENT_UNREGISTERED",)
        assert counts_after_order[7:9] == owner_baseline[7:9]
        assert _strategy_facts(owner_runtime) == session_before
    finally:
        cleanup_errors: list[str] = []
        if deployment is not None and not deployment.closed:
            try:
                deployment.close()
            except BaseException as error:
                cleanup_errors.append("deployment_close_" + type(error).__name__)
        if strategy_started:
            try:
                owner_runtime.close()
                assert owner_runtime.cleanup_failures == 0
                assert owner_runtime.unregister_uncertainties == 0
            except BaseException as error:
                cleanup_errors.append("strategy_close_" + type(error).__name__)
        if owner_started:
            try:
                _close_owner(owner)
            except BaseException as error:
                cleanup_errors.append(type(error).__name__)
        if host_process is not None:
            try:
                host_markers["stop"].touch()
                await asyncio.to_thread(host_process.wait, timeout=20.0)
            except subprocess.TimeoutExpired:
                cleanup_errors.append("risk_host_graceful_wait_timeout")
                if host_process.poll() is None:
                    host_process.terminate()
                    try:
                        await asyncio.to_thread(host_process.wait, timeout=10.0)
                    except subprocess.TimeoutExpired:
                        cleanup_errors.append("risk_host_not_reaped_after_terminate")
                        host_process.kill()
                        await asyncio.to_thread(host_process.wait, timeout=10.0)
            except BaseException as error:
                cleanup_errors.append("risk_host_cleanup_" + type(error).__name__)
            if host_process.returncode != 0:
                cleanup_errors.append(f"risk_host_exit_{host_process.returncode}")
            if not host_markers["closed"].is_file():
                cleanup_errors.append("risk_host_closed_marker_missing")
            if host_markers["failure"].is_file():
                cleanup_errors.append("risk_host_failure_marker_present")
        if cleanup_errors:
            raise AssertionError("AFI11 worker-failure cleanup: " + ",".join(cleanup_errors))


async def _wait_terminal_running(client: Any, headers: dict[str, str], url: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5.0
    latest: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        response = await client.get(url, headers=headers)
        assert response.status_code == 200, response.text
        latest = response.json()
        if latest.get("state") == "running":
            return latest
        if latest.get("state") in _TERMINAL_STATES:
            raise AssertionError({"expected": "running", "actual": latest.get("state")})
        await asyncio.sleep(0.025)
    raise AssertionError({"expected": "running", "last_state": latest.get("state") if latest else None})


def _loopback_endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


if __name__ == "__main__":  # pragma: no cover - executed by the test-owned Risk Host
    raise SystemExit(_child_entry())
