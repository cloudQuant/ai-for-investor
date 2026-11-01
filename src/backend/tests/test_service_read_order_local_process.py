"""Local-process evidence for the application's authorized order read.

A real execution service process runs on this machine; a real strategy client
runtime submits an order and the application reads the durable record through
the same adapter the endpoints use.  The test is skipped when the optional
service packages are not installed.
"""

import multiprocessing
from contextlib import suppress
from decimal import Decimal

import pytest

pytest.importorskip("bt_api_py")
pytest.importorskip("bt_api_execution")
zmq = pytest.importorskip("zmq")

from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402

from app.services.service_read.client import (  # noqa: E402
    AuthorizedServiceReadClient,
    OrderBinding,
    ServiceReadUnavailableError,
)
from app.services.service_read.contracts import ReadQuality  # noqa: E402
from tests.test_service_read_local_process import (  # noqa: E402
    _APP_ID,
    _APP_PRINCIPAL,
    _MAX_MESSAGE_BYTES,
    _REQUEST_TIMEOUT_MS,
    _endpoint,
    _receive,
    _start_process,
)


def _command(host, *command):
    host["pipe"].send(command)
    result = _receive(host["pipe"])
    assert result[0] != "error", result
    return result


_DOMAIN = "paper:afi-order-read"
_SERVICE_ID = "afi-execution-service"
_SERVICE_PRINCIPAL = "afi-execution-principal"
_INSTANCE_ID = "afi-execution-owner"
_SERVICE_SCOPE_REF = "afi-execution-root-v1"
_SERVER_SECURITY_REF = "afi-execution-server-curve-v1"
_ACCOUNT = "account-a"
_STRATEGY = "strategy-afi-order-a"
_STRATEGY_PRINCIPAL = "afi-order-strategy-principal"
_ORDER_SCOPE_REF = "afi-order-entry-a-v1"
_QUERY_SCOPE_REF = "afi-order-query-a-v1"
_SCOPE = WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY)


def _service_config(endpoint):
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


