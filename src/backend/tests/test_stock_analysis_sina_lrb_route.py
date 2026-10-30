"""HTTP and temporary SQLite round-trip coverage for the Sina LRB selector."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.stock_analysis import StockAnalysisTaskModel
from app.schemas.stock_analysis import (
    StockAnalysisParams,
    StockAnalysisSinaLrbSnapshotSelection,
)
from app.services.stock_analysis.tasks import StockAnalysisTaskService

_TASKS_URL = "/api/v1/stock-analysis/tasks"
_PASSWORD = "RouteTest!2345"
_SELECTION_JSON = {
    "instrument_id": "600519.SH",
    "publication_id": "a" * 32,
    "capture_id": "b" * 64,
}


async def _register_and_login(client: AsyncClient, username: str) -> tuple[dict[str, str], str]:
    registration = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": _PASSWORD,
        },
    )
    assert registration.status_code == 200, registration.text

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": _PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return headers, registration.json()["id"]


@pytest.mark.asyncio
async def test_lrb_selector_http_auth_sqlite_and_worker_round_trip(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def hold_background_task(*, task_id: str, user_id: str) -> None:
        return None

    real_worker = StockAnalysisTaskService.run_pending_task
    monkeypatch.setattr(
        StockAnalysisTaskService,
        "run_pending_task",
        staticmethod(hold_background_task),
    )

    request: dict[str, Any] = {
        "symbol": "600519.SH",
        "opendata_sina_lrb_snapshot": _SELECTION_JSON,
    }
    anonymous_create = await client.post(_TASKS_URL, json=request)
    assert anonymous_create.status_code == 401

    owner_headers, owner_id = await _register_and_login(client, "sina_lrb_route_owner")
    other_headers, other_id = await _register_and_login(client, "sina_lrb_route_other")
    assert owner_id != other_id

    ambiguous_request = {
        **request,
        "opendata_sina_fzb_snapshot": _SELECTION_JSON,
    }
    ambiguous_response = await client.post(
        _TASKS_URL, headers=owner_headers, json=ambiguous_request
    )
    assert ambiguous_response.status_code == 422

    created = await client.post(_TASKS_URL, headers=owner_headers, json=request)
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]

    anonymous_read = await client.get(f"{_TASKS_URL}/{task_id}")
    assert anonymous_read.status_code == 401
    owner_read = await client.get(f"{_TASKS_URL}/{task_id}", headers=owner_headers)
    assert owner_read.status_code == 200, owner_read.text
    assert owner_read.json()["task_id"] == task_id
    other_read = await client.get(f"{_TASKS_URL}/{task_id}", headers=other_headers)
    assert other_read.status_code == 404

    # The test client is backed by the per-test in-memory SQLite database.
    # A new session verifies that the HTTP selector crossed the JSON boundary.
    from app.db import database

    async with database.async_session_maker() as session:
        stored = await session.scalar(
            select(StockAnalysisTaskModel).where(StockAnalysisTaskModel.id == task_id)
        )
        assert stored is not None
        assert stored.user_id == owner_id
        assert stored.parameters_json is not None
        assert stored.parameters_json["opendata_sina_lrb_snapshot"] == _SELECTION_JSON
        restored = StockAnalysisParams.model_validate(stored.parameters_json)
        assert restored.opendata_sina_lrb_snapshot == StockAnalysisSinaLrbSnapshotSelection(
            **_SELECTION_JSON
        )

    # Run the real worker loader after replacing only the expensive execution
    # body. This proves the persisted selector reaches the worker as validated
    # task parameters without performing provider I/O or analysis.
    worker_params: list[StockAnalysisParams] = []

    async def capture_worker_params(
        _service: StockAnalysisTaskService,
        _task: StockAnalysisTaskModel,
        params: StockAnalysisParams,
        _analysis_date: date,
        *,
        commit_progress: bool = False,
    ) -> None:
        assert commit_progress is True
        worker_params.append(params)

    monkeypatch.setattr(StockAnalysisTaskService, "_run_task", capture_worker_params)
    await real_worker(task_id=task_id, user_id=owner_id)

    assert len(worker_params) == 1
    assert worker_params[0].opendata_sina_lrb_snapshot == StockAnalysisSinaLrbSnapshotSelection(
        **_SELECTION_JSON
    )
