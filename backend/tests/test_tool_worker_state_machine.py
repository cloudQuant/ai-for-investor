from datetime import datetime, timezone
from typing import Any

import pytest

from app.models.tool import Tool, ToolJob, ToolManifest
from app.services.tool_worker import ResourceLimitError, ToolExecutionContext, ToolTimeoutError, run_tool_job


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def make_manifest(timeout_seconds: int = 60, cpu: int = 1, memory_mb: int = 512) -> ToolManifest:
    return ToolManifest(
        id=3,
        name="Backtest Manifest",
        version="1.0.0",
        entrypoint={"mode": "container", "command": ["python", "-m", "safe_backtest"]},
        parameters_schema={"allowed": {"symbol": {"type": "string"}}},
        resources={"cpu": cpu, "memory_mb": memory_mb, "timeout_seconds": timeout_seconds},
        network={"mode": "none", "allowed_hosts": []},
        output={"format": "json", "max_bytes": 100000},
    )


def make_tool(manifest: ToolManifest | None = None) -> Tool:
    tool = Tool(
        id=5,
        name="Backtest Demo",
        slug="backtest-demo",
        risk_level="low",
        run_mode="internal",
        manifest_id=3,
        config_status="published",
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    tool.manifest = manifest or make_manifest()
    return tool


def make_job(status: str = "queued") -> ToolJob:
    job = ToolJob(
        id=1,
        job_id="job_abc123",
        tool_id=5,
        user_id=7,
        parameters={"symbol": "AAPL"},
        status=status,
        queued_at=datetime.now(timezone.utc),
    )
    job.tool = make_tool()
    return job


@pytest.mark.asyncio
async def test_worker_transitions_queued_job_to_running_then_succeeded() -> None:
    job = make_job()
    db = FakeSession()

    async def executor(context: ToolExecutionContext) -> dict[str, Any]:
        assert context.job_id == "job_abc123"
        assert context.request_id == "req-worker"
        assert context.timeout_seconds == 60
        return {"summary": "Completed safely"}

    result = await run_tool_job(db, job, executor, request_id="req-worker")

    assert result.status == "succeeded"
    assert result.result_summary == "Completed safely"
    assert result.started_at is not None
    assert result.completed_at is not None
    assert result.error_message is None
    assert db.commits >= 2


@pytest.mark.asyncio
async def test_worker_marks_job_timeout_and_stores_safe_reason() -> None:
    job = make_job()
    db = FakeSession()

    async def executor(context: ToolExecutionContext) -> dict[str, Any]:
        raise ToolTimeoutError("command /secret/path/token timed out after 60 seconds")

    result = await run_tool_job(db, job, executor, request_id="req-worker")

    assert result.status == "timeout"
    assert result.completed_at is not None
    assert result.error_message == "Tool execution timed out"
    assert "secret" not in result.error_message


@pytest.mark.asyncio
async def test_worker_marks_job_failed_with_sanitized_failure_reason() -> None:
    job = make_job()
    db = FakeSession()

    async def executor(context: ToolExecutionContext) -> dict[str, Any]:
        raise RuntimeError("Traceback: password=super-secret stack details")

    result = await run_tool_job(db, job, executor, request_id="req-worker")

    assert result.status == "failed"
    assert result.completed_at is not None
    assert result.error_message == "Tool execution failed"
    assert "password" not in result.error_message


@pytest.mark.asyncio
async def test_worker_enforces_manifest_resource_boundaries_before_execution() -> None:
    manifest = make_manifest(cpu=8, memory_mb=8192)
    job = make_job()
    job.tool = make_tool(manifest)
    db = FakeSession()
    called = False

    async def executor(context: ToolExecutionContext) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"summary": "should not run"}

    result = await run_tool_job(db, job, executor, request_id="req-worker")

    assert called is False
    assert result.status == "failed"
    assert result.error_message == "Tool resource limits exceed worker policy"


@pytest.mark.asyncio
async def test_worker_rejects_non_queued_jobs_without_execution() -> None:
    job = make_job(status="succeeded")
    db = FakeSession()
    called = False

    async def executor(context: ToolExecutionContext) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"summary": "should not run"}

    result = await run_tool_job(db, job, executor, request_id="req-worker")

    assert called is False
    assert result.status == "succeeded"
    assert db.commits == 0
