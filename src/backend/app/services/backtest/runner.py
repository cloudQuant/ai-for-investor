"""
Process-local execution runner for backtest tasks.

This runner only manages execution handles owned by the current API process.
Persistent task state remains the responsibility of ``BacktestExecutionManager``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import threading
from collections.abc import Awaitable

logger = logging.getLogger(__name__)


def kill_process_tree(process: subprocess.Popen, task_id: str) -> None:
    """Forcefully terminate a backtest subprocess process-group and reap it."""
    pid = getattr(process, "pid", None)
    if os.name != "nt" and isinstance(pid, int):
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError, AttributeError):
            try:
                process.kill()
            except Exception:  # pragma: no cover - defensive logging path
                logger.warning("Failed to kill subprocess for backtest %s", task_id, exc_info=True)
    else:
        try:
            process.kill()
        except Exception:  # pragma: no cover - defensive logging path
            logger.warning("Failed to kill subprocess for backtest %s", task_id, exc_info=True)
    try:
        process.wait(timeout=1)
    except Exception as exc:
        logger.debug("Process wait after kill failed for %s: %s", task_id, exc)


def wait_and_reap_process(
    process: subprocess.Popen,
    timeout_seconds: float,
    *,
    task_id: str | None = None,
) -> tuple[str, str]:
    """Wait for ``process`` output up to ``timeout_seconds``; kill group & reap on timeout."""
    label = task_id or "<unknown>"
    try:
        return process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        kill_process_tree(process, label)
        try:
            process.communicate(timeout=1)
        except Exception as exc:
            logger.debug("Process drain after timeout failed for %s: %s", label, exc)
        raise
    except BaseException:
        poll_fn = getattr(process, "poll", None)
        if callable(poll_fn) and poll_fn() is None:
            kill_process_tree(process, label)
        raise


class BacktestExecutionRunner:
    """Manage process-local asyncio tasks and subprocess handles."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._processes: dict[str, subprocess.Popen] = {}

    def schedule(self, task_id: str, execution: Awaitable[None]) -> asyncio.Task:
        """Schedule one local execution coroutine and retain its handle."""
        from app.utils.tracing import business_span

        async def _wrapped_execution() -> None:
            with business_span("backtrader.backtest.execute", backtest_id=task_id):
                try:
                    await execution
                finally:
                    current_task = asyncio.current_task()
                    if self._tasks.get(task_id) is current_task:
                        self._tasks.pop(task_id, None)

        task = asyncio.create_task(_wrapped_execution())
        self._tasks[task_id] = task
        return task

    def register_process(self, task_id: str, process: subprocess.Popen) -> None:
        """Register one subprocess handle for later cancellation."""
        self._processes[task_id] = process

    def unregister_process(self, task_id: str) -> None:
        """Forget a subprocess handle once execution finishes."""
        self._processes.pop(task_id, None)

    def get_task(self, task_id: str) -> asyncio.Task | None:
        """Return the process-local asyncio task for one backtest."""
        return self._tasks.get(task_id)

    def get_process(self, task_id: str) -> subprocess.Popen | None:
        """Return the process-local subprocess handle for one backtest."""
        return self._processes.get(task_id)

    def cancel_local_execution(self, task_id: str) -> bool:
        """Best-effort cancellation for execution owned by this process only."""
        task = self._tasks.pop(task_id, None)
        process = self._processes.pop(task_id, None)
        had_local_handle = task is not None or process is not None

        if task and not task.done():
            task.cancel()

        if process and process.poll() is None:
            kill_process_tree(process, task_id)

        return had_local_handle

    def cancel_all(self) -> int:
        """Cancel and kill all tracked local tasks and subprocesses."""
        task_ids = sorted(set(self._tasks) | set(self._processes))
        cancelled = 0
        for task_id in task_ids:
            if self.cancel_local_execution(task_id):
                cancelled += 1
        return cancelled


_DEFAULT_RUNNER_LOCK = threading.Lock()
_default_runner: BacktestExecutionRunner | None = None


def get_default_backtest_runner() -> BacktestExecutionRunner:
    """Return the process-wide default ``BacktestExecutionRunner`` singleton."""
    global _default_runner
    with _DEFAULT_RUNNER_LOCK:
        if _default_runner is None:
            _default_runner = BacktestExecutionRunner()
        return _default_runner


def reset_default_backtest_runner() -> None:
    """Cancel any active tasks/subprocesses and reset the singleton runner (tests)."""
    global _default_runner
    with _DEFAULT_RUNNER_LOCK:
        if _default_runner is not None:
            _default_runner.cancel_all()
        _default_runner = None
