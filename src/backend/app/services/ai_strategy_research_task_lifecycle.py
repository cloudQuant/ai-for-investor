"""Persistence and recovery lifecycle for AI research task snapshots."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.schemas.ai_strategy_research import AIStrategyResearchTaskResponse
from app.services.ai_research_provenance import (
    sign_ai_research_task_snapshot,
    verify_ai_research_task_snapshot,
)
from app.services.ai_strategy_research_task_projection import (
    _freshened_task_response_for_read,
    _redact_sensitive_values,
)
from app.utils.logger import get_logger

_DEFAULT_MAX_TERMINAL_TASKS_PER_USER = 50
_TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}
logger = get_logger("app.services.ai_strategy_research_task_manager")


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _ResearchTaskState:
    user_id: str
    response: AIStrategyResearchTaskResponse
    background_task: asyncio.Task[None] | None = None


class AIStrategyResearchWorkspaceTaskSnapshotStore:
    """Persist completed/recoverable task snapshots in research workspace settings."""

    def __init__(
        self,
        *,
        workspace_service: Any | None = None,
        max_tasks_per_workspace: int = _DEFAULT_MAX_TERMINAL_TASKS_PER_USER,
    ) -> None:
        self._workspace_service = workspace_service
        self._max_tasks_per_workspace = max(int(max_tasks_per_workspace), 1)

    async def save_task(
        self,
        user_id: str,
        response: AIStrategyResearchTaskResponse,
    ) -> None:
        workspace_id = _task_response_research_workspace_id(response)
        if not workspace_id:
            return
        workspace_service = self._get_workspace_service()
        try:
            workspace = await workspace_service.get_workspace(workspace_id, user_id)
        except Exception:
            logger.opt(exception=True).warning(
                "Unable to load AI research task snapshot workspace {}", workspace_id
            )
            return
        if workspace is None:
            return

        settings = dict(getattr(workspace, "settings", None) or {})
        ai_research = dict(settings.get("ai_research") or {})
        # Redaction is part of the persisted representation.  Sign exactly
        # that final payload rather than the in-memory response, whose gateway
        # secrets and other redacted values would otherwise make verification
        # fail after a round-trip through workspace settings.
        task_payload = _signed_task_snapshot_payload(
            response,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        raw_tasks = ai_research.get("tasks")
        existing_tasks = (
            [dict(item) for item in raw_tasks if isinstance(item, dict)]
            if isinstance(raw_tasks, list)
            else []
        )
        tasks = [
            task_payload,
            *[
                item
                for item in existing_tasks
                if str(item.get("task_id") or "") != response.task_id
            ],
        ][: self._max_tasks_per_workspace]
        ai_research["last_task"] = task_payload
        ai_research["tasks"] = tasks

        try:
            from app.schemas.workspace import WorkspaceUpdate

            updated = await workspace_service.update_workspace(
                workspace_id,
                user_id,
                WorkspaceUpdate(settings={"ai_research": ai_research}),
            )
        except Exception:
            logger.opt(exception=True).warning(
                "Unable to update AI research task snapshot workspace {}", workspace_id
            )
            updated = None
        if updated is not None:
            return
        settings["ai_research"] = ai_research
        try:
            workspace.settings = settings
        except Exception:
            logger.opt(exception=True).warning(
                "Unable to assign AI research task snapshot settings for workspace {}", workspace_id
            )
            return

    async def get_task(
        self,
        user_id: str,
        task_id: str,
    ) -> AIStrategyResearchTaskResponse | None:
        task_id = str(task_id or "").strip()
        if not task_id:
            return None
        for workspace in await self._research_workspaces(user_id):
            response = _find_trusted_task_snapshot_in_workspace(
                workspace,
                user_id=user_id,
                task_id=task_id,
            )
            if response is not None:
                workspace_id = str(getattr(workspace, "id", "") or "").strip()
                # The helper above verified the exact raw persisted mapping
                # before Pydantic applied historical defaults. Re-verifying
                # this normalized response would compare a different payload
                # and reject legitimate snapshots merely because omitted
                # defaults were materialized. Recovery below re-signs any
                # server-derived state it returns.
                if not workspace_id:
                    return None
                recovered = _recovered_task_response_for_read(response)
                return _signed_task_response(recovered, user_id=user_id)
        return None

    async def list_tasks(
        self,
        user_id: str,
        *,
        active_only: bool = False,
        limit: int = 20,
    ) -> list[AIStrategyResearchTaskResponse]:
        responses: dict[str, AIStrategyResearchTaskResponse] = {}
        for workspace in await self._research_workspaces(user_id):
            for response in _task_snapshots_from_workspace(workspace):
                recovered = _recovered_task_response_for_read(response)
                if active_only and recovered.status in _TERMINAL_TASK_STATUSES:
                    continue
                current = responses.get(recovered.task_id)
                if current is None or _task_response_history_rank(
                    recovered
                ) > _task_response_history_rank(current):
                    responses[recovered.task_id] = recovered
        items = list(responses.values())
        items.sort(key=lambda item: item.submitted_at, reverse=True)
        return items[: max(limit, 0)]

    async def _research_workspaces(self, user_id: str) -> list[Any]:
        workspace_service = self._get_workspace_service()
        try:
            _, workspaces = await workspace_service.list_workspaces(
                user_id,
                skip=0,
                limit=100,
                workspace_type="research",
            )
        except Exception:
            logger.opt(exception=True).warning(
                "Unable to list AI research workspaces for task snapshot recovery"
            )
            return []
        return list(workspaces)

    def _get_workspace_service(self) -> Any:
        if self._workspace_service is None:
            from app.services.workspace_service import WorkspaceService

            self._workspace_service = WorkspaceService()
        return self._workspace_service


def _task_snapshot_payload(response: AIStrategyResearchTaskResponse) -> dict[str, Any]:
    payload = response.model_dump(mode="json")
    redacted = _redact_sensitive_values(payload)
    return dict(redacted) if isinstance(redacted, dict) else {}


def _signed_task_snapshot_payload(
    response: AIStrategyResearchTaskResponse,
    *,
    user_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    """Return the final redacted task payload with server provenance attached."""
    redacted_payload = _task_snapshot_payload(response)
    signed_payload = sign_ai_research_task_snapshot(
        redacted_payload,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    return dict(signed_payload) if isinstance(signed_payload, dict) else redacted_payload


def _signed_task_response(
    response: AIStrategyResearchTaskResponse,
    *,
    user_id: str,
) -> AIStrategyResearchTaskResponse:
    """Sign mutable server task state once its containing workspace is known."""
    workspace_id = _task_response_research_workspace_id(response)
    signed = sign_ai_research_task_snapshot(
        response,
        user_id=user_id,
        workspace_id=workspace_id or "",
    )
    return signed if isinstance(signed, AIStrategyResearchTaskResponse) else response


def _task_response_research_workspace_id(
    response: AIStrategyResearchTaskResponse,
) -> str | None:
    for value in (
        response.research_workspace_id,
        response.request_snapshot.get("research_workspace_id"),
    ):
        text = str(value or "").strip()
        if text:
            return text

    result = response.result
    if result is None:
        return None
    workspace = getattr(result, "research_workspace", None)
    workspace_id = str(getattr(workspace, "id", "") or "").strip()
    if workspace_id:
        return workspace_id
    record = getattr(result, "run_record", None)
    workspace_id = str(getattr(record, "research_workspace_id", "") or "").strip()
    return workspace_id or None


def _task_snapshots_from_workspace(workspace: Any) -> list[AIStrategyResearchTaskResponse]:
    settings = dict(getattr(workspace, "settings", None) or {})
    ai_research = settings.get("ai_research")
    if not isinstance(ai_research, dict):
        return []

    raw_tasks = ai_research.get("tasks")
    tasks = raw_tasks if isinstance(raw_tasks, list) else []
    responses_by_task_id: dict[str, AIStrategyResearchTaskResponse] = {}
    ordered_task_ids: list[str] = []
    for raw in [*tasks, ai_research.get("last_task")]:
        response = _coerce_task_snapshot(raw)
        if response is None:
            continue
        current = responses_by_task_id.get(response.task_id)
        if current is None:
            ordered_task_ids.append(response.task_id)
            responses_by_task_id[response.task_id] = response
            continue
        if _task_response_history_rank(response) > _task_response_history_rank(current):
            responses_by_task_id[response.task_id] = response

    responses = [responses_by_task_id[task_id] for task_id in ordered_task_ids]
    responses.sort(key=lambda item: item.submitted_at, reverse=True)
    return responses


def _find_task_snapshot_in_workspace(
    workspace: Any,
    task_id: str,
) -> AIStrategyResearchTaskResponse | None:
    target = str(task_id or "").strip()
    if not target:
        return None
    return next(
        (
            response
            for response in _task_snapshots_from_workspace(workspace)
            if response.task_id == target
        ),
        None,
    )


def _find_trusted_task_snapshot_in_workspace(
    workspace: Any,
    *,
    user_id: str,
    task_id: str,
) -> AIStrategyResearchTaskResponse | None:
    """Load one continuation source only after authenticating raw settings.

    Pydantic defaults are useful for rendering old history, but must not turn
    an unsigned or partially supplied JSON mapping into a trusted task.  Verify
    the exact stored payload against the outer workspace before deserializing.
    """
    target = str(task_id or "").strip()
    workspace_id = str(getattr(workspace, "id", "") or "").strip()
    if not target or not workspace_id:
        return None
    settings = dict(getattr(workspace, "settings", None) or {})
    ai_research = settings.get("ai_research")
    if not isinstance(ai_research, dict):
        return None
    raw_tasks = ai_research.get("tasks")
    candidates = (
        [*raw_tasks, ai_research.get("last_task")]
        if isinstance(raw_tasks, list)
        else [ai_research.get("last_task")]
    )
    trusted: list[AIStrategyResearchTaskResponse] = []
    for raw in candidates:
        if not isinstance(raw, dict) or str(raw.get("task_id") or "").strip() != target:
            continue
        if not verify_ai_research_task_snapshot(
            raw,
            user_id=user_id,
            workspace_id=workspace_id,
        ):
            continue
        response = _coerce_task_snapshot(raw)
        if response is not None:
            trusted.append(response)
    if not trusted:
        return None
    return max(trusted, key=_task_response_history_rank)


def _coerce_task_snapshot(raw: Any) -> AIStrategyResearchTaskResponse | None:
    if not isinstance(raw, dict):
        return None
    try:
        return AIStrategyResearchTaskResponse.model_validate(raw)
    except Exception:
        logger.opt(exception=True).warning("Discarding invalid persisted AI research task snapshot")
        return None


def _recovered_task_response_for_read(
    response: AIStrategyResearchTaskResponse,
) -> AIStrategyResearchTaskResponse:
    response = _freshened_task_response_for_read(response.model_copy(deep=True))
    if response.status in _TERMINAL_TASK_STATUSES:
        return response
    continuation_context = _interrupted_task_continuation_context(response)
    has_strategy_snapshot = _task_has_reusable_strategy_snapshot(response)
    next_actions = list(response.next_actions or [])
    if not next_actions:
        if has_strategy_snapshot:
            next_actions = [
                "AI research task was interrupted before completion; continue research from the latest saved strategy snapshot."
            ]
        else:
            next_actions = [
                "AI research task was interrupted before the first reusable strategy snapshot; restart research from the saved request."
            ]
    message = (
        "AI research task interrupted before completion; submit a continuation task "
        "from the latest run record."
        if has_strategy_snapshot
        else (
            "AI research task interrupted before a reusable strategy snapshot was saved; "
            "restart research from the saved request."
        )
    )
    return response.model_copy(
        update={
            "status": "failed",
            "completed_at": response.completed_at or _utc_iso_now(),
            "current_stage": "interrupted",
            "current_backtest_task_id": None,
            "continuation_source": "research_interrupted",
            "continuation_context": continuation_context,
            "error": response.error or "AI research task interrupted before completion",
            "message": message,
            "pipeline": _interrupted_task_pipeline(response),
            "next_actions": next_actions,
        }
    )


def _task_has_reusable_strategy_snapshot(response: AIStrategyResearchTaskResponse) -> bool:
    return bool(
        response.best_strategy_id or response.best_iteration_payload or response.latest_iteration
    )


def _interrupted_task_pipeline(response: AIStrategyResearchTaskResponse) -> dict[str, Any]:
    pipeline = dict(response.pipeline or {})
    pipeline["current_stage"] = "interrupted"
    pipeline["status"] = "failed"
    pipeline["progress"] = response.progress
    pipeline["interrupted_task_id"] = response.task_id
    if response.run_id:
        pipeline["interrupted_run_id"] = response.run_id
    if response.current_backtest_task_id:
        pipeline["interrupted_backtest_task_id"] = response.current_backtest_task_id
    return pipeline


def _interrupted_task_continuation_context(
    response: AIStrategyResearchTaskResponse,
) -> dict[str, Any]:
    context = dict(response.continuation_context or {})
    pipeline = _interrupted_task_pipeline(response)
    failures = []
    for value in (
        response.error,
        response.message,
        "AI research task interrupted before completion",
    ):
        text = str(value or "").strip()
        if text and text not in failures:
            failures.append(text)
    context.update(
        {
            "source": "research_interrupted",
            "run_id": response.run_id,
            "task_id": response.task_id,
            "interrupted_stage": str(response.current_stage or "").strip() or None,
            "interrupted_backtest_task_id": response.current_backtest_task_id,
            "quality_gate_failures": failures,
            "pipeline": pipeline,
        }
    )
    return _redact_sensitive_values(context)


def _task_response_history_rank(response: AIStrategyResearchTaskResponse) -> tuple[Any, ...]:
    status_rank = {
        "completed": 5,
        "cancelled": 4,
        "failed": 3,
        "running": 2,
        "pending": 1,
    }.get(response.status, 0)
    return (
        status_rank,
        1 if response.result is not None else 0,
        response.completed_at or "",
        response.started_at or "",
        response.submitted_at,
    )
