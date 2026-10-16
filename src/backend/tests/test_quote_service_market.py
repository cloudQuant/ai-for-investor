from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import app.services.quote.service_market as service_market_module
from app.services.quote.service_market import (
    MarketQuoteResult,
    ServiceMarketDeployment,
    ServiceMarketDeploymentError,
    project_market_event,
)
from app.services.quote_service import QuoteService


def _market_key(symbol: str = "BTC-USDT-SWAP"):
    from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey

    return MarketSubscriptionKey(
        source_ref="okx-public-market-r1",
        entitlement_ref="public-ticker-r1",
        instrument=MarketInstrumentKey(
            provider="okx",
            venue="OKX",
            environment="live",
            product_type="SWAP",
            instrument_id=symbol,
            native_symbol=symbol,
        ),
        channel="tickers",
    )


def _history_key(symbol: str = "BTC-USDT-SWAP", timeframe: str = "1m"):
    from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey

    return MarketSubscriptionKey(
        source_ref="okx-public-market-r1",
        entitlement_ref="public-history-r1",
        instrument=MarketInstrumentKey(
            provider="okx",
            venue="OKX",
            environment="live",
            product_type="SWAP",
            instrument_id=symbol,
            native_symbol=symbol,
        ),
        channel="bar",
        timeframe=timeframe,
    )


def _deployment_document(symbol: str = "BTC-USDT-SWAP") -> dict:
    return {
        "schema_version": 1,
        "subjects": [
            {
                "subject": "jwt-subject-a",
                "identity": {
                    "principal_ref": "afi-market-principal-a",
                    "actor_ref": "afi-market-application-a",
                    "delegate_ref": None,
                },
                "client_config": {
                    "client_config_schema_version": 1,
                    "process_role": "application_client",
                    "registration": {"application_ref": "afi-market-application-a"},
                    "clients": {
                        "gateway": {
                            "config_schema_version": 1,
                            "settings": {
                                "bindings": [
                                    {
                                        "mount": "application.market",
                                        "service_id": "okx-market-service",
                                        "instance_id": "okx-market-hub",
                                        "scope_ref": "public-market-scope",
                                        "transport_ref": "okx-market-transport",
                                    }
                                ],
                                "options": {"request_timeout_ms": 1_000},
                            },
                        }
                    },
                    "communication": {
                        "config_schema_version": 1,
                        "profiles": {
                            "okx-market-transport": {
                                "backend": "zmq",
                                "config_schema_version": 1,
                                "endpoints": {
                                    "rpc_connect": "tcp://127.0.0.1:5500",
                                    "market_connect": "tcp://127.0.0.1:5501",
                                },
                                "security_profile_ref": "okx-market-curve",
                                "options": {
                                    "request_timeout_ms": 1_000,
                                    "high_water_mark": 128,
                                    "max_message_bytes": 262_144,
                                },
                            }
                        },
                    },
                },
                "scope_claims": {
                    "public-market-scope": {"execution_domain_ref": "afi-public-market"}
                },
                "peer_identities": {
                    "okx-market-service": {
                        "principal_ref": "okx-market-service-principal",
                        "actor_ref": "okx-market-service",
                    }
                },
                "curve_keys": {
                    "okx-market-curve": {
                        "server_key": "abcdefghijklmnopqrstuvwxyz0123456789ABCD",
                        "public_key": "abcdefghijklmnopqrstuvwxyz0123456789ABCD",
                        "secret_key": "abcdefghijklmnopqrstuvwxyz0123456789ABCD",
                    }
                },
                "market_bindings": [
                    {
                        "source": "OKX",
                        "symbol": symbol,
                        "key": _market_key(symbol).to_dict(),
                    }
                ],
            }
        ],
    }


def _history_deployment_document(
    *, symbol: str = "BTC-USDT-SWAP", timeframe: str = "1m", history_only: bool = False
) -> dict:
    document = _deployment_document(symbol)
    profile = document["subjects"][0]
    profile["history_bindings"] = [
        {
            "source": "OKX",
            "symbol": symbol,
            "timeframe": timeframe,
            "key": _history_key(symbol, timeframe).to_dict(),
        }
    ]
    if history_only:
        profile["market_bindings"] = []
    return document


