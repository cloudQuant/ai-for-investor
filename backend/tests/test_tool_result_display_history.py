from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1 import tools
from app.models.tool import ToolJob
from app.models.user import User


class FakeScalarResult:
    def __init__(self, value: Any = None, values: list[Any] | None = None) -> None:
        self.value = value
        self.values = values or []

    def scalar_one_or_none(self) -> Any:
        return self.value

    def scalars(self) -> "FakeScalarResult":
        return self

    def all(self) -> list[Any]:
        return self.values


class FakeSession:
    def __init__(self, results: list[FakeScalarResult] | None = None) -> None:
        self.results = results or []

    async def execute(self, statement: Any) -> FakeScalarResult:
        if self.results:
            return self.results.pop(0)
        return FakeScalarResult()


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/tools/jobs",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-history"
    return request


def verified_user(user_id: int = 7) -> User:
    return User(
        id=user_id,
        email=f"user{user_id}@example.com",
        username=f"user{user_id}",
        password_hash="hash",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )


def patch_current_user(monkeypatch, user: User | None) -> None:
    async def fake_get_current_user(request: Request, db: FakeSession) -> User | None:
        return user

    monkeypatch.setattr(tools, "get_current_user", fake_get_current_user)


def make_job(job_id: str = "job_abc123", user_id: int = 7, status: str = "succeeded", result_summary: str | None = "Safe result") -> ToolJob:
    return ToolJob(
        id=1,
        job_id=job_id,
        tool_id=5,
        user_id=user_id,
        parameters={"symbol": "AAPL"},
        status=status,
        result_summary=result_summary,
        error_message=None,
        queued_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_user_job_history_returns_only_current_users_safe_jobs(monkeypatch) -> None:
    patch_current_user(monkeypatch, verified_user(7))
    own_job = make_job(job_id="job_own", user_id=7, status="queued")
    db = FakeSession([FakeScalarResult(values=[own_job])])

    response = await tools.list_jobs(make_request(), db)

    assert response["request_id"] == "req-history"
    assert len(response["data"]) == 1
    assert response["data"][0]["job_id"] == "job_own"
    assert response["data"][0]["status"] == "queued"


@pytest.mark.asyncio
async def test_user_job_detail_limits_result_output_and_filters_sensitive_information(monkeypatch) -> None:
    patch_current_user(monkeypatch, verified_user(7))
    sensitive_result = "token=abc123 password=secret api_key=hidden " + ("x" * 2500)
    job = make_job(result_summary=sensitive_result)
    db = FakeSession([FakeScalarResult(job)])

    response = await tools.get_job("job_abc123", make_request(), db)
    result = response["data"]["result_summary"]

    assert len(result) <= tools.MAX_JOB_RESULT_SUMMARY_LENGTH
    assert "abc123" not in result
    assert "secret" not in result
    assert "hidden" not in result
    assert "[redacted]" in result


@pytest.mark.asyncio
async def test_user_job_detail_filters_sensitive_error_message(monkeypatch) -> None:
    patch_current_user(monkeypatch, verified_user(7))
    job = make_job(status="failed", result_summary=None)
    job.error_message = "Traceback password=secret at /tmp/stack.py"
    db = FakeSession([FakeScalarResult(job)])

    response = await tools.get_job("job_abc123", make_request(), db)

    assert response["data"]["error_message"] == "Tool execution failed"


@pytest.mark.asyncio
async def test_supported_job_statuses_are_serialized_for_frontend(monkeypatch) -> None:
    patch_current_user(monkeypatch, verified_user(7))
    jobs = [make_job(job_id=f"job_{status}", status=status) for status in ["queued", "running", "succeeded", "failed", "timeout"]]
    db = FakeSession([FakeScalarResult(values=jobs)])

    response = await tools.list_jobs(make_request(), db)

    assert [job["status"] for job in response["data"]] == ["queued", "running", "succeeded", "failed", "timeout"]


@pytest.mark.asyncio
async def test_user_still_cannot_view_another_users_job_result(monkeypatch) -> None:
    patch_current_user(monkeypatch, verified_user(7))
    db = FakeSession([FakeScalarResult(make_job(user_id=8))])

    with pytest.raises(HTTPException) as exc:
        await tools.get_job("job_abc123", make_request(), db)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Not authorized to view this job"
