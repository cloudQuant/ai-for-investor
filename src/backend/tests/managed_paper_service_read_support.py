"""Local-process helpers shared by the managed-paper HTTP integration test.

These definitions mirror the accepted service-read order-process fixture,
without importing that test module or its unrelated optional Monitor fixture.
The support here is configuration and process plumbing only; the integration
test still starts the real SDK worker and Execution ServiceHost.
"""

from __future__ import annotations

import multiprocessing
import socket
from contextlib import suppress
from typing import Any, Callable


_SERVICE_ID = "afi-execution-service"
_SERVICE_PRINCIPAL = "afi-execution-principal"
_INSTANCE_ID = "afi-execution-owner"
_SERVICE_SCOPE_REF = "afi-execution-root-v1"
_SERVER_SECURITY_REF = "afi-execution-server-curve-v1"
_ORDER_SCOPE_REF = "afi-order-entry-a-v1"
_QUERY_SCOPE_REF = "afi-order-query-a-v1"
_REQUEST_TIMEOUT_MS = 2000
_MAX_MESSAGE_BYTES = 65_536


def _record_cleanup_failures(error: BaseException, failures: tuple[str, ...]) -> None:
    """Attach bounded cleanup facts without replacing the primary exception."""
    if not failures:
        return
    bounded = tuple(str(item)[:96] for item in failures[:16])
    message = "Managed-paper cleanup failures: " + ", ".join(bounded)
    try:
        prior = getattr(error, "_afi_managed_paper_cleanup_failures", ())
        if type(prior) is not tuple:
            prior = ()
        error._afi_managed_paper_cleanup_failures = prior + bounded
    except BaseException:
        pass
    add_note = getattr(error, "add_note", None)
    if callable(add_note):
        with suppress(BaseException):
            add_note(message)


def _endpoint() -> str:
    """Reserve an ephemeral loopback port for the local SDK service host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _service_config(endpoint: str) -> dict[str, Any]:
    """Build the same accepted Execution service-host configuration."""
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _SERVICE_ID,
        "scope_ref": _SERVICE_SCOPE_REF,
        "transport_ref": "afi-execution-listener-v1",
        "registration_policy_ref": "afi-execution-registration-v1",
        "service_requirements_ref": "afi-execution-requirements-v1",
        "components": {
            "execution": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _INSTANCE_ID,
                    "bind_ports": ["service.order_entry", "service.order_query"],
                    "options": {"role": "account_owner"},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "afi-execution-listener-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _SERVER_SECURITY_REF,
                    "options": {
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _client_config(
    endpoint: str,
    role: str,
    security_ref: str,
    *,
    strategy: str | None = None,
    application: str | None = None,
) -> dict[str, Any]:
    """Build the service-read/order client config used by the accepted test."""
    if role == "strategy_client":
        bindings = [
            {
                "mount": "broker.orders",
                "service_id": _SERVICE_ID,
                "instance_id": _INSTANCE_ID,
                "scope_ref": _ORDER_SCOPE_REF,
                "transport_ref": "afi-execution-connect-v1",
                "account_ref": "account-a",
            },
        ]
    else:
        bindings = [
            {
                "mount": "application.order_query",
                "service_id": _SERVICE_ID,
                "instance_id": _INSTANCE_ID,
                "scope_ref": _QUERY_SCOPE_REF,
                "transport_ref": "afi-execution-connect-v1",
                "account_ref": "account-a",
            }
        ]
    return {
        "client_config_schema_version": 1,
        "process_role": role,
        "registration": (
            {"strategy_ref": strategy}
            if strategy is not None
            else {"application_ref": application}
        ),
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": bindings,
                    "options": {"request_timeout_ms": _REQUEST_TIMEOUT_MS},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "afi-execution-connect-v1": {
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
            },
        },
    }


def _start_process(
    context: Any,
    target: Callable[..., Any],
    args: tuple[Any, ...],
    label: str,
) -> dict[str, Any]:
    """Start one local process with a private duplex control pipe."""
    parent, child = context.Pipe(duplex=True)
    process = None
    try:
        process = context.Process(target=target, args=(child, *args), name=label)
        process.start()
        child.close()
        return {"process": process, "pipe": parent, "label": label}
    except BaseException as start_error:
        # Preserve the start/close exception while closing every resource that
        # may have been created, including a child from a partial start.
        cleanup_failures: list[str] = []
        if process is not None:
            try:
                if process.pid is not None and process.is_alive():
                    process.terminate()
            except BaseException as error:
                cleanup_failures.append(f"terminate:{type(error).__name__}")
            try:
                if process.pid is not None:
                    process.join(2.0)
            except BaseException as error:
                cleanup_failures.append(f"join:{type(error).__name__}")
            try:
                if process.pid is not None and process.is_alive():
                    process.kill()
            except BaseException as error:
                cleanup_failures.append(f"kill:{type(error).__name__}")
            try:
                if process.pid is not None:
                    process.join(2.0)
            except BaseException as error:
                cleanup_failures.append(f"final_join:{type(error).__name__}")
            try:
                if process.pid is None or not process.is_alive():
                    process.close()
            except BaseException as error:
                cleanup_failures.append(f"process_close:{type(error).__name__}")
        try:
            child.close()
        except BaseException as error:
            cleanup_failures.append(f"child_pipe_close:{type(error).__name__}")
        try:
            parent.close()
        except BaseException as error:
            cleanup_failures.append(f"parent_pipe_close:{type(error).__name__}")
        _record_cleanup_failures(start_error, tuple(cleanup_failures))
        raise


def _receive(pipe: Any, timeout: float = 20.0) -> Any:
    """Receive one bounded reply from a local SDK/Execution process."""
    assert pipe.poll(timeout), "managed-paper service process missed its response bound"
    return pipe.recv()
