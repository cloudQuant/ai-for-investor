"""Local-process evidence for the application's authorized read path.

A real monitor telemetry service process is started on this machine and the
application reads an authorized heartbeat view through the SDK client runtime
over real CURVE transport.  The producer is a real strategy client runtime, so
the snapshot carries a producer-reported heartbeat rather than a fixture.

The test is skipped when the optional service packages are not installed: the
application must remain usable without them, and its read path is optional by
design.
"""

import multiprocessing
import socket
import sys
import time
from contextlib import suppress

import pytest

pytest.importorskip("bt_api_py")
pytest.importorskip("bt_api_monitor")
zmq = pytest.importorskip("zmq")

from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402

from app.services.service_read.client import (  # noqa: E402
    AuthorizedServiceReadClient,
    MonitorBinding,
    ServiceReadUnavailableError,
)
from app.services.service_read.contracts import ReadQuality  # noqa: E402

_DOMAIN = "paper:afi-service-read"
_SERVICE_ID = "afi-monitor-service"
_SERVICE_PRINCIPAL = "afi-monitor-principal"
_INSTANCE_ID = "afi-monitor-telemetry"
_SERVICE_SCOPE_REF = "afi-monitor-root-v1"
_SERVER_SECURITY_REF = "afi-monitor-server-curve-v1"
_STRATEGY = "strategy-afi-a"
_STRATEGY_PRINCIPAL = "afi-strategy-a-principal"
_APP_ID = "afi-dashboard"
_APP_PRINCIPAL = "afi-dashboard-principal"
_TELEMETRY_SCOPE_REF = "afi-strategy-a-telemetry-v1"
_APP_SCOPE_REF = "afi-dashboard-a-v1"
_REQUEST_TIMEOUT_MS = 2000
_MAX_MESSAGE_BYTES = 65_536
_HEARTBEAT_TIMEOUT_SECONDS = 2
_STRATEGY_SCOPE = WireScope(_DOMAIN, strategy_ref=_STRATEGY)


