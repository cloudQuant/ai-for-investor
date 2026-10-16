"""Authenticated portfolio analytics through AFI, SDK, and a separate Risk Host."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import zmq

_SERVICE_ID = "afi04-http-risk-service"
_INSTANCE_ID = "afi04-http-risk-instance"
_SERVICE_PRINCIPAL = "afi04-http-risk-principal"
_APPLICATION_REF = "afi04-http-application"
_DOMAIN = "afi04:offline-http"
_PORTFOLIO = "portfolio-01"
_SCOPE_REF = "afi04-http-risk-scope"
_TRANSPORT_REF = "afi04-http-risk-transport"
_SECURITY_REF = "afi04-http-curve"
_REGISTRATION_POLICY = "afi04-http-registration-v1"
_SERVICE_REQUIREMENTS = "afi04-http-requirements-v1"
_OPERATIONS = frozenset(
    {"analysis.input_upload", "analysis.submit", "analysis.query", "analysis.cancel"}
)
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_TERMINAL_STATES = frozenset(
    {"succeeded", "unavailable", "failed", "cancelled", "expired"}
)
_MAX_WIRE_MESSAGE_BYTES = 1_048_576
_WIRE_ENVELOPE_HEADROOM_BYTES = 16_384
_CHILD_FAILURE_MARKER_MAX_BYTES = 16_384
_CHILD_FAILURE_TRACEBACK_MAX_CHARS = 8_192
_CANCELLATION_LOSS_OBSERVATIONS = 9_200


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _wire_keys() -> dict[str, str]:
    values: dict[str, str] = {}
    for name in ("server", "client"):
        public, secret = zmq.curve_keypair()
        values[f"{name}_public"] = public.decode("ascii")
        values[f"{name}_secret"] = secret.decode("ascii")
    return values


def _service_config(endpoint: str) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _SERVICE_ID,
        "scope_ref": _SCOPE_REF,
        "transport_ref": "risk-listener",
        "registration_policy_ref": _REGISTRATION_POLICY,
        "service_requirements_ref": _SERVICE_REQUIREMENTS,
        "components": {
            "risk": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _INSTANCE_ID,
                    "bind_ports": ["service.risk_analysis"],
                    "options": {
                        "role": "portfolio_analytics",
                        "model_profile_ref": "afi04-http-metrics-v1",
                        "allowed_source_modes": ["research", "imported", "paper"],
                        "max_concurrent_tasks": 2,
                        "max_input_bytes": 2_097_152,
                    },
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "risk-listener": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _SECURITY_REF,
                    "options": {
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_WIRE_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _deployment_profile(
    subject: str, endpoint: str, keys: dict[str, str]
) -> dict[str, Any]:
    subject_tag = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16]
    principal_ref = f"afi04-user-{subject_tag}"
    delegate_ref = f"afi04-delegate-{subject_tag}"
    return {
        "subject": subject,
        "identity": {
            "principal_ref": principal_ref,
            "actor_ref": _APPLICATION_REF,
            "delegate_ref": delegate_ref,
        },
        "client_config": {
            "client_config_schema_version": 1,
            "process_role": "application_client",
            "registration": {"application_ref": _APPLICATION_REF},
            "clients": {
                "risk": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": "application.risk_analysis",
                                "service_id": _SERVICE_ID,
                                "instance_id": _INSTANCE_ID,
                                "portfolio_ref": _PORTFOLIO,
                                "scope_ref": _SCOPE_REF,
                                "transport_ref": _TRANSPORT_REF,
                            }
                        ],
                        "options": {"request_timeout_ms": 5_000},
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
                            "request_timeout_ms": 5_000,
                            "high_water_mark": 32,
                            "max_message_bytes": _MAX_WIRE_MESSAGE_BYTES,
                        },
                    }
                },
            },
        },
        "scope_claims": {
            _SCOPE_REF: {
                "execution_domain_ref": _DOMAIN,
                "portfolio_ref": _PORTFOLIO,
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
                "server_key": keys["server_public"],
                "public_key": keys["client_public"],
                "secret_key": keys["client_secret"],
            }
        },
        "grants": {
            "account_refs": [],
            "order_scope_refs": [],
            "monitor_scope_refs": [],
            "portfolio_refs": [_PORTFOLIO],
        },
        "account_bindings": {},
        "order_bindings": {},
        "monitor_bindings": {},
        "portfolio_analytics_bindings": {
            _PORTFOLIO: {"mount": "application.risk_analysis", "scope_ref": _SCOPE_REF}
        },
        "worker": {"max_queue_size": 8, "maintenance_interval_seconds": 0.01},
    }


def _unavailable_facts() -> dict[str, Any]:
    unavailable = {
        "coverage_complete": None,
        "reason_code": "NO_SOURCE_DATA",
        "status": "unavailable",
    }
    return {
        "facts_snapshot_ref": "offline-unavailable-cut-v2",
        "loss_history": {
            **unavailable,
            "coverage_end_utc": None,
            "coverage_start_utc": None,
            "end_cursor": None,
            "horizon_ref": "one-day-v1",
            "observations": [],
            "source_generation": None,
            "source_ref": None,
            "source_version": None,
            "start_cursor": None,
        },
        "nav_history": {
            **unavailable,
            "coverage_end_utc": None,
            "coverage_start_utc": None,
            "end_cursor": None,
            "observations": [],
            "source_generation": None,
            "source_ref": None,
            "source_version": None,
            "start_cursor": None,
        },
        "portfolio_ref": _PORTFOLIO,
        "scenario": {
            **unavailable,
            "scenario_ref": "offline-scenario",
            "scenario_version": "offline-scenario-v1",
            "shocks": [],
            "source_cursor": None,
            "source_generation": None,
            "source_ref": None,
            "source_version": None,
        },
        "source_generation": "afi04-unavailable-generation-v1",
        "source_mode": "imported",
        "source_ref": "afi04-synthetic-imported-input-v1",
        "source_version": "afi04-facts-v2",
        "spot": {
            **unavailable,
            "as_of_utc": None,
            "positions": [],
            "source_cursor": None,
            "source_generation": None,
            "source_ref": None,
            "source_version": None,
        },
        "version": 2,
    }


def _available_facts() -> dict[str, Any]:
    cut = "2026-01-01T00:00:00+00:00"
    return {
        "facts_snapshot_ref": "snapshot-v2-7",
        "loss_history": {
            "coverage_complete": True,
            "coverage_end_utc": "2026-01-05T00:00:00+00:00",
            "coverage_start_utc": cut,
            "end_cursor": "loss-end-4",
            "horizon_ref": "one-day-v1",
            "observations": [
                {
                    "as_of_utc": f"2026-01-0{day}T00:00:00+00:00",
                    "currency": "USD",
                    "loss": str(day),
                    "loss_unit": "REPORTING_CURRENCY_AMOUNT",
                }
                for day in range(1, 6)
            ],
            "reason_code": None,
            "source_generation": "generation-7",
            "source_ref": "loss-ledger",
            "source_version": "loss-ledger-v1",
            "start_cursor": "loss-start-0",
            "status": "available",
        },
        "nav_history": {
            "coverage_complete": True,
            "coverage_end_utc": "2026-01-04T00:00:00+00:00",
            "coverage_start_utc": cut,
            "end_cursor": "nav-end-3",
            "observations": [
                {"as_of_utc": f"2026-01-0{day}T00:00:00+00:00", "currency": "USD", "nav": value}
                for day, value in enumerate(("100", "120", "90", "110"), start=1)
            ],
            "reason_code": None,
            "source_generation": "generation-7",
            "source_ref": "nav-ledger",
            "source_version": "nav-ledger-v1",
            "start_cursor": "nav-start-0",
            "status": "available",
        },
        "portfolio_ref": _PORTFOLIO,
        "scenario": {
            "coverage_complete": True,
            "reason_code": None,
            "scenario_ref": "risk-off",
            "scenario_version": "risk-off-v3",
            "shocks": [
                {
                    "fx_return": "0",
                    "position_ref": "btc-long",
                    "price_return": "0.1",
                    "shock_unit": "FRACTIONAL_RETURN",
                },
                {
                    "fx_return": "0",
                    "position_ref": "btc-short",
                    "price_return": "0.1",
                    "shock_unit": "FRACTIONAL_RETURN",
                },
                {
                    "fx_return": "-0.1",
                    "position_ref": "eth-long",
                    "price_return": "0.2",
                    "shock_unit": "FRACTIONAL_RETURN",
                },
            ],
            "source_cursor": "scenario-cursor-3",
            "source_generation": "scenario-generation-3",
            "source_ref": "scenario-catalog",
            "source_version": "scenario-catalog-v1",
            "status": "available",
        },
        "source_generation": "generation-7",
        "source_mode": "imported",
        "source_ref": "offline-facts",
        "source_version": "offline-facts-v2",
        "spot": {
            "as_of_utc": cut,
            "coverage_complete": True,
            "positions": [
                {
                    "as_of_utc": cut,
                    "base_currency": "BTC",
                    "fx_unit": "REPORTING_PER_QUOTE",
                    "position_ref": "btc-long",
                    "quantity": "2",
                    "quantity_unit": "BTC",
                    "quote_currency": "USD",
                    "reporting_per_quote": "1",
                    "price_unit": "QUOTE_PER_BASE",
                    "unit_price": "100",
                },
                {
                    "as_of_utc": cut,
                    "base_currency": "BTC",
                    "fx_unit": "REPORTING_PER_QUOTE",
                    "position_ref": "btc-short",
                    "quantity": "-0.5",
                    "quantity_unit": "BTC",
                    "quote_currency": "USD",
                    "reporting_per_quote": "1",
                    "price_unit": "QUOTE_PER_BASE",
                    "unit_price": "100",
                },
                {
                    "as_of_utc": cut,
                    "base_currency": "ETH",
                    "fx_unit": "REPORTING_PER_QUOTE",
                    "position_ref": "eth-long",
                    "quantity": "3",
                    "quantity_unit": "ETH",
                    "quote_currency": "EUR",
                    "reporting_per_quote": "1.1",
                    "price_unit": "QUOTE_PER_BASE",
                    "unit_price": "20",
                },
            ],
            "reason_code": None,
            "source_cursor": "spot-cursor-7",
            "source_generation": "generation-7",
            "source_ref": "spot-ledger",
            "source_version": "spot-ledger-v1",
            "status": "available",
        },
        "version": 2,
    }


def _cancellation_facts() -> dict[str, Any]:
    """Keep one real V2 worker occupied with a fact cut that fits the SDK wire cap."""

    facts = _available_facts()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observations = []
    for index in range(_CANCELLATION_LOSS_OBSERVATIONS):
        as_of = start + timedelta(minutes=index)
        observations.append(
            {
                "as_of_utc": as_of.isoformat(),
                "currency": "USD",
                "loss": str(index % 100 + 1),
                "loss_unit": "REPORTING_CURRENCY_AMOUNT",
            }
        )
    history = facts["loss_history"]
    history["coverage_start_utc"] = start.isoformat()
    history["coverage_end_utc"] = observations[-1]["as_of_utc"]
    history["start_cursor"] = "cancel-loss-start-0"
    history["end_cursor"] = f"cancel-loss-end-{_CANCELLATION_LOSS_OBSERVATIONS - 1}"
    history["observations"] = observations
    facts["facts_snapshot_ref"] = "offline-cancel-snapshot-v2"
    assert len(_canonical_json_bytes(facts)) <= (
        _MAX_WIRE_MESSAGE_BYTES - _WIRE_ENVELOPE_HEADROOM_BYTES
    )
    return facts


def _request(portfolio_ref: str = _PORTFOLIO) -> dict[str, Any]:
    return {
        "confidence": "0.8",
        "loss_horizon_ref": "one-day-v1",
        "portfolio_ref": portfolio_ref,
        "reporting_currency": "USD",
        "scenario_ref": "risk-off",
        "scenario_version": "risk-off-v3",
        "version": 2,
    }


def _unavailable_request() -> dict[str, Any]:
    return {
        "confidence": "0.95",
        "loss_horizon_ref": "one-day-v1",
        "portfolio_ref": _PORTFOLIO,
        "reporting_currency": "USD",
        "scenario_ref": "offline-scenario",
        "scenario_version": "offline-scenario-v1",
        "version": 2,
    }


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _diagnostic_text(value: object, maximum: int) -> str | None:
    return value[:maximum] if type(value) is str else None


def _exception_message(error: BaseException, maximum: int) -> str:
    try:
        message = str(error)
    except BaseException:
        message = "<exception message unavailable>"
    return message[:maximum]


def _exception_field(error: BaseException | None, name: str, maximum: int) -> str | None:
    if error is None:
        return None
    try:
        value = getattr(error, name, None)
    except BaseException:
        return None
    return _diagnostic_text(value, maximum)


def _child_failure_payload(
    error: BaseException | None, cleanup_errors: list[BaseException]
) -> bytes:
    if error is None:
        exception_type = "RiskHostCleanupError"
        message = "Risk Host cleanup failed"
        formatted = ""
    else:
        exception_type = type(error).__name__
        message = _exception_message(error, 512)
        try:
            formatted = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
        except BaseException as formatting_error:
            formatted = f"<traceback unavailable: {type(formatting_error).__name__}>"

    diagnostic = {
        "schema": "afi04-risk-host-failure-v1",
        "exception_type": exception_type[:128],
        "code": _exception_field(error, "code", 128),
        "path": _exception_field(error, "path", 512),
        "message": message[:512],
        "traceback": formatted[-_CHILD_FAILURE_TRACEBACK_MAX_CHARS :],
        "cleanup_errors": [
            {
                "exception_type": type(item).__name__[:128],
                "message": _exception_message(item, 512),
            }
            for item in cleanup_errors[:8]
        ],
    }
    for traceback_limit in (
        _CHILD_FAILURE_TRACEBACK_MAX_CHARS,
        _CHILD_FAILURE_TRACEBACK_MAX_CHARS // 2,
        0,
    ):
        diagnostic["traceback"] = (
            formatted[-traceback_limit:] if traceback_limit else ""
        )
        encoded = json.dumps(
            diagnostic,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        if len(encoded) <= _CHILD_FAILURE_MARKER_MAX_BYTES:
            return encoded
    raise AssertionError("bounded Risk Host failure diagnostic exceeded its fixed limit")


def _read_child_failure(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with path.open("rb") as stream:
            raw = stream.read(_CHILD_FAILURE_MARKER_MAX_BYTES + 1)
    except OSError as error:
        return {"marker_read_error": type(error).__name__}
    if len(raw) > _CHILD_FAILURE_MARKER_MAX_BYTES:
        return {"marker_status": "oversize"}
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return {"marker_status": "invalid", "decode_error": type(error).__name__}
    if type(value) is not dict or value.get("schema") != "afi04-risk-host-failure-v1":
        return {"marker_status": "unexpected_shape"}
    return value


def _host_worker(config_path: Path) -> int:
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
    from bt_api_risk.portfolio_analytics import PortfolioAnalyticsModelProfileV1
    from bt_api_risk.service_analytics import AnalysisTaskStore

    config = json.loads(config_path.read_text(encoding="utf-8"))
    keys = {key: value.encode("ascii") for key, value in config["keys"].items()}
    endpoint = config["endpoint"]
    database = Path(config["database"])
    profile = PortfolioAnalyticsModelProfileV1(
        "afi04-http-metrics-v1",
        max_mark_age_ns=86_400_000_000_000,
        max_fx_age_ns=86_400_000_000_000,
        max_input_bytes=2_097_152,
    )
    stores: list[AnalysisTaskStore] = []

    def resources(component, instance_id, options, _scope):
        if (
            component != "risk"
            or instance_id != _INSTANCE_ID
            or options.get("role") != "portfolio_analytics"
        ):
            raise RuntimeError("unexpected_service_component")
        store = AnalysisTaskStore(
            str(database),
            model_profile=profile,
            allowed_source_modes=options["allowed_source_modes"],
            max_concurrent_tasks=options.get("max_concurrent_tasks", 2),
            max_concurrent_workers=1,
            pending_ttl_seconds=60,
        )
        stores.append(store)
        return ComponentResources.borrowed({"analysis": store}, ready=lambda: True)

    service_identity = WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID)
    app_identity = WireIdentity(
        WireRole.APPLICATION_CLIENT,
        config["principal_ref"],
        _APPLICATION_REF,
        config["delegate_ref"],
    )
    authority = TrustedServiceAuthority(
        identity=service_identity,
        scope=WireScope(_DOMAIN),
        scope_ref=_SCOPE_REF,
        scope_version="afi04-http-risk-scope-v1",
        security_ref=_SECURITY_REF,
        security_version="afi04-http-curve-v1",
        registration_policy_ref=_REGISTRATION_POLICY,
        registration_policy_version="afi04-http-registration-v1",
        service_requirements_ref=_SERVICE_REQUIREMENTS,
        service_requirements_version="afi04-http-requirements-v1",
        curve_public_key=keys["server_public"],
        curve_secret_key=keys["server_secret"],
        principals={keys["client_public"]: config["principal_ref"]},
        grants={
            config["principal_ref"]: (
                PrincipalGrant(
                    app_identity,
                    (
                        ResourceGrant(
                            _INSTANCE_ID,
                            "service.risk_analysis",
                            _SCOPE_REF,
                            WireScope(_DOMAIN, portfolio_ref=_PORTFOLIO),
                            _OPERATIONS,
                        ),
                    ),
                ),
            )
        },
    )
    host = None
    primary_error: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    try:
        host = ServiceHost(
            parse_service_config(_service_config(endpoint)),
            authority,
            str(config["registry"]),
            resources,
        )
        host.start()
        Path(config["ready"]).write_text("ready", encoding="ascii")
        stop = Path(config["stop"])
        while not stop.exists():
            host.serve_once(25)
        host.close()
    except BaseException as error:
        primary_error = error
    finally:
        if host is not None:
            try:
                if host.state != "closed":
                    host.close()
            except BaseException as error:
                cleanup_errors.append(error)
        for store in stores:
            try:
                store.close()
            except BaseException as error:
                cleanup_errors.append(error)

    if primary_error is None and not cleanup_errors:
        Path(config["closed"]).write_text("closed", encoding="ascii")
        return 0

    try:
        failure_path = Path(config["failure"])
        temporary_path = failure_path.with_name(failure_path.name + ".tmp")
        temporary_path.write_bytes(_child_failure_payload(primary_error, cleanup_errors))
        temporary_path.replace(failure_path)
    except BaseException:
        # Keep a best-effort finite class marker if diagnostic serialization
        # itself fails; never replace the original host error with that failure.
        try:
            fallback_message = (
                type(primary_error).__name__
                if primary_error is not None
                else "RiskHostCleanupError"
            )
            Path(config["failure"]).write_text(fallback_message, encoding="ascii")
        except OSError:
            pass
    return 1


def _child_entry() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--risk-host":
        return 2
    return _host_worker(Path(sys.argv[2]))


def _sdk_import_roots() -> list[str]:
    source_root = _BACKEND_ROOT.parents[1]
    package_roots = (
        ("bt_api_base", source_root / "vendor" / "base" / "src"),
        ("bt_api_py", source_root / "vendor" / "sdk"),
        ("bt_api_risk", source_root / "vendor" / "risk" / "src"),
        ("bt_api_transport_zmq", source_root / "vendor" / "transport" / "src"),
    )
    roots: list[str] = []
    for package, expected_root in package_roots:
        try:
            spec = importlib.util.find_spec(package)
        except (ImportError, ValueError):
            spec = None
        locations = tuple(spec.submodule_search_locations or ()) if spec is not None else ()
        expected_package = (expected_root / package).resolve()
        if (
            spec is None
            or len(locations) != 1
            or Path(locations[0]).resolve() != expected_package
            or not (expected_package / "__init__.py").is_file()
        ):
            raise AssertionError(f"fixed_sdk_source_unavailable:{package}")
        root_path = str(expected_root.resolve())
        if root_path not in roots:
            roots.append(root_path)
    return roots

def _wait_for_marker(
    process: subprocess.Popen[bytes],
    ready: Path,
    failure: Path,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if ready.is_file():
            return
        if failure.is_file() or process.poll() is not None:
            break
        time.sleep(0.025)
    diagnostic = {
        "risk_host_exit": process.poll(),
        "risk_host_failure": _read_child_failure(failure),
    }
    raise AssertionError(
        "Risk ServiceHost did not become ready: "
        + json.dumps(diagnostic, sort_keys=True, separators=(",", ":"))
    )


async def _query_terminal(client, headers: dict[str, str], base_path: str) -> dict[str, Any]:
    deadline = time.monotonic() + 20.0
    latest: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        response = await client.get(base_path, headers=headers)
        assert response.status_code == 200, response.text
        latest = response.json()
        if latest.get("state") in _TERMINAL_STATES:
            return latest
        await asyncio.sleep(0.05)
    raise AssertionError(
        {"task_state": latest.get("state") if latest else None, "timeout_seconds": 20}
    )


async def _query_running(client, headers: dict[str, str], base_path: str) -> dict[str, Any]:
    deadline = time.monotonic() + 20.0
    latest: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        response = await client.get(base_path, headers=headers)
        assert response.status_code == 200, response.text
        latest = response.json()
        if latest.get("state") == "running":
            return latest
        if latest.get("state") in _TERMINAL_STATES:
            raise AssertionError({"task_state": latest.get("state"), "expected": "running"})
        await asyncio.sleep(0.01)
    raise AssertionError(
        {"task_state": latest.get("state") if latest else None, "timeout_seconds": 20}
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticated_http_analytics_uses_sdk_owner_and_independent_risk_host(
    client, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exercise computed, unavailable, and cancellation paths without live/account input."""

    from pydantic import SecretStr

    from app import main as main_module
    from app.config import get_settings
    from app.db import database as database_module
    assert main_module.settings is database_module.settings is get_settings()
    # This shared in-memory test DB is intentionally created by the real startup hook.
    monkeypatch.setattr(main_module.settings, "DB_AUTO_CREATE_SCHEMA", True)
    from app.db.database import async_session_maker
    from app.models.portfolio_ledger import PortfolioLedgerImportModel, PortfolioLedgerModel
    from app.utils.security import decode_access_token

    token = auth_headers["Authorization"].split(" ", 1)[1]
    claims = decode_access_token(token)
    assert type(claims) is dict and type(claims.get("sub")) is str
    subject = claims["sub"]
    subject_tag = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16]
    principal_ref = f"afi04-user-{subject_tag}"
    delegate_ref = f"afi04-delegate-{subject_tag}"

    # Give the normal imported-membership endpoint an owner-scoped synthetic
    # source row. The V2 facts remain the fixed offline Risk regression payload.
    async with async_session_maker() as db:
        db.add(
            PortfolioLedgerModel(
                id="afi04-import-ledger",
                owner_id=subject,
                name="AFI04 synthetic analytics source",
                base_currency="USD",
                source_type="imported",
            )
        )
        db.add(
            PortfolioLedgerImportModel(
                id="afi04-import-version",
                portfolio_id="afi04-import-ledger",
                import_format="json",
                idempotency_key="afi04-imported-analytics-v1",
                imported_count=0,
            )
        )
        await db.commit()

    endpoint = _endpoint()
    keys = _wire_keys()
    paths = {
        name: tmp_path / f"{name}.json"
        for name in ("host-config", "deployment")
    }
    markers = {
        name: tmp_path / f"{name}.marker"
        for name in ("host-ready", "host-stop", "host-closed", "host-failure")
    }
    host_config = {
        "closed": str(markers["host-closed"]),
        "database": str(tmp_path / "risk-analysis.sqlite"),
        "endpoint": endpoint,
        "failure": str(markers["host-failure"]),
        "keys": keys,
        "principal_ref": principal_ref,
        "delegate_ref": delegate_ref,
        "ready": str(markers["host-ready"]),
        "registry": str(tmp_path / "risk-registry.sqlite"),
        "stop": str(markers["host-stop"]),
    }
    paths["host-config"].write_text(json.dumps(host_config), encoding="utf-8")
    paths["deployment"].write_text(
        json.dumps(
            {
                "schema_version": 1,
                "subjects": [_deployment_profile(subject, endpoint, keys)],
            }
        ),
        encoding="utf-8",
    )

    pythonpath = [str(_BACKEND_ROOT), *_sdk_import_roots()]
    environment = {
        name: os.environ[name]
        for name in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP")
        if name in os.environ
    }
    environment.update(
        {
            "PYTHONPATH": os.pathsep.join(dict.fromkeys(pythonpath)),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(tmp_path / "risk-host-pycache"),
            "BT_API_LOG_DIR": str(tmp_path / "risk-host-logs"),
        }
    )
    Path(environment["BT_API_LOG_DIR"]).mkdir(parents=True, exist_ok=True)
    host_log = tmp_path / "risk-host.log"
    host_process: subprocess.Popen[bytes] | None = None
    deployment = None
    with host_log.open("wb") as host_log_stream:
        host_process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--risk-host", str(paths["host-config"])],
            cwd=str(_BACKEND_ROOT),
            env=environment,
            stdout=host_log_stream,
            stderr=subprocess.STDOUT,
        )
        try:
            await asyncio.to_thread(
                _wait_for_marker,
                host_process,
                markers["host-ready"],
                markers["host-failure"],
                20.0,
            )
            monkeypatch.setattr(
                main_module.settings,
                "SERVICE_READ_DEPLOYMENT_JSON",
                SecretStr(paths["deployment"].read_text(encoding="utf-8")),
            )
            monkeypatch.setattr(main_module.settings, "RAG_VECTOR_ENABLED", False)

            async with main_module.lifespan(main_module.app):
                deployment = main_module.app.state.service_read_deployment
                assert deployment is not None and not deployment.closed

                created = await client.post(
                    "/api/v1/portfolio/compositions",
                    headers=auth_headers,
                    json={
                        "portfolio_ref": _PORTFOLIO,
                        "source_type": "imported",
                        "base_currency": "USD",
                        "members": [
                            {"kind": "imported_ledger", "ref": "afi04-import-version"}
                        ],
                    },
                )
                assert created.status_code == 201, created.text
                membership = created.json()
                assert membership["source_type"] == "imported"
                task_root = (
                    f"/api/v1/portfolio/compositions/{_PORTFOLIO}/versions/"
                    f"{membership['membership_version']}/analytics-tasks"
                )

                computed_facts = _available_facts()
                computed_request = _request()
                computed = await client.post(
                    task_root,
                    headers=auth_headers,
                    json={
                        "idempotency_key": "afi04-http-computed-v1",
                        "facts": computed_facts,
                        "request": computed_request,
                    },
                )
                assert computed.status_code == 202, computed.text
                computed_task = await _query_terminal(
                    client,
                    auth_headers,
                    f"{task_root}/{computed.json()['task_ref']}",
                )
                assert computed_task["state"] == "succeeded"
                assert computed_task["membership_version"] == membership["membership_version"]
                assert computed_task["membership_sha256"] == membership["membership_sha256"]
                assert "scope_ref" not in computed_task
                report = computed_task["result"]
                assert report["version"] == 2
                assert report["schema_ref"] == "portfolio_analytics_v2"
                assert report["calculation_ref"] == "portfolio_metrics_v1_bundle_v2"
                assert report["serialization_ref"] == "json_sort_keys_compact_ascii_v1"
                assert report["decimal_serialization_ref"] == (
                    "finite_decimal_fixed_point_canonical_v1"
                )
                assert report["status"] == "AVAILABLE"
                assert report["input_sha256"] == computed_task["input_sha256"]
                assert report["input_sha256"] == (
                    "3c3464cb4eba2848dddfa8a942fd301e8118352b96c651899ff2b4f9923172c4"
                )
                assert report["input_sha256"] == _canonical_sha256(computed_facts)
                assert len(report["input_sha256"]) == 64
                assert report["provenance"]["facts_source"]["mode"] == "imported"
                assert report["provenance"]["facts_source"]["source_ref"] == "offline-facts"
                assert report["provenance"]["facts_source"]["source_version"] == (
                    "offline-facts-v2"
                )
                assert report["provenance"]["facts_source"]["generation"] == "generation-7"
                assert report["provenance"]["facts_source"]["snapshot_ref"] == "snapshot-v2-7"
                assert set(report["metrics"]) == {
                    "historical_var_es",
                    "max_drawdown",
                    "spot_exposure",
                    "stress_scenario",
                }
                metrics = report["metrics"]
                assert metrics["spot_exposure"]["value"]["net_reporting_notional"] == "216"
                assert metrics["spot_exposure"]["value"]["gross_reporting_notional"] == "316"
                assert metrics["max_drawdown"]["value"]["max_drawdown_ratio"] == "-0.25"
                assert metrics["max_drawdown"]["value"]["peak_nav"] == "120"
                assert metrics["max_drawdown"]["value"]["trough_nav"] == "90"
                assert metrics["historical_var_es"]["value"]["var_loss"] == "4"
                assert metrics["historical_var_es"]["value"]["expected_shortfall_loss"] == "5"
                assert metrics["stress_scenario"]["value"]["pnl_reporting_amount"] == "20.28"
                assert report["provenance"]["spot"]["source_cursor"] == "spot-cursor-7"
                assert report["provenance"]["spot"]["as_of_utc"] == "2026-01-01T00:00:00+00:00"
                assert report["request_sha256"] == (
                    "7d148c82eb37a56b58acf10702c9a0b1b6c0a1d0e938da79f25d753f39e56498"
                )
                assert report["request_sha256"] == _canonical_sha256(computed_request)
                unsigned_report = dict(report)
                claimed_report_sha256 = unsigned_report.pop("report_sha256")
                assert _canonical_sha256(unsigned_report) == claimed_report_sha256

                unavailable_request = _unavailable_request()
                unavailable_response = await client.post(
                    task_root,
                    headers=auth_headers,
                    json={
                        "idempotency_key": "afi04-http-unavailable-v1",
                        "facts": _unavailable_facts(),
                        "request": unavailable_request,
                    },
                )
                assert unavailable_response.status_code == 202, unavailable_response.text
                unavailable_task = await _query_terminal(
                    client,
                    auth_headers,
                    f"{task_root}/{unavailable_response.json()['task_ref']}",
                )
                assert unavailable_task["state"] == "unavailable"
                unavailable_report = unavailable_task["result"]
                assert unavailable_report["status"] == "UNAVAILABLE"
                assert unavailable_report["input_sha256"] == unavailable_task["input_sha256"]
                for metric in unavailable_report["metrics"].values():
                    assert metric["status"] == "unavailable"
                    assert metric["value"] is None

                cancellable_response = await client.post(
                    task_root,
                    headers=auth_headers,
                    json={
                        "idempotency_key": "afi04-http-cancel-v1",
                        "facts": _cancellation_facts(),
                        "request": computed_request,
                    },
                )
                assert cancellable_response.status_code == 202, cancellable_response.text
                cancellable_ref = cancellable_response.json()["task_ref"]
                cancellable_path = f"{task_root}/{cancellable_ref}"
                running_cancel_task = await _query_running(
                    client, auth_headers, cancellable_path
                )
                assert running_cancel_task["state"] == "running"
                cancelled = await client.post(
                    f"{cancellable_path}/cancel",
                    headers=auth_headers,
                )
                assert cancelled.status_code == 200, cancelled.text
                assert cancelled.json()["state"] == "cancelled"
                cancelled_query = await client.get(
                    cancellable_path, headers=auth_headers
                )
                assert cancelled_query.status_code == 200, cancelled_query.text
                assert cancelled_query.json()["state"] == "cancelled"

            assert deployment is not None and deployment.closed
            assert deployment.close_failures == ()
            assert main_module.app.state.service_read_deployment is None
        finally:
            primary_error = sys.exc_info()[1]
            primary_traceback = (
                primary_error.__traceback__ if primary_error is not None else None
            )
            cleanup_errors: list[str] = []
            if host_process is not None:
                try:
                    markers["host-stop"].touch()
                except BaseException as error:
                    cleanup_errors.append(f"stop_marker:{type(error).__name__}")
                try:
                    await asyncio.to_thread(host_process.wait, timeout=20.0)
                except subprocess.TimeoutExpired:
                    cleanup_errors.append("graceful_wait_timeout")
                except BaseException as error:
                    cleanup_errors.append(f"graceful_wait:{type(error).__name__}")
                if host_process.returncode is None:
                    cleanup_errors.append("forced_termination_after_wait_failure")
                    try:
                        host_process.terminate()
                    except BaseException as error:
                        cleanup_errors.append(f"terminate:{type(error).__name__}")
                    try:
                        await asyncio.to_thread(host_process.wait, timeout=5.0)
                    except subprocess.TimeoutExpired:
                        cleanup_errors.append("terminate_wait_timeout")
                        try:
                            host_process.kill()
                            await asyncio.to_thread(host_process.wait, timeout=5.0)
                        except BaseException as error:
                            cleanup_errors.append(
                                f"kill_or_reap:{type(error).__name__}"
                            )
                        else:
                            cleanup_errors.append("killed_after_terminate_timeout")
                    except BaseException as error:
                        cleanup_errors.append(f"terminate_wait:{type(error).__name__}")

                if host_process.returncode != 0:
                    cleanup_errors.append(
                        f"host_returncode:{host_process.returncode}"
                    )
                if not markers["host-closed"].is_file():
                    cleanup_errors.append("host_closed_marker_missing")
                if markers["host-failure"].is_file():
                    failure_detail = _read_child_failure(markers["host-failure"])
                    cleanup_errors.append(
                        "host_failure:"
                        + json.dumps(
                            failure_detail,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )

            if cleanup_errors:
                cleanup_error = AssertionError(
                    "Risk Host cleanup diagnostics: " + ";".join(cleanup_errors)
                )
                if primary_error is not None:
                    raise primary_error.with_traceback(primary_traceback) from cleanup_error
                raise cleanup_error


if __name__ == "__main__":  # pragma: no cover - spawned Risk Host entry point
    raise SystemExit(_child_entry())
