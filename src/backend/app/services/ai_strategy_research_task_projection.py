"""Task response status projection, redaction, and runtime summaries."""

from __future__ import annotations

import inspect
import typing
from typing import Any

from app.schemas.ai_strategy_research import (
    AIStrategyLiveHandoffApprovalRecord,
    AIStrategyLiveHandoffPackage,
    AIStrategyResearchRunRequest,
    AIStrategyResearchRunResponse,
    AIStrategyResearchTaskResponse,
)
from app.utils.logger import get_logger

_SENSITIVE_REQUEST_KEYS = (
    "api_key",
    "apikey",
    "access_key",
    "password",
    "passphrase",
    "auth_code",
    "credential",
    "secret",
    "token",
    "authorization",
)
_SENSITIVE_REQUEST_OMITTED = object()
logger = get_logger("app.services.ai_strategy_research_task_manager")


def _runner_accepts_progress_callback(runner: Any) -> bool:
    try:
        signature = inspect.signature(runner.run)
    except (TypeError, ValueError):
        return False
    return any(
        name == "progress_callback" or param.kind == inspect.Parameter.VAR_KEYWORD
        for name, param in signature.parameters.items()
    )


def _research_progress_task_updates(
    payload: dict[str, Any],
    request: AIStrategyResearchRunRequest,
    *,
    runtime_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updates = dict(payload)
    for key, value in (runtime_updates or {}).items():
        if isinstance(updates.get(key), dict) and updates[key]:
            continue
        if isinstance(value, dict) and value:
            updates[key] = dict(value)
    if not isinstance(updates.get("pipeline"), dict):
        updates["pipeline"] = _research_progress_pipeline(updates, request)
    redacted = _redact_sensitive_values(updates)
    return dict(redacted) if isinstance(redacted, dict) else updates


def _research_request_runtime_task_updates(
    request: AIStrategyResearchRunRequest,
) -> dict[str, Any]:
    continuation_updates = _research_request_continuation_task_updates(request)
    try:
        if typing.TYPE_CHECKING:
            from app.services.research.generation import _summarize_asset_specs_for_prompt
            from app.services.research.run_records import (
                _request_backtest_environment,
                _resolve_research_asset_specs,
            )
        else:
            from app.services.ai_strategy_research_service import (
                _request_backtest_environment,
                _resolve_research_asset_specs,
                _summarize_asset_specs_for_prompt,
            )

        asset_specs = _resolve_research_asset_specs(request)
        backtest_environment = _request_backtest_environment(request, asset_specs)
        updates: dict[str, Any] = {}
        if asset_specs:
            updates["asset_specs"] = _summarize_asset_specs_for_prompt(asset_specs)
        if backtest_environment:
            updates["backtest_environment"] = backtest_environment
        updates.update(continuation_updates)
        return updates
    except Exception:
        logger.opt(exception=True).warning(
            "Unable to resolve AI research runtime metadata; using request defaults"
        )
        return {
            **continuation_updates,
            "backtest_environment": {
                "initial_cash": request.initial_cash,
                "commission": request.commission,
                "commission_source": "request_default",
                "annual_days": request.annual_days,
                "calc_method": request.calc_method,
                "weight_mode": request.weight_mode,
                **({"start_date": request.start_date} if request.start_date else {}),
                **({"end_date": request.end_date} if request.end_date else {}),
            },
        }


async def _service_continuation_task_updates(
    service: Any | None,
    user_id: str,
    request: AIStrategyResearchRunRequest,
) -> dict[str, Any]:
    if service is None:
        return {}
    provider = getattr(service, "continuation_task_updates", None)
    if not callable(provider):
        return {}
    try:
        result = provider(user_id, request)
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        logger.opt(exception=True).warning("Unable to load AI research continuation metadata")
        return {}
    if not isinstance(result, dict) or not result:
        return {}
    redacted = _redact_sensitive_values(result)
    return dict(redacted) if isinstance(redacted, dict) else {}


def _research_request_continuation_task_updates(
    request: AIStrategyResearchRunRequest,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    continued_from = str(request.continue_from_run_id or "").strip()
    if continued_from:
        updates["continued_from_run_id"] = continued_from
    if isinstance(request.continuation_context, dict) and request.continuation_context:
        redacted = _redact_sensitive_values(dict(request.continuation_context))
        if isinstance(redacted, dict) and redacted:
            updates["continuation_context"] = redacted
            source = str(redacted.get("source") or "").strip()
            if source:
                updates["continuation_source"] = source
    return updates


def _research_progress_pipeline(
    payload: dict[str, Any],
    request: AIStrategyResearchRunRequest,
) -> dict[str, Any]:
    stage = str(payload.get("current_stage") or "running")
    progress = _optional_float(payload.get("progress")) or 0.0
    iteration_count = _optional_int(payload.get("iteration_count")) or 0
    current_iteration = _optional_int(payload.get("current_iteration"))
    max_iterations = _optional_int(payload.get("max_iterations")) or request.max_iterations
    paper_trading_error = _paper_trading_error_from_progress(payload)
    validation_status = _progress_validation_status(payload)
    robustness_status = _progress_robustness_status(payload)
    steps = [
        {"key": "draft", "label": "策略生成", "status": _draft_step_status(stage)},
        {
            "key": "backtest_loop",
            "label": "自动回测迭代",
            "status": _backtest_step_status(stage),
            "iteration_count": iteration_count,
            "current_iteration": current_iteration,
            "max_iterations": max_iterations,
        },
        {
            "key": "validation",
            "label": "样本外验证",
            "status": _validation_step_status(
                stage,
                request=request,
                validation_status=validation_status,
                iteration_count=iteration_count,
            ),
            "validation_status": validation_status,
        },
        {
            "key": "robustness_validation",
            "label": "稳健性验证",
            "status": _robustness_step_status(
                stage,
                request=request,
                robustness_status=robustness_status,
                iteration_count=iteration_count,
            ),
            "robustness_status": robustness_status,
        },
        {"key": "quality_gate", "label": "质量门槛", "status": _quality_step_status(stage)},
        {
            "key": "paper_trading",
            "label": "模拟交易",
            "status": _paper_step_status(stage),
            "error": paper_trading_error,
        },
        {"key": "paper_review", "label": "模拟复核", "status": _review_step_status(stage)},
        {"key": "live_handoff", "label": "实盘交接", "status": _live_handoff_step_status(stage)},
        {
            "key": "live_trading_prepare",
            "label": "实盘准备",
            "status": _live_prepare_step_status(stage),
        },
    ]
    return {
        "current_stage": stage,
        "status": "configuration_invalid" if stage == "configuration_invalid" else "running",
        "progress": progress,
        "paper_trading_error": paper_trading_error,
        "steps": steps,
    }


def _progress_validation_status(payload: dict[str, Any]) -> str | None:
    latest = payload.get("latest_iteration")
    if not isinstance(latest, dict):
        return None
    status = str(latest.get("validation_status") or "").strip()
    return status or None


def _progress_robustness_status(payload: dict[str, Any]) -> str | None:
    latest = payload.get("latest_iteration")
    if not isinstance(latest, dict):
        return None
    status = str(latest.get("robustness_status") or "").strip()
    return status or None


def _draft_step_status(stage: str) -> str:
    if stage in {"draft_generation_failed"}:
        return "failed"
    if stage in {"drafting", "repairing_code"}:
        return "running"
    if stage in {"queued", "starting", "initializing", "workspace_ready", "configuration_invalid"}:
        return "pending"
    return "completed"


def _backtest_step_status(stage: str) -> str:
    if stage in {"backtest_submission_failed", "backtest_failed", "backtest_timeout"}:
        return "failed"
    if stage in {"backtesting", "validating", "robustness_validation", "evaluating", "improving"}:
        return "running"
    if stage in {
        "quality_achieved",
        "paper_trading",
        "paper_trading_failed",
        "paper_review",
        "live_candidate",
        "live_handoff",
        "live_trading_prepare",
        "completed",
    }:
        return "completed"
    return "pending"


def _validation_step_status(
    stage: str,
    *,
    request: AIStrategyResearchRunRequest,
    validation_status: str | None,
    iteration_count: int,
) -> str:
    if not request.out_of_sample_validation:
        return "skipped"
    normalized = str(validation_status or "").strip()
    if normalized == "passed":
        return "completed"
    if normalized == "failed":
        return "failed"
    if normalized in {"skipped", "not_required"}:
        return "skipped"
    if stage == "configuration_invalid":
        return "failed"
    if stage == "validating":
        return "running"
    if stage == "cancelled":
        return "cancelled"
    if iteration_count <= 0 or stage in {"queued", "starting", "initializing", "workspace_ready"}:
        return "pending"
    return "pending"


def _robustness_step_status(
    stage: str,
    *,
    request: AIStrategyResearchRunRequest,
    robustness_status: str | None,
    iteration_count: int,
) -> str:
    if not request.robustness_validation:
        return "skipped"
    normalized = str(robustness_status or "").strip()
    if normalized == "passed":
        return "completed"
    if normalized == "failed":
        return "failed"
    if stage == "configuration_invalid":
        return "failed"
    if stage == "robustness_validation":
        return "running"
    if stage == "cancelled":
        return "cancelled"
    if iteration_count <= 0 or stage in {"queued", "starting", "initializing", "workspace_ready"}:
        return "pending"
    return "pending"


def _quality_step_status(stage: str) -> str:
    if stage == "configuration_invalid":
        return "failed"
    if stage in {
        "quality_achieved",
        "paper_trading",
        "paper_review",
        "live_candidate",
        "live_handoff",
        "live_trading_prepare",
        "completed",
    }:
        return "completed"
    if stage in {"backtest_submission_failed", "backtest_failed", "backtest_timeout"}:
        return "failed"
    if stage in {"backtesting", "validating", "robustness_validation", "evaluating", "improving"}:
        return "running"
    return "pending"


def _paper_step_status(stage: str) -> str:
    if stage == "paper_trading_failed":
        return "failed"
    if stage == "paper_trading":
        return "running"
    if stage in {
        "paper_review",
        "live_candidate",
        "live_handoff",
        "live_trading_prepare",
        "completed",
    }:
        return "completed"
    return "pending"


def _review_step_status(stage: str) -> str:
    if stage == "paper_review":
        return "running"
    if stage in {"live_candidate", "live_handoff", "live_trading_prepare"}:
        return "completed"
    return "pending"


def _live_handoff_step_status(stage: str) -> str:
    if stage == "live_handoff":
        return "running"
    if stage == "live_trading_prepare":
        return "completed"
    return "pending"


def _live_prepare_step_status(stage: str) -> str:
    if stage == "live_trading_prepare":
        return "completed"
    return "pending"


def _paper_trading_error_from_progress(payload: dict[str, Any]) -> str | None:
    if str(payload.get("current_stage") or "") != "paper_trading_failed":
        return None
    message = str(payload.get("message") or "").strip()
    prefix = "Paper trading start failed:"
    if message.startswith(prefix):
        return message[len(prefix) :].strip() or message
    return message or "Paper trading start failed"


def _research_result_task_updates(result: Any) -> dict[str, Any]:
    """Build task-level paper trading and pipeline summary from a completed run."""

    record = _freshened_research_run_record(getattr(result, "run_record", None))
    paper_trading = getattr(result, "paper_trading", None)
    paper_workspace = getattr(paper_trading, "workspace", None)
    paper_unit = getattr(paper_trading, "unit", None)
    paper_handoff = getattr(paper_trading, "handoff", None)
    best_strategy = getattr(result, "best_strategy", None)

    record_handoff = getattr(record, "paper_handoff", None)
    handoff = _redact_sensitive_values(_merged_non_empty_dict(record_handoff, paper_handoff))
    record_monitoring_plan = getattr(record, "paper_monitoring_plan", None)
    result_monitoring_plan = getattr(result, "paper_monitoring_plan", None)
    monitoring_plan = _first_non_empty_list(record_monitoring_plan, result_monitoring_plan)
    record_pipeline = getattr(record, "pipeline", None)
    result_pipeline = getattr(result, "pipeline", None)
    pipeline = _first_non_empty_dict(record_pipeline, result_pipeline)
    record_next_actions = getattr(record, "next_actions", None)
    result_next_actions = getattr(result, "next_actions", None)
    next_actions = _first_non_empty_list(record_next_actions, result_next_actions)
    promotion_audit = _first_non_empty_list(
        getattr(record, "promotion_audit", None),
        getattr(result, "promotion_audit", None),
    )
    best_metrics = _first_non_empty_dict(
        getattr(record, "best_metrics", None),
        getattr(result, "best_metrics", None),
    )
    best_quality_gate_evaluations = _first_non_empty_list(
        getattr(record, "best_quality_gate_evaluations", None),
        getattr(result, "best_quality_gate_evaluations", None),
    )
    robustness_validation = _first_non_empty_dict(
        getattr(record, "robustness_validation", None),
        getattr(result, "robustness_validation", None),
        handoff.get("robustness_validation"),
    )
    best_diagnostics = _first_non_empty_dict(
        getattr(record, "best_diagnostics", None),
        getattr(result, "best_diagnostics", None),
    )
    asset_specs = _merged_non_empty_dict(
        getattr(record, "asset_specs", None),
        handoff.get("asset_specs"),
    )
    backtest_environment = _merged_non_empty_dict(
        getattr(record, "backtest_environment", None),
        handoff.get("backtest_environment"),
    )
    live_handoff = _redacted_model_for_task(
        getattr(record, "live_handoff", None),
        AIStrategyLiveHandoffPackage,
    )
    live_handoff_approval = _redacted_model_for_task(
        getattr(record, "live_handoff_approval", None),
        AIStrategyLiveHandoffApprovalRecord,
    )
    continuation_updates = _research_record_continuation_task_updates(record)
    timeout_cancel_updates = _backtest_timeout_cancel_task_updates(record, result)

    updates = {
        "run_status": getattr(record, "status", None) or getattr(result, "status", None),
        "achieved": _optional_bool(
            getattr(record, "achieved", None),
            getattr(result, "achieved", None),
        ),
        "target_sharpe": _optional_float(
            getattr(record, "target_sharpe", None),
            getattr(result, "target_sharpe", None),
        ),
        "best_iteration": _optional_int(
            getattr(record, "best_iteration", None),
            getattr(result, "best_iteration", None),
        ),
        "best_sharpe": _optional_float(
            getattr(record, "best_sharpe", None),
            _metric_float(best_metrics, "sharpe_ratio", "sharpe"),
        ),
        "best_quality_score": _optional_float(
            getattr(record, "best_quality_score", None),
            getattr(result, "best_quality_score", None),
        ),
        "best_quality_gate_evaluations": best_quality_gate_evaluations,
        "robustness_validation": robustness_validation,
        "best_diagnostics": best_diagnostics,
        "best_metrics": best_metrics,
        "best_strategy_id": getattr(record, "best_strategy_id", None)
        or getattr(best_strategy, "id", None),
        "best_strategy_name": getattr(record, "best_strategy_name", None)
        or getattr(best_strategy, "name", None),
        "asset_specs": asset_specs,
        "backtest_environment": backtest_environment,
        "paper_workspace_id": getattr(record, "paper_workspace_id", None)
        or getattr(paper_workspace, "id", None),
        "paper_workspace_name": getattr(record, "paper_workspace_name", None)
        or getattr(paper_workspace, "name", None)
        or handoff.get("paper_workspace_name"),
        "paper_unit_id": getattr(record, "paper_unit_id", None) or getattr(paper_unit, "id", None),
        "paper_trading_started": _paper_trading_started_for_task(
            record,
            paper_trading,
            pipeline,
        ),
        "paper_monitoring_plan": monitoring_plan,
        "paper_handoff": handoff,
        "paper_review_status": getattr(record, "paper_review_status", None),
        "paper_review_ready_for_live": bool(getattr(record, "paper_review_ready_for_live", False)),
        "paper_reviewed_at": getattr(record, "paper_reviewed_at", None),
        "paper_review_evaluations": _first_non_empty_list(
            getattr(record, "paper_review_evaluations", None),
        ),
        "paper_review_next_actions": _first_non_empty_list(
            getattr(record, "paper_review_next_actions", None),
        ),
        "live_readiness_checklist": _first_non_empty_list(
            getattr(record, "live_readiness_checklist", None),
            pipeline.get("live_readiness_checklist"),
            handoff.get("live_readiness_checklist"),
        ),
        "live_readiness_expires_at": getattr(record, "live_readiness_expires_at", None)
        or pipeline.get("live_readiness_expires_at")
        or handoff.get("live_readiness_expires_at"),
        "live_handoff": live_handoff,
        "live_handoff_approval": live_handoff_approval,
        "live_workspace_id": getattr(record, "live_workspace_id", None)
        or pipeline.get("live_workspace_id"),
        "live_workspace_name": getattr(record, "live_workspace_name", None)
        or pipeline.get("live_workspace_name"),
        "live_unit_id": getattr(record, "live_unit_id", None) or pipeline.get("live_unit_id"),
        "live_trading_prepared": bool(
            getattr(record, "live_trading_prepared", False) or pipeline.get("live_trading_prepared")
        ),
        "live_trading_prepared_at": getattr(record, "live_trading_prepared_at", None)
        or pipeline.get("live_trading_prepared_at")
        or _live_prepare_step_prepared_at(pipeline),
        "pipeline": pipeline,
        "promotion_audit": promotion_audit,
        "next_actions": next_actions,
    }
    updates.update(timeout_cancel_updates)
    updates.update(continuation_updates)
    return updates


def _task_updates_with_best_iteration(
    response: AIStrategyResearchTaskResponse,
    updates: dict[str, Any],
) -> dict[str, Any]:
    if "best_iteration_payload" in updates:
        return updates
    latest_iteration = updates.get("latest_iteration")
    if not isinstance(latest_iteration, dict):
        return updates
    candidate = _redact_sensitive_values(dict(latest_iteration))
    if not isinstance(candidate, dict):
        return updates
    current = (
        dict(response.best_iteration_payload)
        if isinstance(response.best_iteration_payload, dict)
        else None
    )
    if current is None or _task_iteration_payload_rank(candidate) > _task_iteration_payload_rank(
        current
    ):
        updates = dict(updates)
        updates["best_iteration_payload"] = candidate
    return updates


def _task_iteration_payload_rank(payload: dict[str, Any]) -> tuple[int, float, float, int, int]:
    metrics = payload.get("metrics")
    metric_payload = dict(metrics) if isinstance(metrics, dict) else {}
    passed = _payload_truthy(payload.get("passed"))
    quality_score = _optional_float(payload.get("quality_score")) or 0.0
    sharpe = _optional_float(payload.get("sharpe_ratio"))
    if sharpe is None:
        sharpe = _metric_float(metric_payload, "sharpe_ratio", "sharpe", "sharpeRatio")
    total_trades = _optional_int(payload.get("total_trades"))
    if total_trades is None:
        total_trades = _optional_int(metric_payload.get("total_trades"))
    if total_trades is None:
        total_trades = _optional_int(metric_payload.get("trades"))
    iteration = _optional_int(payload.get("iteration")) or 0
    return (
        1 if passed else 0,
        quality_score,
        sharpe or 0.0,
        total_trades or 0,
        -iteration,
    )


def _payload_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "passed"}
    return bool(value)


def _latest_iteration_for_task(result: AIStrategyResearchRunResponse) -> dict[str, Any] | None:
    if not result.iterations:
        return None
    payload = result.iterations[-1].model_dump(mode="json")
    redacted = _redact_sensitive_values(payload)
    return dict(redacted) if isinstance(redacted, dict) else None


def _best_iteration_for_task(result: AIStrategyResearchRunResponse) -> dict[str, Any] | None:
    if not result.iterations:
        return None
    best_iteration = result.best_iteration
    matched = next(
        (item for item in result.iterations if item.iteration == best_iteration),
        None,
    )
    item = matched or max(
        result.iterations,
        key=lambda iteration: (
            bool(iteration.passed),
            float(iteration.quality_score or 0.0),
            float(iteration.sharpe_ratio or 0.0),
            int(iteration.total_trades or 0),
            -int(iteration.iteration or 0),
        ),
    )
    payload = item.model_dump(mode="json")
    redacted = _redact_sensitive_values(payload)
    return dict(redacted) if isinstance(redacted, dict) else None


def _backtest_timeout_cancel_task_updates(record: Any, result: Any) -> dict[str, Any]:
    for status in _latest_iteration_statuses(record, result):
        snapshot = _status_trading_snapshot(status)
        if not snapshot:
            continue
        task_id = str(snapshot.get("backtest_timeout_task_id") or "").strip()
        if not task_id:
            continue
        return {
            "cancelled_backtest_task_id": task_id,
            "child_cancelled": bool(snapshot.get("backtest_timeout_cancel_requested")),
        }
    return {}


def _latest_iteration_statuses(record: Any, result: Any) -> list[Any]:
    statuses: list[Any] = []
    for source in (getattr(record, "iterations", None), getattr(result, "iterations", None)):
        if not isinstance(source, list):
            continue
        for item in reversed(source):
            for key in ("validation_unit_status", "unit_status"):
                if isinstance(item, dict):
                    status = item.get(key)
                else:
                    status = getattr(item, key, None)
                if status is not None:
                    statuses.append(status)
    return statuses


def _live_prepare_step_prepared_at(pipeline: dict[str, Any]) -> str | None:
    steps = pipeline.get("steps")
    if not isinstance(steps, list):
        return None
    for step in reversed(steps):
        if not isinstance(step, dict):
            continue
        if str(step.get("key") or "") != "live_trading_prepare":
            continue
        prepared_at = step.get("prepared_at")
        if prepared_at is None:
            return None
        return str(prepared_at).strip() or None
    return None


def _paper_trading_started_for_task(
    record: Any,
    paper_trading: Any,
    pipeline: dict[str, Any],
) -> bool:
    stage = str(pipeline.get("current_stage") or "").strip()
    error = str(pipeline.get("paper_trading_error") or "").strip()
    if stage == "paper_trading_failed" or error:
        return False
    return bool(
        getattr(record, "paper_trading_started", False) or getattr(paper_trading, "started", False)
    )


def _research_record_continuation_task_updates(record: Any) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if record is None:
        return updates

    continued_from = str(getattr(record, "continued_from_run_id", None) or "").strip()
    if continued_from:
        updates["continued_from_run_id"] = continued_from

    source = str(getattr(record, "continuation_source", None) or "").strip()
    context = getattr(record, "continuation_context", None)
    if isinstance(context, dict) and context:
        redacted = _redact_sensitive_values(dict(context))
        if isinstance(redacted, dict) and redacted:
            updates["continuation_context"] = redacted
            if not source:
                source = str(redacted.get("source") or "").strip()
            if not continued_from:
                context_run_id = str(redacted.get("run_id") or "").strip()
                if context_run_id:
                    updates["continued_from_run_id"] = context_run_id
    if source:
        updates["continuation_source"] = source
    return updates


def _status_trading_snapshot(status: Any) -> dict[str, Any]:
    if isinstance(status, dict):
        snapshot = status.get("trading_snapshot")
    else:
        snapshot = getattr(status, "trading_snapshot", None)
    return dict(snapshot) if isinstance(snapshot, dict) else {}


def _freshened_task_response_for_read(
    response: AIStrategyResearchTaskResponse,
) -> AIStrategyResearchTaskResponse:
    result = _freshened_research_result_for_task(response.result)
    if result is None or result is response.result:
        return response
    updates = _research_result_task_updates(result)
    pipeline = updates.get("pipeline")
    current_stage = response.current_stage
    if isinstance(pipeline, dict):
        current_stage = str(pipeline.get("current_stage") or current_stage)
    return response.model_copy(
        update={
            **updates,
            "current_stage": current_stage,
            "result": result,
        }
    )


def _freshened_research_result_for_task(result: Any) -> Any:
    record = _freshened_research_run_record(getattr(result, "run_record", None))
    if record is None or not hasattr(result, "model_copy"):
        return result
    if record == getattr(result, "run_record", None):
        return result
    return result.model_copy(
        update={
            "run_record": record,
            "pipeline": record.pipeline,
            "next_actions": record.next_actions,
        }
    )


def _freshened_research_run_record(record: Any) -> Any:
    if record is None:
        return None
    try:
        if typing.TYPE_CHECKING:
            from app.services.research.run_records import (
                _research_run_record_with_live_readiness_freshness,
            )
        else:
            from app.services.ai_strategy_research_service import (
                _research_run_record_with_live_readiness_freshness,
            )

        return _research_run_record_with_live_readiness_freshness(record)
    except Exception:
        logger.opt(exception=True).warning("Unable to refresh AI research live-readiness state")
        return record


def _first_non_empty_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _merged_non_empty_dict(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if not isinstance(value, dict) or not value:
            continue
        for key, item in value.items():
            if isinstance(item, dict) and isinstance(merged.get(key), dict):
                nested = dict(merged[key])
                nested.update(item)
                merged[key] = nested
            else:
                merged[key] = item
    return merged


def _first_non_empty_list(*values: Any) -> list[Any]:
    for value in values:
        if isinstance(value, list) and value:
            return list(value)
    return []


def _optional_bool(*values: Any) -> bool | None:
    for value in values:
        if value is not None:
            return bool(value)
    return None


def _optional_float(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number:
            return number
    return None


def _optional_int(*values: Any) -> int | None:
    for value in values:
        number = _optional_float(value)
        if number is not None:
            return int(number)
    return None


def _metric_float(metrics: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _optional_float(metrics.get(key))
        if value is not None:
            return value
    return None


def _research_request_snapshot(request: AIStrategyResearchRunRequest) -> dict[str, Any]:
    payload = request.model_dump(mode="json")
    sanitized = _omit_sensitive_request_values(payload)
    if not isinstance(sanitized, dict):
        return {}
    explicit_fields = set(_research_request_explicit_fields(request))
    for key in (
        "data_config",
        "unit_settings",
        "optimization_config",
        "gateway_config",
        "continuation_context",
    ):
        if key not in explicit_fields and sanitized.get(key) == {}:
            sanitized.pop(key, None)
    return dict(sanitized)


def _research_request_explicit_fields(request: AIStrategyResearchRunRequest) -> list[str]:
    fields: object = getattr(request, "model_fields_set", None)
    if fields is None:
        fields = getattr(request, "__fields_set__", set())
    if not isinstance(fields, (set, frozenset)):
        return []
    return sorted(str(field).strip() for field in fields if str(field).strip())


def _redacted_research_result_for_task(result: Any) -> AIStrategyResearchRunResponse | None:
    if not hasattr(result, "model_dump"):
        return None
    try:
        payload = result.model_dump(mode="python")
        redacted = _redact_sensitive_values(payload)
        return AIStrategyResearchRunResponse.model_validate(redacted)
    except Exception:
        logger.opt(exception=True).warning("Unable to redact AI research result for task storage")
        return None


def _redacted_model_for_task(value: Any, model_cls: Any) -> Any:
    if value is None:
        return None
    try:
        if hasattr(value, "model_dump"):
            payload = value.model_dump(mode="python")
        elif isinstance(value, dict):
            payload = dict(value)
        else:
            return None
        return model_cls.model_validate(_redact_sensitive_values(payload))
    except Exception:
        logger.opt(exception=True).warning("Unable to redact AI research model for task storage")
        return None


def _redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_request_key(str(key)):
                result[key] = "***"
            else:
                result[key] = _redact_sensitive_values(item)
        return result
    if isinstance(value, list):
        return [_redact_sensitive_values(item) for item in value]
    return value


def _omit_sensitive_request_values(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_request_key(str(key)):
                continue
            cleaned = _omit_sensitive_request_values(item)
            if cleaned is _SENSITIVE_REQUEST_OMITTED:
                continue
            result[key] = cleaned
        return result
    if isinstance(value, list):
        items: list[object] = []
        for item in value:
            cleaned = _omit_sensitive_request_values(item)
            if cleaned is not _SENSITIVE_REQUEST_OMITTED:
                items.append(cleaned)
        return items
    if value == "***":
        return _SENSITIVE_REQUEST_OMITTED
    return value


def _is_sensitive_request_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(marker in lowered for marker in _SENSITIVE_REQUEST_KEYS)
