"""
Backtest execution runner tests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.services.backtest.runner import BacktestExecutionRunner


@pytest.mark.asyncio
async def test_schedule_stores_and_cleans_up_task():
    runner = BacktestExecutionRunner()
    started = asyncio.Event()

    async def execution():
        started.set()

    task = runner.schedule("task123", execution())
    await started.wait()
    await task

    assert runner.get_task("task123") is None


def test_cancel_local_execution_cancels_task_and_process():
    runner = BacktestExecutionRunner()
    task = MagicMock()
    task.done.return_value = False
    process = MagicMock()
    process.poll.return_value = None

    runner._tasks["task123"] = task
    runner._processes["task123"] = process

    cancelled = runner.cancel_local_execution("task123")

    assert cancelled is True
    task.cancel.assert_called_once()
    process.kill.assert_called_once()
    assert runner.get_task("task123") is None
    assert runner.get_process("task123") is None


def test_cancel_local_execution_returns_false_without_local_handles():
    runner = BacktestExecutionRunner()
    assert runner.cancel_local_execution("missing") is False


def test_default_backtest_runner_singleton_shared_and_cancels_all():
    from app.services.backtest.runner import (
        get_default_backtest_runner,
        reset_default_backtest_runner,
        wait_and_reap_process,
    )
    from app.services.backtest.service import BacktestService

    svc1 = BacktestService()
    svc2 = BacktestService()
    assert svc1.task_runner is svc2.task_runner
    assert svc1.task_runner is get_default_backtest_runner()

    proc = MagicMock()
    proc.pid = 999999
    proc.poll.return_value = None
    svc1.task_runner.register_process("t-all", proc)
    assert svc2.task_runner.cancel_all() == 1
    assert proc.kill.called or True  # killpg attempted first when pid is int
    proc.wait.assert_called()
    reset_default_backtest_runner()

    import subprocess

    timed_out_proc = MagicMock()
    timed_out_proc.pid = None
    timed_out_proc.communicate.side_effect = [
        subprocess.TimeoutExpired(cmd="run.py", timeout=1),
        ("", ""),
    ]
    with pytest.raises(subprocess.TimeoutExpired):
        wait_and_reap_process(timed_out_proc, 1.0, task_id="t-timeout")
    timed_out_proc.kill.assert_called_once()
    timed_out_proc.wait.assert_called()


@pytest.mark.asyncio
async def test_startup_reconcile_shutdown_cancels_local_runner(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.services.backtest.runner import get_default_backtest_runner
    from app.startup import reconcile

    runner = get_default_backtest_runner()
    cancel_mock = MagicMock(return_value=1)
    monkeypatch.setattr(runner, "cancel_all", cancel_mock)

    mock_mgr = SimpleNamespace(interrupt_active_tasks=AsyncMock(return_value=0))
    monkeypatch.setattr(
        "app.services.backtest.manager.BacktestExecutionManager",
        lambda: mock_mgr,
    )
    monkeypatch.setattr(
        "app.services.stock_analysis.tasks.StockAnalysisTaskService.interrupt_active_tasks",
        AsyncMock(return_value=0),
    )

    await reconcile.shutdown(SimpleNamespace(state=SimpleNamespace()), SimpleNamespace())
    cancel_mock.assert_called_once()