def test_configured_service_market_path_does_not_import_legacy_zmq_modules():
    script = r"""
import builtins
import sys
import threading

blocked = {
    "app.services.quote.runtime",
    "app.services.quote.zmq_receiver",
}
original_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name in blocked:
        raise AssertionError(f"legacy quote transport imported: {name}")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import

from app.services.quote.service_market import MarketQuoteResult
from app.services.quote_service import QuoteService

symbol = "BTC-USDT-SWAP"
key = type("Key", (), {"stream_id": "configured-stream"})()

class Deployment:
    def configured_routes(self, subject, source, symbols):
        assert (subject, source, symbols) == ("jwt-subject-a", "OKX", [symbol])
        return {symbol: key}

    def read_quotes(self, subject, routes, *, wait_ms):
        assert subject == "jwt-subject-a"
        assert routes == {symbol: key}
        assert wait_ms == 250
        return {
            key.stream_id: MarketQuoteResult(
                {"symbol": symbol, "last_price": 65000.0}, None, True
            )
        }

service = object.__new__(QuoteService)
service._service_market_loaded = True
service._service_market_deployment = Deployment()
service._service_market_error = None
service._service_market_load_lock = threading.Lock()
quotes, config_error = service._read_service_market_quotes(
    "OKX", "jwt-subject-a", [symbol]
)
assert config_error is None
assert quotes[symbol].data == {"symbol": symbol, "last_price": 65000.0}
assert blocked.isdisjoint(sys.modules)
print("service-market-without-legacy-imports")
"""
    backend_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "service-market-without-legacy-imports" in result.stdout


def test_legacy_zmq_helpers_are_loaded_when_fallback_is_invoked(monkeypatch):
    receiver_module = ModuleType("app.services.quote.zmq_receiver")
    receiver_rows = []

    class FakeReceiver:
        def __init__(self, source, market_endpoint):
            self.source = source
            self.market_endpoint = market_endpoint
            self.started = False

        def start(self):
            self.started = True
            receiver_rows.append(self)

        def stop(self):
            self.started = False

        @property
        def is_alive(self):
            return self.started

    receiver_module.ZmqTickReceiver = FakeReceiver
    runtime_module = ModuleType("app.services.quote.runtime")
    command_result = {"accepted": ["BTC-USDT-SWAP"]}
    runtime_module.send_gateway_command = lambda *args, **kwargs: command_result
    monkeypatch.setitem(sys.modules, "app.services.quote.zmq_receiver", receiver_module)
    monkeypatch.setitem(sys.modules, "app.services.quote.runtime", runtime_module)

    QuoteService._instance = None
    service = QuoteService()
    state = {"config": SimpleNamespace(market_endpoint="tcp://127.0.0.1:5501")}
    service._ensure_receiver_for_gateway("OKX", "gateway-1", state)

    assert receiver_rows[0].source == "OKX"
    assert receiver_rows[0].market_endpoint == "tcp://127.0.0.1:5501"
    assert receiver_rows[0].started is True
    assert service._send_gateway_command(
        "tcp://127.0.0.1:5500", "subscribe", {"symbols": ["BTC-USDT-SWAP"]}
    ) is command_result


def _projection(symbol: str = "BTC-USDT-SWAP") -> dict:
    return {
        "exchange_name": "OKX",
        "symbol": symbol,
        "instrument_id": symbol,
        "asset_type": "SWAP",
        "timestamp": 1_797_523_200.25,
        "price": 67_001.5,
        "last_price": 67_001.5,
        "bid_price": 67_001.4,
        "ask_price": 67_001.6,
        "bid_volume": 2.0,
        "ask_volume": 3.0,
        "volume": 123.0,
        "turnover": 8_250_000.0,
        "high": 68_000.0,
        "low": 66_000.0,
        "open": 66_500.0,
    }


