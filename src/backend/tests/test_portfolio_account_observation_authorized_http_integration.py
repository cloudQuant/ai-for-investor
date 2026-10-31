"""Prove the authorized SDK account-observation path reaches portfolio HTTP."""

from __future__ import annotations

import asyncio
import json
import math
import multiprocessing
import socket
import threading
import time
import traceback
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_DOMAIN = "paper:afi-account-observation-http"
_ACCOUNT_REF = "afi-observation-account"
_ACCOUNT_ID = "synthetic-private-provider-account-id"
_SUBJECT_A = "afi-observation-reader"
_SUBJECT_B = "afi-observation-ungranted-reader"
_APP_PRINCIPAL = "afi-observation-application-principal"
_APP_ACTOR = "afi-observation-dashboard"
_APP_DELEGATE = "afi-observation-delegate"
_SERVICE_ID = "afi-observation-gateway-service"
_SERVICE_PRINCIPAL = "afi-observation-gateway-principal"
_INSTANCE_ID = "afi-observation-gateway-instance"
_SERVICE_SCOPE_REF = "afi-observation-gateway-service-scope-v1"
_CLIENT_SCOPE_REF = "afi-observation-account-read-v1"
_SECURITY_REF = "afi-observation-gateway-curve-v1"
_TRANSPORT_REF = "afi-observation-gateway-connect-v1"
_JOURNAL_SCOPE = "afi-observation-private-journal-scope"
_STATE_SCOPE = "afi-observation-private-state-scope"
_JWT_SECRET = "afi-account-observation-integration-jwt-key-0123456789"
_JWT_ALGORITHM = "HS256"
_REQUEST_TIMEOUT_MS = 2000
_MAX_MESSAGE_BYTES = 1_048_576


class _SyntheticAccountProvider:
    """Return one current SDK observation and support one controlled read failure."""

    def __init__(self, account_key: Any, observation: Any) -> None:
        self.account_key = account_key
        self.observation = observation
        self.generation: str | None = None
        self.connect_calls = 0
        self.read_calls = 0
        self.close_calls = 0
        self.fail_next_read = False

    def connect(self, *, account_key: Any, generation: str, timeout: float) -> None:
        if (
            account_key != self.account_key
            or not generation
            or timeout <= 0
            or self.generation is not None
        ):
            raise AssertionError("invalid synthetic account-session connect")
        self.connect_calls += 1
        self.generation = generation

    def read_account(self, *, generation: str, timeout: float) -> Any:
        if generation != self.generation or timeout <= 0:
            raise AssertionError("synthetic account read used a stale session")
        self.read_calls += 1
        if self.fail_next_read:
            self.fail_next_read = False
            raise RuntimeError("synthetic provider read failure")
        return self.observation

    def close(self) -> bool:
        self.close_calls += 1
        self.generation = None
        return True


