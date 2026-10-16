"""Focused AFI surface checks for trusted SDK Gateway operator ownership."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from typing import Any

import bt_api_py.gateway_operator_application as operator_sdk
import httpx
from fastapi import FastAPI

import app.main as main_module
import app.services.quote_service as quote_service_module
from app.api.afi_owner_scope import (
    PersistedOwnerScope,
    require_persisted_owner_scope,
)
from app.api.service_gateway_operator import router
from app.services.live_trading import manager as live_manager_module
from app.services.live_trading.service_gateway_operator_guard import (
    is_legacy_manual_gateway_excluded,
)
from app.services.quote.service_market import ServiceMarketDeploymentError
from app.services.quote_service import QuoteService
from app.services.service_gateway_operator import ServiceGatewayOperatorControl

_OWNER = "operator-owner-1"
_ACCOUNT_PROFILE = "test.account-session"
_MARKET_PROFILE = "test.market-hub"


class _ProfileRegistry:
    def __init__(self) -> None:
        self._profiles = {
            _ACCOUNT_PROFILE: operator_sdk.GatewayOperatorProfile(
                _ACCOUNT_PROFILE,
                "account_session_worker",
                lambda: None,
            ),
            _MARKET_PROFILE: operator_sdk.GatewayOperatorProfile(
                _MARKET_PROFILE,
                "market_hub",
                lambda: None,
            ),
        }

    def resolve(self, profile_ref: str) -> Any:
        return self._profiles[profile_ref]


class _FakeOperatorApplication:
    created: list[_FakeOperatorApplication]

    def __init__(self, profile: operator_sdk.GatewayOperatorProfile) -> None:
        self.profile = profile
        self.start_calls = 0
        self.stop_calls = 0
        self.cleanup_calls = 0
        self.close_calls = 0
        self._status: dict[str, Any] = {
            "state": "new",
            "role": profile.role,
            "ready": False,
            "error_code": None,
            "operation": {"name": None, "state": "idle", "error_code": None},
            "account_session": None,
            "cleanup": {"unclaimed_provider_count": 0, "last_cleanup_code": None},
        }
        self.created.append(self)

    @property
    def status(self) -> dict[str, Any]:
        return self._status

    def start(self, *, timeout_seconds: float) -> dict[str, Any]:
        assert timeout_seconds == 30.0
        self.start_calls += 1
        self._status = {**self._status, "state": "running", "ready": True}
        return self._status

    def recover_account_session(self, *, timeout_seconds: float) -> dict[str, Any]:
        assert timeout_seconds == 30.0
        return self._status

    def stop(self, *, timeout_seconds: float) -> dict[str, Any]:
        assert timeout_seconds == 30.0
        self.stop_calls += 1
        self._status = {**self._status, "state": "closed", "ready": False}
        return self._status

    def retry_unclaimed_provider_cleanup(self, *, timeout_seconds: float) -> dict[str, Any]:
        assert timeout_seconds == 30.0
        self.cleanup_calls += 1
        return self._status

    def close(self, *, timeout_seconds: float) -> dict[str, Any]:
        assert timeout_seconds == 30.0
        self.close_calls += 1
        self._status = {**self._status, "state": "closed", "ready": False}
        return self._status


def _deployment(*, auto_start_account: bool = False) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "operators": [
                {
                    "profile_ref": _ACCOUNT_PROFILE,
                    "account_ref": "account-1",
                    "authorized_subjects": [_OWNER],
                    "operations": ["status", "start", "stop", "recover", "cleanup"],
                    "auto_start": auto_start_account,
                    "legacy_gateway_keys": ["manual:OKX:account-1"],
                },
                {
                    "profile_ref": _MARKET_PROFILE,
                    "account_ref": None,
                    "authorized_subjects": [_OWNER],
                    "operations": ["status", "start", "stop"],
                    "auto_start": True,
                    "legacy_gateway_keys": [],
                },
            ],
        }
    )


def _control(*, auto_start_account: bool = False) -> ServiceGatewayOperatorControl:
    control = ServiceGatewayOperatorControl.from_value(
        _deployment(auto_start_account=auto_start_account),
        profile_registry=_ProfileRegistry(),
    )
    assert control is not None
    return control


def test_status_page_does_not_start_owner_and_account_start_blocks_legacy_manager(
    monkeypatch,
) -> None:
    _FakeOperatorApplication.created = []
    monkeypatch.setattr(
        operator_sdk,
        "GatewayOperatorApplication",
        _FakeOperatorApplication,
    )
    monkeypatch.setattr(live_manager_module, "get_existing_live_trading_manager", lambda: None)
    control = _control()
    control.protect_configured_legacy_owners()
    assert is_legacy_manual_gateway_excluded("OKX", "account-1")

    connect_calls: list[str] = []

    def unexpected_legacy_connect(**_kwargs: Any) -> dict[str, str]:
        connect_calls.append("called")
        return {"status": "connected"}

    monkeypatch.setattr(
        live_manager_module.manual_gateway_service,
        "connect_gateway",
        unexpected_legacy_connect,
    )
    manager = object.__new__(live_manager_module.LiveTradingManager)
    manager._gateway_lock = threading.RLock()
    manager._gateways = {}
    legacy_result = manager.connect_gateway("OKX", {"account_id": "account-1"})
    assert legacy_result["status"] == "error"
    assert connect_calls == []

    app = FastAPI()
    app.state.service_gateway_operator_control = control
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_persisted_owner_scope] = lambda: PersistedOwnerScope(
        _OWNER,
        "HUMAN",
    )

    async def exercise_http_surface() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            status_response = await client.get(
                f"/api/v1/service-gateway/operators/{_ACCOUNT_PROFILE}"
            )
            assert status_response.status_code == 200
            assert status_response.json()["state"] == "new"
            assert _FakeOperatorApplication.created == []

            ungranted_cleanup = await client.post(
                f"/api/v1/service-gateway/operators/{_MARKET_PROFILE}/cleanup"
            )
            assert ungranted_cleanup.status_code == 403
            assert ungranted_cleanup.json()["detail"]["code"] == "OPERATION_NOT_GRANTED"
            assert _FakeOperatorApplication.created == []

            app.dependency_overrides[require_persisted_owner_scope] = lambda: PersistedOwnerScope(
                "other-owner",
                "HUMAN",
            )
            denied = await client.post(
                f"/api/v1/service-gateway/operators/{_ACCOUNT_PROFILE}/start"
            )
            assert denied.status_code == 403
            assert _FakeOperatorApplication.created == []

            app.dependency_overrides[require_persisted_owner_scope] = lambda: PersistedOwnerScope(
                _OWNER,
                "HUMAN",
            )
            started = await client.post(
                f"/api/v1/service-gateway/operators/{_ACCOUNT_PROFILE}/start"
            )
            assert started.status_code == 200
            assert started.json()["state"] == "running"
            assert len(_FakeOperatorApplication.created) == 1

            _FakeOperatorApplication.created[0]._status = {
                "state": "running",
                "role": "account_session_worker",
                "ready": True,
                "error_code": None,
                "operation": {
                    "name": "start",
                    "state": "succeeded",
                    "error_code": None,
                    "secret": "do-not-project",
                },
                "account_session": {
                    "state": "ready",
                    "session_generation": "generation-1",
                    "ready": True,
                    "fresh_for_seconds": 1.5,
                    "secret": "do-not-project",
                },
                "cleanup": {
                    "unclaimed_provider_count": 0,
                    "last_cleanup_code": None,
                    "secret": "do-not-project",
                },
                "endpoint": "do-not-project",
            }
            sanitized = await client.get(f"/api/v1/service-gateway/operators/{_ACCOUNT_PROFILE}")
            assert sanitized.status_code == 200
            assert set(sanitized.json()) == {
                "profile_ref",
                "account_ref",
                "role",
                "state",
                "ready",
                "error_code",
                "operation",
                "account_session",
                "cleanup",
            }
            assert sanitized.json()["operation"] == {
                "name": "start",
                "state": "succeeded",
                "error_code": None,
            }
            assert sanitized.json()["account_session"] == {
                "state": "ready",
                "session_generation": "generation-1",
                "ready": True,
                "fresh_for_seconds": 1.5,
            }

            cleanup = await client.post(
                f"/api/v1/service-gateway/operators/{_ACCOUNT_PROFILE}/cleanup"
            )
            assert cleanup.status_code == 200
            assert _FakeOperatorApplication.created[0].cleanup_calls == 1

            stopped = await client.post(
                f"/api/v1/service-gateway/operators/{_ACCOUNT_PROFILE}/stop"
            )
            assert stopped.status_code == 200
            assert _FakeOperatorApplication.created[0].stop_calls == 1

    try:
        asyncio.run(exercise_http_surface())
    finally:
        control.close()

    assert not is_legacy_manual_gateway_excluded("OKX", "account-1")
    assert _FakeOperatorApplication.created[0].close_calls == 1


def test_service_v2_start_serializes_with_legacy_manual_connect(monkeypatch) -> None:
    started = threading.Event()
    release_start = threading.Event()
    connect_finished = threading.Event()
    connect_calls: list[str] = []

    class _BlockingApplication(_FakeOperatorApplication):
        def start(self, *, timeout_seconds: float) -> dict[str, Any]:
            assert timeout_seconds == 30.0
            self.start_calls += 1
            started.set()
            assert release_start.wait(timeout=5)
            self._status = {**self._status, "state": "running", "ready": True}
            return self._status

    monkeypatch.setattr(
        operator_sdk,
        "GatewayOperatorApplication",
        _BlockingApplication,
    )
    monkeypatch.setattr(live_manager_module, "get_existing_live_trading_manager", lambda: None)
    manager = object.__new__(live_manager_module.LiveTradingManager)
    manager._gateway_lock = threading.RLock()
    manager._gateways = {}
    manager._normalize_gateway_exchange_type = lambda exchange: str(exchange).upper()
    manager._coerce_bool = lambda value, default=False: bool(value)
    manager._coerce_float = lambda value, default=0.0: float(value or default)
    monkeypatch.setattr(
        live_manager_module,
        "_manual_gateway_account_id_hint",
        lambda _exchange, credentials: str(credentials.get("account_id") or ""),
    )

    def legacy_connect(**_kwargs: Any) -> dict[str, str]:
        connect_calls.append("called")
        return {"status": "connected"}

    monkeypatch.setattr(
        live_manager_module.manual_gateway_service, "connect_gateway", legacy_connect
    )
    control = _control()
    start_error: list[BaseException] = []

    def start_operator() -> None:
        try:
            control.start(_ACCOUNT_PROFILE, _OWNER)
        except BaseException as exc:
            start_error.append(exc)

    operator_thread = threading.Thread(target=start_operator)
    operator_thread.start()
    try:
        assert started.wait(timeout=5)
        legacy_result: list[dict[str, str]] = []

        def connect_legacy() -> None:
            try:
                legacy_result.append(manager.connect_gateway("OKX", {"account_id": "account-1"}))
            finally:
                connect_finished.set()

        connect_thread = threading.Thread(target=connect_legacy)
        connect_thread.start()
        assert not connect_finished.wait(timeout=0.05)
        release_start.set()
        operator_thread.join(timeout=5)
        connect_thread.join(timeout=5)
        assert not operator_thread.is_alive()
        assert not connect_thread.is_alive()
        assert start_error == []
        assert legacy_result[0]["status"] == "error"
        assert connect_calls == []
    finally:
        release_start.set()
        operator_thread.join(timeout=5)
        control.close()


def test_auto_start_uses_only_explicit_profile_flags(monkeypatch) -> None:
    _FakeOperatorApplication.created = []
    monkeypatch.setattr(
        operator_sdk,
        "GatewayOperatorApplication",
        _FakeOperatorApplication,
    )
    monkeypatch.setattr(live_manager_module, "get_existing_live_trading_manager", lambda: None)
    control = _control(auto_start_account=False)
    try:
        control.protect_configured_legacy_owners()
        control.start_auto_profiles()
        assert [item.profile.profile_ref for item in _FakeOperatorApplication.created] == [
            _MARKET_PROFILE
        ]
        assert _FakeOperatorApplication.created[0].start_calls == 1
    finally:
        control.close()


def test_lifespan_starts_only_explicit_profiles_and_closes_quote_before_operator(
    monkeypatch,
) -> None:
    _FakeOperatorApplication.created = []
    order: list[str] = []

    class _OrderedApplication(_FakeOperatorApplication):
        def close(self, *, timeout_seconds: float) -> dict[str, Any]:
            order.append("operator")
            return super().close(timeout_seconds=timeout_seconds)

    class _Secret:
        def get_secret_value(self) -> str:
            return _deployment(auto_start_account=False)

    class _QuoteService:
        def shutdown(self) -> bool:
            order.append("quote")
            return True

    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _no_service_read(*_args: Any, **_kwargs: Any) -> None:
        return None

    class _ShutdownManager:
        async def initiate(self, _app: FastAPI) -> None:
            return None

    settings = type(
        "_Settings",
        (),
        {
            "SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON": _Secret(),
            "PORTFOLIO_VALUATION_BINDINGS_JSON": _Secret(),
            "SERVICE_READ_DEPLOYMENT_JSON": None,
            "RAG_VECTOR_ENABLED": False,
        },
    )()
    monkeypatch.setattr(operator_sdk, "GatewayOperatorApplication", _OrderedApplication)
    monkeypatch.setattr(
        operator_sdk.GatewayOperatorProfileRegistry,
        "from_entry_points",
        classmethod(lambda _cls: _ProfileRegistry()),
    )
    monkeypatch.setattr(live_manager_module, "get_existing_live_trading_manager", lambda: None)
    monkeypatch.setattr(main_module, "settings", settings)
    monkeypatch.setattr(main_module, "configure_service_read", lambda _directory: None)
    monkeypatch.setattr(main_module, "run_startup", _noop)
    monkeypatch.setattr(main_module, "run_shutdown", _noop)
    monkeypatch.setattr(main_module, "start_service_read_deployment", _no_service_read)
    monkeypatch.setattr(
        main_module,
        "PortfolioValuationBindingRegistry",
        type("_Bindings", (), {"from_json": staticmethod(lambda _value: object())}),
    )
    monkeypatch.setattr(main_module, "GracefulShutdownManager", _ShutdownManager)
    monkeypatch.setattr(quote_service_module, "get_quote_service", lambda: _QuoteService())

    app = FastAPI()

    async def exercise_lifespan() -> None:
        async with main_module.lifespan(app):
            assert [item.profile.profile_ref for item in _OrderedApplication.created] == [
                _MARKET_PROFILE
            ]
            assert _OrderedApplication.created[0].start_calls == 1
            assert _OrderedApplication.created[0].close_calls == 0

    asyncio.run(exercise_lifespan())
    assert order == ["quote", "operator"]
    assert _OrderedApplication.created[0].close_calls == 1
    assert app.state.service_gateway_operator_control is None


def test_normal_fastapi_bootstrap_starts_and_closes_real_operator_host(
    tmp_path, monkeypatch
) -> None:
    import zmq
    from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_py.gateway_operator import GatewayOkxMarketBinding, GatewayOperatorDeployment
    from bt_api_py.gateway_operator_application import (
        GatewayOperatorProfile,
        GatewayOperatorProfileRegistry,
    )
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    service_id = "afi-normal-bootstrap-service"
    instance_id = "afi-normal-bootstrap-market"
    scope_ref = "afi-normal-bootstrap-scope"
    transport_ref = "afi-normal-bootstrap-transport"
    security_ref = "afi-normal-bootstrap-curve"
    domain_ref = "afi-normal-bootstrap-domain"
    principal_ref = "afi-normal-bootstrap-client"
    application_ref = "afi-normal-bootstrap-application"
    service_principal_ref = "afi-normal-bootstrap-service-principal"
    profile_ref = "afi-normal-bootstrap-market-profile"
    subject = "afi-normal-bootstrap-owner"
    symbol = "BTC-USDT-SWAP"
    operations = frozenset(
        {
            "market.subscribe",
            "market.unsubscribe",
            "market.snapshot",
            "market.head",
            "market.read_after",
        }
    )
    key = MarketSubscriptionKey(
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

    def _free_endpoint() -> str:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", 0))
            return f"tcp://127.0.0.1:{probe.getsockname()[1]}"
        finally:
            probe.close()

    rpc_bind, market_bind = _free_endpoint(), _free_endpoint()
    server_public, server_secret = zmq.curve_keypair()
    client_public, _client_secret = zmq.curve_keypair()
    config = parse_service_config(
        {
            "service_config_schema_version": 1,
            "process_role": "service",
            "service_id": service_id,
            "scope_ref": scope_ref,
            "transport_ref": transport_ref,
            "registration_policy_ref": "afi-normal-bootstrap-policy",
            "service_requirements_ref": "afi-normal-bootstrap-requirements",
            "components": {
                "gateway": {
                    "config_schema_version": 2,
                    "settings": {
                        "instance_id": instance_id,
                        "bind_ports": ["service.market_source"],
                        "options": {"role": "market_hub"},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    transport_ref: {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_bind": rpc_bind, "market_bind": market_bind},
                        "security_profile_ref": security_ref,
                        "options": {
                            "high_water_mark": 128,
                            "max_message_bytes": 262_144,
                        },
                    }
                },
            },
        }
    )
    scope = WireScope(domain_ref)
    authority = TrustedServiceAuthority(
        identity=WireIdentity(WireRole.SERVICE, service_principal_ref, service_id),
        scope=scope,
        scope_ref=scope_ref,
        scope_version="afi-normal-bootstrap-scope-v1",
        security_ref=security_ref,
        security_version="afi-normal-bootstrap-curve-v1",
        registration_policy_ref=config.registration_policy_ref,
        registration_policy_version="afi-normal-bootstrap-policy-v1",
        service_requirements_ref=config.service_requirements_ref,
        service_requirements_version="afi-normal-bootstrap-requirements-v1",
        curve_public_key=server_public,
        curve_secret_key=server_secret,
        principals={client_public: principal_ref},
        grants={
            principal_ref: (
                PrincipalGrant(
                    WireIdentity(WireRole.APPLICATION_CLIENT, principal_ref, application_ref),
                    (
                        ResourceGrant(
                            instance_id,
                            "service.market_source",
                            scope_ref,
                            scope,
                            operations,
                        ),
                    ),
                ),
            )
        },
    )

    class _UnopenedStream:
        def start(self, *, connect_timeout: float) -> None:
            assert connect_timeout == 1.0

        def stop(self) -> None:
            return None

    market_binding = GatewayOkxMarketBinding(
        key_universe=(key,),
        principal_allowed_keys={principal_ref: frozenset({key})},
        stream_factory=lambda _key, _ticker_queue: _UnopenedStream(),
        connect_timeout_seconds=1.0,
    )
    deployment_threads: list[int] = []
    deployments: list[GatewayOperatorDeployment] = []

    def _deployment_factory() -> GatewayOperatorDeployment:
        deployment_threads.append(threading.get_ident())
        deployment = GatewayOperatorDeployment(
            config,
            authority,
            tmp_path / "normal-bootstrap-operator.sqlite3",
            resource_provider=lambda *_args: None,
            okx_market=market_binding,
        )
        deployments.append(deployment)
        return deployment

    profile = GatewayOperatorProfile(profile_ref, "market_hub", _deployment_factory)
    registry = GatewayOperatorProfileRegistry((profile,))
    monkeypatch.setattr(
        operator_sdk.GatewayOperatorProfileRegistry,
        "from_entry_points",
        classmethod(lambda _cls: registry),
    )
    deployment_json = json.dumps(
        {
            "schema_version": 1,
            "operators": [
                {
                    "profile_ref": profile_ref,
                    "account_ref": None,
                    "authorized_subjects": [subject],
                    "operations": ["status", "start", "stop"],
                    "auto_start": True,
                    "legacy_gateway_keys": [],
                }
            ],
        }
    )
    normal_settings = main_module.settings.model_copy(
        update={
            "SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON": SecretStr(deployment_json),
            "SERVICE_READ_DEPLOYMENT_JSON": SecretStr(""),
            "PORTFOLIO_VALUATION_BINDINGS_JSON": SecretStr(""),
            "AKSHARE_DATA_DATABASE_URL": "",
            "DB_AUTO_CREATE_SCHEMA": True,
            "DB_AUTO_CREATE_DEFAULT_ADMIN": False,
            "RAG_VECTOR_ENABLED": False,
            "MARKET_DATA_THS_SCHEDULER_ENABLED": False,
            "STOCK_SIGNAL_SCHEDULE_ENABLED": False,
            "ASSET_RESEARCH_TASK_RUNNER_ENABLED": False,
            "ASSET_RESEARCH_SCHEDULE_ENABLED": False,
            "ASSET_RESEARCH_OUTCOME_EVALUATOR_ENABLED": False,
        }
    )
    import app.db.database as database_module

    monkeypatch.setattr(main_module, "settings", normal_settings)
    monkeypatch.setattr(database_module, "settings", normal_settings)

    application = None
    with TestClient(main_module.app) as client:
        assert client.get("/openapi.json").status_code == 200
        control = main_module.app.state.service_gateway_operator_control
        status = control.status(profile_ref, subject)
        assert status["state"] == "running"
        assert status["ready"] is True
        application = control._applications[profile_ref]
        assert len(deployments) == 1
        assert deployment_threads == [deployments[0]._owner_thread_id]
        assert application._thread is not None
        assert application._thread.ident == deployment_threads[0]
        assert deployments[0].state == "started"

    assert application is not None
    assert application.status["state"] == "closed"
    assert application._thread is not None and not application._thread.is_alive()
    assert deployments[0].state == "closed"
    assert main_module.app.state.service_gateway_operator_control is None


def test_quote_shutdown_retains_uncertain_client_before_operator_can_close() -> None:
    class _Deployment:
        def __init__(self) -> None:
            self.fail_close = True
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.fail_close:
                raise ServiceMarketDeploymentError("CLOSE_FAILED")

    service = object.__new__(QuoteService)
    deployment = _Deployment()
    service._service_market_load_lock = threading.Lock()
    service._service_market_deployment = deployment
    service._service_market_error = None
    service._service_market_loaded = True
    service._receivers = {}
    service._subscribed_symbols = {}

    assert service.shutdown() is False
    assert service._service_market_deployment is deployment
    assert service._service_market_loaded is True

    deployment.fail_close = False
    assert service.shutdown() is True
    assert deployment.close_calls == 2
    assert service._service_market_deployment is None
    assert service._service_market_loaded is False
