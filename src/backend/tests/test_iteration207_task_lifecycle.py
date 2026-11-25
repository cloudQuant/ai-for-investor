from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.db.database import async_session_maker
from app.models.backtest import BacktestTask
from app.models.overfitting_result import OverfittingResultModel
from app.models.user import User
from app.services.overfitting.service import OverfittingService
from app.utils.async_tasks import cancel_tracked_tasks, spawn_tracked_task


@pytest.mark.asyncio
async def test_tracked_task_registry_cancels_and_awaits_owned_tasks() -> None:
    tasks: set[asyncio.Task] = set()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def wait_forever() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = spawn_tracked_task(wait_forever(), tasks=tasks, name="iteration207-owned-task")
    await started.wait()
    assert tasks == {task}

    assert await cancel_tracked_tasks(tasks) == 1

    assert task.cancelled()
    assert cancelled.is_set()
    assert tasks == set()


@pytest.mark.asyncio
async def test_overfitting_restart_and_shutdown_settle_durable_active_tasks(auth_user) -> None:
    user, _headers = auth_user
    async with async_session_maker() as session:
        user_id = await session.scalar(select(User.id).where(User.username == user["username"]))
        backtest = BacktestTask(user_id=user_id, status="completed")
        session.add(backtest)
        await session.flush()
        result = OverfittingResultModel(
            task_id="iteration207-overfitting-lifecycle",
            backtest_id=backtest.id,
            user_id=user_id,
            status="running",
        )
        session.add(result)
        await session.commit()

    assert await OverfittingService.reconcile_orphaned_tasks() == 1
    async with async_session_maker() as session:
        stored = await session.scalar(
            select(OverfittingResultModel).where(
                OverfittingResultModel.task_id == "iteration207-overfitting-lifecycle"
            )
        )
        assert stored.status == "failed"
        assert "restarted" in stored.error_message
        stored.status = "running"
        await session.commit()

    assert await OverfittingService.interrupt_active_tasks() == 1
    async with async_session_maker() as session:
        stored = await session.scalar(
            select(OverfittingResultModel).where(
                OverfittingResultModel.task_id == "iteration207-overfitting-lifecycle"
            )
        )
        assert stored.status == "cancelled"
        assert "shutdown" in stored.error_message