def _endpoint():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _service_config(endpoint):
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _SERVICE_ID,
        "scope_ref": _SERVICE_SCOPE_REF,
        "transport_ref": "afi-telemetry-listener-v1",
        "registration_policy_ref": "afi-telemetry-registration-v1",
        "service_requirements_ref": "afi-telemetry-requirements-v1",
        "components": {
            "monitor": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _INSTANCE_ID,
                    "bind_ports": ["service.telemetry_ingress", "service.monitor_query"],
                    "options": {
                        "role": "telemetry_ingress",
                        "max_streams": 16,
                        "max_bytes": 65_536,
                        "heartbeat_timeout_seconds": _HEARTBEAT_TIMEOUT_SECONDS,
                        "retention_seconds": 60,
                    },
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "afi-telemetry-listener-v1": {
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


def _producer_config(endpoint, security_ref):
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": _STRATEGY},
        "clients": {
            "monitor": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "runtime.telemetry",
                            "service_id": _SERVICE_ID,
                            "instance_id": _INSTANCE_ID,
                            "scope_ref": _TELEMETRY_SCOPE_REF,
                            "transport_ref": "afi-telemetry-connect-v1",
                            "required": True,
                        }
                    ],
                    "options": {"request_timeout_ms": _REQUEST_TIMEOUT_MS},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "afi-telemetry-connect-v1": {
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


def _reader_config(endpoint, security_ref):
    return {
        "client_config_schema_version": 1,
        "process_role": "application_client",
        "registration": {"application_ref": _APP_ID},
        "clients": {
            "monitor": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "application.monitor",
                            "service_id": _SERVICE_ID,
                            "instance_id": _INSTANCE_ID,
                            "scope_ref": _APP_SCOPE_REF,
                            "transport_ref": "afi-telemetry-query-v1",
                            "required": True,
                        }
                    ],
                    "options": {"request_timeout_ms": _REQUEST_TIMEOUT_MS},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "afi-telemetry-query-v1": {
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


def _host_process(control, raw_config, registry_path, keys):
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

    config = parse_service_config(raw_config)
    host = None
    try:
        authority = TrustedServiceAuthority(
            identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID),
            scope=WireScope(_DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="afi-service-scope-v1",
            security_ref=_SERVER_SECURITY_REF,
            security_version="curve-key-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="afi-telemetry-policy-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="afi-telemetry-requirements-v1",
            curve_public_key=keys["server_public"],
            curve_secret_key=keys["server_secret"],
            principals={
                keys["strategy_public"]: _STRATEGY_PRINCIPAL,
                keys["application_public"]: _APP_PRINCIPAL,
            },
            grants={
                _STRATEGY_PRINCIPAL: (
                    PrincipalGrant(
                        WireIdentity(WireRole.STRATEGY_CLIENT, _STRATEGY_PRINCIPAL, _STRATEGY),
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.telemetry_ingress",
                                _TELEMETRY_SCOPE_REF,
                                _STRATEGY_SCOPE,
                                frozenset({"telemetry.append"}),
                            ),
                        ),
                    ),
                ),
                _APP_PRINCIPAL: (
                    PrincipalGrant(
                        WireIdentity(WireRole.APPLICATION_CLIENT, _APP_PRINCIPAL, _APP_ID),
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.monitor_query",
                                _APP_SCOPE_REF,
                                _STRATEGY_SCOPE,
                                frozenset({"telemetry.snapshot"}),
                            ),
                        ),
                    ),
                ),
            },
        )

        def resource_provider(component, _instance_id, _options, _scope):
            if component != "monitor":
                raise AssertionError("unexpected service component")
            return ComponentResources.borrowed(
                {"targets": frozenset({_STRATEGY_SCOPE})}, ready=lambda: True
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
                control.send(("closed", host.state))
                return
            raise AssertionError("unknown local telemetry host command")
    except BaseException as exc:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(Exception):
            control.send(("error", getattr(exc, "code", type(exc).__name__)))
        raise
    finally:
        control.close()


def _start_process(context, target, args, label):
    parent, child = context.Pipe(duplex=True)
    process = context.Process(target=target, args=(child, *args), name=label)
    process.start()
    child.close()
    return {"process": process, "pipe": parent, "label": label}


def _receive(pipe, timeout=20.0):
    assert pipe.poll(timeout), "spawned monitor service missed its response bound"
    return pipe.recv()


def _heartbeat_sample(sequence=1):
    return {
        "schema_version": 1,
        "stream_id": "afi-strategy-a-stream",
        "sequence": sequence,
        "kind": "heartbeat",
        "observed_at": time.time(),
        "metrics": {},
        "dropped_queue_total": 0,
        "dropped_delivery_total": 0,
    }


def test_application_reads_authorized_telemetry_from_a_real_service_process(tmp_path):
    from bt_api_py.service_config import parse_client_config
    from bt_api_py.service_runtime import (
        ClientCurveKeys,
        ServiceClientRuntime,
        ZmqTransportFactory,
    )

    context = multiprocessing.get_context("spawn")
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    strategy_public, strategy_secret = zmq.curve_keypair()
    application_public, application_secret = zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "strategy_public": strategy_public,
        "application_public": application_public,
    }
    host = None
    producer = None
    reader = None
    try:
        host = _start_process(
            context,
            _host_process,
            (
                _service_config(endpoint),
                str(tmp_path / "afi-telemetry-registry.sqlite3"),
                keys,
            ),
            "afi-monitor-host",
        )
        ready = _receive(host["pipe"])
        assert ready[0] == "ready", ready
        assert ready[1] == endpoint

        producer = ServiceClientRuntime(
            parse_client_config(_producer_config(endpoint, "afi-strategy-curve-v1")),
            identity=WireIdentity(WireRole.STRATEGY_CLIENT, _STRATEGY_PRINCIPAL, _STRATEGY),
            scope_resolver=lambda _ref: _STRATEGY_SCOPE,
            peer_resolver=lambda _service: WireIdentity(
                WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID
            ),
            transport_factory=ZmqTransportFactory(
                {
                    "afi-strategy-curve-v1": ClientCurveKeys(
                        server_public, strategy_public, strategy_secret
                    )
                }
            ),
        )
        assert producer.start().degraded_count == 0

        reader = ServiceClientRuntime(
            parse_client_config(_reader_config(endpoint, "afi-dashboard-curve-v1")),
            identity=WireIdentity(WireRole.APPLICATION_CLIENT, _APP_PRINCIPAL, _APP_ID),
            scope_resolver=lambda _ref: _STRATEGY_SCOPE,
            peer_resolver=lambda _service: WireIdentity(
                WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID
            ),
            transport_factory=ZmqTransportFactory(
                {
                    "afi-dashboard-curve-v1": ClientCurveKeys(
                        server_public, application_public, application_secret
                    )
                }
            ),
        )
        assert reader.start().degraded_count == 0
        client = AuthorizedServiceReadClient(
            reader,
            account_bindings={},
            monitor_bindings={
                _APP_SCOPE_REF: MonitorBinding("application.monitor", _APP_SCOPE_REF, _STRATEGY)
            },
        )

        # Before the producer reports, the application must not invent health.
        before = client.read_strategy_health(_APP_SCOPE_REF)
        assert before.quality is ReadQuality.NOT_COLLECTED
        assert before.is_healthy is False
        assert before.metrics == {}

        producer.call(
            "runtime.telemetry",
            "telemetry.append",
            _heartbeat_sample(1),
            scope_ref=_TELEMETRY_SCOPE_REF,
        )
        fresh = client.read_strategy_health(_APP_SCOPE_REF)
        assert fresh.quality is ReadQuality.FRESH
        assert fresh.is_healthy is True
        assert fresh.sequence == 1
        assert fresh.stream_id == "afi-strategy-a-stream"

        # Past the service's heartbeat bound the same observation is stale.
        deadline = time.monotonic() + _HEARTBEAT_TIMEOUT_SECONDS + 1.0
        while time.monotonic() < deadline:
            time.sleep(0.2)
        stale = client.read_strategy_health(_APP_SCOPE_REF)
        assert stale.quality is ReadQuality.STALE
        assert stale.is_healthy is False
        assert stale.sequence == 1

        # A stopped service is reported as unavailable, not as healthy.
        host["pipe"].send(("close",))
        assert _receive(host["pipe"])[0] == "closed"
        host["process"].join(20)
        assert host["process"].exitcode == 0
        host["pipe"].close()
        host["process"].close()
        host = None

        unavailable = client.read_strategy_health(_APP_SCOPE_REF)
        assert unavailable.quality is ReadQuality.UNAVAILABLE
        assert unavailable.is_healthy is False
        assert unavailable.detail_code

        # A scope the deployment never granted is a refusal, not a page state.
        with pytest.raises(ServiceReadUnavailableError, match="SCOPE_NOT_CONFIGURED"):
            client.read_strategy_health("afi-not-granted-v1")
    finally:
        for runtime in (reader, producer):
            if runtime is not None:
                with suppress(Exception):
                    runtime.close()
        if host is not None:
            with suppress(Exception):
                host["pipe"].send(("close",))
                _receive(host["pipe"], timeout=10.0)
            host["process"].join(10)
            if host["process"].is_alive():
                host["process"].terminate()
                raise AssertionError("spawned monitor service did not exit normally")
            assert host["process"].exitcode == 0
            host["pipe"].close()
            host["process"].close()
        assert "zmq" in sys.modules