def test_service_market_directory_binds_only_exact_subject_source_and_symbol():
    directory = ServiceMarketDeployment.from_value(json.dumps(_deployment_document()))

    assert directory is not None
    routes = directory.configured_routes("jwt-subject-a", "okx", ["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    assert routes == {"BTC-USDT-SWAP": _market_key()}
    assert directory.configured_routes("jwt-subject-b", "OKX", ["BTC-USDT-SWAP"]) == {}
    assert directory.configured_routes("jwt-subject-a", "BINANCE", ["BTC-USDT-SWAP"]) == {}
    assert directory.configured_routes("jwt-subject-a", "OKX", ["btc-usdt-swap"]) == {}
    directory.close()


def test_service_market_reads_only_configured_key_and_rejects_after_close():
    directory = ServiceMarketDeployment.from_value(json.dumps(_deployment_document()))
    assert directory is not None

    with pytest.raises(ServiceMarketDeploymentError) as error:
        directory.read_quotes(
            "jwt-subject-a",
            {"ETH-USDT-SWAP": _market_key("ETH-USDT-SWAP")},
            wait_ms=0,
        )
    assert error.value.code == "MARKET_BINDING_NOT_CONFIGURED"

    directory.close()
    with pytest.raises(ServiceMarketDeploymentError) as error:
        directory.read_quotes("jwt-subject-a", {"BTC-USDT-SWAP": _market_key()}, wait_ms=0)
    assert error.value.code == "DEPLOYMENT_CLOSED"


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda doc: doc["subjects"][0]["client_config"]["clients"]["gateway"]["settings"]["bindings"][0].update(mount="application.orders"), "INVALID_CLIENT_CONFIG"),
        (lambda doc: doc["subjects"][0]["market_bindings"][0]["key"]["instrument"].update(provider="binance"), "UNSUPPORTED_MARKET_BINDING"),
        (lambda doc: doc["subjects"][0]["scope_claims"]["public-market-scope"].update(account_ref="account-1"), "INVALID_DEPLOYMENT"),
    ],
)
def test_service_market_directory_rejects_widened_or_mismatched_binding(mutate, code):
    document = _deployment_document()
    mutate(document)

    with pytest.raises(ServiceMarketDeploymentError) as error:
        ServiceMarketDeployment.from_value(json.dumps(document))

    assert error.value.code == code


def test_service_market_directory_rejects_duplicate_json_keys():
    with pytest.raises(ServiceMarketDeploymentError) as error:
        ServiceMarketDeployment.from_value('{"schema_version":1,"schema_version":1,"subjects":[] }')

    assert error.value.code == "INVALID_DEPLOYMENT"


def test_project_market_event_maps_established_okx_projection_to_quote_tick_input():
    from bt_api_base.service_protocol import (
        WireEnvelope,
        WireHeader,
        WireIdentity,
        WireMessageKind,
        WireRole,
        WireScope,
    )

    key = _market_key()
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    event = WireEnvelope(
        WireHeader(
            protocol_version=2,
            kind=WireMessageKind.EVENT,
            message_id="synthetic-market-event-1",
            correlation_id=None,
            identity=WireIdentity(WireRole.SERVICE, "okx-market-service-principal", "okx-market-service"),
            scope=WireScope("afi-public-market"),
            operation="market.event",
            schema_id="sdk.market.event",
            schema_version=1,
            sent_at_utc=now,
            stream_id=key.stream_id,
            stream_epoch="synthetic-market-epoch-1",
            sequence=1,
        ),
        {"key": key.to_dict(), "data": _projection()},
    )

    projected = project_market_event(event, expected_key=key)

    assert projected["symbol"] == "BTC-USDT-SWAP"
    assert projected["price"] == 67_001.5
    assert projected["bid_price"] == 67_001.4
    assert projected["ask_price"] == 67_001.6
    assert projected["volume"] == 123.0
    assert projected["high_price"] == 68_000.0
    assert projected["low_price"] == 66_000.0
    assert projected["open_price"] == 66_500.0
    assert projected["timestamp"] == 1_797_523_200.25


