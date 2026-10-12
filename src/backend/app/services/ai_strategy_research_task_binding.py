"""Task-scoped research request binding and continuation helpers."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from app.schemas.ai_strategy_research import (
    AIStrategyResearchRunRequest,
    AIStrategyResearchTaskResponse,
)
from app.services.ai_strategy_research_task_projection import (
    _omit_sensitive_request_values,
    _redact_sensitive_values,
)

_MARKET_DATA_BINDING_KEY_PREFIX = "market_data_binding_"
_MARKET_DATA_RUNTIME_BINDING_KEY = "market_data_binding"
# A continuation is a rerun of a server-owned source, rather than a fresh
# request body. Keep the override surface small: source identity, lineage,
# research basis, and the internal improvement context are rebuilt below.
# ``prompt`` remains here only so the mandate gate can distinguish a browser's
# inherited prompt from an attempted new objective.
_CONTINUATION_OPERATIONAL_OVERRIDE_FIELDS = frozenset(
    {
        "prompt",
        "data_config",
        "gateway_config",
        "max_iterations",
        "backtest_timeout_seconds",
        "poll_interval_seconds",
        "start_paper_trading",
        "min_paper_trading_days",
        "paper_workspace_name",
        "trading_workspace_id",
    }
)


async def _prepare_research_task_request(
    task_id: str,
    request: AIStrategyResearchRunRequest,
    request_preparer: Callable[[str, AIStrategyResearchRunRequest], Any] | None,
) -> AIStrategyResearchRunRequest:
    """Run a server-only request preparer before task state is observable.

    A preparer must return a full request model.  Requiring a replacement
    instead of allowing an in-place mutation makes the exact prepared request
    the one that is snapshotted and dispatched to the background runner.
    """
    if request_preparer is None:
        return request
    prepared = request_preparer(task_id, request)
    if inspect.isawaitable(prepared):
        prepared = await prepared
    if not isinstance(prepared, AIStrategyResearchRunRequest):
        raise ValueError("AI_RESEARCH_REQUEST_PREPARATION_INVALID")
    return prepared


def _apply_market_data_research_task_binding_guard(
    request: AIStrategyResearchRunRequest,
) -> AIStrategyResearchRunRequest:
    """Apply the synchronous research binding guard before task state exists.

    The task endpoint has an additional request-preparation phase that can
    attach a task-scoped binding.  Once that phase has completed, its exact
    request must pass the same gate as a synchronous research call before the
    manager creates observable task state, dispatches background work, or
    persists a snapshot.
    """
    # Keep the rule in one place.  The lazy import also avoids constructing a
    # research service or adding an import cycle while this module is loaded.
    from app.services.ai_strategy_research_service import _apply_market_data_research_binding_guard

    return _apply_market_data_research_binding_guard(request)


def _continuation_request_from_task(
    task: AIStrategyResearchTaskResponse,
    overrides: dict[str, Any],
) -> AIStrategyResearchRunRequest:
    snapshot = task.request_snapshot if isinstance(task.request_snapshot, dict) else {}
    cleaned = _omit_sensitive_request_values(dict(snapshot))
    had_market_data_binding = _contains_market_data_binding_values(cleaned)
    payload = _strip_market_data_binding_values(cleaned)
    if not isinstance(payload, dict):
        payload = {}
    # Saved task snapshots only contain redacted gateway credentials, so they
    # cannot be safely reused. Fresh overrides may still provide a gateway_config.
    payload.pop("gateway_config", None)
    continuation_context = _task_continuation_context_for_submit(task)
    run_id = _task_continuation_run_id(task)
    source_continue_from_run_id = run_id or str(payload.get("continue_from_run_id") or "").strip()
    source_research_workspace_id = str(
        task.research_workspace_id or payload.get("research_workspace_id") or ""
    ).strip()
    source_seed_strategy_id = str(
        task.best_strategy_id or payload.get("seed_strategy_id") or ""
    ).strip()
    payload_data_config = payload.get("data_config")
    data_config = dict(payload_data_config) if isinstance(payload_data_config, dict) else {}
    market_data_continuation_intent: dict[str, Any] | None = None
    if had_market_data_binding:
        # A saved binding is scoped to the old task and has already been
        # removed above. Preserve only the declarative asset intent so an old
        # bound task cannot become a legacy CSV request through an override.
        # The fresh task preparer will validate that intent and issue a new
        # task-scoped binding when the bridge is enabled.
        market_data_continuation_intent = _market_data_continuation_intent(data_config)
        payload["data_config"] = market_data_continuation_intent
    elif task.asset_specs and "asset_specs" not in data_config:
        data_config["asset_specs"] = dict(task.asset_specs)
        payload["data_config"] = data_config
    if task.backtest_environment:
        unit_settings = dict(payload.get("unit_settings") or {})
        for key, value in dict(task.backtest_environment).items():
            unit_settings.setdefault(key, value)
        payload["unit_settings"] = unit_settings

    if continuation_context:
        payload["continuation_context"] = continuation_context
    else:
        payload.pop("continuation_context", None)
    # This is response metadata, never an input to the next research request.
    payload.pop("continuation_source", None)

    if not str(payload.get("symbol") or "").strip():
        symbol = _task_iteration_symbol(task)
        if symbol:
            payload["symbol"] = symbol
    if not str(payload.get("prompt") or "").strip():
        payload["prompt"] = _task_continuation_prompt(task)

    for key, value in (overrides or {}).items():
        if key not in _CONTINUATION_OPERATIONAL_OVERRIDE_FIELDS:
            continue
        if value is not None:
            if (
                key == "data_config"
                and market_data_continuation_intent is not None
                and not _is_market_data_continuation_intent(value)
            ):
                # Do not let an old bound snapshot silently fall back to a
                # legacy path. An exact asset-intent replacement remains
                # supported so the server can bind the new task to a new
                # market-data artifact.
                continue
            payload[key] = value

    # Client overrides must never redirect a continuation to another run,
    # workspace, strategy, or LLM feedback payload. Reapply all four from
    # server-persisted source state after the operational allowlist.
    if source_continue_from_run_id:
        payload["continue_from_run_id"] = source_continue_from_run_id
    else:
        payload.pop("continue_from_run_id", None)
    if source_research_workspace_id:
        payload["research_workspace_id"] = source_research_workspace_id
    else:
        payload.pop("research_workspace_id", None)
    if source_seed_strategy_id:
        payload["seed_strategy_id"] = source_seed_strategy_id
    else:
        payload.pop("seed_strategy_id", None)
    if continuation_context:
        payload["continuation_context"] = continuation_context
    else:
        payload.pop("continuation_context", None)

    request = AIStrategyResearchRunRequest.model_validate(payload)
    if not request.continue_from_run_id and not request.seed_strategy_id:
        raise ValueError("AI research task has no run or strategy snapshot to continue")
    return request


def _strip_market_data_binding_values(value: Any) -> Any:
    """Remove prior server-issued bindings before continuation overrides apply.

    A binding is scoped to one task intent and may encode a point-in-time
    cutoff.  Retaining it in a recovered snapshot would let a continuation
    reuse data authorized for an earlier task.  The API's fresh preparer will
    issue a replacement when the Iteration 197 bridge is enabled.
    """
    if isinstance(value, dict):
        return {
            key: _strip_market_data_binding_values(item)
            for key, item in value.items()
            if not _is_market_data_binding_key(key)
        }
    if isinstance(value, list):
        return [_strip_market_data_binding_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_strip_market_data_binding_values(item) for item in value)
    return value


def _contains_market_data_binding_values(value: Any) -> bool:
    """Return whether a recovered snapshot carries any task-scoped binding."""
    if isinstance(value, dict):
        return any(
            _is_market_data_binding_key(key) or _contains_market_data_binding_values(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_market_data_binding_values(item) for item in value)
    return False


def _market_data_continuation_intent(data_config: dict[str, Any]) -> dict[str, Any]:
    """Retain only fail-closed asset intent from a prior task binding."""
    asset_type = data_config.get("market_data_asset_type")
    if isinstance(asset_type, str):
        return {"market_data_asset_type": asset_type}
    # Malformed historical snapshots still need a bridge marker. With the
    # bridge disabled it produces MARKET_DATA_BRIDGE_DISABLED; with it enabled
    # the server-side binder rejects the blank intent instead of using legacy
    # CSV configuration from the recovered task.
    return {"market_data_asset_type": ""}


def _is_market_data_continuation_intent(value: Any) -> bool:
    """Allow only a complete replacement of the one safe continuation intent."""
    return (
        isinstance(value, dict)
        and set(value) == {"market_data_asset_type"}
        and isinstance(value.get("market_data_asset_type"), str)
    )


def _is_market_data_binding_key(key: Any) -> bool:
    """Recognize every task-scoped binding field retained in a snapshot."""
    normalized = str(key).casefold()
    return normalized == _MARKET_DATA_RUNTIME_BINDING_KEY or normalized.startswith(
        _MARKET_DATA_BINDING_KEY_PREFIX
    )


def _task_continuation_run_id(task: AIStrategyResearchTaskResponse) -> str:
    for value in (
        task.run_id,
        task.continued_from_run_id,
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _task_continuation_context_for_submit(
    task: AIStrategyResearchTaskResponse,
) -> dict[str, Any]:
    # Never inherit the prior request's arbitrary context. It may have been
    # supplied by a browser before this hard boundary existed. Every value
    # below comes from task state written by the task manager or research run.
    context: dict[str, Any] = {
        "source": _task_continuation_source(task),
        "task_id": task.task_id,
        "run_id": _task_continuation_run_id(task) or task.run_id,
        "task_status": task.status,
        "task_stage": task.current_stage,
        "quality_gate_failures": _task_continuation_failures(task),
        "metrics": _task_continuation_metrics(task),
    }
    if task.current_backtest_task_id:
        context["current_backtest_task_id"] = task.current_backtest_task_id
    if task.cancelled_backtest_task_id:
        context["cancelled_backtest_task_id"] = task.cancelled_backtest_task_id
    if task.pipeline:
        context["pipeline"] = dict(task.pipeline)
    return dict(_redact_sensitive_values(context))


def _task_continuation_source(task: AIStrategyResearchTaskResponse) -> str:
    stage = str(task.current_stage or "").strip()
    status = str(task.status or "").strip()
    if task.paper_review_status and not task.paper_review_ready_for_live:
        return "paper_review"
    if stage == "interrupted":
        return "research_interrupted"
    if status == "cancelled" or stage == "cancelled":
        return "research_cancelled"
    if stage == "paper_trading_failed":
        return "paper_trading_failed"
    return "research_failure"


def _task_continuation_failures(
    task: AIStrategyResearchTaskResponse,
) -> list[str]:
    failures: list[str] = []
    for source in (
        _task_iteration_list(task.best_iteration_payload, "quality_gate_failures"),
        _task_iteration_list(task.latest_iteration, "quality_gate_failures"),
        [task.error, task.message],
        task.paper_review_next_actions,
        task.next_actions,
    ):
        for item in source if isinstance(source, list) else [source]:
            text = str(item or "").strip()
            if text and text not in failures:
                failures.append(text)
    if not failures:
        failures.append(f"Previous AI research task ended with status {task.status}")
    return failures


def _task_continuation_metrics(task: AIStrategyResearchTaskResponse) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for value in (
        task.best_metrics,
        _task_iteration_mapping(task.best_iteration_payload, "metrics"),
        _task_iteration_mapping(task.latest_iteration, "metrics"),
    ):
        if isinstance(value, dict):
            metrics.update(value)
    return metrics


def _task_iteration_list(value: Any, key: str) -> list[Any]:
    if isinstance(value, dict) and isinstance(value.get(key), list):
        return list(value[key])
    return []


def _task_iteration_mapping(value: Any, key: str) -> dict[str, Any]:
    if isinstance(value, dict) and isinstance(value.get(key), dict):
        return dict(value[key])
    return {}


def _task_iteration_symbol(task: AIStrategyResearchTaskResponse) -> str:
    for payload in (task.best_iteration_payload, task.latest_iteration):
        if not isinstance(payload, dict):
            continue
        for container_key in ("unit_snapshot", "unit"):
            container = payload.get(container_key)
            if isinstance(container, dict):
                symbol = str(container.get("symbol") or "").strip()
                if symbol:
                    return symbol
    return ""


def _task_continuation_prompt(task: AIStrategyResearchTaskResponse) -> str:
    symbol = _task_iteration_symbol(task)
    suffix = f"（{symbol}）" if symbol else ""
    return f"继续优化中断或未完成的 AI 策略投研任务{suffix}"
