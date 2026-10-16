"""AFI chart history over the explicitly operated service-v2 Market Hub.

The history provider is a synthetic leaf; AFI's chart route, owner-thread
ServiceMarketClient, operator lifecycle, Gateway Hub, ServiceHost, RPC and
CURVE transport are the production implementations.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import zmq
from bt_api_base.market_history_protocol import (
    MarketBar,
    MarketHistoryPage,
    MarketHistoryRequest,
)
from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_py import gateway_operator_application as operator_sdk
from bt_api_py.gateway_operator import GatewayMarketBinding, GatewayOperatorDeployment
from bt_api_py.service_config import parse_service_config
from bt_api_py.service_host import TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

_SERVICE_ID = "afi-history-operator-service"
_INSTANCE_ID = "afi-history-operator-hub"
_SCOPE_REF = "afi-history-operator-scope-v1"
_TRANSPORT_REF = "afi-history-operator-transport-v1"
_SECURITY_REF = "afi-history-operator-curve-v1"
_DOMAIN_REF = "afi-history-operator-public-domain"
_SUBJECT = "afi-history-ui-subject"
_PRINCIPAL = "afi-history-ui-principal"
_APPLICATION = "afi-history-ui-application"
_SERVICE_PRINCIPAL = "afi-history-service-principal"
_SYMBOL = "BTC-USDT-SWAP"
_TICKER_KEY = MarketSubscriptionKey(
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
_BAR_KEY = MarketSubscriptionKey(
    source_ref="okx-public-market-r1",
    entitlement_ref="public-history-r1",
    instrument=MarketInstrumentKey(
        provider="okx",
        venue="OKX",
        environment="live",
        product_type="SWAP",
        instrument_id=_SYMBOL,
        native_symbol=_SYMBOL,
    ),
    channel="bar",
    timeframe="1m",
)
_HISTORY_OPERATIONS = frozenset({"market.history"})


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
        "registration_policy_ref": "afi-history-operator-policy-v1",
        "service_requirements_ref": "afi-history-operator-requirements-v1",
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


def _market_client_deployment(
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
                                            "transport_ref": "afi-history-market-client-v1",
                                        }
                                    ],
                                    "options": {"request_timeout_ms": 5_000},
                                },
                            }
                        },
                        "communication": {
                            "config_schema_version": 1,
                            "profiles": {
                                "afi-history-market-client-v1": {
                                    "backend": "zmq",
                                    "config_schema_version": 1,
                                    "endpoints": {
                                        "rpc_connect": rpc_connect,
                                        "market_connect": market_connect,
                                    },
                                    "security_profile_ref": _SECURITY_REF,
                                    "options": {
                                        "request_timeout_ms": 5_000,
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
                    # The bar ACL is a separate audience; it is not inserted
                    # into live ticker bindings or granted a SUB operation.
                    "market_bindings": [],
                    "history_bindings": [
                        {
                            "source": "OKX",
                            "symbol": _SYMBOL,
                            "timeframe": "1m",
                            "key": _BAR_KEY.to_dict(),
                        }
                    ],
                }
            ]
        },
        separators=(",", ":"),
    )


def _operator_control_deployment() -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "operators": [
                {
                    "profile_ref": "afi-history-market-profile",
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


class _SyntheticStreamProvider:
    def __init__(self) -> None:
        self.subscribe_calls = 0
        self.unsubscribe_calls = 0

    def subscribe(self, key: MarketSubscriptionKey, *, generation: str) -> object:
        self.subscribe_calls += 1
        return (key, generation)

    def unsubscribe(self, handle: object) -> bool:
        self.unsubscribe_calls += 1
        return True


class _SyntheticHistoryProvider:
    def __init__(self) -> None:
        self.fetch_calls: list[tuple[int, MarketHistoryRequest, float]] = []
        self.close_calls = 0

    def fetch(
        self, request: MarketHistoryRequest, timeout_seconds: float
    ) -> MarketHistoryPage:
        self.fetch_calls.append((threading.get_ident(), request, timeout_seconds))
        assert request.key == _BAR_KEY
        start = datetime.fromisoformat(request.start_time_utc.replace("Z", "+00:00"))
        end = datetime.fromisoformat(request.end_time_utc.replace("Z", "+00:00"))
        close = start + timedelta(minutes=1)
        bars = (
            MarketBar(
                request.start_time_utc,
                close.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "10.5",
                "12.25",
                "9.5",
                "11.75",
                "3.125",
            ),
        )
        return MarketHistoryPage(
            request=request,
            bars=bars,
            complete=True,
            next_start_time_utc=None,
            observed_at_utc=max(datetime.now(UTC), end).isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z"),
        )

    def close(self) -> None:
        self.close_calls += 1


@pytest.mark.integration
def test_quote_chart_uses_explicit_operator_history_only_service_path(
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
    provider_rows: list[_SyntheticStreamProvider] = []
    history_rows: list[_SyntheticHistoryProvider] = []
    deployment_threads: list[int] = []
    deployments: list[GatewayOperatorDeployment] = []

    config = parse_service_config(_service_config(rpc_bind, market_bind))
    authority = TrustedServiceAuthority(
        identity=service_identity,
        scope=service_scope,
        scope_ref=_SCOPE_REF,
        scope_version="afi-history-market-scope-v1",
        security_ref=_SECURITY_REF,
        security_version="afi-history-market-curve-v1",
        registration_policy_ref=config.registration_policy_ref,
        registration_policy_version="afi-history-operator-policy-v1",
        service_requirements_ref=config.service_requirements_ref,
        service_requirements_version="afi-history-operator-requirements-v1",
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
                            _HISTORY_OPERATIONS,
                        ),
                    ),
                ),
            )
        },
    )

    def stream_provider_factory() -> _SyntheticStreamProvider:
        provider = _SyntheticStreamProvider()
        provider_rows.append(provider)
        return provider

    def history_provider_factory() -> _SyntheticHistoryProvider:
        history = _SyntheticHistoryProvider()
        history_rows.append(history)
        return history

    def deployment_factory() -> GatewayOperatorDeployment:
        deployment_threads.append(threading.get_ident())
        deployment = GatewayOperatorDeployment(
            config,
            authority,
            tmp_path / "afi-history-market.sqlite3",
            resource_provider=lambda *_args: pytest.fail(
                "market role must use the SDK operator's production factory"
            ),
            market_binding=GatewayMarketBinding(
                key_universe=(_TICKER_KEY,),
                principal_allowed_keys={_PRINCIPAL: frozenset({_TICKER_KEY})},
                provider_factory=stream_provider_factory,
                history_key_universe=(_BAR_KEY,),
                principal_allowed_history_keys={
                    _PRINCIPAL: frozenset({_BAR_KEY})
                },
                history_provider_factory=history_provider_factory,
                history_timeout_seconds=2.0,
            ),
        )
        deployments.append(deployment)
        return deployment

    profile_ref = "afi-history-market-profile"
    registry = operator_sdk.GatewayOperatorProfileRegistry(
        (
            operator_sdk.GatewayOperatorProfile(
                profile_ref,
                "market_hub",
                deployment_factory,
            ),
        )
    )
    control = ServiceGatewayOperatorControl.from_value(
        _operator_control_deployment(),
        profile_registry=registry,
    )
    assert control is not None

    service = None
    try:
        monkeypatch.setenv(
            "SERVICE_MARKET_DEPLOYMENT_JSON",
            _market_client_deployment(
                rpc_bind,
                market_bind,
                server_public,
                client_public,
                client_secret,
            ),
        )
        QuoteService._instance = None
        service = QuoteService()
        monkeypatch.setattr(
            service,
            "_get_live_trading_manager",
            lambda: pytest.fail("configured chart history used legacy GatewayRuntime"),
        )

        class _OwnerDatabase:
            async def execute(self, *_args):
                return SimpleNamespace(all=lambda: [])

        async def database_override():
            yield _OwnerDatabase()

        app = FastAPI()
        app.state.service_gateway_operator_control = control
        app.include_router(operator_api.router, prefix="/api/v1")
        app.include_router(quote_api.router, prefix="/api/v1/quote")
        app.dependency_overrides[quote_api.get_current_user] = lambda: SimpleNamespace(
            sub=_SUBJECT
        )
        app.dependency_overrides[require_persisted_owner_scope] = lambda: PersistedOwnerScope(
            _SUBJECT,
            "HUMAN",
        )
        app.dependency_overrides[quote_api.get_db] = database_override
        app.dependency_overrides[quote_api.get_quote_service] = lambda: service

        async def exercise_http_routes() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                status_before = await client.get(
                    f"/api/v1/service-gateway/operators/{profile_ref}"
                )
                assert status_before.status_code == 200, status_before.text
                assert status_before.json()["state"] == "new"
                assert deployments == [], "status must not create or start the operator"

                started = await client.post(
                    f"/api/v1/service-gateway/operators/{profile_ref}/start"
                )
                if started.status_code != 200:
                    failed_status = await client.get(
                        f"/api/v1/service-gateway/operators/{profile_ref}"
                    )
                    pytest.fail(
                        f"operator start returned {started.status_code}: {started.text}; "
                        f"finite status: {failed_status.text}"
                    )
                assert started.json()["state"] == "running"

                chart = await client.get(
                    "/api/v1/quote/chart",
                    params={
                        "source": "OKX",
                        "symbol": _SYMBOL,
                        "timeframe": "M1",
                        "count": 10,
                    },
                )
                return status_before, started, chart

        _status, _started, chart_response = asyncio.run(exercise_http_routes())
        assert chart_response.status_code == 200, chart_response.text
        result = chart_response.json()
        assert result["complete"] is True
        assert result["error_code"] is None
        assert result["total"] == 1
        assert result["bars"][0]["open"] == 10.5
        assert result["bars"][0]["high"] == 12.25
        assert result["bars"][0]["low"] == 9.5
        assert result["bars"][0]["close"] == 11.75
        assert result["bars"][0]["volume"] == 3.125

        assert len(deployments) == 1
        deployment = deployments[0]
        application = control._applications[profile_ref]
        assert deployment_threads == [deployment._owner_thread_id]
        assert application._thread is not None
        assert application._thread.ident == deployment_threads[0]
        assert deployment.state == "started"
        assert len(history_rows) == 1
        assert len(history_rows[0].fetch_calls) == 1
        history_thread, request, timeout_seconds = history_rows[0].fetch_calls[0]
        assert history_thread == deployment._owner_thread_id
        assert request.key == _BAR_KEY
        assert request.limit == 10
        assert timeout_seconds == 2.0
        assert len(provider_rows) == 1
        assert provider_rows[0].subscribe_calls == 0, "history-only access must not SUB"

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
        assert history_rows[0].close_calls == 1
    finally:
        if service is not None:
            service.shutdown()
        control.close()