def test_project_market_event_rejects_key_and_projection_mismatch():
    from bt_api_base.service_protocol import (
        WireEnvelope,
        WireHeader,
        WireIdentity,
        WireMessageKind,
        WireRole,
        WireScope,
    )

    key = _market_key()
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    event = WireEnvelope(
        WireHeader(
            protocol_version=2,
            kind=WireMessageKind.EVENT,
            message_id="synthetic-market-event-2",
            correlation_id=None,
            identity=WireIdentity(WireRole.SERVICE, "okx-market-service-principal", "okx-market-service"),
            scope=WireScope("afi-public-market"),
            operation="market.event",
            schema_id="sdk.market.event",
            schema_version=1,
            sent_at_utc=now,
            stream_id=key.stream_id,
            stream_epoch="synthetic-market-epoch-1",
            sequence=1,
        ),
        {"key": key.to_dict(), "data": {**_projection(), "symbol": "ETH-USDT-SWAP"}},
    )

    with pytest.raises(ServiceMarketDeploymentError) as error:
        project_market_event(event, expected_key=key)

    assert error.value.code == "MARKET_INSTRUMENT_MISMATCH"


def _quote_service(monkeypatch: pytest.MonkeyPatch) -> QuoteService:
    QuoteService._instance = None
    service = QuoteService()
    monkeypatch.setattr(service, "_get_live_trading_manager", lambda: SimpleNamespace())
    monkeypatch.setattr(service, "_get_running_workspace_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        service,
        "_get_default_symbols_for_source",
        lambda _source: [
            {"symbol": "BTC-USDT-SWAP", "name": "BTC", "exchange": "OKX", "category": "crypto"},
            {"symbol": "ETH-USDT-SWAP", "name": "ETH", "exchange": "OKX", "category": "crypto"},
        ],
    )
    monkeypatch.setattr(service, "_build_quote_plans", lambda *args, **kwargs: {})
    return service


def test_quote_service_uses_configured_v2_key_without_opening_legacy_receiver(monkeypatch):
    service = _quote_service(monkeypatch)
    key = _market_key()

    class _Directory:
        def configured_routes(self, subject, source, symbols):
            assert subject == "jwt-subject-a"
            assert source == "OKX"
            return {"BTC-USDT-SWAP": key}

        def read_quotes(self, subject, routes, *, wait_ms):
            assert wait_ms == 250
            return {
                key.stream_id: MarketQuoteResult(_projected_raw(), None, True),
            }

    service._service_market_loaded = True
    service._service_market_deployment = _Directory()
    monkeypatch.setattr(
        service,
        "_ensure_receiver",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy receiver opened")),
    )
    monkeypatch.setattr(
        service,
        "_subscribe_symbols_on_gateway",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy subscribe sent")),
    )

    result = service.get_quotes("OKX", "jwt-subject-a", ["BTC-USDT-SWAP"])

    assert result["refresh_mode"] == "push"
    assert result["total"] == 1
    tick = result["ticks"][0]
    assert tick["gateway_key"] == "service-market"
    assert tick["last_price"] == 67_001.5
    assert tick["bid_price"] == 67_001.4
    assert tick["status"] == "normal"


def test_quote_service_does_not_fallback_when_configured_v2_route_fails(monkeypatch):
    service = _quote_service(monkeypatch)
    key = _market_key()

    class _Directory:
        def configured_routes(self, _subject, _source, _symbols):
            return {"BTC-USDT-SWAP": key}

        def read_quotes(self, _subject, _routes, *, wait_ms):
            return {key.stream_id: MarketQuoteResult(None, "SERVICE_NOT_READY", False)}

    service._service_market_loaded = True
    service._service_market_deployment = _Directory()
    monkeypatch.setattr(
        service,
        "_ensure_receiver",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy receiver opened")),
    )
    monkeypatch.setattr(
        service,
        "_subscribe_symbols_on_gateway",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy subscribe sent")),
    )

    result = service.get_quotes("OKX", "jwt-subject-a", ["BTC-USDT-SWAP"])

    assert result["ticks"][0]["status"] == "error"
    assert result["ticks"][0]["error_message"] == "SERVICE_NOT_READY"
    assert result["refresh_mode"] == "polling"


