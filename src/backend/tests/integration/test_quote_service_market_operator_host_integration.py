"""AFI quote consumer over the configured service-v2 operator composition.

The exchange WebSocket leaf is synthetic; operator, OKX queue adapter, Hub,
ServiceHost, ServiceMarketClient, AFI projection, and HTTP route are real.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from types import SimpleNamespace
from typing import Any

import bt_api_py.gateway_operator_application as operator_sdk
import httpx
import pytest
import zmq
from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_okx.containers.tickers import OkxTickerData
from bt_api_okx.market_provider import BoundedOkxTickerQueue
from bt_api_py.gateway_operator import (
    GatewayOkxMarketBinding,
    GatewayOperatorDeployment,
)
from bt_api_py.service_config import parse_service_config
from bt_api_py.service_host import TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

_SERVICE_ID = "afi-operator-market-service"
_INSTANCE_ID = "afi-operator-market-hub"
_SCOPE_REF = "afi-operator-market-scope-v1"
_TRANSPORT_REF = "afi-operator-market-transport-v1"
_SECURITY_REF = "afi-operator-market-curve-v1"
_DOMAIN_REF = "afi-operator-market-public-domain"
_SUBJECT = "afi-operator-market-ui-subject"
_PRINCIPAL = "afi-operator-market-ui-principal"
_APPLICATION = "afi-operator-market-ui-application"
_SERVICE_PRINCIPAL = "afi-operator-market-service-principal"
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
_MARKET_OPERATIONS = frozenset(
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
        endpoints = []
        for _ in range(2):
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", 0))
            sockets.append(probe)
            endpoints.append(f"tcp://127.0.0.1:{probe.getsockname()[1]}")
        return endpoints[0], endpoints[1]
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
        "registration_policy_ref": "afi-operator-market-policy-v1",
        "service_requirements_ref": "afi-operator-market-requirements-v1",
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
                                            "transport_ref": "afi-operator-market-client-v1",
                                        }
                                    ],
                                    "options": {"request_timeout_ms": 1_000},
                                },
                            }
                        },
                        "communication": {
                            "config_schema_version": 1,
                            "profiles": {
                                "afi-operator-market-client-v1": {
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
                    "scope_claims": {_SCOPE_REF: {"execution_domain_ref": _DOMAIN_REF}},
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


def _operator_deployment() -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "operators": [
                {
                    "profile_ref": "afi-operator-market-profile",
                    "account_ref": None,
                    "authorized_subjects": [_SUBJECT],
                    "operations": ["status", "start", "stop"],
                    "auto_start": False,
                    "legacy_gateway_keys": [],
                }
            ],
        },
        separators=(",", ":"),
    )


class _SyntheticOkxStream:
    def __init__(self, sink: BoundedOkxTickerQueue) -> None:
        self._sink = sink
        self.started = False
        self.stop_calls = 0

    def start(self, *, connect_timeout: float) -> None:
        assert connect_timeout == 1.0
        self.started = True
        self._sink.put(
            OkxTickerData(
                {
                    "instType": "SWAP",
                    "instId": _SYMBOL,
                    "last": "67001.5",
                    "bidPx": "67001.4",
                    "askPx": "67001.6",
                    "bidSz": "2",
                    "askSz": "3",
                    "vol24h": "123",
                    "volCcy24h": "8250000",
                    "open24h": "66500",
                    "high24h": "68000",
                    "low24h": "66000",
                    "ts": str(int(time.time() * 1000)),
                },
                _SYMBOL,
                "SWAP",
                has_been_json_encoded=True,
            )
        )

    def stop(self) -> None:
        self.stop_calls += 1


@pytest.mark.integration
def test_quote_http_route_uses_operator_okx_queue_and_service_market_client(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import FastAPI

    import app.api.quote as quote_api
    import app.api.service_gateway_operator as operator_api
    from app.api.afi_owner_scope import PersistedOwnerScope, require_persisted_owner_scope
    from app.services.quote_service import QuoteService
    from app.services.service_gateway_operator import ServiceGatewayOperatorControl

    rpc_bind, market_bind = _free_endpoints()
    server_public, server_secret = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    service_identity = WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID)
    service_scope = WireScope(_DOMAIN_REF)
    application_identity = WireIdentity(WireRole.APPLICATION_CLIENT, _PRINCIPAL, _APPLICATION)
    streams: list[_SyntheticOkxStream] = []

    def stream_factory(
        key: MarketSubscriptionKey, ticker_queue: BoundedOkxTickerQueue
    ) -> _SyntheticOkxStream:
        assert key == _KEY
        stream = _SyntheticOkxStream(ticker_queue)
        streams.append(stream)
        return stream

    config = parse_service_config(_service_config(rpc_bind, market_bind))
    authority = TrustedServiceAuthority(
        identity=service_identity,
        scope=service_scope,
        scope_ref=_SCOPE_REF,
        scope_version="afi-operator-market-scope-v1",
        security_ref=_SECURITY_REF,
        security_version="afi-operator-market-curve-v1",
        registration_policy_ref=config.registration_policy_ref,
        registration_policy_version="afi-operator-market-policy-v1",
        service_requirements_ref=config.service_requirements_ref,
        service_requirements_version="afi-operator-market-requirements-v1",
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
                            _MARKET_OPERATIONS,
                        ),
                    ),
                ),
            )
        },
    )
    deployment_factory_threads: list[int] = []
    deployments: list[GatewayOperatorDeployment] = []

    def deployment_factory() -> GatewayOperatorDeployment:
        deployment_factory_threads.append(threading.get_ident())
        deployment = GatewayOperatorDeployment(
            config,
            authority,
            tmp_path / "afi-operator-market.sqlite3",
            resource_provider=lambda *_args: pytest.fail(
                "market role must use the SDK operator's production factory"
            ),
            okx_market=GatewayOkxMarketBinding(
                key_universe=(_KEY,),
                principal_allowed_keys={_PRINCIPAL: frozenset({_KEY})},
                stream_factory=stream_factory,
                connect_timeout_seconds=1.0,
            ),
        )
        deployments.append(deployment)
        return deployment

    profile_ref = "afi-operator-market-profile"
    profile = operator_sdk.GatewayOperatorProfile(
        profile_ref,
        "market_hub",
        deployment_factory,
    )
    profile_registry = operator_sdk.GatewayOperatorProfileRegistry((profile,))
    control = ServiceGatewayOperatorControl.from_value(
        _operator_deployment(),
        profile_registry=profile_registry,
    )
    assert control is not None
    service = None
    try:
        monkeypatch.setenv(
            "SERVICE_MARKET_DEPLOYMENT_JSON",
            _market_deployment(
                rpc_bind,
                market_bind,
                server_public,
                client_public,
                client_secret,
            ),
        )

        QuoteService._instance = None
        service = QuoteService()
        monkeypatch.setattr(service, "_get_live_trading_manager", lambda: None)
        monkeypatch.setattr(service, "_get_running_workspace_context", lambda *_a, **_k: {})
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
        app.state.service_gateway_operator_control = control
        app.include_router(operator_api.router, prefix="/api/v1")
        app.include_router(quote_api.router, prefix="/api/v1/quote")
        app.dependency_overrides[quote_api.get_current_user] = lambda: SimpleNamespace(sub=_SUBJECT)
        app.dependency_overrides[require_persisted_owner_scope] = lambda: PersistedOwnerScope(
            _SUBJECT,
            "HUMAN",
        )
        app.dependency_overrides[quote_api.get_db] = get_db_override
        app.dependency_overrides[quote_api.get_quote_service] = lambda: service

        async def request_quote_after_explicit_start():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                status_response = await client.get(
                    f"/api/v1/service-gateway/operators/{profile_ref}"
                )
                assert status_response.status_code == 200, status_response.text
                assert status_response.json()["state"] == "new"
                assert status_response.json()["ready"] is False
                assert deployments == [], "status must not construct or start an operator"

                start_response = await client.post(
                    f"/api/v1/service-gateway/operators/{profile_ref}/start"
                )
                assert start_response.status_code == 200, start_response.text
                assert start_response.json()["state"] == "running"
                assert start_response.json()["ready"] is True

                return await client.get(
                    "/api/v1/quote/ticks",
                    params={"source": "OKX", "symbols": _SYMBOL},
                )

        response = asyncio.run(request_quote_after_explicit_start())
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["refresh_mode"] == "push"
        tick = body["ticks"][0]
        assert tick["gateway_key"] == "service-market"
        assert tick["symbol"] == _SYMBOL
        assert tick["last_price"] == 67_001.5
        assert tick["bid_price"] == 67_001.4
        assert tick["ask_price"] == 67_001.6
        assert tick["volume"] == 123.0
        assert tick["status"] == "normal"
        assert len(streams) == 1 and streams[0].started
        assert len(deployments) == 1
        deployment = deployments[0]
        application = control._applications[profile_ref]
        assert deployment_factory_threads == [deployment._owner_thread_id]
        assert application._thread is not None
        assert application._thread.ident == deployment_factory_threads[0]
        assert deployment.state == "started"

        assert service.shutdown() is True
        service = None

        async def stop_operator() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.post(
                    f"/api/v1/service-gateway/operators/{profile_ref}/stop"
                )

        stop_response = asyncio.run(stop_operator())
        assert stop_response.status_code == 200, stop_response.text
        assert stop_response.json()["state"] == "closed"
        assert application.status["state"] == "closed"
        assert application._thread is not None and not application._thread.is_alive()
        assert deployment.state == "closed"
        assert streams[0].stop_calls == 1
    finally:
        if service is not None:
            service.shutdown()
        control.close()
