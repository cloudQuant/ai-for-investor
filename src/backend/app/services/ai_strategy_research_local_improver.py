"""Draft preparation and local/continuation improvement helpers for AI strategy research."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.schemas.ai_strategy_research import (
    AIStrategyResearchIteration,
    AIStrategyResearchRunRequest,
    AIStrategyResearchRunResponse,
)
from app.schemas.strategy import AIStrategyDraft, ParamSpec, StrategyCopilotDraftRequest
from app.schemas.workspace import WorkspaceResponse
from app.services import research as _research_helpers  # noqa: F401
from app.services.ai_research_provenance import sign_ai_research_run_record
from app.services.research.continuation import (
    _continuation_improvement_metrics,
    _continuation_quality_gate_failures,
    _draft_from_strategy,
    _ensure_runnable_initial_draft,
    _ensure_runnable_seed_draft,
    _normalize_research_draft,
)
from app.services.research.generation import (
    _build_research_draft_prompt,
    _initial_generation_metadata_from_response,
    _metric_float,
    _metric_int,
    _param_float,
    _param_int,
    _rewrite_code_param_defaults,
    _seed_generation_metadata,
    _set_param_default,
    _strategy_generation_metadata,
)
from app.services.research.paper_handoff import (
    _build_research_run_record,
    _compact_research_iteration,
    _configuration_failure_diagnostics,
    _dict_payload,
    _run_next_actions,
    _string_list,
)
from app.services.research.pipeline_audit import _pipeline_summary, _utc_iso_now
from app.services.research.robustness import _improvement_metrics, _validate_strategy_code_draft
from app.services.research.run_records import _emit_research_progress, _research_loop_progress
from app.services.research.types import StrategyImprovement
from app.services.strategy.ai_draft import build_ai_strategy_draft

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None] | None

_CONTINUATION_NOTE_BY_SOURCE: dict[str, str] = {
    "paper_trading_failed": "基于上一轮模拟交易启动失败原因生成 continuation 改进版。",
    "research_cancelled": "基于上一轮取消前已完成迭代的失败指标生成 continuation 改进版。",
    "research_failure": "基于上一轮投研未达标原因生成 continuation 改进版。",
    "live_handoff_rejected": "基于上一轮实盘交接驳回意见生成 continuation 改进版。",
}
_DEFAULT_CONTINUATION_NOTE = "基于上一轮模拟交易复核结果生成 continuation 改进版。"


@dataclass(frozen=True, slots=True)
class _LocalFailureSignals:
    sharpe: float
    max_drawdown: float
    total_trades: int
    failures: list[str]
    drawdown_failed: bool
    out_of_sample_failed: bool
    robustness_failed: bool
    execution_cost_failed: bool
    valuation_context_failed: bool
    live_handoff_rejected: bool
    regressed: bool
    stalled: bool
    trade_count_failed: bool


def _extract_local_failure_signals(
    metrics: dict[str, Any],
    quality_gate_failures: list[str] | None,
    request: AIStrategyResearchRunRequest | None,
) -> _LocalFailureSignals:
    failures = [str(item) for item in quality_gate_failures or []]
    research_feedback = _dict_payload(metrics.get("research_feedback"))
    failure_categories = {
        str(item)
        for item in [
            *_string_list(metrics.get("failure_categories")),
            *_string_list(research_feedback.get("failure_categories")),
        ]
        if str(item).strip()
    }
    sharpe = _metric_float(metrics, "sharpe_ratio", "sharpe", "sharpeRatio")
    max_drawdown = _metric_float(metrics, "max_drawdown", "maxDrawdown", default=0.0)
    total_trades = _metric_int(metrics, "total_trades", "totalTrades", "trades")
    progress_status = (
        str(_dict_payload(metrics.get("iteration_progress")).get("status") or "").strip().lower()
    )
    trade_count_failed = (
        (request is not None and total_trades < max(int(request.min_total_trades), 1))
        or "trade_count" in failure_categories
        or any("trade" in item.lower() or "交易" in item for item in failures)
    )
    return _LocalFailureSignals(
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        total_trades=total_trades,
        failures=failures,
        drawdown_failed=(
            "drawdown" in failure_categories
            or any("drawdown" in item.lower() or "回撤" in item for item in failures)
        ),
        out_of_sample_failed="out_of_sample" in failure_categories,
        robustness_failed="robustness" in failure_categories,
        execution_cost_failed="execution_cost" in failure_categories,
        valuation_context_failed="valuation_context" in failure_categories,
        live_handoff_rejected="live_handoff_rejected" in failure_categories,
        regressed=progress_status == "regressed",
        stalled=progress_status == "stalled",
        trade_count_failed=trade_count_failed,
    )


def _append_local_signal_notes(signals: _LocalFailureSignals, notes: list[str]) -> None:
    if signals.regressed:
        notes.append("上一轮自动改稿相对前一轮退化，本轮切换为保守修复。")
    elif signals.stalled:
        notes.append("上一轮自动改稿基本停滞，本轮将扩大信号和风控结构调整幅度。")
    signal_messages = (
        (signals.out_of_sample_failed, "样本外验证未通过，本轮降低参数敏感度并优先保留稳健信号。"),
        (signals.robustness_failed, "稳健性验证未通过，本轮降低过拟合和参数敏感性风险。"),
        (signals.execution_cost_failed, "执行成本或滑点压力偏高，本轮降低换手和无效交易。"),
        (
            signals.valuation_context_failed,
            "资产规格或估值上下文存在风险，本轮保留交易约束并避免扩大杠杆暴露。",
        ),
        (
            signals.live_handoff_rejected,
            "实盘交接人工审批未通过，本轮按审批意见降低上线风险并重新验证。",
        ),
    )
    for active, message in signal_messages:
        if active:
            notes.append(message)


def _adjust_local_risk_params(
    params: dict[str, ParamSpec],
    signals: _LocalFailureSignals,
    target_sharpe: float,
    notes: list[str],
) -> None:
    if "risk_pct" in params:
        current = _param_float(params["risk_pct"], 0.01)
        risk_scale = (
            0.65
            if signals.regressed
            else 0.7
            if signals.live_handoff_rejected
            else 0.75
            if signals.out_of_sample_failed
            else 0.8
        )
        next_value = max(round(current * risk_scale, 5), 0.001)
        _set_param_default(params, "risk_pct", next_value)
        notes.append(f"将单笔风险从 {current:g} 下调到 {next_value:g}")

    if "stop_loss_pct" in params and (signals.max_drawdown < -10 or signals.drawdown_failed):
        current = _param_float(params["stop_loss_pct"], 0.05)
        stop_scale = 0.7 if signals.regressed else 0.8
        next_value = max(round(current * stop_scale, 4), 0.01)
        _set_param_default(params, "stop_loss_pct", next_value)
        notes.append(f"最大回撤偏大，止损比例从 {current:g} 收紧到 {next_value:g}")

    if "take_profit_pct" in params and signals.sharpe < target_sharpe:
        current = _param_float(params["take_profit_pct"], 0.1)
        tp_scale = 1.03 if signals.regressed else 1.15 if signals.stalled else 1.1
        next_value = round(current * tp_scale, 4)
        _set_param_default(params, "take_profit_pct", next_value)
        notes.append(f"盈亏比不足，止盈比例从 {current:g} 提高到 {next_value:g}")

    if "atr_stop_multiplier" in params:
        current = _param_float(params["atr_stop_multiplier"], 2.0)
        atr_scale = 0.8 if signals.regressed else 0.85 if signals.stalled else 0.9
        next_value = round(max(current * atr_scale, 1.0), 3)
        _set_param_default(params, "atr_stop_multiplier", next_value)
        notes.append(f"ATR 止损倍数从 {current:g} 调整到 {next_value:g}")


def _adjust_local_indicator_params(
    params: dict[str, ParamSpec],
    signals: _LocalFailureSignals,
    target_sharpe: float,
    notes: list[str],
) -> None:
    if "fast_period" in params and "slow_period" in params:
        fast = _param_int(params["fast_period"], 10)
        slow = _param_int(params["slow_period"], 30)
        if signals.execution_cost_failed:
            next_fast, next_slow = fast + 1, max(slow + 3, fast + 3)
        elif signals.total_trades < 3:
            next_fast = max(fast - (2 if signals.stalled else 1), 2)
            next_slow = max(slow + (4 if signals.stalled else 2), next_fast + 2)
        elif signals.regressed:
            next_fast, next_slow = fast, max(slow + 1, fast + 2)
        elif signals.stalled:
            next_fast = max(fast - 1, 2)
            next_slow = max(slow + 3, next_fast + 2)
        else:
            next_fast, next_slow = fast, max(slow + 2, fast + 2)
        if next_fast != fast or next_slow != slow:
            _set_param_default(params, "fast_period", next_fast)
            _set_param_default(params, "slow_period", next_slow)
            notes.append(f"调整均线窗口为 fast={next_fast}, slow={next_slow}")

    if "rsi_period" in params and signals.sharpe < target_sharpe:
        current = _param_int(params["rsi_period"], 14)
        if signals.total_trades < 3:
            next_rsi = max(current - (2 if signals.stalled else 1), 5)
        else:
            next_rsi = current + (2 if signals.regressed or signals.stalled else 1)
        _set_param_default(params, "rsi_period", next_rsi)
        notes.append(f"RSI 周期从 {current} 调整到 {next_rsi}")


def run_local_strategy_improvement(
    draft: AIStrategyDraft,
    *,
    iteration: int,
    metrics: dict[str, Any],
    target_sharpe: float,
    quality_gate_failures: list[str] | None,
    request: AIStrategyResearchRunRequest | None,
) -> StrategyImprovement:
    """Apply deterministic local strategy revision rules based on backtest diagnostics."""
    improved = draft.model_copy(deep=True)
    notes: list[str] = []
    signals = _extract_local_failure_signals(metrics, quality_gate_failures, request)
    suffix = f" v{iteration + 1}"
    base_name = re.sub(r"\s+v\d+$", "", improved.name).strip()
    improved.name = f"{base_name}{suffix}"[:100]
    improved.description = (
        f"{improved.description or ''}\n"
        f"AI research revision {iteration + 1}: previous Sharpe {signals.sharpe:.3f}, "
        f"target {target_sharpe:.3f}."
    ).strip()
    if signals.trade_count_failed and request is not None:
        rebuilt = build_ai_strategy_draft(request.prompt)
        improved = _normalize_research_draft(rebuilt, request)
        improved.name = f"{base_name}{suffix}"[:100]
        improved.description = (
            f"{improved.description or ''}\n"
            f"AI research revision {iteration + 1}: rebuilt after trade-count failure; "
            f"previous closed trades {signals.total_trades}, target {request.min_total_trades}."
        ).strip()
        notes.append(
            "上一轮缺少闭合交易，本轮重建为带止损、止盈和最长持仓退出的基础模板，"
            "优先生成可计数的完成交易。"
        )

    _append_local_signal_notes(signals, notes)
    _adjust_local_risk_params(improved.params, signals, target_sharpe, notes)
    _adjust_local_indicator_params(improved.params, signals, target_sharpe, notes)
    if signals.failures:
        notes.append("本轮未通过验收门槛：" + "；".join(signals.failures))
    if not notes:
        notes.append("上一轮指标未达标，保留策略结构并创建新版本继续验证")

    improved.code = _rewrite_code_param_defaults(improved.code, improved.params)
    improved.risk_points = list(
        dict.fromkeys(
            [
                *improved.risk_points,
                "该版本由自动投研循环基于上一轮回测指标生成，需要继续做样本外验证。",
            ]
        )
    )
    improved.next_steps = [
        "继续回测新版本并比较 Sharpe、回撤和交易次数",
        "达标后进入 paper 模拟交易并观察实盘风控指标",
    ]
    return StrategyImprovement(
        draft=improved,
        notes=notes,
        metadata={"source": "local_rules", "provider": "local", "model_id": None},
    )


async def build_configuration_invalid_result(
    service: Any,
    *,
    user_id: str,
    run_id: str,
    request: AIStrategyResearchRunRequest,
    research_workspace: WorkspaceResponse,
    started_at: str,
    configuration_failure: str,
    progress_callback: ProgressCallback,
) -> AIStrategyResearchRunResponse:
    """Record, persist, and return early failure response when request config is invalid."""
    await service._record_pipeline_event(
        user_id=user_id,
        run_id=run_id,
        request=request,
        workspace_id=research_workspace.id,
        stage="configuration_invalid",
        status="failed",
        summary="AI投研配置校验未通过。",
        error=configuration_failure,
    )
    await _emit_research_progress(
        progress_callback,
        {
            "run_id": run_id,
            "research_workspace_id": research_workspace.id,
            "current_stage": "configuration_invalid",
            "progress": 100.0,
            "iteration_count": 0,
            "max_iterations": request.max_iterations,
            "message": configuration_failure,
        },
    )
    completed_at = _utc_iso_now()
    pipeline = _pipeline_summary(
        status="configuration_invalid",
        achieved=False,
        iteration_count=0,
        max_iterations=request.max_iterations,
        out_of_sample_validation=request.out_of_sample_validation,
        validation_status=None,
        robustness_validation=request.robustness_validation,
        robustness_status=None,
        paper_trading_started=False,
        paper_trading_error=None,
        paper_review_status=None,
        paper_review_ready_for_live=False,
        workflow_mode=request.workflow_mode,
        workflow_steps=[str(step) for step in request.workflow_steps],
    )
    response = AIStrategyResearchRunResponse(
        run_id=run_id,
        status="configuration_invalid",
        achieved=False,
        target_sharpe=request.target_sharpe,
        started_at=started_at,
        completed_at=completed_at,
        best_iteration=None,
        best_quality_score=0.0,
        best_quality_gate_evaluations=[],
        best_diagnostics=_configuration_failure_diagnostics(configuration_failure),
        best_metrics={},
        research_workspace=research_workspace,
        mandate_id=request.mandate_id,
        iterations=[],
        best_strategy=None,
        paper_trading=None,
        paper_monitoring_plan=[],
        pipeline=pipeline,
        promotion_audit=[],
        next_actions=_run_next_actions(
            status="configuration_invalid",
            achieved=False,
            request=request,
            result_iteration=None,
            paper_trading=None,
            run_failures=[configuration_failure],
        ),
        message=configuration_failure,
    )
    run_record = sign_ai_research_run_record(
        _build_research_run_record(
            run_id=run_id,
            request=request,
            response=response,
            started_at=started_at,
            completed_at=completed_at,
        ),
        user_id=user_id,
        workspace_id=str(research_workspace.id),
    )
    response = response.model_copy(update={"promotion_audit": run_record.promotion_audit})
    research_workspace = await service._persist_research_run_record(
        user_id, research_workspace, run_record
    )
    return response.model_copy(
        update={"research_workspace": research_workspace, "run_record": run_record}
    )


async def prepare_run_initial_draft(
    service: Any,
    *,
    user_id: str,
    run_id: str,
    request: AIStrategyResearchRunRequest,
    research_workspace: WorkspaceResponse,
    started_at: str,
    draft: AIStrategyDraft | None,
    progress_callback: ProgressCallback,
) -> tuple[AIStrategyDraft, list[str], dict[str, Any]]:
    """Generate or validate the initial runnable draft before iteration 1."""
    if draft is not None:
        seed_draft, notes = _ensure_runnable_seed_draft(draft, request)
        metadata = _seed_generation_metadata(request)
    else:
        await service._record_pipeline_event(
            user_id=user_id,
            run_id=run_id,
            request=request,
            workspace_id=research_workspace.id,
            stage="drafting",
            status="started",
            summary="开始生成首轮策略草案。",
        )
        await _emit_research_progress(
            progress_callback,
            {
                "current_stage": "drafting",
                "progress": 5.0,
                "iteration_count": 0,
                "max_iterations": request.max_iterations,
                "message": "Generating initial strategy draft",
            },
        )
        try:
            draft_response = await service.strategy_service.generate_copilot_draft(
                user_id,
                StrategyCopilotDraftRequest(
                    prompt=_build_research_draft_prompt(request),
                    knowledge_base_id=request.knowledge_base_id,
                    thinking_mode=request.thinking_mode,
                ),
            )
            metadata = _initial_generation_metadata_from_response(
                draft_response, source="ai_initial_draft", request=request
            )
            normalized = _normalize_research_draft(draft_response.strategy_draft, request)
            seed_draft, notes = _ensure_runnable_initial_draft(normalized, request)
        except asyncio.CancelledError:
            fallback_draft = _normalize_research_draft(
                build_ai_strategy_draft(request.prompt), request
            )
            await service._persist_cancelled_research_run(
                user_id=user_id,
                request=request,
                research_workspace=research_workspace,
                run_id=run_id,
                started_at=started_at,
                iterations=[],
                best_iteration=None,
                selected_iteration=None,
                run_failures=["AI research cancelled while generating initial strategy draft"],
                draft=fallback_draft,
            )
            raise
        except Exception as exc:
            await service._record_pipeline_event(
                user_id=user_id,
                run_id=run_id,
                request=request,
                workspace_id=research_workspace.id,
                stage="drafting",
                status="failed",
                summary="AI首轮策略草案生成失败，准备使用本地可运行草案继续。",
                error=str(exc),
            )
            await _emit_research_progress(
                progress_callback,
                {
                    "current_stage": "draft_generation_failed",
                    "progress": 6.0,
                    "iteration_count": 0,
                    "max_iterations": request.max_iterations,
                    "message": f"Initial strategy draft generation failed: {exc}",
                },
            )
            seed_draft = _normalize_research_draft(build_ai_strategy_draft(request.prompt), request)
            _validate_strategy_code_draft(seed_draft.code)
            metadata = {
                "source": "local_initial_fallback",
                "provider": "local",
                "fallback_reason": str(exc),
            }
            notes = [f"AI初始策略生成失败，已使用本地可运行草案继续投研：{exc}"]

    await service._record_pipeline_event(
        user_id=user_id,
        run_id=run_id,
        request=request,
        workspace_id=research_workspace.id,
        stage="drafting",
        status="completed",
        summary="首轮策略草案已准备完成。",
        output_payload={"strategy_name": seed_draft.name, "metadata": metadata, "notes": notes},
    )
    return seed_draft, notes, metadata


async def apply_continuation_improvement(
    service: Any,
    *,
    user_id: str,
    run_id: str,
    request: AIStrategyResearchRunRequest,
    research_workspace: WorkspaceResponse,
    started_at: str,
    draft: AIStrategyDraft,
    pending_improvement_notes: list[str],
    pending_generation_metadata: dict[str, Any],
) -> tuple[AIStrategyDraft, list[str], dict[str, Any]]:
    """Apply continuation improvement when resuming from a prior research failure context."""
    continuation_failures = _continuation_quality_gate_failures(request.continuation_context)
    if not continuation_failures:
        return draft, pending_improvement_notes, pending_generation_metadata
    try:
        improvement = await service._improve_draft(
            draft,
            iteration=0,
            metrics=_continuation_improvement_metrics(request.continuation_context, request),
            target_sharpe=request.target_sharpe,
            quality_gate_failures=continuation_failures,
            user_id=user_id,
            request=request,
        )
    except asyncio.CancelledError:
        await service._persist_cancelled_research_run(
            user_id=user_id,
            request=request,
            research_workspace=research_workspace,
            run_id=run_id,
            started_at=started_at,
            iterations=[],
            best_iteration=None,
            selected_iteration=None,
            run_failures=["AI research cancelled while preparing continuation draft"],
            draft=draft,
        )
        raise
    next_draft = _normalize_research_draft(improvement.draft, request)
    continuation_source = str(request.continuation_context.get("source") or "")
    continuation_note = _CONTINUATION_NOTE_BY_SOURCE.get(
        continuation_source, _DEFAULT_CONTINUATION_NOTE
    )
    return (
        next_draft,
        [continuation_note, *improvement.notes],
        _strategy_generation_metadata(
            improvement.metadata, phase="continuation_improvement", iteration=1
        ),
    )


async def improve_after_failed_iteration(
    service: Any,
    *,
    user_id: str,
    run_id: str,
    request: AIStrategyResearchRunRequest,
    research_workspace: WorkspaceResponse,
    started_at: str,
    iteration: int,
    item: AIStrategyResearchIteration,
    draft: AIStrategyDraft,
    iterations: list[AIStrategyResearchIteration],
    best_iteration: AIStrategyResearchIteration | None,
    selected_iteration: AIStrategyResearchIteration | None,
    run_failures: list[str],
    progress_callback: ProgressCallback,
) -> tuple[AIStrategyDraft, list[str], dict[str, Any]]:
    """Generate the next candidate draft after a failed research iteration."""
    await service._record_pipeline_event(
        user_id=user_id,
        run_id=run_id,
        request=request,
        workspace_id=research_workspace.id,
        stage="optimization_loop",
        status="started",
        iteration=iteration + 1,
        summary=f"根据第 {iteration} 轮审查结果准备下一版策略。",
        input_payload={
            "quality_gate_failures": item.quality_gate_failures,
            "metrics": item.metrics,
        },
    )
    await _emit_research_progress(
        progress_callback,
        {
            "current_stage": "improving",
            "progress": min(_research_loop_progress(iteration, request.max_iterations) + 2.0, 82.0),
            "current_iteration": iteration + 1,
            "iteration_count": len(iterations),
            "max_iterations": request.max_iterations,
            "latest_iteration": _compact_research_iteration(item),
            "message": f"Improving strategy for iteration {iteration + 1}",
        },
    )
    try:
        improvement_base_draft = draft
        rollback_note = None
        iteration_progress = item.diagnostics.get("iteration_progress")
        progress_status = (
            str(iteration_progress.get("status") or "").strip()
            if isinstance(iteration_progress, dict)
            else ""
        )
        if (
            progress_status == "regressed"
            and best_iteration is not None
            and best_iteration.iteration != item.iteration
        ):
            improvement_base_draft = _draft_from_strategy(best_iteration.strategy, request)
            rollback_note = (
                f"第 {iteration} 轮自动改稿退化，下一版回退到当前最佳第 "
                f"{best_iteration.iteration} 轮策略后继续改进。"
            )
        improvement = await service._improve_draft(
            improvement_base_draft,
            iteration=iteration,
            metrics=_improvement_metrics(
                item.metrics,
                item.validation_metrics,
                iteration_progress=iteration_progress,
                diagnostics=item.diagnostics,
            ),
            target_sharpe=request.target_sharpe,
            quality_gate_failures=item.quality_gate_failures,
            user_id=user_id,
            request=request,
        )
    except asyncio.CancelledError:
        await service._persist_cancelled_research_run(
            user_id=user_id,
            request=request,
            research_workspace=research_workspace,
            run_id=run_id,
            started_at=started_at,
            iterations=iterations,
            best_iteration=best_iteration,
            selected_iteration=selected_iteration,
            run_failures=run_failures,
        )
        raise

    next_draft = _normalize_research_draft(improvement.draft, request)
    notes = [rollback_note, *improvement.notes] if rollback_note else improvement.notes
    metadata = _strategy_generation_metadata(
        improvement.metadata, phase="quality_gate_improvement", iteration=iteration + 1
    )
    await service._record_pipeline_event(
        user_id=user_id,
        run_id=run_id,
        request=request,
        workspace_id=research_workspace.id,
        stage="optimization_loop",
        status="completed",
        iteration=iteration + 1,
        summary=f"第 {iteration + 1} 轮策略改稿已完成。",
        output_payload={"notes": notes, "metadata": metadata},
    )
    return next_draft, notes, metadata