def test_get_data_sources_does_not_start_legacy_market_consumers(monkeypatch):
    service = _quote_service(monkeypatch)
    state = {"exchange_type": "OKX", "manual": False}
    mixed_gateway = {
        "state": state,
        "symbols": {
            "BTC-USDT-SWAP": {
                "symbol": "BTC-USDT-SWAP",
                "workspace_ids": {"workspace-1"},
                "workspace_names": {"Demo"},
            },
            "ETH-USDT-SWAP": {
                "symbol": "ETH-USDT-SWAP",
                "workspace_ids": {"workspace-1"},
                "workspace_names": {"Demo"},
            },
        },
        "workspaces": {
            "workspace-1": {
                "workspace_id": "workspace-1",
                "workspace_name": "Demo",
                "symbols": {"BTC-USDT-SWAP", "ETH-USDT-SWAP"},
            }
        },
    }
    workspace_context = {"OKX": {"gateway-1": mixed_gateway}}

    monkeypatch.setattr(
        service,
        "_get_running_workspace_context",
        lambda *_args, **_kwargs: workspace_context,
    )
    monkeypatch.setattr(
        service,
        "_get_source_gateway_states",
        lambda _manager, source, _context: {"gateway-1": state} if source == "OKX" else {},
    )
    monkeypatch.setattr(service, "_is_gateway_state_ready", lambda _state: True)

    def fail_legacy_start(*_args, **_kwargs):
        raise AssertionError("source status must not start or subscribe a market consumer")

    monkeypatch.setattr(
        service,
        "_ensure_receiver_for_gateway",
        fail_legacy_start,
    )
    monkeypatch.setattr(
        service,
        "_subscribe_symbols_on_gateway_state",
        fail_legacy_start,
    )

    sources = service.get_data_sources("jwt-subject-a")

    okx = next(item for item in sources if item["source"] == "OKX")
    assert okx["status"] == "available"
    assert okx["workspaces"][0]["symbols"] == ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]


def test_workspace_only_configured_v2_quote_avoids_legacy_path(monkeypatch):
    service = _quote_service(monkeypatch)
    key = _market_key()
    state = {"exchange_type": "OKX", "manual": False}
    workspace_gateway = {
        "state": state,
        "symbols": {
            "BTC-USDT-SWAP": {
                "symbol": "BTC-USDT-SWAP",
                "workspace_ids": {"workspace-1"},
                "workspace_names": {"Demo"},
            }
        },
        "workspaces": {},
    }
    service._get_running_workspace_context = lambda *_args, **_kwargs: {
        "OKX": {"gateway-1": workspace_gateway}
    }

    class _Directory:
        def configured_routes(self, subject, source, symbols):
            assert subject == "jwt-subject-a"
            assert source == "OKX"
            assert symbols == ["ETH-USDT-SWAP", "BTC-USDT-SWAP"]
            return {"BTC-USDT-SWAP": key}

        def read_quotes(self, subject, routes, *, wait_ms):
            assert subject == "jwt-subject-a"
            assert routes == {"BTC-USDT-SWAP": key}
            assert wait_ms == 250
            return {key.stream_id: MarketQuoteResult(_projected_raw(), None, True)}

    service._service_market_loaded = True
    service._service_market_deployment = _Directory()
    legacy_ensures: list[str] = []
    legacy_subscriptions: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        service,
        "_ensure_receiver",
        lambda source, _manager: legacy_ensures.append(source),
    )
    monkeypatch.setattr(
        service,
        "_subscribe_symbols_on_gateway",
        lambda source, symbols: legacy_subscriptions.append((source, list(symbols))),
    )

    result = service.get_quotes("OKX", "jwt-subject-a", ["ETH-USDT-SWAP"])

    assert legacy_ensures == ["OKX"]
    assert legacy_subscriptions == [("OKX", ["ETH-USDT-SWAP"])]
    assert result["total"] == 1
    tick = result["ticks"][0]
    assert tick["gateway_key"] == "service-market"
    assert tick["origins"] == ["workspace"]
    assert tick["workspace_ids"] == ["workspace-1"]
    assert tick["workspace_names"] == ["Demo"]


