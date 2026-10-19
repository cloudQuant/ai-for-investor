"""Quote HTTP path over a real local SDK Host and synthetic market provider."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import zmq
from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_gateway.market_hub import GatewayMarketHub
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

_SERVICE_ID = "afi-okx-market-service"
_INSTANCE_ID = "afi-okx-market-hub"
_SCOPE_REF = "afi-okx-market-public-v1"
_TRANSPORT_REF = "afi-okx-market-transport-v1"
_SECURITY_REF = "afi-okx-market-curve-v1"
_DOMAIN_REF = "afi-market-public-domain"
_SUBJECT = "afi-market-ui-subject"
_PRINCIPAL = "afi-market-ui-principal"
_APPLICATION = "afi-market-ui-application"
_SERVICE_PRINCIPAL = "afi-okx-market-service-principal"
_SYMBOL = "BTC-USDT-SWAP"
_KEY = MarketSubscriptionKey(
    source_ref="okx-public-market-r1",
    entitlement_ref="public-ticker-r1",
    instrument=MarketInstrumentKey(
        provider="okx",
        venue="OKX",
        environment="live",
        product_type="SWAP",
        instrument_id=_SYMBOL,
        native_symbol=_SYMBOL,
    ),
    channel="tickers",
)
_OPERATIONS = frozenset(
    {
        "market.subscribe",
        "market.unsubscribe",
        "market.snapshot",
        "market.head",
        "market.read_after",
    }
)


def _free_endpoints() -> tuple[str, str]:
    sockets: list[socket.socket] = []
    try:
        values = []
        for _ in range(2):
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", 0))
            sockets.append(probe)
            values.append(f"tcp://127.0.0.1:{probe.getsockname()[1]}")
        return values[0], values[1]
    finally:
        for probe in sockets:
            probe.close()


def _service_config(rpc_bind: str, market_bind: str) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _SERVICE_ID,
        "scope_ref": _SCOPE_REF,
        "transport_ref": _TRANSPORT_REF,
        "registration_policy_ref": "afi-market-host-registration-v1",
        "service_requirements_ref": "afi-market-host-requirements-v1",
        "components": {
            "gateway": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _INSTANCE_ID,
                    "bind_ports": ["service.market_source"],
                    "options": {"role": "market_hub"},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": rpc_bind, "market_bind": market_bind},
                    "security_profile_ref": _SECURITY_REF,
                    "options": {"high_water_mark": 128, "max_message_bytes": 262_144},
                }
            },
        },
    }


def _market_projection() -> dict[str, Any]:
    return {
        "exchange_name": "OKX",
        "symbol": _SYMBOL,
        "instrument_id": _SYMBOL,
        "asset_type": "SWAP",
        "timestamp": time.time(),
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


class _SyntheticTickerProvider:
    def __init__(self) -> None:
        self.hub: GatewayMarketHub | None = None
        self.generation: str | None = None
        self.active_handle: tuple[str, int, str] | None = None
        self.starts = 0
        self.stops = 0
        self._last_publish = 0.0

    def subscribe(self, key: MarketSubscriptionKey, *, generation: str) -> object:
        if key != _KEY or not generation:
            raise AssertionError("unexpected synthetic market subscription")
        self.starts += 1
        self.generation = generation
        self.active_handle = ("afi-synthetic-okx-ticker", self.starts, generation)
        return self.active_handle

    def _is_active_handle(self, handle: object) -> bool:
        active_handle = self.active_handle
        return (
            active_handle is not None
            and isinstance(handle, tuple)
            and len(handle) == 3
            and type(handle[0]) is str
            and type(handle[1]) is int
            and type(handle[2]) is str
            and handle == active_handle
            and handle[2] == self.generation
        )

    def unsubscribe(self, handle: object) -> bool:
        if not self._is_active_handle(handle):
            raise AssertionError("unexpected synthetic market handle")
        self.stops += 1
        self.generation = None
        self.active_handle = None
        return True

    def poll(self, handle: object, *, limit: int) -> tuple[object, ...]:
        if not self._is_active_handle(handle):
            raise AssertionError("unexpected synthetic market poll handle")
        if type(limit) is not int or limit < 1:
            raise AssertionError("market hub must request a positive bounded poll")
        return ()

    def publish_if_due(self) -> None:
        if self.hub is None or self.generation is None:
            return
        now = time.monotonic()
        if now - self._last_publish < 0.05:
            return
        self._last_publish = now
        sent_at = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        self.hub.publish(
            _KEY,
            _market_projection(),
            sent_at,
            generation=self.generation,
        )


def _market_deployment(
    rpc_connect: str,
    market_connect: str,
    server_public: bytes,
    client_public: bytes,
    client_secret: bytes,
) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "subjects": [
                {
                    "subject": _SUBJECT,
                    "identity": {
                        "principal_ref": _PRINCIPAL,
                        "actor_ref": _APPLICATION,
                        "delegate_ref": None,
                    },
                    "client_config": {
                        "client_config_schema_version": 1,
                        "process_role": "application_client",
                        "registration": {"application_ref": _APPLICATION},
                        "clients": {
                            "gateway": {
                                "config_schema_version": 1,
                                "settings": {
                                    "bindings": [
                                        {
                                            "mount": "application.market",
                                            "service_id": _SERVICE_ID,
                                            "instance_id": _INSTANCE_ID,
                                            "scope_ref": _SCOPE_REF,
                                            "transport_ref": "afi-market-client-v1",
                                        }
                                    ],
                                    "options": {"request_timeout_ms": 1_000},
                                },
                            }
                        },
                        "communication": {
                            "config_schema_version": 1,
                            "profiles": {
                                "afi-market-client-v1": {
                                    "backend": "zmq",
                                    "config_schema_version": 1,
                                    "endpoints": {
                                        "rpc_connect": rpc_connect,
                                        "market_connect": market_connect,
                                    },
                                    "security_profile_ref": _SECURITY_REF,
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
                        _SCOPE_REF: {"execution_domain_ref": _DOMAIN_REF}
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
                            "public_key": client_public.decode("ascii"),
                            "secret_key": client_secret.decode("ascii"),
                        }
                    },
                    "market_bindings": [
                        {"source": "OKX", "symbol": _SYMBOL, "key": _KEY.to_dict()}
                    ],
                }
            ],
        },
        separators=(",", ":"),
    )


def test_quote_http_route_reads_real_service_market_client_and_host(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    from fastapi import FastAPI

    import app.api.quote as quote_api
    from app.services.quote_service import QuoteService

    rpc_bind, market_bind = _free_endpoints()
    server_public, server_secret = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    service_identity = WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID)
    service_scope = WireScope(_DOMAIN_REF)
    application_identity = WireIdentity(WireRole.APPLICATION_CLIENT, _PRINCIPAL, _APPLICATION)
    provider = _SyntheticTickerProvider()
    stop_host = threading.Event()
    host_ready = threading.Event()
    host_errors: list[str] = []
    host_facts: dict[str, Any] = {}

    authority = TrustedServiceAuthority(
        identity=service_identity,
        scope=service_scope,
        scope_ref=_SCOPE_REF,
        scope_version="afi-market-host-scope-r1",
        security_ref=_SECURITY_REF,
        security_version="afi-market-host-curve-r1",
        registration_policy_ref="afi-market-host-registration-v1",
        registration_policy_version="afi-market-host-policy-r1",
        service_requirements_ref="afi-market-host-requirements-v1",
        service_requirements_version="afi-market-host-requirements-r1",
        curve_public_key=server_public,
        curve_secret_key=server_secret,
        principals={client_public: _PRINCIPAL},
        grants={
            _PRINCIPAL: (
                PrincipalGrant(
                    application_identity,
                    (
                        ResourceGrant(
                            _INSTANCE_ID,
                            "service.market_source",
                            _SCOPE_REF,
                            service_scope,
                            _OPERATIONS,
                        ),
                    ),
                ),
            )
        },
    )

    def host_owner() -> None:
        host = None
        hub: GatewayMarketHub | None = None
        try:
            config = parse_service_config(_service_config(rpc_bind, market_bind))

            def resource_provider(component, _instance_id, _options, _scope):
                nonlocal hub
                if component != "gateway":
                    raise AssertionError("unexpected component")
                hub = GatewayMarketHub(
                    provider,
                    key_universe=frozenset({_KEY}),
                    principal_allowed_keys={_PRINCIPAL: frozenset({_KEY})},
                    service_identity=service_identity,
                    service_scope=service_scope,
                )
                provider.hub = hub
                return ComponentResources.owned(
                    {"hub": hub},
                    ready=lambda: hub.ready,
                    close=hub.close,
                )

            host = ServiceHost(
                config,
                authority,
                str(tmp_path / "afi-service-market-host.sqlite3"),
                resource_provider,
            )
            host.start()
            host_facts["market_endpoint"] = host.market_endpoint
            host_ready.set()
            while not stop_host.is_set():
                host.serve_once(10)
                provider.publish_if_due()
            host.close()
            host_facts["state"] = host.state
            host_facts["active_registrations"] = host.summary["market"][
                "active_registrations"
            ]
        except BaseException as error:
            host_errors.append(str(getattr(error, "code", type(error).__name__)))
            host_ready.set()
            if host is not None and host.state not in {"closed", "failed"}:
                try:
                    host.close()
                except BaseException:
                    pass
        finally:
            if hub is not None:
                provider.hub = hub

    host_thread = threading.Thread(target=host_owner, name="afi-market-test-host", daemon=False)
    host_thread.start()
    service = None
    try:
        assert host_ready.wait(10), "synthetic ServiceHost did not start"
        assert not host_errors, host_errors
        market_endpoint = host_facts.get("market_endpoint")
        # ServiceHost binds the endpoint selected in the validated service config.
        if market_endpoint is None:
            market_endpoint = market_bind
        monkeypatch.setenv(
            "SERVICE_MARKET_DEPLOYMENT_JSON",
            _market_deployment(
                rpc_bind,
                market_endpoint,
                server_public,
                client_public,
                client_secret,
            ),
        )

        QuoteService._instance = None
        service = QuoteService()
        monkeypatch.setattr(service, "_get_live_trading_manager", lambda: None)
        monkeypatch.setattr(service, "_get_running_workspace_context", lambda *args, **kwargs: {})
        monkeypatch.setattr(
            service,
            "_get_default_symbols_for_source",
            lambda _source: [
                {"symbol": _SYMBOL, "name": "BTC", "exchange": "OKX", "category": "crypto"}
            ],
        )

        class _Database:
            async def execute(self, *_args):
                return SimpleNamespace(all=lambda: [])

        async def get_db_override():
            yield _Database()

        app = FastAPI()
        app.include_router(quote_api.router, prefix="/api/v1/quote")
        app.dependency_overrides[quote_api.get_current_user] = lambda: SimpleNamespace(
            sub=_SUBJECT
        )
        app.dependency_overrides[quote_api.get_db] = get_db_override
        app.dependency_overrides[quote_api.get_quote_service] = lambda: service

        async def request_quote():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.get(
                    "/api/v1/quote/ticks",
                    params={"source": "OKX", "symbols": _SYMBOL},
                )

        response = asyncio.run(request_quote())
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["refresh_mode"] == "push", {
            "body": body,
            "deployment_error": service._service_market_error,
            "provider_starts": provider.starts,
        }
        tick = body["ticks"][0]
        assert tick["gateway_key"] == "service-market"
        assert tick["symbol"] == _SYMBOL
        assert tick["last_price"] == 67_001.5
        assert tick["bid_price"] == 67_001.4
        assert tick["ask_price"] == 67_001.6
        assert tick["volume"] == 123.0
        assert tick["status"] == "normal"
        assert provider.starts == 1
        active_handle = provider.active_handle
        assert active_handle is not None
        assert provider._is_active_handle(active_handle)
        assert not provider._is_active_handle(active_handle[:2])
        assert not provider._is_active_handle(
            (active_handle[0], active_handle[1] + 1, active_handle[2])
        )
        assert not provider._is_active_handle(
            (active_handle[0], active_handle[1], "stale-generation")
        )

        first_deployment = service._service_market_deployment
        assert first_deployment is not None
        service.shutdown()
        assert service._service_market_deployment is None
        assert service._service_market_loaded is False
        assert service._service_market_error is None

        restarted_response = asyncio.run(request_quote())
        assert restarted_response.status_code == 200, restarted_response.text
        restarted_body = restarted_response.json()
        assert restarted_body["total"] == 1
        restarted_tick = restarted_body["ticks"][0]
        assert restarted_tick["gateway_key"] == "service-market"
        assert restarted_tick["symbol"] == _SYMBOL
        assert restarted_tick["last_price"] == 67_001.5
        assert restarted_tick["status"] == "normal"
        second_deployment = service._service_market_deployment
        assert second_deployment is not None
        assert second_deployment is not first_deployment
        assert service._service_market_loaded is True
        assert provider.starts == 2
    finally:
        if service is not None:
            service.shutdown()
        stop_host.set()
        host_thread.join(timeout=10)
        assert not host_thread.is_alive(), "synthetic ServiceHost owner did not stop"
        assert not host_errors, host_errors
        assert host_facts.get("state") == "closed"
        assert host_facts.get("active_registrations") == 0
        assert provider.starts == provider.stops