def _client_config(endpoint, role, security_ref, *, strategy=None, application=None):
    # The application is read-only: it never asks for the order-entry mount.
    if role == "strategy_client":
        bindings = [
            {
                "mount": "broker.orders",
                "service_id": _SERVICE_ID,
                "instance_id": _INSTANCE_ID,
                "scope_ref": _ORDER_SCOPE_REF,
                "transport_ref": "afi-execution-connect-v1",
                "account_ref": _ACCOUNT,
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
                "account_ref": _ACCOUNT,
            }
        ]
    return {
        "client_config_schema_version": 1,
        "process_role": role,
        "registration": (
            {"strategy_ref": strategy} if strategy is not None else {"application_ref": application}
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


class _Provider:
    def __init__(self):
        self.submitted = []
        self.fail_next = False

    def submit(self, intent):
        from bt_api_execution import ProviderObservation

        self.submitted.append(intent.intent_id)
        if self.fail_next:
            self.fail_next = False
            raise TimeoutError("synthetic provider timeout")
        return ProviderObservation.accepted(intent.intent_id, "provider-order-1")

    def cancel(self, intent):  # pragma: no cover - not exercised here
        raise AssertionError("cancellation is not expected")


class _Gate:
    def __init__(self):
        self.reserved = []

    def reserve(self, intent):
        from types import SimpleNamespace

        reference = getattr(intent, "intent_id", None) or intent.cancel_id
        self.reserved.append(reference)
        return SimpleNamespace(permit_id=f"permit-{reference}")

    def validate(self, permit_id, intent):
        from types import SimpleNamespace

        return SimpleNamespace(permit_id=permit_id)

    def claim_for_dispatch(self, permit_id, intent):
        from types import SimpleNamespace

        return SimpleNamespace(permit_id=permit_id)

    def claim_before_dispatch(self, permit_id, intent):
        from bt_api_execution import CancelDispatchClaimReceiptV1

        return CancelDispatchClaimReceiptV1(
            permit_reference=permit_id,
            scope_key=intent.scope.key,
            cancel_id=intent.cancel_id,
            intent_fingerprint=intent.fingerprint,
        )

    def release(self, permit_id, reason):
        return None

    def settle(self, permit_id):
        return None


def _host_process(control, raw_config, registry_path, keys, store_path):
    from bt_api_execution import ExecutionScope, SqliteExecutionStore
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

    config = parse_service_config(raw_config)
    provider = _Provider()
    gate = _Gate()
    store = None
    host = None
    try:
        authority = TrustedServiceAuthority(
            identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID),
            scope=WireScope(_DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="afi-execution-scope-v1",
            security_ref=_SERVER_SECURITY_REF,
            security_version="curve-key-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="afi-execution-policy-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="afi-execution-requirements-v1",
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
                                "service.order_entry",
                                _ORDER_SCOPE_REF,
                                _SCOPE,
                                frozenset({"orders.submit", "orders.cancel"}),
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
                                "service.order_query",
                                _QUERY_SCOPE_REF,
                                _SCOPE,
                                frozenset({"orders.query"}),
                            ),
                        ),
                    ),
                ),
            },
        )
        execution_scope = ExecutionScope("PAPER", "simulation", _ACCOUNT, _STRATEGY, "20261014")
        store = SqliteExecutionStore(store_path)

        def resource_provider(component, _instance_id, _options, _scope):
            if component != "execution":
                raise AssertionError("unexpected service component")
            return ComponentResources.borrowed(
                {
                    "store": store,
                    "targets": {_SCOPE: execution_scope},
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
                store.close()
                store = None
                control.send(("closed", host.state))
                return
            if command == ("counts",):
                control.send(("counts", tuple(provider.submitted), tuple(gate.reserved)))
                continue
            if command == ("fail_next_submit",):
                provider.fail_next = True
                control.send(("armed",))
                continue
            raise AssertionError("unknown local execution host command")
    except BaseException as exc:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        if store is not None:
            with suppress(BaseException):
                store.close()
        with suppress(Exception):
            control.send(("error", getattr(exc, "code", type(exc).__name__)))
        raise
    finally:
        control.close()


def _runtime(endpoint, role, security_ref, keys, *, strategy=None, application=None):
    from bt_api_py.service_config import parse_client_config
    from bt_api_py.service_runtime import (
        ClientCurveKeys,
        ServiceClientRuntime,
        ZmqTransportFactory,
    )

    peer = WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID)
    identity = (
        WireIdentity(WireRole.STRATEGY_CLIENT, _STRATEGY_PRINCIPAL, _STRATEGY)
        if strategy is not None
        else WireIdentity(WireRole.APPLICATION_CLIENT, _APP_PRINCIPAL, _APP_ID)
    )
    return ServiceClientRuntime(
        parse_client_config(
            _client_config(endpoint, role, security_ref, strategy=strategy, application=application)
        ),
        identity=identity,
        scope_resolver=lambda _ref: _SCOPE,
        peer_resolver=lambda _service: peer,
        transport_factory=ZmqTransportFactory(
            {
                security_ref: ClientCurveKeys(
                    keys["server_public"],
                    keys["client_public"],
                    keys["client_secret"],
                )
            }
        ),
    )


def _submit(submitter, intent_id, signal_id, quantity):
    return submitter.submit(
        intent_id=intent_id,
        signal_id=signal_id,
        instrument="BTC-USDT",
        side="BUY",
        position_effect="OPEN",
        order_type="LIMIT",
        quantity=Decimal(quantity),
        price=Decimal("50000"),
    )


def test_application_reads_order_state_from_a_real_execution_service(tmp_path):
    from bt_api_py.service_execution import ServiceExecutionClient
    from bt_api_py.service_runtime import ServiceRuntimeError

    context = multiprocessing.get_context("spawn")
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    strategy_public, strategy_secret = zmq.curve_keypair()
    application_public, application_secret = zmq.curve_keypair()
    host = None
    producer = None
    reader = None
    try:
        host = _start_process(
            context,
            _host_process,
            (
                _service_config(endpoint),
                str(tmp_path / "afi-execution-registry.sqlite3"),
                {
                    "server_public": server_public,
                    "server_secret": server_secret,
                    "strategy_public": strategy_public,
                    "application_public": application_public,
                },
                str(tmp_path / "afi-execution.sqlite3"),
            ),
            "afi-execution-host",
        )
        assert _receive(host["pipe"])[0] == "ready"

        producer = _runtime(
            endpoint,
            "strategy_client",
            "afi-order-strategy-curve-v1",
            {
                "server_public": server_public,
                "client_public": strategy_public,
                "client_secret": strategy_secret,
            },
            strategy=_STRATEGY,
        )
        assert producer.start().degraded_count == 0
        submitter = ServiceExecutionClient(producer, "broker.orders", scope_ref=_ORDER_SCOPE_REF)

        reader = _runtime(
            endpoint,
            "application_client",
            "afi-order-dashboard-curve-v1",
            {
                "server_public": server_public,
                "client_public": application_public,
                "client_secret": application_secret,
            },
            application=_APP_ID,
        )
        assert reader.start().degraded_count == 0
        client = AuthorizedServiceReadClient(
            reader,
            account_bindings={},
            order_bindings={
                _QUERY_SCOPE_REF: OrderBinding("application.order_query", _QUERY_SCOPE_REF)
            },
        )

        before = client.read_order(_QUERY_SCOPE_REF, "intent-1")
        assert before.quality is ReadQuality.NOT_COLLECTED
        assert before.state is None

        _submit(submitter, "intent-1", "signal-1", "2")
        accepted = client.read_order(_QUERY_SCOPE_REF, "intent-1")
        assert accepted.quality is ReadQuality.FRESH
        assert accepted.state == "ACKED"
        assert accepted.provider_order_id == "provider-order-1"
        assert accepted.is_terminal is False

        assert _command(host, "fail_next_submit") == ("armed",)
        _submit(submitter, "intent-2", "signal-2", "1")
        unknown = client.read_order(_QUERY_SCOPE_REF, "intent-2")
        assert unknown.is_unknown is True
        assert unknown.state == "UNKNOWN"
        assert unknown.unknown_reason

        host["pipe"].send(("close",))
        assert _receive(host["pipe"])[0] == "closed"
        host["process"].join(20)
        assert host["process"].exitcode == 0
        host["pipe"].close()
        host["process"].close()
        host = _start_process(
            context,
            _host_process,
            (
                _service_config(endpoint),
                str(tmp_path / "afi-execution-registry.sqlite3"),
                {
                    "server_public": server_public,
                    "server_secret": server_secret,
                    "strategy_public": strategy_public,
                    "application_public": application_public,
                },
                str(tmp_path / "afi-execution.sqlite3"),
            ),
            "afi-execution-host-r2",
        )
        assert _receive(host["pipe"])[0] == "ready"

        # A restarted service has a new epoch: the borrowed runtime refuses the
        # stale registration, and the durable facts survive an explicit recovery.
        with pytest.raises(ServiceRuntimeError, match="STALE_EPOCH"):
            reader.call(
                "application.order_query",
                "orders.query",
                {"intent_id": "intent-1"},
                scope_ref=_QUERY_SCOPE_REF,
            )
        assert reader.recover().degraded_count == 0
        assert client.read_order(_QUERY_SCOPE_REF, "intent-1").state == "ACKED"
        assert client.read_order(_QUERY_SCOPE_REF, "intent-2").state == "UNKNOWN"
        assert _command(host, "counts")[1] == ()

        with pytest.raises(ServiceReadUnavailableError, match="SCOPE_NOT_CONFIGURED"):
            client.read_order("afi-not-granted-v1", "intent-1")
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
                raise AssertionError("spawned execution service did not exit normally")
            assert host["process"].exitcode == 0
            host["pipe"].close()
            host["process"].close()