def _account_observation_service_process(
    control: Any,
    raw_config: dict[str, Any],
    registry_path: str,
    journal_path: str,
    guard_directory: str,
    diagnostic_path: str,
    account_key_values: dict[str, Any],
    observation_values: dict[str, Any],
    service_keys: dict[str, bytes],
) -> None:
    """Spawn target: an actual Gateway ServiceHost with a synthetic provider."""

    from bt_api_base.account_protocol import AccountKey, AccountObservation
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
    observation = AccountObservation.from_dict(observation_values)
    if observation.account_key != account_key:
        raise AssertionError("synthetic observation does not match the bound account")
    required_coverage = observation.coverage

    journal = GatewayEventJournal(journal_path)
    if type(journal) is not GatewayEventJournal:
        raise AssertionError("synthetic Gateway journal must use the accepted exact type")
    journal.active_connections = 0
    journal.connection_close_attempts = 0
    journal.connection_close_failures = 0
    original_journal_connection = journal._connection

    @contextmanager
    def tracked_journal_connection() -> Any:
        connection = journal._connect()
        journal.active_connections += 1
        primary_error: BaseException | None = None
        try:
            yield connection
        except BaseException as error:
            primary_error = error
            raise
        finally:
            journal.connection_close_attempts += 1
            try:
                connection.close()
            except BaseException as close_error:
                journal.connection_close_failures += 1
                if primary_error is not None:
                    _add_failure_note(
                        primary_error,
                        "Synthetic Gateway journal connection close failed: "
                        + type(close_error).__name__,
                    )
                else:
                    raise
            else:
                journal.active_connections -= 1

    # Observe the exact production journal instance without changing its class
    # or the connection/close behavior used by the Gateway worker.
    journal._connection = tracked_journal_connection
    holder: dict[str, Any] = {"journal": journal}
    provider = _SyntheticAccountProvider(account_key, observation)
    account_scope = GatewayServiceAccountScope(
        account_ref=_ACCOUNT_REF,
        execution_domain_ref=_DOMAIN,
        journal_account_scope=_JOURNAL_SCOPE,
        account_read_strategy_scope=_STATE_SCOPE,
        shared_account_facts_scope=_STATE_SCOPE,
    )
    # The trusted service identity authenticates the Gateway peer. The read
    # handler receives the authenticated application identity from ServiceCallContext.
    principal = GatewayPrincipal(
        principal_id=_APP_PRINCIPAL,
        account_scopes=frozenset({_JOURNAL_SCOPE}),
        strategy_scopes=frozenset({_STATE_SCOPE}),
        allowed_kinds=frozenset({GatewayCommandKind.READ}),
    )

    def resource_provider(
        component: str, _instance_id: str, options: Any, _scope: Any
    ) -> Any:
        if component != "gateway" or options.get("role") != "account_session_worker":
            raise AssertionError("unexpected Gateway resource request")
        guard = LocalAccountSessionGuard(
            Path(guard_directory),
            account_key.account_key_id,
            owner_ref="afi-observation-synthetic-session",
        )
        holder["guard"] = guard
        worker = GatewayAccountSessionWorker(
            provider,
            journal,
            account_key=account_key,
            journal_account_scope=_JOURNAL_SCOPE,
            state_scope=_STATE_SCOPE,
            guard=guard,
            required_coverage=required_coverage,
            refresh_interval_seconds=3600,
            max_staleness_seconds=7200,
            request_timeout_seconds=2,
        )
        holder["worker"] = worker
        return ComponentResources.owned(
            {
                "journal": journal,
                "accounts": {_ACCOUNT_REF: account_scope},
                "principals": {_APP_PRINCIPAL: principal},
            },
            ready=lambda: True,
            close=worker.close,
            internal_ports={"service.provider_session": worker},
        )

    application_identity = WireIdentity(
        WireRole.APPLICATION_CLIENT,
        _APP_PRINCIPAL,
        _APP_ACTOR,
        _APP_DELEGATE,
    )
    app_grant = ResourceGrant(
        _INSTANCE_ID,
        "service.account_read",
        _CLIENT_SCOPE_REF,
        WireScope(_DOMAIN, account_ref=_ACCOUNT_REF),
        frozenset({"account.snapshot"}),
    )
    host = None
    child_failure: BaseException | None = None
    registry = None
    registry_originals: list[tuple[str, Any]] = []
    account_snapshot_handler_key = (_INSTANCE_ID, "account.snapshot")
    original_account_snapshot_handler = None

    def record_gateway_diagnostic(
        stage: str,
        *,
        error: BaseException | None = None,
        **facts: Any,
    ) -> None:
        """Preserve the first synthetic Gateway failure plus later reply facts."""

        path = Path(diagnostic_path)
        try:
            if path.is_file():
                existing = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    existing = {}
            else:
                existing = {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing = {}
        observation: dict[str, Any] = {"stage": stage, **facts}
        if error is not None:
            observation.update(
                {
                    "exception_type": type(error).__name__,
                    "traceback": "".join(
                        traceback.format_exception(type(error), error, error.__traceback__)
                    ),
                }
            )
        if not existing:
            existing = {"first_observation": observation, "observations": []}
        else:
            existing.setdefault("observations", []).append(observation)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(existing, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
        except BaseException as diagnostic_error:
            if error is not None:
                _add_failure_note(
                    error,
                    "Synthetic Gateway failure diagnostic could not be written: "
                    + type(diagnostic_error).__name__,
                )
                return
            raise

    def child_cleanup_state() -> dict[str, Any]:
        worker = holder.get("worker")
        guard = holder.get("guard")
        guard_record_closed = False
        if guard is not None:
            try:
                if guard.lock_path.is_file():
                    record = json.loads(guard.lock_path.read_text(encoding="utf-8"))
                    status = record.get("status") if isinstance(record, dict) else None
                    guard_record_closed = status == "closed"
            except (OSError, ValueError, AttributeError):
                pass
        guard_released = (
            guard is not None
            and guard._phase == "idle"
            and guard._fd is None
            and not guard._os_locked
            and guard_record_closed
        )
        return {
            "host_closed": host is not None and host.state == "closed",
            "host_cleanup_failure_count": len(getattr(host, "_last_cleanup_failures", ()))
            if host is not None
            else None,
            "registry_closed": host is not None and host._registry is None,
            "worker_closed": worker is not None and worker.state == "closed",
            "guard_released": guard_released,
            "journal_idle": journal.active_connections == 0
            and journal.connection_close_attempts >= 1
            and journal.connection_close_failures == 0,
        }

    try:
        host = ServiceHost(
            config,
            TrustedServiceAuthority(
                identity=WireIdentity(
                    WireRole.SERVICE,
                    _SERVICE_PRINCIPAL,
                    _SERVICE_ID,
                ),
                scope=WireScope(_DOMAIN),
                scope_ref=config.scope_ref,
                scope_version="afi-observation-gateway-scope-v1",
                security_ref=_SECURITY_REF,
                security_version="curve-key-v1",
                registration_policy_ref=config.registration_policy_ref,
                registration_policy_version="afi-observation-policy-v1",
                service_requirements_ref=config.service_requirements_ref,
                service_requirements_version="afi-observation-requirements-v1",
                curve_public_key=service_keys["server_public"],
                curve_secret_key=service_keys["server_secret"],
                principals={service_keys["application_public"]: _APP_PRINCIPAL},
                grants={_APP_PRINCIPAL: (PrincipalGrant(application_identity, (app_grant,)),)},
            ),
            registry_path,
            resource_provider,
        )
        host.start()
        registry = host._registry
        if registry is None:
            raise AssertionError("started synthetic Gateway has no service registry")
        handlers = registry._handlers
        if account_snapshot_handler_key not in handlers:
            raise AssertionError("synthetic Gateway did not register account.snapshot")
        original_account_snapshot_handler = handlers[account_snapshot_handler_key]
        original_dispatch = registry._dispatch
        original_normalize_result = registry._normalize_result
        registry_originals.extend(
            (
                ("_dispatch", original_dispatch),
                ("_normalize_result", original_normalize_result),
            )
        )

        def diagnostic_account_snapshot_handler(context: Any, arguments: Any) -> Any:
            result_fits = context.result_fits
            if callable(result_fits):

                def diagnostic_result_fits(result: Mapping[str, Any]) -> bool:
                    try:
                        fits = result_fits(result)
                    except BaseException as error:
                        record_gateway_diagnostic("result_fits", error=error)
                        raise
                    if fits is False:
                        record_gateway_diagnostic(
                            "result_fits",
                            outcome="false",
                            result_type=type(result).__name__,
                            result_keys=sorted(
                                key for key in result if type(key) is str
                            )[:64]
                            if isinstance(result, Mapping)
                            else None,
                        )
                    return fits

                context = replace(context, result_fits=diagnostic_result_fits)
            try:
                result = original_account_snapshot_handler(context, arguments)
            except BaseException as error:
                record_gateway_diagnostic("account_snapshot_handler", error=error)
                raise
            if not isinstance(result, Mapping):
                record_gateway_diagnostic(
                    "account_snapshot_handler",
                    outcome="non_mapping_result",
                    result_type=type(result).__name__,
                )
            return result

        def diagnostic_normalize_result(value: Any, *, depth: int = 0) -> Any:
            try:
                return original_normalize_result(value, depth=depth)
            except BaseException as error:
                record_gateway_diagnostic(
                    "normalize_result",
                    error=error,
                    depth=depth,
                    value_type=type(value).__name__,
                )
                raise

        def diagnostic_dispatch(principal_ref: str, request: Any) -> Any:
            try:
                response = original_dispatch(principal_ref, request)
            except BaseException as error:
                if getattr(getattr(request, "header", None), "operation", None) == (
                    "account.snapshot"
                ):
                    record_gateway_diagnostic("registry_dispatch", error=error)
                raise
            if (
                getattr(getattr(request, "header", None), "operation", None)
                == "account.snapshot"
                and isinstance(response, Mapping)
                and response.get("ok") is not True
            ):
                reply_code = response.get("code")
                record_gateway_diagnostic(
                    "registry_reply",
                    reply_code=reply_code
                    if type(reply_code) is str
                    and reply_code.isascii()
                    and reply_code.isupper()
                    and len(reply_code) <= 64
                    else "other",
                    operation="account.snapshot",
                )
            return response

        handlers[account_snapshot_handler_key] = diagnostic_account_snapshot_handler
        registry._normalize_result = diagnostic_normalize_result
        registry._dispatch = diagnostic_dispatch
        worker = holder["worker"]
        control.send(
            (
                "ready",
                host.endpoint,
                host.state,
                provider.connect_calls,
                provider.read_calls,
                worker.state,
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
                        {
                            "provider_connect_calls": provider.connect_calls,
                            "provider_read_calls": provider.read_calls,
                            "provider_close_calls": provider.close_calls,
                            **child_cleanup_state(),
                        },
                    )
                )
                return
            if command == ("status",):
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
            if command == ("fail_next_read",):
                provider.fail_next_read = True
                try:
                    worker.refresh()
                except Exception as error:
                    control.send(("refresh_failed", getattr(error, "code", "unknown")))
                else:
                    control.send(("refresh_succeeded",))
                continue
            raise AssertionError("unknown synthetic Gateway host command")
    except BaseException as error:
        child_failure = error
        host_close_error: str | None = None
        if host is not None and host.state not in {"closed", "failed", "close_failed"}:
            try:
                host.close()
            except BaseException as close_error:
                host_close_error = _finite_error_code(close_error)
        try:
            control.send(
                (
                    "error",
                    {
                        "error_code": _finite_error_code(error),
                        "host_close_error": host_close_error,
                        "cleanup": child_cleanup_state(),
                    },
                )
            )
        except BaseException as send_error:
            _add_failure_note(
                error,
                "Synthetic Gateway child could not report its failure: "
                + type(send_error).__name__,
            )
        raise
    finally:
        cleanup_errors: list[tuple[str, BaseException]] = []
        if registry is not None:
            for name, original in reversed(registry_originals):
                try:
                    setattr(registry, name, original)
                except BaseException as restore_error:
                    cleanup_errors.append(("restore_registry_" + name, restore_error))
            if original_account_snapshot_handler is not None:
                try:
                    registry._handlers[account_snapshot_handler_key] = (
                        original_account_snapshot_handler
                    )
                except BaseException as restore_error:
                    cleanup_errors.append(("restore_account_snapshot_handler", restore_error))
        try:
            journal._connection = original_journal_connection
        except BaseException as restore_error:
            cleanup_errors.append(("restore_journal_connection_observer", restore_error))
        try:
            control.close()
        except BaseException as close_error:
            cleanup_errors.append(("close_child_control_pipe", close_error))
        if cleanup_errors:
            if child_failure is not None:
                for stage, cleanup_error in cleanup_errors:
                    _add_failure_note(
                        child_failure,
                        "Synthetic Gateway child cleanup failed at "
                        + stage
                        + ": "
                        + type(cleanup_error).__name__,
                    )
            else:
                stage, cleanup_error = cleanup_errors[0]
                _add_failure_note(
                    cleanup_error,
                    "Synthetic Gateway child cleanup stage: " + stage,
                )
                raise cleanup_error


def _gateway_service_config(endpoint: str) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _SERVICE_ID,
        "scope_ref": _SERVICE_SCOPE_REF,
        "transport_ref": _TRANSPORT_REF,
        "registration_policy_ref": "afi-observation-registration-v1",
        "service_requirements_ref": "afi-observation-service-requirements-v1",
        "components": {
            "gateway": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _INSTANCE_ID,
                    "bind_ports": ["service.account_read", "service.provider_session"],
                    "options": {
                        "role": "account_session_worker",
                        "account_session_ref": "afi-observation-session-v1",
                    },
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _SECURITY_REF,
                    "options": {
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _application_profile(
    *,
    endpoint: str,
    account_key: dict[str, Any],
    resources: list[dict[str, str]],
    server_public: bytes,
    application_public: bytes,
    application_secret: bytes,
) -> dict[str, Any]:
    identity = {
        "principal_ref": _APP_PRINCIPAL,
        "actor_ref": _APP_ACTOR,
        "delegate_ref": _APP_DELEGATE,
    }
    return {
        "subject": _SUBJECT_A,
        "identity": identity,
        "client_config": {
            "client_config_schema_version": 1,
            "process_role": "application_client",
            "registration": {"application_ref": _APP_ACTOR},
            "clients": {
                "gateway": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": "application.account",
                                "service_id": _SERVICE_ID,
                                "instance_id": _INSTANCE_ID,
                                "scope_ref": _CLIENT_SCOPE_REF,
                                "transport_ref": _TRANSPORT_REF,
                                "account_ref": _ACCOUNT_REF,
                            }
                        ],
                        "options": {"request_timeout_ms": _REQUEST_TIMEOUT_MS},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    _TRANSPORT_REF: {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_connect": endpoint},
                        "security_profile_ref": _SECURITY_REF,
                        "options": {
                            "request_timeout_ms": _REQUEST_TIMEOUT_MS,
                            "high_water_mark": 32,
                            "max_message_bytes": _MAX_MESSAGE_BYTES,
                        },
                    }
                },
            },
        },
        "scope_claims": {
            _CLIENT_SCOPE_REF: {
                "execution_domain_ref": _DOMAIN,
                "account_ref": _ACCOUNT_REF,
                "strategy_ref": None,
            }
        },
        "peer_identities": {
            _SERVICE_ID: {
                "principal_ref": _SERVICE_PRINCIPAL,
                "actor_ref": _SERVICE_ID,
            }
        },
        "curve_keys": {
            _SECURITY_REF: {
                "server_key": server_public.decode("ascii"),
                "public_key": application_public.decode("ascii"),
                "secret_key": application_secret.decode("ascii"),
            }
        },
        "grants": {
            "account_refs": [_ACCOUNT_REF],
            "account_book_refs": [],
            "strategy_book_refs": [],
            "order_scope_refs": [],
            "monitor_scope_refs": [],
        },
        "account_bindings": {
            _ACCOUNT_REF: {
                "mount": "application.account",
                "scope_ref": _CLIENT_SCOPE_REF,
                "currency": "USDT",
                "account_key": account_key,
                "coverage": resources,
                "require_open_orders": False,
            }
        },
        "account_book_bindings": {},
        "strategy_book_bindings": {},
        "order_bindings": {},
        "monitor_bindings": {},
        "worker": {"max_queue_size": 8, "maintenance_interval_seconds": 300.0},
    }


def _endpoint() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    return f"tcp://127.0.0.1:{port}"


def _add_failure_note(error: BaseException, note: str) -> None:
    """Keep the first exception while exposing cleanup facts on Python 3.10+."""
    add_note = getattr(error, "add_note", None)
    if callable(add_note):
        add_note(note)
    else:  # BaseException.add_note was added in Python 3.11.
        error.args = (*error.args, note)


def _safe_code(code: Any, *, absent: str | None = None) -> str | None:
    if (
        type(code) is str
        and 0 < len(code) <= 64
        and code.isascii()
        and code[0] in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        and all(char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for char in code)
    ):
        return code
    return absent if code is None else "OTHER_ACCOUNT_READ_ERROR"


def _finite_error_code(error: BaseException) -> str:
    """Return only a bounded code token, never an exception message or value."""
    try:
        code = getattr(error, "code", None)
    except BaseException:
        code = None
    return _safe_code(code) or "OTHER_ACCOUNT_READ_ERROR"


def _service_account_refresh_diagnostic(
    state: Any,
    *,
    outcome: str,
    error_code: str | None = None,
    expected_account: Any,
) -> dict[str, Any]:
    """Keep the refresh outcome separate from the captured protocol reply."""
    observation = getattr(state, "observation", None) if state is not None else None
    account_key = getattr(observation, "account_key", None)
    account_key_present = account_key is not None
    account_key_matches_expected = (
        type(account_key) is type(expected_account) and account_key == expected_account
        if account_key_present
        else False
    )
    return {
        "outcome": outcome if outcome in {"accepted", "error"} else "unknown",
        "error_code": error_code,
        "last_view_present": state is not None,
        "last_view_observation_present": observation is not None,
        "last_view_account_key_present": account_key_present,
        "last_view_account_key_matches_expected": account_key_matches_expected,
    }


def _account_snapshot_reply_diagnostic(
    reply: Any, *, expected_account: Mapping[str, Any]
) -> dict[str, Any]:
    """Summarize only readiness, cut, cursor, coverage, and generation facts."""
    if not isinstance(reply, Mapping):
        return {"reply_received": False}
    status = reply.get("state_status")
    status = status if isinstance(status, Mapping) else {}
    snapshot = reply.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    payload = snapshot.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    observation = payload.get("observation")
    observation = observation if isinstance(observation, Mapping) else {}
    raw_account_key = observation.get("account_key")
    account_key_present = raw_account_key is not None
    account_key_shape_matches = (
        type(raw_account_key) is dict
        and set(raw_account_key) == set(expected_account)
    )
    account_key_matches_expected = (
        account_key_shape_matches and raw_account_key == dict(expected_account)
    )
    coverage = observation.get("coverage")
    balances = observation.get("balances")
    positions = observation.get("positions")
    rows = [
        row
        for values in (balances, positions)
        if type(values) in {tuple, list}
        for row in values
        if isinstance(row, Mapping)
    ]
    valuation = observation.get("valuation")
    if isinstance(valuation, Mapping):
        rows.append(valuation)
    observed_at = [row.get("observed_at_utc") for row in rows]
    completed_at = observation.get("completed_at_utc")
    fresh_for = status.get("fresh_for_seconds")
    status_generation = status.get("session_generation")
    payload_generation = payload.get("session_generation")
    next_cursor = reply.get("next_cursor")
    latest_cursor = reply.get("latest_cursor")
    snapshot_cursor = snapshot.get("cursor")

    def compare(left: Any, right: Any) -> str:
        if type(left) is not int or left < 0 or type(right) is not int or right < 0:
            return "missing"
        return "match" if left == right else "mismatch"

    generations_present = (
        type(status_generation) is str
        and bool(status_generation)
        and type(payload_generation) is str
        and bool(payload_generation)
    )
    try:
        fresh_for_seconds = float(fresh_for)
        if not math.isfinite(fresh_for_seconds) or not 0 <= fresh_for_seconds <= 86_400:
            fresh_for_seconds = None
    except (TypeError, ValueError, OverflowError):
        fresh_for_seconds = None
    return {
        "reply_received": True,
        "observation_present": bool(observation),
        "account_key_present": account_key_present,
        "account_key_shape_matches_expected": account_key_shape_matches,
        "account_key_matches_expected": account_key_matches_expected,
        "ready": status.get("ready") if type(status.get("ready")) is bool else None,
        "fresh_for_seconds": fresh_for_seconds
        if type(fresh_for) in {int, float}
        else None,
        "generation_relation": (
            "match" if status_generation == payload_generation else "mismatch"
        )
        if generations_present
        else "missing",
        "snapshot_page_cursor_relation": compare(snapshot_cursor, next_cursor),
        "page_latest_cursor_relation": compare(next_cursor, latest_cursor),
        "coverage_resource_count": len(coverage)
        if type(coverage) in {tuple, list}
        else None,
        "balances_complete": observation.get("balances_complete")
        if type(observation.get("balances_complete")) is bool
        else None,
        "positions_complete": observation.get("positions_complete")
        if type(observation.get("positions_complete")) is bool
        else None,
        "consistency": observation.get("consistency")
        if type(observation.get("consistency")) is str
        and observation.get("consistency") in {"provider_atomic", "multi_query"}
        else "other",
        "cut_row_count": len(rows),
        "cut_observed_at_count": sum(type(value) is str for value in observed_at),
        "cut_matches_completed_at": bool(rows)
        and type(completed_at) is str
        and len(observed_at) == len(rows)
        and all(value == completed_at for value in observed_at),
    }


def _start_process(context: Any, target: Any, arguments: tuple[Any, ...]) -> dict[str, Any]:
    parent, child = context.Pipe(duplex=True)
    process = context.Process(target=target, args=(child, *arguments), name="afi-observation-host")
    try:
        process.start()
        child.close()
    except BaseException as start_error:
        cleanup = {
            "forced_cleanup": False,
            "terminate_attempted": False,
            "parent_pipe_closed": False,
            "child_endpoint_copy_closed": False,
            "process_handle_closed": False,
            "errors": [],
        }

        def attempt(stage: str, callback: Any) -> Any:
            try:
                return callback()
            except BaseException as error:
                cleanup["errors"].append({"stage": stage, "type": type(error).__name__})
                return None

        for name, connection in (
            ("child_endpoint_copy_closed", child),
            ("parent_pipe_closed", parent),
        ):
            try:
                connection.close()
                cleanup[name] = True
            except BaseException as error:
                cleanup["errors"].append({"stage": name, "type": type(error).__name__})
        started = attempt("read_process_pid", lambda: process.pid) is not None

        def close_process_handle(stage: str) -> None:
            try:
                process.close()
                cleanup["process_handle_closed"] = True
            except BaseException as error:
                cleanup["errors"].append({"stage": stage, "type": type(error).__name__})

        if started:
            alive = attempt("check_process_alive", process.is_alive)
            if alive is not False:
                cleanup["forced_cleanup"] = True
                cleanup["terminate_attempted"] = True
                attempt("terminate_process", process.terminate)
            attempt("join_process", lambda: process.join(10.0))
            cleanup["exitcode"] = attempt("read_exitcode", lambda: process.exitcode)
            alive = attempt("check_process_after_join", process.is_alive)
            if alive is False:
                close_process_handle("close_process_handle")
            else:
                cleanup["process_still_alive"] = True
        else:
            close_process_handle("close_unstarted_process")
        _add_failure_note(
            start_error,
            "Synthetic Gateway ServiceHost startup cleanup: "
            + json.dumps(cleanup, sort_keys=True),
        )
        raise
    return {"pipe": parent, "process": process}


def _receive(pipe: Any, timeout: float = 20.0) -> Any:
    assert pipe.poll(timeout), "synthetic Gateway ServiceHost missed its response bound"
    return pipe.recv()


_CHILD_CLEANUP_FIELDS = frozenset(
    {
        "host_closed",
        "host_cleanup_failure_count",
        "registry_closed",
        "worker_closed",
        "guard_released",
        "journal_idle",
    }
)


def _finite_child_cleanup(value: Any) -> dict[str, Any] | None:
    if type(value) is not dict or not _CHILD_CLEANUP_FIELDS <= set(value):
        return None
    if any(type(value.get(key)) is not bool for key in _CHILD_CLEANUP_FIELDS - {"host_cleanup_failure_count"}):
        return None
    failures = value.get("host_cleanup_failure_count")
    if type(failures) is not int or failures < 0:
        return None
    return {key: value[key] for key in _CHILD_CLEANUP_FIELDS}


def _close_process(host: dict[str, Any] | None) -> dict[str, Any]:
    """Close the synthetic host and retain only the lifecycle facts under test."""
    outcome: dict[str, Any] = {
        "close_response_received": False,
        "close_ack_valid": False,
        "close_ack": None,
        "child_error": None,
        "exitcode": None,
        "child_endpoint_closed": False,
        "forced_cleanup": False,
        "terminate_attempted": False,
        "parent_pipe_closed": False,
        "process_handle_closed": False,
        "errors": [],
        "clean": False,
    }
    if host is None:
        return outcome

    process = host["process"]
    pipe = host["pipe"]

    def record_error(stage: str, error: BaseException) -> None:
        outcome["errors"].append({"stage": stage, "type": type(error).__name__})

    try:
        alive = process.is_alive()
    except BaseException as error:
        record_error("check_before_close", error)
        alive = True
    if alive:
        try:
            pipe.send(("close",))
        except BaseException as error:
            record_error("send_close", error)
        else:
            try:
                reply = _receive(pipe, timeout=10.0)
            except BaseException as error:
                record_error("receive_close_ack", error)
            else:
                outcome["close_response_received"] = True
                if type(reply) is tuple and len(reply) == 2 and reply[0] == "closed":
                    payload = reply[1] if type(reply[1]) is dict else {}
                    ack = _finite_child_cleanup(payload)
                    counts = {
                        key: payload.get(key)
                        if type(payload.get(key)) is int and payload.get(key) >= 0
                        else None
                        for key in ("provider_connect_calls", "provider_read_calls", "provider_close_calls")
                    }
                    outcome["close_ack"] = {**(ack or {}), **counts}
                    outcome["close_ack_valid"] = bool(
                        ack
                        and type(counts["provider_connect_calls"]) is int
                        and counts["provider_connect_calls"] == 1
                        and type(counts["provider_read_calls"]) is int
                        and counts["provider_read_calls"] >= 1
                        and type(counts["provider_close_calls"]) is int
                        and counts["provider_close_calls"] == 1
                        and ack["host_closed"]
                        and ack["host_cleanup_failure_count"] == 0
                        and ack["registry_closed"]
                        and ack["worker_closed"]
                        and ack["guard_released"]
                        and ack["journal_idle"]
                    )
                    if not outcome["close_ack_valid"]:
                        outcome["errors"].append("close_ack_invalid")
                elif type(reply) is tuple and len(reply) == 2 and reply[0] == "error":
                    payload = reply[1] if type(reply[1]) is dict else {}
                    outcome["child_error"] = {
                        "error_code": _safe_code(payload.get("error_code"))
                        or "OTHER_ACCOUNT_READ_ERROR",
                        "cleanup": _finite_child_cleanup(payload.get("cleanup")),
                    }
                    outcome["errors"].append("child_reported_error")
                else:
                    outcome["errors"].append("close_response_invalid")
    else:
        outcome["errors"].append("host_exited_before_close_ack")

    try:
        process.join(10.0)
        alive = process.is_alive()
    except BaseException as error:
        record_error("join_after_close", error)
        alive = True
    if alive:
        outcome["forced_cleanup"] = True
        outcome["terminate_attempted"] = True
        try:
            process.terminate()
            process.join(10.0)
            alive = process.is_alive()
        except BaseException as error:
            record_error("terminate_and_join", error)
            alive = True
    if alive:
        outcome["errors"].append("host_alive_after_cleanup")

    try:
        outcome["exitcode"] = process.exitcode
    except BaseException as error:
        record_error("read_exitcode", error)
    outcome["child_endpoint_closed"] = outcome["exitcode"] is not None
    if outcome["exitcode"] != 0:
        outcome["errors"].append("nonzero_or_missing_exitcode")

    try:
        pipe.close()
        outcome["parent_pipe_closed"] = True
    except BaseException as error:
        record_error("close_pipe", error)

    try:
        if process.is_alive():
            outcome["errors"].append("process_alive_before_handle_close")
        else:
            process.close()
            outcome["process_handle_closed"] = True
    except BaseException as error:
        record_error("close_process_handle", error)

    outcome["clean"] = (
        outcome["close_ack_valid"]
        and outcome["exitcode"] == 0
        and not outcome["forced_cleanup"]
        and outcome["parent_pipe_closed"]
        and outcome["child_endpoint_closed"]
        and outcome["process_handle_closed"]
        and not outcome["errors"]
    )
    return outcome


def _account_total_failure_diagnostic(
    projected: Any,
    *,
    refresh_event: dict[str, Any] | None = None,
    reply_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep failure output bounded and omit all account and execution identifiers."""
    accounts = projected.get("accounts") if isinstance(projected, Mapping) else None
    rows: list[dict[str, Any]] = []
    for row in accounts if isinstance(accounts, list) else ():
        if not isinstance(row, Mapping):
            continue
        observation = row.get("provider_observation")
        observation = observation if isinstance(observation, Mapping) else {}
        coverage = observation.get("coverage")
        coverage = coverage if isinstance(coverage, Mapping) else {}
        resources = coverage.get("resources")
        cut = observation.get("cut")
        cut = cut if isinstance(cut, Mapping) else {}
        rows.append(
            {
                "quality": row.get("quality")
                if type(row.get("quality")) is str
                and row.get("quality") in {"fresh", "stale", "not_collected", "unavailable"}
                else "other",
                "detail_code": _safe_code(row.get("detail_code"), absent=None),
                "currency": row.get("currency")
                if type(row.get("currency")) is str
                and row["currency"].isascii()
                and row["currency"].isalnum()
                and row["currency"].isupper()
                and len(row["currency"]) <= 12
                else None,
                "cash_missing": row.get("cash") is None,
                "value_missing": row.get("value") is None,
                "included_in_total": row.get("included_in_total")
                if type(row.get("included_in_total")) is bool
                else None,
                "provider_status": observation.get("status")
                if type(observation.get("status")) is str
                and observation.get("status") in {"available", "stale", "unavailable", "absent"}
                else "other",
                "provider_code": _safe_code(observation.get("code"), absent=None),
                "coverage_resource_count": len(resources) if isinstance(resources, list) else None,
                "coverage_complete": coverage.get("state") == "complete",
                "cut_row_count": cut.get("row_count")
                if type(cut.get("row_count")) is int
                else None,
                "cut_observed_at_count": cut.get("row_observed_at_count")
                if type(cut.get("row_observed_at_count")) is int
                else None,
                "cut_skew_is_zero": cut.get("row_skew_ns") == "0",
                "cut_skew_present": type(cut.get("row_skew_ns")) is str,
            }
        )
    total = projected.get("account_total") if isinstance(projected, Mapping) else None
    total = total if isinstance(total, Mapping) else {}
    return {
        "account_total_status": total.get("status")
        if type(total.get("status")) is str
        else None,
        "account_total_currency": total.get("currency")
        if type(total.get("currency")) is str
        and total["currency"].isascii()
        and total["currency"].isalnum()
        and total["currency"].isupper()
        and 1 < len(total["currency"]) <= 12
        else None,
        "account_total_value_missing": total.get("value") is None,
        "accounts": rows,
        "account_snapshot_reply": reply_event or {"reply_received": False},
        "service_account_refresh": refresh_event or {"outcome": "not_observed"},
    }


def _access_token(subject: str) -> str:
    import jwt

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


def _synthetic_observation_values(account_key: dict[str, Any]) -> dict[str, Any]:
    from bt_api_base.account_protocol import AccountKey

    return _make_observation(AccountKey.from_dict(account_key)).to_dict()


def _make_observation(account_key: Any) -> Any:
    from bt_api_base.account_protocol import (
        AccountBalance,
        AccountObservation,
        AccountPosition,
        AccountResourceKey,
        AccountValuation,
    )
    from bt_api_base.market_protocol import MarketInstrumentKey

    observed_at = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    spot = AccountResourceKey("spot", "cash")
    linear = AccountResourceKey("linear", "cross")
    balances = (
        AccountBalance(
            resource=spot,
            currency="USDT",
            total="123.45",
            available="120.00",
            locked="3.45",
            observed_at_utc=observed_at,
        ),
        AccountBalance(
            resource=spot,
            currency="EUR",
            total="0",
            available="0",
            locked="0",
            observed_at_utc=observed_at,
        ),
        AccountBalance(
            resource=linear,
            currency="BTC",
            total=None,
            available=None,
            locked=None,
            observed_at_utc=observed_at,
        ),
    )
    positions = (
        AccountPosition(
            resource=spot,
            instrument=MarketInstrumentKey(
                provider=account_key.provider,
                venue=account_key.venue,
                environment=account_key.environment,
                product_type="spot",
                instrument_id="spot:BTC-USDT",
                native_symbol="BTCUSDT",
            ),
            side="net",
            quantity="2",
            qty_unit="base_asset",
            average_price="40.5",
            price_currency="USDT",
            observed_at_utc=observed_at,
        ),
        AccountPosition(
            resource=linear,
            instrument=MarketInstrumentKey(
                provider=account_key.provider,
                venue=account_key.venue,
                environment=account_key.environment,
                product_type="linear",
                instrument_id="linear:BTCUSDT-PERP",
                native_symbol="BTCUSDT-PERP",
            ),
            side="short",
            quantity="0",
            qty_unit="contracts",
            average_price=None,
            price_currency=None,
            observed_at_utc=observed_at,
        ),
    )
    return AccountObservation(
        account_key=account_key,
        observation_id="afi-observation-snapshot-r1",
        coverage=(spot, linear),
        balances=balances,
        positions=positions,
        valuation=AccountValuation(
            currency="USDT",
            available_cash="120.00",
            equity="500.00",
            observed_at_utc=observed_at,
        ),
        started_at_utc=observed_at,
        completed_at_utc=observed_at,
        consistency="multi_query",
        balances_complete=True,
        positions_complete=True,
    )


def _assert_service_read_access_denied(response: Any) -> None:
    """Check the exact access-denial code in the application's standard envelope."""
    assert response.status_code == 403
    payload = response.json()
    assert payload.get("error") == "HTTP_403"
    details = payload.get("details")
    assert isinstance(details, dict)
    assert details.get("code") == "SERVICE_READ_ACCESS_DENIED"


def test_authorized_gateway_observation_reaches_portfolio_projection_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise AccountObservation → ServiceAccountClient → authorized HTTP projection."""

    import httpx
    import zmq
    from bt_api_base.account_protocol import AccountKey, AccountResourceKey
    from bt_api_py import service_account as sdk_service_account
    from bt_api_py.service_runtime import ServiceClientRuntime
    from pydantic import SecretStr
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    import app
    import app.api.portfolio.api as portfolio_api
    import app.main as main_module
    import app.services.portfolio_composition as portfolio_composition_module
    import app.services.service_read.client as service_read_client
    import app.services.service_read.contracts as service_read_contracts
    import app.services.service_read.deployment as service_read_deployment
    import app.services.service_read.session as service_read_session
    from app.db.database import get_db
    from app.models.portfolio_composition import PortfolioCompositionVersion
    from app.models.strategy_approval_authority import StrategyApprovalAuthorityEpoch
    from app.schemas.portfolio_composition import (
        PortfolioCompositionCreate,
        PortfolioCompositionMember,
    )
    from app.services.portfolio_composition import PortfolioCompositionService
    from app.services.service_read.deployment import ServiceReadDeployment
    from app.utils import security

    backend_root = Path(__file__).resolve().parents[1]
    app_root = (backend_root / "app").resolve()

    def assert_normal_backend_origin(module: Any) -> None:
        origin = getattr(module, "__file__", None)
        assert isinstance(origin, str), f"{module.__name__} has no source origin"
        resolved_origin = Path(origin).resolve()
        assert resolved_origin.is_relative_to(app_root), (
            module.__name__,
            str(resolved_origin),
            str(app_root),
        )

    for backend_module in (
        app,
        main_module,
        portfolio_api,
        portfolio_composition_module,
        service_read_client,
        service_read_contracts,
        service_read_deployment,
        service_read_session,
    ):
        assert_normal_backend_origin(backend_module)

    monkeypatch.setattr(
        portfolio_api,
        "_get_manager",
        lambda: (_ for _ in ()).throw(
            AssertionError("versioned compositions must not instantiate the legacy manager")
        ),
    )
    monkeypatch.setattr(main_module.settings, "DB_AUTO_CREATE_SCHEMA", True)
    monkeypatch.setattr(main_module.settings, "RAG_VECTOR_ENABLED", False)
    monkeypatch.setattr(
        security,
        "settings",
        SimpleNamespace(JWT_SECRET_KEY=_JWT_SECRET, JWT_ALGORITHM=_JWT_ALGORITHM),
    )

    async def no_startup(*_args: Any, **_kwargs: Any) -> None:
        return None

    class NoopShutdownManager:
        async def initiate(self, _app: Any) -> None:
            return None

    monkeypatch.setattr(main_module, "run_startup", no_startup)
    monkeypatch.setattr(main_module, "run_shutdown", no_startup)
    monkeypatch.setattr(main_module, "GracefulShutdownManager", NoopShutdownManager)

    original_session_start = service_read_session.SdkServiceReadSession.start
    captured_sessions: list[Any] = []

    def capture_real_session_start(session: Any) -> None:
        original_session_start(session)
        captured_sessions.append(session)

    monkeypatch.setattr(
        service_read_session.SdkServiceReadSession,
        "start",
        capture_real_session_start,
    )

    runtime_reply_events: list[dict[str, Any]] = []
    refresh_events: list[dict[str, Any]] = []
    observation_events_lock = threading.Lock()
    original_runtime_call = ServiceClientRuntime.call
    original_account_refresh = sdk_service_account.ServiceAccountClient.refresh

    def capture_authorized_runtime_call(runtime: Any, *args: Any, **kwargs: Any) -> Any:
        operation = args[1] if len(args) > 1 else kwargs.get("operation")
        if operation != "account.snapshot":
            return original_runtime_call(runtime, *args, **kwargs)
        try:
            reply = original_runtime_call(runtime, *args, **kwargs)
        except BaseException as error:
            with observation_events_lock:
                runtime_reply_events.append(
                    {"reply_received": False, "error_code": _finite_error_code(error)}
                )
            raise
        with observation_events_lock:
            runtime_reply_events.append(
                _account_snapshot_reply_diagnostic(
                    reply, expected_account=account_key.to_dict()
                )
            )
        return reply

    def capture_real_account_refresh(client: Any) -> Any:
        with observation_events_lock:
            reply_count_before = len(runtime_reply_events)
        try:
            state = original_account_refresh(client)
        except BaseException as error:
            try:
                last_view = client.last_view
            except BaseException:
                last_view = None
            event = _service_account_refresh_diagnostic(
                last_view,
                outcome="error",
                error_code=_finite_error_code(error),
                expected_account=account_key,
            )
            with observation_events_lock:
                reply = (
                    dict(runtime_reply_events[-1])
                    if len(runtime_reply_events) > reply_count_before
                    else None
                )
                refresh_events.append({"refresh": event, "reply": reply})
            raise
        event = _service_account_refresh_diagnostic(
            state, outcome="accepted", expected_account=account_key
        )
        with observation_events_lock:
            reply = (
                dict(runtime_reply_events[-1])
                if len(runtime_reply_events) > reply_count_before
                else None
            )
            refresh_events.append({"refresh": event, "reply": reply})
        return state

    monkeypatch.setattr(ServiceClientRuntime, "call", capture_authorized_runtime_call)
    monkeypatch.setattr(
        sdk_service_account.ServiceAccountClient,
        "refresh",
        capture_real_account_refresh,
    )

    def account_failure_diagnostic(projected: Any) -> dict[str, Any]:
        with observation_events_lock:
            latest_refresh = dict(refresh_events[-1]) if refresh_events else {}
        return _account_total_failure_diagnostic(
            projected,
            refresh_event=latest_refresh.get("refresh"),
            reply_event=latest_refresh.get("reply"),
        )

    account_key = AccountKey(
        provider="PAPER",
        venue="synthetic-venue",
        environment="simulation",
        account_id=_ACCOUNT_ID,
        subaccount_id=None,
    )
    resources = [
        AccountResourceKey("spot", "cash").to_dict(),
        AccountResourceKey("linear", "cross").to_dict(),
    ]
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    application_public, application_secret = zmq.curve_keypair()
    service_keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "application_public": application_public,
    }
    raw_profile = _application_profile(
        endpoint=endpoint,
        account_key=account_key.to_dict(),
        resources=resources,
        server_public=server_public,
        application_public=application_public,
        application_secret=application_secret,
    )
    monkeypatch.setattr(
        main_module.settings,
        "SERVICE_READ_DEPLOYMENT_JSON",
        SecretStr(json.dumps({"schema_version": 1, "subjects": [raw_profile]})),
    )

    engine = None
    app_db = None

    async def create_tables() -> None:
        assert engine is not None
        async with engine.begin() as connection:
            await connection.run_sync(PortfolioCompositionVersion.__table__.create)
            await connection.run_sync(StrategyApprovalAuthorityEpoch.__table__.create)

    async def override_db() -> Any:
        assert app_db is not None
        async with app_db() as session:
            yield session

    app = main_module.app
    previous_db_override = app.dependency_overrides.get(get_db)
    dependency_override_installed = False
    root = tmp_path / "afi-authorized-account-observation"
    guard_directory = root / "session-guard"
    host: dict[str, Any] | None = None
    deployment: ServiceReadDeployment | None = None
    owner_threads: tuple[Any, ...] = ()
    primary_error: BaseException | None = None
    host_cleanup_summary: dict[str, Any] | None = None
    host_cleanup_error: str | None = None
    dependency_override_restored = False
    app_database_disposed = False

    try:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        app_db = async_sessionmaker(engine, expire_on_commit=False)
        asyncio.run(create_tables())
        app.dependency_overrides[get_db] = override_db
        dependency_override_installed = True
        root.mkdir()
        guard_directory.mkdir()

        context = multiprocessing.get_context("spawn")
        host = _start_process(
            context,
            _account_observation_service_process,
            (
                _gateway_service_config(endpoint),
                str(root / "gateway-registry.sqlite3"),
                str(root / "gateway-journal.sqlite3"),
                str(guard_directory),
                str(root / "gateway-failure-traceback.json"),
                account_key.to_dict(),
                _synthetic_observation_values(account_key.to_dict()),
                service_keys,
            ),
        )
        ready = _receive(host["pipe"])
        assert ready[0] == "ready", ready
        assert ready[1] == endpoint
        assert ready[2] == "started"
        assert ready[3:5] == (1, 1)
        assert ready[5] == "ready"

        async def exercise_http() -> None:
            nonlocal deployment, owner_threads
            async with main_module.lifespan(app):
                deployment = app.state.service_read_deployment
                assert deployment is not None
                assert len(deployment._workers) == 1
                worker = deployment._workers[0]
                assert worker._thread is not None and worker._thread.is_alive()
                owner_threads = (worker._thread,)
                assert captured_sessions
                assert captured_sessions[0]._read_client is not None

                headers_a = {"Authorization": f"Bearer {_access_token(_SUBJECT_A)}"}
                headers_b = {"Authorization": f"Bearer {_access_token(_SUBJECT_B)}"}
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://afi-account-observation.synthetic.test",
                ) as client:
                    created = await client.post(
                        "/api/v1/portfolio/compositions",
                        headers=headers_a,
                        json={
                            "portfolio_ref": "authorized-account-observation",
                            "source_type": "live",
                            "base_currency": "USDT",
                            "members": [{"kind": "account", "ref": _ACCOUNT_REF}],
                        },
                    )
                    assert created.status_code == 201, created.text
                    assert created.json()["membership_version"] == 1
                    foreign_owner_write = await client.post(
                        "/api/v1/portfolio/compositions",
                        headers=headers_b,
                        json={
                            "portfolio_ref": "ungranted-account-observation",
                            "source_type": "live",
                            "base_currency": "USDT",
                            "members": [{"kind": "account", "ref": _ACCOUNT_REF}],
                        },
                    )
                    _assert_service_read_access_denied(foreign_owner_write)
                    unknown_ref_write = await client.post(
                        "/api/v1/portfolio/compositions",
                        headers=headers_a,
                        json={
                            "portfolio_ref": "unknown-account-observation",
                            "source_type": "live",
                            "base_currency": "USDT",
                            "members": [{"kind": "account", "ref": "afi-unknown-account"}],
                        },
                    )
                    _assert_service_read_access_denied(unknown_ref_write)

                    # Recreate pre-existing memberships that cannot be written now.
                    # The API reads below still exercise the current authorization boundary.
                    async def seed_historical_membership(
                        owner_subject: str, portfolio_ref: str, account_ref: str
                    ) -> None:
                        async with app_db() as session:
                            row = await PortfolioCompositionService(session).create_version(
                                owner_subject,
                                PortfolioCompositionCreate(
                                    portfolio_ref=portfolio_ref,
                                    source_type="live",
                                    base_currency="USDT",
                                    members=[
                                        PortfolioCompositionMember(
                                            kind="account", ref=account_ref
                                        )
                                    ],
                                ),
                            )
                            assert row.membership_version == 1

                    await seed_historical_membership(
                        _SUBJECT_B,
                        "ungranted-account-observation",
                        _ACCOUNT_REF,
                    )
                    await seed_historical_membership(
                        _SUBJECT_A,
                        "unknown-account-observation",
                        "afi-unknown-account",
                    )

                    async def overview(portfolio_ref: str, headers: dict[str, str]) -> Any:
                        response = await client.get(
                            "/api/v1/portfolio/overview",
                            params={"portfolio_ref": portfolio_ref, "membership_version": 1},
                            headers=headers,
                        )
                        return response

                    current = await overview("authorized-account-observation", headers_a)
                    assert current.status_code == 200, current.text
                    projected = current.json()
                    assert projected["source_status"] == "projected", (
                        account_failure_diagnostic(projected)
                    )
                    expected_account_total = {
                        "status": "current",
                        "currency": "USDT",
                        "value": "500.00",
                    }
                    account_total_failure_message = ""
                    if projected.get("account_total") != expected_account_total:
                        diagnostic_path = (
                            tmp_path / "afi03-authorized-http-first-failure.json"
                        )
                        diagnostic = account_failure_diagnostic(projected)
                        gateway_diagnostic_path = root / "gateway-failure-traceback.json"
                        try:
                            gateway_diagnostic = json.loads(
                                gateway_diagnostic_path.read_text(encoding="utf-8")
                            )
                        except (OSError, UnicodeError, json.JSONDecodeError):
                            gateway_diagnostic = {"artifact": "not_available"}
                        first_failure = {
                            "phase": "authorized_overview_account_total",
                            "http_status": current.status_code,
                            "source_status": projected.get("source_status")
                            if projected.get("source_status")
                            in {"projected", "unavailable", "absent"}
                            else "other",
                            "account_total_matches_expected": False,
                            "diagnostic": diagnostic,
                            "gateway_failure_diagnostic": gateway_diagnostic,
                        }
                        diagnostic_path.write_text(
                            json.dumps(first_failure, sort_keys=True, separators=(",", ":"))
                            + "\n",
                            encoding="utf-8",
                        )
                        account_total_failure_message = (
                            "authorized account total differs from the required 500.00 "
                            f"USDT projection; finite diagnostic saved at {diagnostic_path}"
                        )
                    assert projected["account_total"] == expected_account_total, (
                        account_total_failure_message
                        or account_failure_diagnostic(projected)
                    )
                    assert projected["account_snapshot_consistency"]["status"] == (
                        "single_account_cut"
                    )
                    assert projected["account_snapshot_consistency"]["atomic"] is False
                    assert projected["provider_snapshot_consistency"]["status"] == (
                        "single_account_observation_cut"
                    )
                    account = projected["accounts"][0]
                    assert account["cash"] == "120.00"
                    assert account["value"] == "500.00"
                    assert account["currency"] == "USDT"
                    assert account["included_in_total"] is True
                    observation = account["provider_observation"]
                    assert observation["status"] == "available"
                    assert observation["source"] == "AUTHORIZED_PROVIDER_ACCOUNT_OBSERVATION"
                    assert observation["consistency"] == "multi_query"
                    assert observation["coverage"] == {
                        "resources": [
                            {"product_type": "spot", "margin_pool": "cash"},
                            {"product_type": "linear", "margin_pool": "cross"},
                        ],
                        "balances_complete": True,
                        "positions_complete": True,
                        "state": "complete",
                    }
                    assert observation["cut"]["started_at_utc"]
                    assert observation["cut"]["completed_at_utc"]
                    assert observation["cut"]["started_at_utc"] == (
                        observation["cut"]["completed_at_utc"]
                    )
                    assert observation["cut"]["row_observed_at_count"] == 6
                    assert observation["cut"]["row_count"] == 6
                    assert observation["cut"]["row_skew_ns"] == "0"
                    assert observation["valuation"]["currency"] == "USDT"
                    assert observation["valuation"]["available_cash"] == "120.00"
                    assert observation["valuation"]["equity"] == "500.00"
                    assert observation["valuation"]["observed_at_utc"] == (
                        observation["cut"]["completed_at_utc"]
                    )
                    balances = {
                        (row["resource"]["product_type"], row["currency"]): row
                        for row in observation["balances"]
                    }
                    assert balances[("spot", "USDT")]["total"] == "123.45"
                    assert balances[("spot", "USDT")]["available"] == "120.00"
                    assert balances[("spot", "EUR")]["total"] == "0"
                    assert balances[("spot", "EUR")]["available"] == "0"
                    assert balances[("linear", "BTC")]["total"] is None
                    assert balances[("linear", "BTC")]["available"] is None
                    assert all(
                        row["observed_at_utc"] == observation["cut"]["completed_at_utc"]
                        for row in balances.values()
                    )
                    positions = observation["positions"]
                    assert len(positions) == 2
                    assert positions[0]["instrument"] == {
                        "provider": "PAPER",
                        "venue": "synthetic-venue",
                        "environment": "simulation",
                        "product_type": "spot",
                        "instrument_id": "spot:BTC-USDT",
                        "native_symbol": "BTCUSDT",
                    }
                    assert positions[0]["quantity"] == "2"
                    assert positions[0]["qty_unit"] == "base_asset"
                    assert positions[0]["average_price"] == "40.5"
                    assert positions[0]["price_currency"] == "USDT"
                    assert positions[1]["instrument"] == {
                        "provider": "PAPER",
                        "venue": "synthetic-venue",
                        "environment": "simulation",
                        "product_type": "linear",
                        "instrument_id": "linear:BTCUSDT-PERP",
                        "native_symbol": "BTCUSDT-PERP",
                    }
                    assert positions[1]["quantity"] == "0"
                    assert positions[1]["qty_unit"] == "contracts"
                    assert positions[1]["average_price"] is None
                    assert positions[1]["price_currency"] is None
                    for position in positions:
                        assert position["observed_at_utc"] == (
                            observation["cut"]["completed_at_utc"]
                        )
                        assert position["valuation_inputs"] == {
                            "mark_price": {"status": "missing", "value": None},
                            "contract_multiplier": {"status": "unsupported", "value": None},
                            "fx_rate": {"status": "unsupported", "value": None},
                            "market_value": {"status": "not_calculated", "value": None},
                        }
                    serialized_projection = json.dumps(projected, sort_keys=True)
                    for private_value in (
                        _ACCOUNT_ID,
                        account_key.account_key_id,
                        _JOURNAL_SCOPE,
                        _STATE_SCOPE,
                        "account_key_id",
                        "account_scope",
                        "strategy_scope",
                    ):
                        assert private_value not in serialized_projection

                    foreign = await overview("ungranted-account-observation", headers_b)
                    _assert_service_read_access_denied(foreign)
                    unknown = await overview("unknown-account-observation", headers_a)
                    _assert_service_read_access_denied(unknown)

                    authorized_client = captured_sessions[0]._read_client
                    assert authorized_client is not None
                    account_client = authorized_client._account_clients[_ACCOUNT_REF]
                    previous_clock = authorized_client._clock

                    def just_past_account_freshness_deadline() -> float:
                        # read_account() refreshes this real SDK facade before
                        # projecting the AFI view, so consult its newly accepted
                        # deadline and cross it by a clear one-second margin.
                        state_view = account_client.last_view
                        assert state_view is not None
                        return state_view.fresh_until_monotonic + 1.0

                    authorized_client._clock = just_past_account_freshness_deadline
                    try:
                        stale = await overview("authorized-account-observation", headers_a)
                    finally:
                        authorized_client._clock = previous_clock
                    assert stale.status_code == 200, stale.text
                    stale_account = stale.json()["accounts"][0]
                    assert stale_account["quality"] == "stale"
                    assert stale_account["value"] == "500.00"
                    assert stale_account["included_in_total"] is False
                    assert stale_account["provider_observation"]["status"] == "stale"
                    assert stale.json()["account_total"]["status"] == "incomplete"
                    assert stale.json()["account_total"]["value"] is None

                    host["pipe"].send(("fail_next_read",))
                    refresh_result = _receive(host["pipe"])
                    assert refresh_result == ("refresh_failed", "PROVIDER_READ_FAILED")
                    unavailable = await overview("authorized-account-observation", headers_a)
                    assert unavailable.status_code == 200, unavailable.text
                    unavailable_account = unavailable.json()["accounts"][0]
                    assert unavailable_account["quality"] == "unavailable"
                    assert unavailable_account["cash"] is None
                    assert unavailable_account["value"] is None
                    assert unavailable_account["provider_observation"] == {
                        "status": "unavailable",
                        "code": "ACCOUNT_READ_FAILED",
                    }
                    assert unavailable.json()["account_total"]["status"] == "incomplete"
                    assert unavailable.json()["account_total"]["value"] is None
                    assert unavailable.json()["provider_snapshot_consistency"]["status"] == (
                        "observation_absent_or_unavailable"
                    )
                    assert unavailable.json()["provider_snapshot_consistency"][
                        "coverage_status"
                    ] == "not_established"

            assert deployment is not None and deployment.closed
            assert deployment.close_failures == ()
            assert getattr(app.state, "service_read_deployment", None) is None
            assert all(not thread.is_alive() for thread in owner_threads)

        asyncio.run(exercise_http())
        host["pipe"].send(("status",))
        status_reply = _receive(host["pipe"])
        assert status_reply == ("status", 1, 2, 0, False)
    except BaseException as error:
        primary_error = error
        if host is not None:
            try:
                host_cleanup_summary = _close_process(host)
            except BaseException as cleanup_error:
                host_cleanup_error = type(cleanup_error).__name__
        raise
    else:
        try:
            host_cleanup_summary = _close_process(host)
        except BaseException as error:
            primary_error = error
            raise
    finally:
        final_cleanup_errors: list[tuple[str, BaseException]] = []
        try:
            if dependency_override_installed:
                if previous_db_override is None:
                    app.dependency_overrides.pop(get_db, None)
                else:
                    app.dependency_overrides[get_db] = previous_db_override
            dependency_override_restored = (
                app.dependency_overrides.get(get_db) is previous_db_override
            )
        except BaseException as error:
            final_cleanup_errors.append(("restore_dependency_override", error))
        if engine is None:
            app_database_disposed = True
        else:
            try:
                asyncio.run(engine.dispose())
                app_database_disposed = True
            except BaseException as error:
                final_cleanup_errors.append(("dispose_app_database", error))

        app_deployment = getattr(app.state, "service_read_deployment", None)
        observed_deployment = deployment or app_deployment
        observed_threads = owner_threads or tuple(
            worker._thread
            for worker in getattr(observed_deployment, "_workers", ())
            if getattr(worker, "_thread", None) is not None
        )
        try:
            owner_threads_alive = sum(thread.is_alive() for thread in observed_threads)
        except BaseException:
            owner_threads_alive = None
        try:
            deployment_close_failure_count = (
                len(observed_deployment.close_failures)
                if observed_deployment is not None
                else None
            )
            deployment_closed = (
                observed_deployment.closed if observed_deployment is not None else None
            )
        except BaseException:
            deployment_close_failure_count = None
            deployment_closed = None
        service_read_cleanup = {
            "deployment_closed": deployment_closed,
            "deployment_close_failure_count": deployment_close_failure_count,
            "deployment_unbound_from_app": app_deployment is None,
            "owner_thread_count": len(observed_threads),
            "owner_threads_alive": owner_threads_alive,
            "dependency_override_restored": dependency_override_restored,
            "app_database_disposed": app_database_disposed,
            "temporary_artifact_owner_present": root.is_dir(),
        }
        full_cleanup_summary = {
            "service_read": service_read_cleanup,
            "gateway_host": host_cleanup_summary,
            "gateway_cleanup_error": host_cleanup_error,
            "final_cleanup_errors": [
                {"stage": stage, "type": type(error).__name__}
                for stage, error in final_cleanup_errors
            ],
        }
        if primary_error is not None:
            _add_failure_note(
                primary_error,
                "Synthetic authorized account-observation cleanup: "
                + json.dumps(full_cleanup_summary, sort_keys=True),
            )

        if primary_error is None and not final_cleanup_errors:
            assert host_cleanup_summary is not None
            assert service_read_cleanup["deployment_closed"] is True, full_cleanup_summary
            assert service_read_cleanup["deployment_close_failure_count"] == 0, (
                full_cleanup_summary
            )
            assert service_read_cleanup["deployment_unbound_from_app"] is True, (
                full_cleanup_summary
            )
            assert service_read_cleanup["owner_threads_alive"] == 0, full_cleanup_summary
            assert dependency_override_restored is True, full_cleanup_summary
            assert app_database_disposed is True, full_cleanup_summary
            assert host_cleanup_summary["clean"] is True, full_cleanup_summary

        if final_cleanup_errors and primary_error is None:
            first_error = final_cleanup_errors[0][1]
            if len(final_cleanup_errors) > 1:
                _add_failure_note(
                    first_error,
                    "Additional synthetic AFI test cleanup errors: "
                    + json.dumps(full_cleanup_summary["final_cleanup_errors"][1:], sort_keys=True),
                )
            _add_failure_note(
                first_error,
                "Synthetic authorized account-observation cleanup: "
                + json.dumps(full_cleanup_summary, sort_keys=True),
            )
            raise first_error
