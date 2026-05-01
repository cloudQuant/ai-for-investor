import asyncio
from typing import Any

from fastapi.testclient import TestClient

from app.api.v1 import admin
from app.core.observability import (
    build_alerts,
    email_snapshot,
    record_api_request,
    record_email_delivery,
    reset_observability_metrics,
)
from app.main import create_app
from app.models.tool import ToolJobStatus
from test_rbac_admin_bootstrap import FakeScalarResult, user_with_roles


class ObservabilitySession:
    async def execute(self, statement: Any) -> FakeScalarResult:
        text = str(statement)
        if "tool_jobs.status = :status_1" in text:
            return FakeScalarResult(3)
        if "tool_jobs.status IN" in text:
            return FakeScalarResult(2)
        if "count(tool_jobs.id)" in text:
            return FakeScalarResult(10)
        if "count(audit_logs.id)" in text:
            return FakeScalarResult(4)
        return FakeScalarResult(0)


class FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **kwargs: Any) -> None:
        self.events.append((event, kwargs))


def test_api_metrics_track_request_volume_latency_and_error_rate() -> None:
    reset_observability_metrics()
    record_api_request(200, 12.5)
    record_api_request(500, 30.0)

    response = TestClient(create_app(include_lifespan=False)).get("/health")

    assert response.status_code == 200
    from app.core.observability import api_snapshot

    snapshot = api_snapshot()
    assert snapshot["request_volume"] >= 3
    assert snapshot["error_count"] == 1
    assert snapshot["error_rate"] > 0
    assert snapshot["average_latency_ms"] > 0
    assert snapshot["status_counts"]["200"] >= 2
    assert snapshot["status_counts"]["500"] == 1


def test_email_metrics_track_delivery_success_and_failure() -> None:
    reset_observability_metrics()
    record_email_delivery(True)
    record_email_delivery(False)

    snapshot = email_snapshot()

    assert snapshot == {"attempted": 2, "succeeded": 1, "failed": 1, "failure_rate": 0.5}


def test_alerts_cover_api_worker_email_and_storage_failures() -> None:
    alerts = build_alerts(
        {"error_rate": 0.1, "max_latency_ms": 2500},
        {"queue_backlog": 100, "job_failure_rate": 0.5},
        {"failure_rate": 0.2},
        {"health": "unhealthy"},
        {"health": "unhealthy"},
    )
    names = {alert["name"] for alert in alerts}

    assert "critical_api_error_rate" in names
    assert "critical_api_latency" in names
    assert "critical_worker_queue_backlog" in names
    assert "critical_worker_failure_rate" in names
    assert "critical_email_failure_rate" in names
    assert "critical_database_health" in names
    assert "critical_storage_health" in names


def test_admin_observability_dashboard_requires_admin_and_returns_operational_metrics(monkeypatch) -> None:
    reset_observability_metrics()
    record_api_request(200, 10)
    record_email_delivery(True)
    fake_logger = FakeLogger()
    monkeypatch.setattr(admin, "logger", fake_logger)
    request = type("Request", (), {"state": type("State", (), {"request_id": "req-obs"})()})()
    session = ObservabilitySession()
    user = user_with_roles("admin")

    async def fake_get_current_user(request: Any, db: Any):
        return user

    monkeypatch.setattr(admin, "get_current_user", fake_get_current_user)

    response = asyncio.run(admin.observability_dashboard(request, session))
    data = response["data"]

    assert data["api"]["request_volume"] == 1
    assert data["worker"]["queue_backlog"] == 3
    assert data["worker"]["failed_jobs"] == 2
    assert data["email"]["attempted"] == 1
    assert data["database"]["health"] == "healthy"
    assert data["database"]["audit_events"] == 4
    assert data["storage"]["health"] == "healthy"
    assert data["alerts"]
    assert response["request_id"] == "req-obs"
    assert fake_logger.events[-1] == ("admin_observability_accessed", {"user_id": 123, "request_id": "req-obs"})


def test_worker_status_enum_values_support_observability_dashboard() -> None:
    assert ToolJobStatus.QUEUED.value == "queued"
    assert ToolJobStatus.RUNNING.value == "running"
    assert ToolJobStatus.FAILED.value == "failed"
    assert ToolJobStatus.TIMEOUT.value == "timeout"
