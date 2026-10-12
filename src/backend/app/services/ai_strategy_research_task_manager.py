"""Async task manager for long-running AI strategy research loops."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Callable
from typing import Any

from app.schemas.ai_strategy_research import (
    AIStrategyResearchRunRequest,
    AIStrategyResearchTaskResponse,
)
from app.services.ai_research_provenance import verify_ai_research_task_snapshot
from app.services.ai_strategy_research_task_binding import (
    _apply_market_data_research_task_binding_guard,
    _continuation_request_from_task,
    _prepare_research_task_request,
)
from app.services.ai_strategy_research_task_lifecycle import (
    _DEFAULT_MAX_TERMINAL_TASKS_PER_USER,
    _TERMINAL_TASK_STATUSES,
    AIStrategyResearchWorkspaceTaskSnapshotStore,
    _ResearchTaskState,
    _signed_task_response,
    _task_response_research_workspace_id,
    _utc_iso_now,
)
from app.services.ai_strategy_research_task_projection import (
    _best_iteration_for_task,
    _freshened_research_result_for_task,
    _freshened_task_response_for_read,
    _latest_iteration_for_task,
    _redacted_research_result_for_task,
    _research_progress_task_updates,
    _research_request_explicit_fields,
    _research_request_runtime_task_updates,
    _research_request_snapshot,
    _research_result_task_updates,
    _runner_accepts_progress_callback,
    _service_continuation_task_updates,
    _task_updates_with_best_iteration,
)
from app.services.ai_strategy_research_task_projection import (
    _omit_sensitive_request_values as _omit_sensitive_request_values,
)
from app.utils.logger import get_logger

_CANCEL_CLEANUP_TIMEOUT_SECONDS = 1.0
logger = get_logger(__name__)


class AIStrategyResearchTaskManager:
    """Track in-process AI research loop tasks for API polling."""

    def __init__(
        self,
        *,
        backtest_service_factory: Callable[[], Any] | None = None,
        task_snapshot_store: Any | None = None,
        max_terminal_tasks_per_user: int = _DEFAULT_MAX_TERMINAL_TASKS_PER_USER,
    ) -> None:
        self._tasks: dict[str, _ResearchTaskState] = {}
        self._lock = asyncio.Lock()
        self._backtest_service_factory = backtest_service_factory
        self._task_snapshot_store = task_snapshot_store
        self._max_terminal_tasks_per_user = max(int(max_terminal_tasks_per_user), 0)

    async def submit(
        self,
        user_id: str,
        request: AIStrategyResearchRunRequest,
        *,
        service: Any | None = None,
        request_preparer: Callable[[str, AIStrategyResearchRunRequest], Any] | None = None,
    ) -> AIStrategyResearchTaskResponse:
        """Create a task after an optional server-owned request preparation step.

        ``request_preparer`` receives the generated task id before any runtime
        details or persisted snapshot exist.  Iteration 197 uses this boundary
        to bind a strict local-only market-data artifact to the exact task; a
        failure therefore leaves no runnable task or stale snapshot behind.
        """
        task_id = str(uuid.uuid4())
        request = await _prepare_research_task_request(task_id, request, request_preparer)
        request = _apply_market_data_research_task_binding_guard(request)
        runtime_updates = _research_request_runtime_task_updates(request)
        runtime_updates.update(
            await _service_continuation_task_updates(
                service,
                user_id,
                request,
            )
        )
        response = AIStrategyResearchTaskResponse(
            task_id=task_id,
            status="pending",
            submitted_at=_utc_iso_now(),
            mandate_id=request.mandate_id,
            request_snapshot=_research_request_snapshot(request),
            request_explicit_fields=_research_request_explicit_fields(request),
            request_explicit_fields_persisted=True,
            # The envelope binds the concrete container ID.  Keeping it only
            # in request_snapshot would leave an otherwise recoverable task
            # unsigned until the background run reaches its final update.
            research_workspace_id=request.research_workspace_id,
            current_stage="queued",
            progress=0.0,
            max_iterations=request.max_iterations,
            message="AI research task submitted",
            **runtime_updates,
        )
        response = _signed_task_response(response, user_id=user_id)
        async with self._lock:
            self._tasks[task_id] = _ResearchTaskState(user_id=user_id, response=response)

        loop = asyncio.get_running_loop()
        background_task = loop.create_task(
            self._run_task(
                task_id,
                user_id,
                request,
                service=service,
                runtime_updates=runtime_updates,
            )
        )
        background_task.add_done_callback(
            lambda _: loop.create_task(self._prune_terminal_tasks(user_id))
        )
        async with self._lock:
            state = self._tasks.get(task_id)
            if state is not None:
                state.background_task = background_task
                response = state.response.model_copy(deep=True)
        await self._save_task_snapshot(user_id, response)
        return response

    async def get_task(
        self,
        user_id: str,
        task_id: str,
    ) -> AIStrategyResearchTaskResponse | None:
        memory_response: AIStrategyResearchTaskResponse | None = None
        async with self._lock:
            state = self._tasks.get(task_id)
            if state is not None and state.user_id == user_id:
                memory_response = _freshened_task_response_for_read(
                    state.response.model_copy(deep=True)
                )
        if memory_response is not None:
            # In-process state is server-owned, but retain the same signed
            # source contract as recovered snapshots once it has a research
            # workspace.  This also ensures continuation callers cannot
            # accidentally depend on unsigned response defaults.
            return _signed_task_response(memory_response, user_id=user_id)
        return await self._load_task_snapshot(user_id, task_id)

    async def list_tasks(
        self,
        user_id: str,
        *,
        active_only: bool = False,
        limit: int = 20,
    ) -> list[AIStrategyResearchTaskResponse]:
        async with self._lock:
            items = [
                _freshened_task_response_for_read(state.response.model_copy(deep=True))
                for state in self._tasks.values()
                if state.user_id == user_id
                and (not active_only or state.response.status not in _TERMINAL_TASK_STATUSES)
            ]
        persisted_items = await self._list_task_snapshots(
            user_id,
            active_only=active_only,
            limit=max(limit, 0),
        )
        items_by_id = {item.task_id: item for item in persisted_items}
        for item in items:
            items_by_id[item.task_id] = item
        items = list(items_by_id.values())
        items.sort(key=lambda item: item.submitted_at, reverse=True)
        return items[: max(limit, 0)]

    async def cancel_task(
        self,
        user_id: str,
        task_id: str,
    ) -> AIStrategyResearchTaskResponse | None:
        background_task: asyncio.Task[None] | None = None
        child_task_id: str | None = None
        async with self._lock:
            state = self._tasks.get(task_id)
            if state is None or state.user_id != user_id:
                return None
            if state.response.status in _TERMINAL_TASK_STATUSES:
                return state.response.model_copy(deep=True)
            background_task = state.background_task
            child_task_id = state.response.current_backtest_task_id
            state.response = _signed_task_response(
                state.response.model_copy(
                    update={
                        "status": "cancelled",
                        "completed_at": _utc_iso_now(),
                        "current_stage": "cancelled",
                        "message": "AI research task cancelled",
                    }
                ),
                user_id=state.user_id,
            )
            response = state.response.model_copy(deep=True)
        await self._save_task_snapshot(user_id, response)
        child_cancelled = False
        if child_task_id:
            child_cancelled = await self._cancel_child_backtest(child_task_id, user_id)
            await self._update_task(
                task_id,
                cancelled_backtest_task_id=child_task_id,
                child_cancelled=child_cancelled,
            )
        if background_task is not None and not background_task.done():
            background_task.cancel()
            await self._wait_for_cancel_cleanup(background_task)
        latest = await self.get_task(user_id, task_id)
        return latest or response

    async def continue_task(
        self,
        user_id: str,
        task_id: str,
        *,
        overrides: dict[str, Any] | None = None,
        service: Any | None = None,
        request_preparer: Callable[[str, AIStrategyResearchRunRequest], Any] | None = None,
    ) -> AIStrategyResearchTaskResponse | None:
        source_task = await self.get_task(user_id, task_id)
        if source_task is None:
            return None
        source_workspace_id = _task_response_research_workspace_id(source_task)
        if not source_workspace_id or not verify_ai_research_task_snapshot(
            source_task,
            user_id=user_id,
            workspace_id=source_workspace_id,
        ):
            raise ValueError("AI_RESEARCH_CONTINUATION_PROVENANCE_INVALID")
        request = _continuation_request_from_task(source_task, overrides or {})
        return await self.submit(
            user_id,
            request,
            service=service,
            request_preparer=request_preparer,
        )

    async def _run_task(
        self,
        task_id: str,
        user_id: str,
        request: AIStrategyResearchRunRequest,
        *,
        service: Any | None,
        runtime_updates: dict[str, Any],
    ) -> None:
        await self._update_task(
            task_id,
            status="running",
            **_research_progress_task_updates(
                {
                    "started_at": _utc_iso_now(),
                    "current_stage": "starting",
                    "progress": 1.0,
                    "max_iterations": request.max_iterations,
                    "message": "AI research task is running",
                },
                request,
                runtime_updates=runtime_updates,
            ),
        )
        try:
            runner = service
            if runner is None:
                from app.services.ai_strategy_research_service import AIStrategyResearchService

                runner = AIStrategyResearchService()

            async def progress_callback(payload: dict[str, Any]) -> None:
                await self._update_task(
                    task_id,
                    status="running",
                    **_research_progress_task_updates(
                        payload,
                        request,
                        runtime_updates=runtime_updates,
                    ),
                )

            if _runner_accepts_progress_callback(runner):
                result = await runner.run(
                    user_id,
                    request,
                    progress_callback=progress_callback,
                )
            else:
                result = await runner.run(user_id, request)
            result = _freshened_research_result_for_task(result)

            latest_iteration = _latest_iteration_for_task(result)
            best_iteration_payload = _best_iteration_for_task(result)
            paper_updates = _research_result_task_updates(result)
            task_result = _redacted_research_result_for_task(result)
            await self._update_task(
                task_id,
                status="completed",
                completed_at=_utc_iso_now(),
                run_id=result.run_id,
                research_workspace_id=result.research_workspace.id,
                current_stage=str((result.pipeline or {}).get("current_stage") or "completed"),
                progress=100.0,
                iteration_count=len(result.iterations),
                max_iterations=request.max_iterations,
                latest_iteration=latest_iteration,
                best_iteration_payload=best_iteration_payload,
                current_backtest_task_id=None,
                result=task_result,
                message=result.message,
                **paper_updates,
            )
        except asyncio.CancelledError:
            await self._update_task(
                task_id,
                status="cancelled",
                completed_at=_utc_iso_now(),
                current_stage="cancelled",
                message="AI research task cancelled",
            )
        except Exception as exc:
            await self._update_task(
                task_id,
                status="failed",
                completed_at=_utc_iso_now(),
                current_stage="failed",
                error=str(exc),
                message="AI research task failed",
            )

    async def _update_task(self, task_id: str, **updates: Any) -> None:
        snapshot_user_id: str | None = None
        snapshot_response: AIStrategyResearchTaskResponse | None = None
        async with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                return
            updates = _task_updates_with_best_iteration(state.response, updates)
            new_status = updates.get("status")
            if (
                state.response.status in _TERMINAL_TASK_STATUSES
                and new_status is not None
                and new_status != state.response.status
            ):
                return
            state.response = _signed_task_response(
                state.response.model_copy(update=updates),
                user_id=state.user_id,
            )
            self._prune_terminal_tasks_locked(state.user_id)
            snapshot_user_id = state.user_id
            snapshot_response = state.response.model_copy(deep=True)
        if snapshot_user_id is not None and snapshot_response is not None:
            await self._save_task_snapshot(snapshot_user_id, snapshot_response)

    async def _save_task_snapshot(
        self,
        user_id: str,
        response: AIStrategyResearchTaskResponse,
    ) -> None:
        store = self._task_snapshot_store
        if store is None:
            return
        saver = getattr(store, "save_task", None)
        if not callable(saver):
            return
        try:
            result = saver(user_id, response)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.opt(exception=True).warning(
                "Unable to persist AI research task snapshot {}", response.task_id
            )
            return

    async def _load_task_snapshot(
        self,
        user_id: str,
        task_id: str,
    ) -> AIStrategyResearchTaskResponse | None:
        store = self._task_snapshot_store
        if store is None:
            return None
        getter = getattr(store, "get_task", None)
        if not callable(getter):
            return None
        try:
            result = getter(user_id, task_id)
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            logger.opt(exception=True).warning(
                "Unable to load AI research task snapshot {}", task_id
            )
            return None
        if isinstance(result, AIStrategyResearchTaskResponse):
            return _freshened_task_response_for_read(result.model_copy(deep=True))
        return None

    async def _list_task_snapshots(
        self,
        user_id: str,
        *,
        active_only: bool,
        limit: int,
    ) -> list[AIStrategyResearchTaskResponse]:
        store = self._task_snapshot_store
        if store is None:
            return []
        lister = getattr(store, "list_tasks", None)
        if not callable(lister):
            return []
        try:
            result = lister(user_id, active_only=active_only, limit=limit)
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            logger.opt(exception=True).warning("Unable to list AI research task snapshots")
            return []
        if not isinstance(result, list):
            return []
        return [
            _freshened_task_response_for_read(item.model_copy(deep=True))
            for item in result
            if isinstance(item, AIStrategyResearchTaskResponse)
        ]

    async def _cancel_child_backtest(self, task_id: str, user_id: str) -> bool:
        try:
            service = self._backtest_service_factory() if self._backtest_service_factory else None
            if service is None:
                from app.services.backtest.service import BacktestService

                service = BacktestService()
            return bool(await service.cancel_task(task_id, user_id))
        except Exception:
            logger.opt(exception=True).warning("Unable to cancel child backtest task {}", task_id)
            return False

    async def _wait_for_cancel_cleanup(
        self,
        background_task: asyncio.Task[None],
    ) -> None:
        try:
            done, _ = await asyncio.wait(
                {background_task},
                timeout=_CANCEL_CLEANUP_TIMEOUT_SECONDS,
            )
        except Exception:
            return
        if background_task in done and not background_task.cancelled():
            # Retrieve an exception without re-raising it, matching the previous
            # shielded await while allowing caller cancellation to propagate.
            background_task.exception()

    async def _prune_terminal_tasks(self, user_id: str) -> None:
        async with self._lock:
            self._prune_terminal_tasks_locked(user_id)

    def _prune_terminal_tasks_locked(self, user_id: str) -> None:
        terminal_items: list[tuple[str, str]] = []
        for task_id, state in self._tasks.items():
            if state.user_id != user_id:
                continue
            if state.response.status not in _TERMINAL_TASK_STATUSES:
                continue
            background_task = state.background_task
            if background_task is not None and not background_task.done():
                continue
            terminal_items.append((state.response.submitted_at, task_id))

        if len(terminal_items) <= self._max_terminal_tasks_per_user:
            return

        terminal_items.sort(reverse=True)
        for _, task_id in terminal_items[self._max_terminal_tasks_per_user :]:
            self._tasks.pop(task_id, None)


_manager: AIStrategyResearchTaskManager | None = None


def get_ai_strategy_research_task_manager() -> AIStrategyResearchTaskManager:
    global _manager
    if _manager is None:
        _manager = AIStrategyResearchTaskManager(
            task_snapshot_store=AIStrategyResearchWorkspaceTaskSnapshotStore()
        )
    return _manager
