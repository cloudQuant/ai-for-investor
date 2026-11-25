"""Tracked background asyncio task helpers to prevent silent task drops."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def spawn_tracked_task(
    coro: Coroutine[Any, Any, Any],
    *,
    tasks: set[asyncio.Task[Any]] | None = None,
    name: str | None = None,
    task_logger: logging.Logger | None = None,
) -> asyncio.Task[Any]:
    """Schedule a background coroutine with a strong reference and exception logging."""
    target = tasks if tasks is not None else _BACKGROUND_TASKS
    task = asyncio.create_task(coro)
    if name is not None and isinstance(task, asyncio.Task):
        task.set_name(name)
    if not isinstance(task, asyncio.Task):
        return task
    target.add(task)
    active_logger = task_logger or logger

    def _on_done(done_task: asyncio.Task[Any]) -> None:
        target.discard(done_task)
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc is not None:
            active_logger.error(
                "Unhandled exception in background task %s",
                done_task.get_name() if hasattr(done_task, "get_name") else done_task,
                exc_info=exc,
            )

    task.add_done_callback(_on_done)
    return task


def get_tracked_tasks() -> set[asyncio.Task[Any]]:
    """Return the process-wide background task registry (primarily for inspection/tests)."""
    return _BACKGROUND_TASKS


async def cancel_tracked_tasks(tasks: set[asyncio.Task[Any]] | None = None) -> int:
    """Cancel and await all remaining tracked background tasks."""
    target = tasks if tasks is not None else _BACKGROUND_TASKS
    pending = [task for task in list(target) if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    target.clear()
    return len(pending)
