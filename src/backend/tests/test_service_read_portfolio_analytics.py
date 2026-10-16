"""Fixed analytics actions stay on the existing service-read owner thread."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from app.services.service_read.worker import ServiceReadWorker


class _AnalyticsSession:
    def __init__(self) -> None:
        self.owner_thread_id: int | None = None
        self.calls: list[tuple[str, tuple[Any, ...], int]] = []
        self.closed = False

    def start(self) -> None:
        self.owner_thread_id = threading.get_ident()

    def maintain(self) -> None:
        assert threading.get_ident() == self.owner_thread_id

    def close(self) -> None:
        assert threading.get_ident() == self.owner_thread_id
        self.closed = True

    def _record(self, name: str, *arguments: Any) -> dict[str, Any]:
        thread_id = threading.get_ident()
        self.calls.append((name, arguments, thread_id))
        return {"ok": True, "code": "OK", "result": {"operation": name}}

    def upload_portfolio_analytics_input(
        self, scope_ref: str, input_snapshot_id: str, facts: dict[str, Any]
    ) -> dict[str, Any]:
        return self._record("upload", scope_ref, input_snapshot_id, facts)

    def submit_portfolio_analytics_task(
        self, scope_ref: str, task_ref: str, input_snapshot_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        return self._record("submit", scope_ref, task_ref, input_snapshot_id, request)

    def query_portfolio_analytics_task(
        self, scope_ref: str, task_ref: str
    ) -> dict[str, Any]:
        return self._record("query", scope_ref, task_ref)

    def cancel_portfolio_analytics_task(
        self, scope_ref: str, task_ref: str
    ) -> dict[str, Any]:
        return self._record("cancel", scope_ref, task_ref)


@pytest.mark.asyncio
async def test_four_fixed_analytics_actions_share_the_service_read_owner_thread() -> None:
    sessions: list[_AnalyticsSession] = []

    def create_session() -> _AnalyticsSession:
        session = _AnalyticsSession()
        sessions.append(session)
        return session

    worker = ServiceReadWorker(
        create_session,
        max_queue_size=4,
        maintenance_interval_seconds=30.0,
        name="afi-analytics-owner-test",
    )
    caller_thread_id = threading.get_ident()
    try:
        await worker.start()
        upload = await worker.upload_portfolio_analytics_input(
            "configured-analysis-scope", "input-cut-1", {"version": 2}
        )
        submit = await worker.submit_portfolio_analytics_task(
            "configured-analysis-scope", "task-1", "input-cut-1", {"version": 2}
        )
        query = await worker.query_portfolio_analytics_task(
            "configured-analysis-scope", "task-1"
        )
        cancel = await worker.cancel_portfolio_analytics_task(
            "configured-analysis-scope", "task-1"
        )
    finally:
        await worker.aclose()

    assert len(sessions) == 1
    session = sessions[0]
    assert session.closed is True
    assert [item[0] for item in session.calls] == ["upload", "submit", "query", "cancel"]
    assert all(item[2] == session.owner_thread_id for item in session.calls)
    assert session.owner_thread_id != caller_thread_id
    assert [item["result"]["operation"] for item in (upload, submit, query, cancel)] == [
        "upload",
        "submit",
        "query",
        "cancel",
    ]
