"""Production lifespan composition for the optional service-read worker."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.api.deps import get_current_user
from app.api.service_read import configure_service_read, router
from app.schemas.auth import TokenPayload
from app.services.service_read.contracts import StrategyHealthView
from app.services.service_read.deployment import (
    ServiceReadDeploymentError,
    start_service_read_deployment,
)
from app.services.service_read.worker import ServiceReadWorker


def _subject_profile(
    subject: str = "user-a",
    *,
    application_ref: str = "application-a",
    scope_ref: str = "telemetry-a",
    strategy_ref: str = "strategy-a",
    mount: str = "application.monitor",
) -> dict[str, Any]:
    """Return one synthetic, read-only deployment profile."""

    service_id = "monitor-service"
    transport_ref = "monitor-transport-v1"
    alias = {
        "application.account": "gateway",
        "application.order_query": "execution",
        "application.monitor": "monitor",
        "application.orders": "execution",
    }[mount]
    return {
        "subject": subject,
        "identity": {
            "principal_ref": f"principal-{subject}",
            "actor_ref": application_ref,
            "delegate_ref": f"delegate-{subject}",
        },
        "client_config": {
            "client_config_schema_version": 1,
            "process_role": "application_client",
            "registration": {"application_ref": application_ref},
            "clients": {
                alias: {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": mount,
                                "service_id": service_id,
                                "instance_id": "monitor-instance",
                                "scope_ref": scope_ref,
                                "transport_ref": transport_ref,
                            }
                        ],
                        "options": {"request_timeout_ms": 2000},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    transport_ref: {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_connect": "tcp://127.0.0.1:5555"},
                        "security_profile_ref": "synthetic-curve-v1",
                        "options": {
                            "request_timeout_ms": 2000,
                            "high_water_mark": 16,
                            "max_message_bytes": 65_536,
                        },
                    }
                },
            },
        },
        "scope_claims": {
            scope_ref: {
                "execution_domain_ref": "paper:synthetic",
                "strategy_ref": strategy_ref,
            }
        },
        "peer_identities": {
            service_id: {"principal_ref": "synthetic-monitor-principal", "actor_ref": service_id}
        },
        "curve_keys": {
            "synthetic-curve-v1": {
                "server_key": "A" * 40,
                "public_key": "B" * 40,
                "secret_key": "C" * 40,
            }
        },
        "grants": {
            "account_refs": [],
            "order_scope_refs": [],
            "monitor_scope_refs": [scope_ref],
        },
        "account_bindings": {},
        "order_bindings": {},
        "monitor_bindings": {
            scope_ref: {"mount": "application.monitor", "strategy_ref": strategy_ref}
        },
        "worker": {"max_queue_size": 8, "maintenance_interval_seconds": 0.01},
    }


def _document(*profiles: dict[str, Any]) -> SecretStr:
    return SecretStr(json.dumps({"schema_version": 1, "subjects": list(profiles)}))


class _ObservedSession:
    def __init__(self, events: list[tuple[str, int]], *, fail_start: bool = False) -> None:
        self.events = events
        self.fail_start = fail_start

    def _record(self, operation: str) -> None:
        self.events.append((operation, threading.get_ident()))

    def start(self) -> None:
        self._record("start")
        if self.fail_start:
            raise RuntimeError("synthetic startup failure")

    def maintain(self) -> None:
        self._record("maintain")

    def read_account(self, account_ref: str, *, currency: str | None = None) -> Any:
        raise AssertionError((account_ref, currency))

    def read_order(self, scope_ref: str, intent_id: str) -> Any:
        raise AssertionError((scope_ref, intent_id))

    def read_strategy_health(self, scope_ref: str) -> StrategyHealthView:
        self._record("read")
        return StrategyHealthView.not_collected("strategy-a", scope_ref)

    def close(self) -> None:
        self._record("close")


class _NoopShutdownManager:
    async def initiate(self, _app: FastAPI) -> None:
        return None


@pytest.fixture
def lifecycle_app(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, FastAPI]:
    import slowapi.extension

    path_is_file = Path.is_file
    os_path_isfile = slowapi.extension.os.path.isfile

    def _path_is_file_without_dotenv(path: Path) -> bool:
        if path.name.casefold() in {".env", ".slowapi.env"}:
            return False
        return path_is_file(path)

    def _os_path_isfile_without_dotenv(path: Any) -> bool:
        if Path(path).name.casefold() == ".env":
            return False
        return os_path_isfile(path)

    monkeypatch.setattr(Path, "is_file", _path_is_file_without_dotenv)
    monkeypatch.setattr(slowapi.extension.os.path, "isfile", _os_path_isfile_without_dotenv)

    import app.main as main_module
    import app.services.quote_service as quote_service

    async def _nothing(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(main_module, "run_startup", _nothing)
    monkeypatch.setattr(main_module, "run_shutdown", _nothing)
    monkeypatch.setattr(main_module, "GracefulShutdownManager", _NoopShutdownManager)
    monkeypatch.setattr(main_module.settings, "RAG_VECTOR_ENABLED", False)
    monkeypatch.setattr(
        quote_service,
        "get_quote_service",
        lambda: SimpleNamespace(shutdown=lambda: None),
    )
    configure_service_read(None)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(
        sub="user-a", username="synthetic-user"
    )
    try:
        yield main_module, app
    finally:
        configure_service_read(None)


async def _get(app: FastAPI, path: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://service-read-test"
    ) as client:
        return await client.get(path)


def test_unconfigured_lifespan_keeps_reads_503_without_building_workers(
    lifecycle_app: tuple[Any, FastAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    main_module, app = lifecycle_app
    monkeypatch.setattr(main_module.settings, "SERVICE_READ_DEPLOYMENT_JSON", SecretStr(""))
    import app.services.service_read.deployment as deployment_module

    def _unexpected_worker(_profile: Any) -> ServiceReadWorker:
        raise AssertionError("an empty deployment must not construct a worker")

    monkeypatch.setattr(deployment_module, "_build_worker", _unexpected_worker)

    async def _exercise() -> None:
        async with main_module.lifespan(app):
            response = await _get(app, "/api/v1/service-read/strategy-health/telemetry-a")
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "SERVICE_READ_NOT_CONFIGURED"
            assert app.state.service_read_deployment is None

        response = await _get(app, "/api/v1/service-read/strategy-health/telemetry-a")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "SERVICE_READ_NOT_CONFIGURED"

    asyncio.run(_exercise())


def test_lifespan_installs_subject_directory_and_closes_owner_thread(
    lifecycle_app: tuple[Any, FastAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    main_module, app = lifecycle_app
    monkeypatch.setattr(
        main_module.settings,
        "SERVICE_READ_DEPLOYMENT_JSON",
        _document(_subject_profile()),
    )
    events: list[tuple[str, int]] = []
    import app.services.service_read.deployment as deployment_module

    def _build_test_worker(profile: Any) -> ServiceReadWorker:
        assert profile.subject == "user-a"
        assert profile.identity.actor_ref == "application-a"
        return ServiceReadWorker(
            lambda: _ObservedSession(events),
            max_queue_size=profile.max_queue_size,
            maintenance_interval_seconds=profile.maintenance_interval_seconds,
            name="synthetic-service-read-owner",
        )

    monkeypatch.setattr(deployment_module, "_build_worker", _build_test_worker)
    main_thread = threading.get_ident()

    async def _exercise() -> None:
        async with main_module.lifespan(app):
            await asyncio.sleep(0.03)
            response = await _get(app, "/api/v1/service-read/strategy-health/telemetry-a")
            assert response.status_code == 200
            assert response.json()["quality"] == "not_collected"
            denied = await _get(app, "/api/v1/service-read/strategy-health/telemetry-other")
            assert denied.status_code == 403
            assert denied.json()["detail"]["code"] == "SERVICE_READ_ACCESS_DENIED"
            assert app.state.service_read_deployment is not None

    asyncio.run(_exercise())
    operations = [operation for operation, _thread_id in events]
    assert operations[0] == "start"
    assert "maintain" in operations
    assert operations.count("read") == 1
    assert operations[-1] == "close"
    owner_threads = {thread_id for _operation, thread_id in events}
    assert len(owner_threads) == 1
    assert main_thread not in owner_threads
    assert app.state.service_read_deployment is None


def test_lifespan_retains_uncertain_partial_without_retrying_close(
    lifecycle_app: tuple[Any, FastAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    main_module, app = lifecycle_app

    class _UncertainDeployment:
        closed = False

        def __init__(self) -> None:
            self.close_calls = 0

        async def aclose(self) -> None:
            self.close_calls += 1
            raise RuntimeError("synthetic close uncertainty")

    partial = _UncertainDeployment()

    async def _failed_start(_configuration: Any) -> Any:
        try:
            await partial.aclose()
        except RuntimeError:
            pass
        raise ServiceReadDeploymentError("START_FAILED", deployment=partial)

    monkeypatch.setattr(main_module, "start_service_read_deployment", _failed_start)

    async def _exercise() -> None:
        with pytest.raises(ServiceReadDeploymentError) as error:
            async with main_module.lifespan(app):
                pytest.fail("startup failure must not reach the request phase")
        assert error.value.code == "START_FAILED"

    asyncio.run(_exercise())
    assert partial.close_calls == 1
    assert app.state.service_read_deployment is partial


def test_partial_startup_closes_every_created_worker_before_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.service_read.deployment as deployment_module

    events: dict[str, list[tuple[str, int]]] = {"user-a": [], "user-b": []}

    def _build_test_worker(profile: Any) -> ServiceReadWorker:
        event_list = events[profile.subject]
        return ServiceReadWorker(
            lambda: _ObservedSession(event_list, fail_start=profile.subject == "user-b"),
            maintenance_interval_seconds=1.0,
            name=f"synthetic-{profile.subject}",
        )

    monkeypatch.setattr(deployment_module, "_build_worker", _build_test_worker)
    document = _document(
        _subject_profile(),
        _subject_profile(
            "user-b",
            application_ref="application-b",
            scope_ref="telemetry-b",
            strategy_ref="strategy-b",
        ),
    )

    async def _exercise() -> None:
        with pytest.raises(ServiceReadDeploymentError) as error:
            await start_service_read_deployment(document)

        assert error.value.code == "START_FAILED"
        assert error.value.deployment is not None
        assert error.value.deployment.closed
        assert all(any(operation == "close" for operation, _ in rows) for rows in events.values())
        for rows in events.values():
            thread_ids = {thread_id for _operation, thread_id in rows}
            assert len(thread_ids) == 1
            assert rows[-1][0] == "close"

    asyncio.run(_exercise())


def test_writable_client_mount_is_rejected_before_worker_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.service_read.deployment as deployment_module

    def _unexpected_worker(_profile: Any) -> ServiceReadWorker:
        raise AssertionError("invalid writable config must fail before worker construction")

    monkeypatch.setattr(deployment_module, "_build_worker", _unexpected_worker)
    profile = _subject_profile(mount="application.orders")

    async def _exercise() -> None:
        with pytest.raises(ServiceReadDeploymentError):
            await start_service_read_deployment(_document(profile))

    asyncio.run(_exercise())


def test_admin_provider_delete_returns_an_empty_204_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.ai_observability as observability_module
    from app.api.data.deps import require_data_admin_user

    deleted: list[str] = []
    monkeypatch.setattr(
        observability_module,
        "delete_provider_config",
        lambda provider_key, **_kwargs: deleted.append(provider_key),
    )

    app = FastAPI()
    app.include_router(observability_module.router)
    app.dependency_overrides[require_data_admin_user] = lambda: SimpleNamespace()

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://observability-test"
        ) as client:
            return await client.delete("/admin/ai/provider-configs/synthetic-provider")

    response = asyncio.run(_exercise())

    assert response.status_code == 204
    assert response.content == b""
    assert deleted == ["synthetic-provider"]