def test_uncertain_service_market_close_retains_production_owner_and_retries(monkeypatch):
    service = _quote_service(monkeypatch)
    key = _market_key()
    directory = ServiceMarketDeployment.from_value(json.dumps(_deployment_document()))
    assert directory is not None

    class _Transport:
        def __init__(self) -> None:
            self.close_calls = 0
            self.fail_first_close = True

        def close(self):
            self.close_calls += 1
            if self.fail_first_close:
                self.fail_first_close = False
                raise RuntimeError("transient transport close failure")

    class _Client:
        healthy = False

        def __init__(self) -> None:
            self.close_calls = 0
            self.fail_close = True

        def poll(self, *, timeout_ms: int):
            assert timeout_ms == 0
            return None

        def close(self):
            self.close_calls += 1
            if self.fail_close:
                raise RuntimeError("transient client close failure")

    transport = _Transport()
    runtimes = []
    client = _Client()

    def _ensure_runtime(owner) -> None:
        if owner._runtime is None:
            from bt_api_py.service_runtime import ServiceClientRuntime

            profile = owner._profile
            runtime = ServiceClientRuntime(
                profile.client_config,
                identity=profile.identity,
                scope_resolver=lambda _scope_ref: profile.scope,
                peer_resolver=lambda _service_id: profile.peer,
                transport_factory=lambda *_args: transport,
            )
            # Exercise the SDK runtime's exact transport-close retry path on
            # the same owner thread without starting an RPC or provider.
            runtime._transports[(profile.service_id, "okx-market-transport")] = transport
            runtimes.append(runtime)
            owner._runtime = runtime

    def _ensure_client(owner, requested_key) -> None:
        owner._clients[requested_key.stream_id] = (requested_key, client)

    monkeypatch.setattr(
        service_market_module._ServiceMarketOwner,
        "_ensure_runtime",
        _ensure_runtime,
    )
    monkeypatch.setattr(
        service_market_module._ServiceMarketOwner,
        "_ensure_client",
        _ensure_client,
    )
    directory.read_quotes("jwt-subject-a", {"BTC-USDT-SWAP": key}, wait_ms=0)
    owner = directory._workers["jwt-subject-a"]
    assert len(runtimes) == 1
    runtime = runtimes[0]

    service._service_market_loaded = True
    service._service_market_deployment = directory
    service._service_market_error = None
    monkeypatch.setattr(
        service,
        "_ensure_receiver",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("uncertain v2 owner fell back to legacy receiver")
        ),
    )
    monkeypatch.setattr(
        service,
        "_subscribe_symbols_on_gateway",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("uncertain v2 owner fell back to legacy subscribe")
        ),
    )

    assert service.shutdown() is False

    assert service._service_market_deployment is directory
    assert service._service_market_loaded is True
    assert service._service_market_error is None
    assert owner._clients == {key.stream_id: (key, client)}
    assert owner._runtime is runtime
    assert runtime.state == "new"
    assert owner._thread is not None and owner._thread.is_alive()
    result = service.get_quotes("OKX", "jwt-subject-a", ["BTC-USDT-SWAP"])
    assert result["ticks"][0]["status"] == "error"
    assert result["ticks"][0]["error_message"] == "DEPLOYMENT_CLOSED"

    client.fail_close = False
    assert service.shutdown() is False
    assert client.close_calls == 2
    assert owner._clients == {}
    assert owner._runtime is runtime
    assert runtime.state == "close_failed"
    assert runtime.cleanup_failures == 1
    assert runtime.unregister_uncertainties == 0
    assert owner._thread is not None and owner._thread.is_alive()
    assert service._service_market_deployment is directory
    assert service._service_market_loaded is True

    assert service.shutdown() is True
    assert client.close_calls == 2
    assert runtime.state == "closed"
    assert runtime.cleanup_failures == 1
    assert transport.close_calls == 2
    assert owner._clients == {}
    assert owner._runtime is None
    assert owner._thread is None
    assert service._service_market_deployment is None
    assert service._service_market_loaded is False


def _projected_raw() -> dict:
    return {
        "symbol": "BTC-USDT-SWAP",
        "instrument_id": "BTC-USDT-SWAP",
        "exchange": "OKX",
        "asset_type": "SWAP",
        "timestamp": 1_797_523_200.25,
        "price": 67_001.5,
        "last_price": 67_001.5,
        "bid_price": 67_001.4,
        "ask_price": 67_001.6,
        "bid_volume": 2.0,
        "ask_volume": 3.0,
        "volume": 123.0,
        "turnover": 8_250_000.0,
        "high_price": 68_000.0,
        "low_price": 66_000.0,
        "open_price": 66_500.0,
    }


