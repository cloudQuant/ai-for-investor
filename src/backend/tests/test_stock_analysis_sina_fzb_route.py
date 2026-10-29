"""HTTP and SQLite round-trip coverage for explicit Sina FZB selectors."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.stock_analysis import StockAnalysisTaskModel
from app.schemas.stock_analysis import (
    StockAnalysisParams,
    StockAnalysisSinaFzbSnapshotSelection,
)
from app.services.stock_analysis.tasks import StockAnalysisTaskService

_TASKS_URL = "/api/v1/stock-analysis/tasks"
_PASSWORD = "RouteTest!2345"
_SELECTION_JSON = {
    "instrument_id": "600519.SH",
    "publication_id": "a" * 32,
    "capture_id": "b" * 64,
}


async def _register_and_login(
    client: AsyncClient, username: str
) -> tuple[dict[str, str], str]:
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
async def test_sina_selector_route_auth_ownership_and_sqlite_json_round_trip(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_op_run_pending_task(*, task_id: str, user_id: str) -> None:
        return None

    monkeypatch.setattr(
        StockAnalysisTaskService,
        "run_pending_task",
        staticmethod(no_op_run_pending_task),
    )

    selector_request: dict[str, Any] = {
        "symbol": "600519.SH",
        "opendata_sina_fzb_snapshot": _SELECTION_JSON,
    }
    anonymous_create = await client.post(_TASKS_URL, json=selector_request)
    assert anonymous_create.status_code == 401

    owner_headers, owner_id = await _register_and_login(client, "sina_route_owner")
    other_headers, other_id = await _register_and_login(client, "sina_route_other")
    assert owner_id != other_id

    created = await client.post(_TASKS_URL, headers=owner_headers, json=selector_request)
    assert created.status_code == 202, created.text
    created_payload = created.json()
    task_id = created_payload["task_id"]

    anonymous_read = await client.get(f"{_TASKS_URL}/{task_id}")
    assert anonymous_read.status_code == 401

    owner_read = await client.get(f"{_TASKS_URL}/{task_id}", headers=owner_headers)
    assert owner_read.status_code == 200, owner_read.text
    assert owner_read.json()["task_id"] == task_id
    assert owner_read.json()["symbol"] == "600519.SH"

    other_read = await client.get(f"{_TASKS_URL}/{task_id}", headers=other_headers)
    assert other_read.status_code == 404

    # A fresh SQLAlchemy session proves the selector survived SQLite JSON
    # serialization and can be rehydrated by the worker's request schema.
    from app.db import database

    async with database.async_session_maker() as session:
        stored = await session.scalar(
            select(StockAnalysisTaskModel).where(StockAnalysisTaskModel.id == task_id)
        )
        assert stored is not None
        assert stored.user_id == owner_id
        assert stored.parameters_json is not None
        assert stored.parameters_json["opendata_sina_fzb_snapshot"] == _SELECTION_JSON
        restored = StockAnalysisParams.model_validate(stored.parameters_json)
        assert restored.opendata_sina_fzb_snapshot == StockAnalysisSinaFzbSnapshotSelection(
            **_SELECTION_JSON
        )

    # Recreate the JSON shape written by older releases, where the optional
    # selector key did not exist, and ensure a new session can still load it.
    legacy_created = await client.post(
        _TASKS_URL,
        headers=owner_headers,
        json={"symbol": "000001.SZ"},
    )
    assert legacy_created.status_code == 202, legacy_created.text
    legacy_task_id = legacy_created.json()["task_id"]

    async with database.async_session_maker() as session:
        legacy_row = await session.scalar(
            select(StockAnalysisTaskModel).where(
                StockAnalysisTaskModel.id == legacy_task_id
            )
        )
        assert legacy_row is not None
        legacy_parameters = dict(legacy_row.parameters_json or {})
        legacy_parameters.pop("opendata_sina_fzb_snapshot", None)
        legacy_row.parameters_json = legacy_parameters
        await session.commit()

    async with database.async_session_maker() as session:
        reloaded_legacy = await session.scalar(
            select(StockAnalysisTaskModel).where(
                StockAnalysisTaskModel.id == legacy_task_id
            )
        )
        assert reloaded_legacy is not None
        assert reloaded_legacy.parameters_json is not None
        assert "opendata_sina_fzb_snapshot" not in reloaded_legacy.parameters_json
        restored_legacy = StockAnalysisParams.model_validate(reloaded_legacy.parameters_json)
        assert restored_legacy.opendata_sina_fzb_snapshot is None
