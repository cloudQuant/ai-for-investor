"""Shared ownership and expiry checks for durable asset-research task leases."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.models.asset_research import AssetAnalysisTask


class TaskLeaseState(Enum):
    """Current database relationship between a task and a worker claim."""

    ACTIVE = "ACTIVE"
    LOST = "LOST"
    EXPIRED = "EXPIRED"


class TaskLeaseRejectedError(RuntimeError):
    """Stable lease rejection that callers can map into their task lifecycle."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate_task_lease(
    task: AssetAnalysisTask | None,
    *,
    lease_token: str,
    now: datetime,
) -> TaskLeaseState:
    """Classify a task lease using fresh state, token ownership, and UTC expiry."""
    if task is None or task.status != "RUNNING" or task.lease_token != lease_token:
        return TaskLeaseState.LOST
    if task.lease_expires_at is None or as_utc(task.lease_expires_at) <= as_utc(now):
        return TaskLeaseState.EXPIRED
    return TaskLeaseState.ACTIVE


async def require_active_task_lease(
    db: AsyncSession,
    *,
    task_id: str,
    lease_token: str,
    now: datetime,
) -> None:
    """Refresh and reject a claim whose status, token, or expiry no longer matches."""
    bind = db.bind
    if bind is None:
        raise TaskLeaseRejectedError("TASK_LEASE_STATE_UNAVAILABLE")
    sqlite_uses_static_pool = bind.dialect.name == "sqlite" and (
        (isinstance(bind, AsyncConnection) and isinstance(bind.engine.pool, StaticPool))
        or (isinstance(bind, AsyncEngine) and isinstance(bind.pool, StaticPool))
    )
    if sqlite_uses_static_pool:
        # The in-memory pytest database uses one StaticPool connection. Opening
        # a second session on that same connection while the worker has an
        # active transaction can deadlock, so refresh using the worker session.
        task = await db.get(AssetAnalysisTask, task_id, populate_existing=True)
    else:
        # A MySQL REPEATABLE READ transaction can keep seeing the first task row
        # version loaded by the worker, even with populate_existing=True. Use a
        # short independent session so cancellation and lease replacement
        # committed by another worker are visible before provider dispatch;
        # closing it releases the connection before any external I/O starts.
        session_bind = bind.engine if isinstance(bind, AsyncConnection) else bind
        async with AsyncSession(bind=session_bind, expire_on_commit=False) as lease_db:
            task = await lease_db.get(AssetAnalysisTask, task_id, populate_existing=True)
    state = validate_task_lease(task, lease_token=lease_token, now=now)
    if state is TaskLeaseState.LOST:
        raise TaskLeaseRejectedError("TASK_LEASE_LOST")
    if state is TaskLeaseState.EXPIRED:
        raise TaskLeaseRejectedError("TASK_LEASE_EXPIRED")


def release_task_lease(task: AssetAnalysisTask, *, lease_token: str) -> None:
    """Clear lease fields only when the supplied worker still owns the task."""
    if task.lease_token != lease_token:
        return
    task.lease_token = None
    task.lease_expires_at = None
    task.lease_heartbeat_at = None


def as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive DATETIME reads and aware production reads."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