def test_history_bindings_are_exact_subject_timeframe_and_separate_from_tickers():
    directory = ServiceMarketDeployment.from_value(
        json.dumps(_history_deployment_document(history_only=True))
    )
    assert directory is not None
    key = _history_key()

    assert directory.configured_history_key(
        "jwt-subject-a", "okx", "BTC-USDT-SWAP", "1m"
    ) == key
    assert directory.configured_history_key(
        "jwt-subject-b", "OKX", "BTC-USDT-SWAP", "1m"
    ) is None
    assert directory.configured_history_key(
        "jwt-subject-a", "OKX", "BTC-USDT-SWAP", "5m"
    ) is None
    assert directory.has_configured_history_symbol(
        "jwt-subject-a", "OKX", "BTC-USDT-SWAP"
    )
    profile = directory._profiles["jwt-subject-a"]
    assert profile.routes == {}
    assert profile.requested_operations == frozenset({"market.history"})
    directory.close()


@pytest.mark.parametrize(
    "mutation,code",
    [
        (
            lambda doc: doc["subjects"][0]["history_bindings"][0].update(timeframe="1M"),
            "UNSUPPORTED_HISTORY_TIMEFRAME",
        ),
        (
            lambda doc: doc["subjects"][0]["history_bindings"][0]["key"]["instrument"].update(environment="demo"),
            "UNSUPPORTED_HISTORY_BINDING",
        ),
        (
            lambda doc: doc["subjects"][0]["history_bindings"][0]["key"].update(entitlement_ref="public-ticker-r1"),
            "UNSUPPORTED_HISTORY_BINDING",
        ),
    ],
)
def test_history_binding_rejects_widened_or_inconsistent_key(mutation, code):
    document = _history_deployment_document(history_only=True)
    mutation(document)

    with pytest.raises(ServiceMarketDeploymentError) as error:
        ServiceMarketDeployment.from_value(json.dumps(document))

    assert error.value.code == code


def test_history_page_uses_owner_thread_client_without_stream_start(monkeypatch):
    from bt_api_base.market_history_protocol import (
        MarketBar,
        MarketHistoryPage,
        MarketHistoryRequest,
    )

    directory = ServiceMarketDeployment.from_value(
        json.dumps(_history_deployment_document(history_only=True))
    )
    assert directory is not None
    key = _history_key()
    request = MarketHistoryRequest(
        key,
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:01:00Z",
        1,
    )
    owner_thread_ids: list[int] = []
    start_calls: list[int] = []

    class _Client:
        def history(self, actual_request):
            owner_thread_ids.append(threading.get_ident())
            assert actual_request == request
            return MarketHistoryPage(
                actual_request,
                (
                    MarketBar(
                        "2026-01-01T00:00:00Z",
                        "2026-01-01T00:01:00Z",
                        "10",
                        "12",
                        "9",
                        "11",
                        "3",
                    ),
                ),
                True,
                None,
                "2026-01-01T00:01:00Z",
            )

        def start(self):
            start_calls.append(threading.get_ident())
            raise AssertionError("history-only clients must not subscribe")

    monkeypatch.setattr(
        service_market_module._ServiceMarketOwner,
        "_ensure_runtime",
        lambda _owner: None,
    )
    monkeypatch.setattr(
        service_market_module._ServiceMarketOwner,
        "_ensure_history_client",
        lambda _owner, _key: _Client(),
    )
    page = directory.read_history_page(
        "jwt-subject-a", "OKX", "BTC-USDT-SWAP", "1m", key, request
    )
    owner = directory._workers["jwt-subject-a"]

    assert type(page) is MarketHistoryPage
    assert page.request == request
    assert owner_thread_ids == [owner._thread.ident]
    assert start_calls == []
    directory.close()
    assert owner._thread is None


