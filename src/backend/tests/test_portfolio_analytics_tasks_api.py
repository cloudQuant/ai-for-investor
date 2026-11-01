"""HTTP contract tests for the Risk-backed offline portfolio task adapter."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api import service_read as service_read_api
from app.schemas.portfolio_analytics_tasks import PortfolioAnalyticsTaskCreate


def _facts(portfolio_ref: str = "analytics-research") -> dict:
    unavailable = {
        "status": "unavailable",
        "reason_code": "NO_SOURCE_DATA",
        "coverage_complete": None,
    }
    return {
        "version": 2,
        "portfolio_ref": portfolio_ref,
        "source_mode": "research",
        "source_ref": "offline-source-bundle",
        "source_version": "bundle.v1",
        "source_generation": "snapshot-generation-1",
        "facts_snapshot_ref": "facts-cut-1",
        "spot": {
            **unavailable,
            "as_of_utc": None,
            "source_ref": None,
            "source_version": None,
            "source_generation": None,
            "source_cursor": None,
            "positions": [],
        },
        "nav_history": {
            **unavailable,
            "source_ref": None,
            "source_version": None,
            "source_generation": None,
            "coverage_start_utc": None,
            "coverage_end_utc": None,
            "start_cursor": None,
            "end_cursor": None,
            "observations": [],
        },
        "loss_history": {
            **unavailable,
            "horizon_ref": "daily.v1",
            "source_ref": None,
            "source_version": None,
            "source_generation": None,
            "coverage_start_utc": None,
            "coverage_end_utc": None,
            "start_cursor": None,
            "end_cursor": None,
            "observations": [],
        },
        "scenario": {
            **unavailable,
            "scenario_ref": "offline-scenario",
            "scenario_version": "scenario.v1",
            "source_ref": None,
            "source_version": None,
            "source_generation": None,
            "source_cursor": None,
            "shocks": [],
        },
    }


def _request(portfolio_ref: str = "analytics-research") -> dict:
    return {
        "version": 2,
        "portfolio_ref": portfolio_ref,
        "reporting_currency": "USD",
        "loss_horizon_ref": "daily.v1",
        "confidence": "0.95",
        "scenario_ref": "offline-scenario",
        "scenario_version": "scenario.v1",
    }


@pytest.mark.parametrize("section", ["facts", "request"])
def test_v2_schema_version_requires_an_exact_json_integer(section: str) -> None:
    payload = {
        "idempotency_key": "offline-analysis-version-type",
        "facts": _facts(),
        "request": _request(),
    }
    payload[section]["version"] = 2.0

    with pytest.raises(ValidationError):
        PortfolioAnalyticsTaskCreate.model_validate(payload)


class _AnalyticsWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.task: dict | None = None
        self.input_snapshot_id: str | None = None
        self.input_sha256 = "a" * 64

    async def upload_portfolio_analytics_input(
        self, scope_ref: str, input_snapshot_id: str, facts: dict
    ) -> dict:
        self.calls.append(("upload", scope_ref, facts))
        self.input_snapshot_id = input_snapshot_id
        return {
            "ok": True,
            "code": "OK",
            "result": {
                "input_snapshot_id": input_snapshot_id,
                "input_sha256": self.input_sha256,
                "source_mode": "research",
                "created_ns": 1_760_000_000_000_000_000,
            },
        }

    async def submit_portfolio_analytics_task(
        self, scope_ref: str, task_ref: str, input_snapshot_id: str, request: dict
    ) -> dict:
        self.calls.append(("submit", scope_ref, request))
        self.task = {
            "task_ref": task_ref,
            "state": "pending",
            "input_snapshot_id": input_snapshot_id,
            "input_sha256": self.input_sha256,
            "created_ns": 1_760_000_000_000_000_000,
            "state_ns": 1_760_000_000_000_000_000,
            "detail_code": None,
            "result": None,
        }
        return {"ok": True, "code": "OK", "result": dict(self.task)}

    async def query_portfolio_analytics_task(self, scope_ref: str, task_ref: str) -> dict:
        self.calls.append(("query", scope_ref, {"task_ref": task_ref}))
        if self.task is None or self.task["task_ref"] != task_ref:
            return {"ok": False, "code": "TASK_NOT_FOUND", "result": {}}
        return {"ok": True, "code": "OK", "result": dict(self.task)}

    async def cancel_portfolio_analytics_task(self, scope_ref: str, task_ref: str) -> dict:
        self.calls.append(("cancel", scope_ref, {"task_ref": task_ref}))
        if self.task is None or self.task["task_ref"] != task_ref:
            return {"ok": False, "code": "TASK_NOT_FOUND", "result": {}}
        if self.task["state"] == "pending":
            self.task["state"] = "cancelled"
        return {"ok": True, "code": "OK", "result": dict(self.task)}


@pytest.mark.asyncio
async def test_offline_v2_task_uses_configured_scope_and_version_bound_task_refs(
    client, auth_headers, monkeypatch
):
    worker = _AnalyticsWorker()
    configured_scope = "deployment-owned-analytics-scope"
    binding = SimpleNamespace(
        mount="application.risk_analysis",
        scope_ref=configured_scope,
        portfolio_ref="analytics-research",
    )
    access = SimpleNamespace(
        worker=worker,
        portfolio_analytics_bindings={"analytics-research": binding},
    )
    resolved: list[tuple[str, str]] = []

    def resolve(current_user, portfolio_ref: str):
        resolved.append((current_user.sub, portfolio_ref))
        return access

    monkeypatch.setattr(
        service_read_api,
        "resolve_portfolio_analytics_access",
        resolve,
        raising=False,
    )

    created = await client.post(
        "/api/v1/portfolio/compositions",
        headers=auth_headers,
        json={
            "portfolio_ref": "analytics-research",
            "source_type": "research",
            "base_currency": "USD",
            "members": [{"kind": "research_artifact", "ref": "artifact-1"}],
        },
    )
    assert created.status_code == 201, created.text
    membership = created.json()

    body = {
        "idempotency_key": "offline-analysis-1",
        "facts": _facts(),
        "request": _request(),
    }
    submitted = await client.post(
        "/api/v1/portfolio/compositions/analytics-research/versions/1/analytics-tasks",
        headers=auth_headers,
        json=body,
    )
    assert submitted.status_code == 202, submitted.text
    task = submitted.json()
    assert task["state"] == "pending"
    assert task["membership_version"] == membership["membership_version"] == 1
    assert task["membership_sha256"] == membership["membership_sha256"]
    assert task["task_ref"].startswith("afi2:")
    assert task["input_snapshot_id"].startswith("afi2-input:")
    assert "scope_ref" not in task
    assert "membership_version" not in worker.calls[1][2]
    assert [call[0] for call in worker.calls] == ["upload", "submit"]
    assert all(call[1] == configured_scope for call in worker.calls)
    assert len(resolved) == 1
    assert all(item[1] == "analytics-research" for item in resolved)

    queried = await client.get(
        f"/api/v1/portfolio/compositions/analytics-research/versions/1/analytics-tasks/{task['task_ref']}",
        headers=auth_headers,
    )
    assert queried.status_code == 200, queried.text
    assert queried.json()["input_snapshot_id"] == task["input_snapshot_id"]

    cancelled = await client.post(
        f"/api/v1/portfolio/compositions/analytics-research/versions/1/analytics-tasks/{task['task_ref']}/cancel",
        headers=auth_headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled"
    assert len(resolved) == 3

    second_version = await client.post(
        "/api/v1/portfolio/compositions",
        headers=auth_headers,
        json={
            "portfolio_ref": "analytics-research",
            "source_type": "research",
            "base_currency": "USD",
            "members": [{"kind": "research_artifact", "ref": "artifact-2"}],
        },
    )
    assert second_version.status_code == 201, second_version.text
    before_wrong_version_read = len(worker.calls)
    wrong_version = await client.get(
        f"/api/v1/portfolio/compositions/analytics-research/versions/2/analytics-tasks/{task['task_ref']}",
        headers=auth_headers,
    )
    assert wrong_version.status_code == 404
    assert len(worker.calls) == before_wrong_version_read
    assert len(resolved) == 4


@pytest.mark.asyncio
async def test_v2_request_rejects_application_membership_field(client, auth_headers, monkeypatch):
    worker = _AnalyticsWorker()
    binding = SimpleNamespace(
        mount="application.risk_analysis",
        scope_ref="deployment-owned-analytics-scope",
        portfolio_ref="analytics-research",
    )
    monkeypatch.setattr(
        service_read_api,
        "resolve_portfolio_analytics_access",
        lambda current_user, portfolio_ref: SimpleNamespace(
            worker=worker,
            portfolio_analytics_bindings={"analytics-research": binding},
        ),
        raising=False,
    )
    created = await client.post(
        "/api/v1/portfolio/compositions",
        headers=auth_headers,
        json={
            "portfolio_ref": "analytics-research",
            "source_type": "research",
            "base_currency": "USD",
            "members": [{"kind": "research_artifact", "ref": "artifact-1"}],
        },
    )
    assert created.status_code == 201, created.text
    body = {
        "idempotency_key": "offline-analysis-2",
        "facts": _facts(),
        "request": {**_request(), "membership_version": 1},
    }
    rejected = await client.post(
        "/api/v1/portfolio/compositions/analytics-research/versions/1/analytics-tasks",
        headers=auth_headers,
        json=body,
    )
    assert rejected.status_code == 422
    assert worker.calls == []
