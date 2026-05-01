from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import record_worker_job
from app.models.tool import ToolJob, ToolJobStatus


MAX_WORKER_CPU = 4
MAX_WORKER_MEMORY_MB = 4096
MAX_WORKER_TIMEOUT_SECONDS = 600


class ToolTimeoutError(Exception):
    pass


class ResourceLimitError(Exception):
    pass


@dataclass(frozen=True)
class ToolExecutionContext:
    job_id: str
    request_id: str | None
    parameters: dict[str, Any]
    entrypoint: dict[str, Any]
    resources: dict[str, Any]
    network: dict[str, Any]
    timeout_seconds: int


ToolExecutor = Callable[[ToolExecutionContext], Awaitable[dict[str, Any]]]


def validate_worker_resource_policy(job: ToolJob) -> None:
    manifest = getattr(getattr(job, "tool", None), "manifest", None)
    resources = getattr(manifest, "resources", None) or {}
    timeout_seconds = resources.get("timeout_seconds")
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1 or timeout_seconds > MAX_WORKER_TIMEOUT_SECONDS:
        raise ResourceLimitError("Tool resource limits exceed worker policy")
    if resources.get("cpu", 0) > MAX_WORKER_CPU or resources.get("memory_mb", 0) > MAX_WORKER_MEMORY_MB:
        raise ResourceLimitError("Tool resource limits exceed worker policy")


def build_execution_context(job: ToolJob, request_id: str | None = None) -> ToolExecutionContext:
    manifest = getattr(getattr(job, "tool", None), "manifest", None)
    resources = getattr(manifest, "resources", None) or {}
    return ToolExecutionContext(
        job_id=job.job_id,
        request_id=request_id,
        parameters=job.parameters or {},
        entrypoint=getattr(manifest, "entrypoint", None) or {},
        resources=resources,
        network=getattr(manifest, "network", None) or {},
        timeout_seconds=resources.get("timeout_seconds", MAX_WORKER_TIMEOUT_SECONDS),
    )


def safe_failure_reason(error: Exception) -> str:
    if isinstance(error, ToolTimeoutError):
        return "Tool execution timed out"
    if isinstance(error, ResourceLimitError):
        return "Tool resource limits exceed worker policy"
    return "Tool execution failed"


async def mark_job_running(db: AsyncSession, job: ToolJob) -> None:
    job.status = ToolJobStatus.RUNNING.value
    job.started_at = datetime.now(timezone.utc)
    await db.commit()


async def mark_job_succeeded(db: AsyncSession, job: ToolJob, result: dict[str, Any]) -> ToolJob:
    job.status = ToolJobStatus.SUCCEEDED.value
    job.result_summary = str(result.get("summary", "Tool execution completed"))[:1000]
    job.error_message = None
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()
    record_worker_job(ToolJobStatus.SUCCEEDED.value)
    return job


async def mark_job_failed(db: AsyncSession, job: ToolJob, status: str, error: Exception) -> ToolJob:
    job.status = status
    job.error_message = safe_failure_reason(error)
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()
    record_worker_job(status)
    return job


async def run_tool_job(db: AsyncSession, job: ToolJob, executor: ToolExecutor, request_id: str | None = None) -> ToolJob:
    if job.status != ToolJobStatus.QUEUED.value:
        return job
    try:
        validate_worker_resource_policy(job)
        await mark_job_running(db, job)
        context = build_execution_context(job, request_id=request_id)
        result = await executor(context)
        return await mark_job_succeeded(db, job, result)
    except ToolTimeoutError as error:
        return await mark_job_failed(db, job, ToolJobStatus.TIMEOUT.value, error)
    except ResourceLimitError as error:
        return await mark_job_failed(db, job, ToolJobStatus.FAILED.value, error)
    except Exception as error:
        return await mark_job_failed(db, job, ToolJobStatus.FAILED.value, error)