def test_configured_chart_history_projects_complete_page_without_legacy_fallback(monkeypatch):
    from bt_api_base.market_history_protocol import (
        MarketBar,
        MarketHistoryPage,
    )

    service = _quote_service(monkeypatch)
    key = _history_key()
    calls = []

    class _Directory:
        def has_configured_history_symbol(self, subject, source, symbol):
            assert (subject, source, symbol) == (
                "jwt-subject-a",
                "OKX",
                "BTC-USDT-SWAP",
            )
            return True

        def configured_history_key(self, subject, source, symbol, timeframe):
            assert (subject, source, symbol, timeframe) == (
                "jwt-subject-a",
                "OKX",
                "BTC-USDT-SWAP",
                "1m",
            )
            return key

        def read_history_page(self, subject, source, symbol, timeframe, actual_key, request):
            calls.append(request)
            assert (subject, source, symbol, timeframe, actual_key) == (
                "jwt-subject-a",
                "OKX",
                "BTC-USDT-SWAP",
                "1m",
                key,
            )
            start = datetime.fromisoformat(request.start_time_utc.replace("Z", "+00:00"))
            close = start + timedelta(minutes=1)
            return MarketHistoryPage(
                request,
                (
                    MarketBar(
                        request.start_time_utc,
                        close.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                        "10.5",
                        "12.25",
                        "9.5",
                        "11.75",
                        "3.125",
                    ),
                ),
                True,
                None,
                request.end_time_utc,
            )

    service._service_market_loaded = True
    service._service_market_deployment = _Directory()
    service._service_market_error = None
    service._service_market_load_lock = threading.Lock()
    monkeypatch.setattr(
        service,
        "_get_live_trading_manager",
        lambda: (_ for _ in ()).throw(AssertionError("configured history used legacy manager")),
    )

    result = service.get_chart_data(
        "OKX", "BTC-USDT-SWAP", "M1", 10, "jwt-subject-a"
    )

    assert result["complete"] is True
    assert result["error_code"] is None
    assert result["total"] == 1
    assert result["bars"] == [
        {
            "date": calls[0].start_time_utc,
            "open": 10.5,
            "high": 12.25,
            "low": 9.5,
            "close": 11.75,
            "volume": 3.125,
        }
    ]
    assert len(calls) == 1 and calls[0].limit == 10


def test_configured_chart_history_failure_does_not_fall_back(monkeypatch):
    service = _quote_service(monkeypatch)
    key = _history_key()

    class _Directory:
        def has_configured_history_symbol(self, *_args):
            return True

        def configured_history_key(self, *_args):
            return key

        def read_history_page(self, *_args):
            raise ServiceMarketDeploymentError("HISTORY_UNAVAILABLE")

    service._service_market_loaded = True
    service._service_market_deployment = _Directory()
    service._service_market_error = None
    service._service_market_load_lock = threading.Lock()
    monkeypatch.setattr(
        service,
        "_get_live_trading_manager",
        lambda: (_ for _ in ()).throw(AssertionError("configured history used legacy manager")),
    )

    result = service.get_chart_data(
        "OKX", "BTC-USDT-SWAP", "M1", 10, "jwt-subject-a"
    )

    assert result["bars"] == []
    assert result["complete"] is False
    assert result["error_code"] == "HISTORY_UNAVAILABLE"


def test_unconfigured_chart_history_preserves_legacy_route(monkeypatch):
    service = _quote_service(monkeypatch)

    class _Directory:
        def has_configured_history_symbol(self, *_args):
            return False

    service._service_market_loaded = True
    service._service_market_deployment = _Directory()
    service._service_market_error = None
    service._service_market_load_lock = threading.Lock()
    config = SimpleNamespace(command_endpoint="tcp://127.0.0.1:5500")
    monkeypatch.setattr(service, "_get_live_trading_manager", lambda: object())
    monkeypatch.setattr(service, "_find_gateway_config", lambda *_args: config)
    command_calls = []

    def send_command(endpoint, operation, arguments, **kwargs):
        command_calls.append((endpoint, operation, arguments, kwargs))
        return [{"datetime": "2026-01-01T00:00:00Z", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 3}]

    monkeypatch.setattr(service, "_send_gateway_command", send_command)

    result = service.get_chart_data(
        "OKX", "BTC-USDT-SWAP", "M1", 10, "jwt-subject-a"
    )

    assert result["bars"][0]["close"] == 2.0
    assert command_calls[0][1] == "get_bars"
