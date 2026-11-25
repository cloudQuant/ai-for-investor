"""Stage and local-rule helpers decomposed from AI strategy research orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas.ai_strategy_research import (
    AIStrategyPaperTradingStart,
    AIStrategyResearchIteration,
    AIStrategyResearchRunRequest,
    AIStrategyResearchRunResponse,
)
from app.schemas.strategy import (
    AIStrategyDraft,
    StrategyResponse,
)
from app.schemas.workspace import UnitStatusResponse, WorkspaceResponse
from app.services import research as _research_helpers  # noqa: F401
from app.services.ai_research_provenance import sign_ai_research_run_record
from app.services.research.continuation import (
    _iteration_robustness_payload,
    _normalize_research_draft,
)
from app.services.research.generation import (
    _strategy_generation_metadata,
)
from app.services.research.paper_handoff import (
    _apply_initial_live_handoff_to_run_record,
    _apply_initial_paper_review_to_run_record,
    _build_research_run_record,
    _compact_research_iteration,
    _iteration_diagnostics,
    _iteration_next_actions,
    _paper_monitoring_plan,
    _run_failure_diagnostics,
    _run_next_actions,
)
from app.services.research.pipeline_audit import (
    _paper_trading_start_error,
    _pipeline_summary,
    _utc_iso_now,
)
from app.services.research.robustness import (
    _out_of_sample_failures,
    _out_of_sample_gate_evaluations,
    _research_completion_message,
    _robustness_failures_from_result,
    _robustness_gate_payloads,
    _robustness_validation_request,
)
from app.services.research.run_records import (
    _emit_research_progress,
    _research_loop_progress,
)
from app.services.research.types import OutOfSampleWindow

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None] | None


async def submit_iteration_backtest(
    service: Any,
    *,
    user_id: str,
    run_id: str,
    request: AIStrategyResearchRunRequest,
    research_workspace: WorkspaceResponse,
    started_at: str,
    iteration: int,
    draft: AIStrategyDraft,
    backtest_request: Any,
    iterations: list[AIStrategyResearchIteration],
    best_iteration: AIStrategyResearchIteration | None,
    selected_iteration: AIStrategyResearchIteration | None,
    run_failures: list[str],
    pending_improvement_notes: list[str],
    pending_generation_metadata: dict[str, Any],
    progress_callback: ProgressCallback,
) -> tuple[Any | None, AIStrategyDraft, list[str], dict[str, Any], bool]:
    """Submit a backtest task or repair the draft upon submission failure."""
    try:
        backtest_response = await service.strategy_service.backtest_copilot_draft(
            user_id, research_workspace.id, backtest_request
        )
        if backtest_response is None:
            raise ValueError("Research workspace or generated strategy was not found")
        return (
            backtest_response,
            draft,
            pending_improvement_notes,
            pending_generation_metadata,
            False,
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
            run_failures=[
                *run_failures,
                f"AI research cancelled while submitting backtest iteration {iteration}",
            ],
            draft=draft,
        )
        raise
    except Exception as exc:
        failure_reason = f"Backtest submission failed before iteration {iteration}: {exc}"
        run_failures.append(failure_reason)
        await service._record_pipeline_event(
            user_id=user_id,
            run_id=run_id,
            request=request,
            workspace_id=research_workspace.id,
            stage="backtest_submission_failed",
            status="failed",
            iteration=iteration,
            summary="回测任务提交失败。",
            metrics={
                "backtest_submission_failed": True,
                "failure_count": len(run_failures),
            },
            error=failure_reason,
        )
        await _emit_research_progress(
            progress_callback,
            {
                "current_stage": "backtest_submission_failed",
                "progress": _research_loop_progress(iteration - 1, request.max_iterations),
                "current_iteration": iteration,
                "iteration_count": len(iterations),
                "max_iterations": request.max_iterations,
                "current_backtest_task_id": None,
                "message": failure_reason,
            },
        )
        if iteration >= request.max_iterations:
            return None, draft, pending_improvement_notes, pending_generation_metadata, False

        await service._record_pipeline_event(
            user_id=user_id,
            run_id=run_id,
            request=request,
            workspace_id=research_workspace.id,
            stage="optimization_loop",
            status="started",
            iteration=iteration + 1,
            summary=f"根据第 {iteration} 轮提交失败原因准备下一版策略。",
            input_payload={"failure_reason": failure_reason},
        )
        await _emit_research_progress(
            progress_callback,
            {
                "current_stage": "improving",
                "progress": min(
                    _research_loop_progress(iteration, request.max_iterations) + 2.0, 82.0
                ),
                "current_iteration": iteration + 1,
                "iteration_count": len(iterations),
                "max_iterations": request.max_iterations,
                "message": f"Improving strategy for iteration {iteration + 1}",
            },
        )
        try:
            improvement = await service._improve_draft(
                draft,
                iteration=iteration,
                metrics={
                    "backtest_submission_failed": True,
                    "backtest_submission_failure_count": len(run_failures),
                },
                target_sharpe=request.target_sharpe,
                quality_gate_failures=[failure_reason],
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
                draft=draft,
            )
            raise
        next_draft = _normalize_research_draft(improvement.draft, request)
        next_notes = [
            f"第 {iteration} 轮回测提交失败，已基于失败原因生成下一版策略：{failure_reason}",
            *improvement.notes,
        ]
        next_meta = _strategy_generation_metadata(
            improvement.metadata, phase="backtest_submission_repair", iteration=iteration + 1
        )
        await service._record_pipeline_event(
            user_id=user_id,
            run_id=run_id,
            request=request,
            workspace_id=research_workspace.id,
            stage="optimization_loop",
            status="completed",
            iteration=iteration + 1,
            summary="提交失败修复版策略已生成。",
            output_payload={"notes": next_notes, "metadata": next_meta},
        )
        return None, next_draft, next_notes, next_meta, True


async def run_iteration_oos_validation(
    service: Any,
    *,
    user_id: str,
    run_id: str,
    request: AIStrategyResearchRunRequest,
    research_workspace: WorkspaceResponse,
    iteration: int,
    iterations_count: int,
    draft: AIStrategyDraft,
    validation_window: OutOfSampleWindow | None,
    passed: bool,
    quality_gate_failures: list[str],
    failure_reason: str | None,
    progress_callback: ProgressCallback,
) -> tuple[bool, list[str], str | None, dict[str, Any]]:
    """Run out-of-sample validation for a passed in-sample iteration when configured."""
    validation_window_payload = validation_window.as_dict() if validation_window else None
    oos_state: dict[str, Any] = {
        "unit": None,
        "run_result": None,
        "unit_status": None,
        "status": None,
        "metrics": {},
        "gate_evaluations": [],
        "failures": [],
        "failure_reason": None,
        "window_payload": validation_window_payload,
    }
    if not (passed and request.out_of_sample_validation):
        return passed, quality_gate_failures, failure_reason, oos_state

    if validation_window is None:
        skip_reason = (
            "Out-of-sample validation skipped because start_date/end_date "
            "do not define a splittable range"
        )
        oos_state["status"] = "skipped"
        oos_state["failure_reason"] = skip_reason
        if request.require_out_of_sample_validation:
            oos_state["failures"] = [skip_reason]
            quality_gate_failures = [*quality_gate_failures, skip_reason]
            failure_reason = skip_reason
            passed = False
    else:
        await service._record_pipeline_event(
            user_id=user_id,
            run_id=run_id,
            request=request,
            workspace_id=research_workspace.id,
            stage="validating",
            status="started",
            iteration=iteration,
            summary=f"开始第 {iteration} 轮样本外验证。",
            input_payload={"validation_window": validation_window_payload},
        )
        await _emit_research_progress(
            progress_callback,
            {
                "current_stage": "validating",
                "progress": min(
                    _research_loop_progress(iteration, request.max_iterations) + 1.0, 83.0
                ),
                "current_iteration": iteration,
                "iteration_count": iterations_count,
                "max_iterations": request.max_iterations,
                "latest_iteration": {
                    "iteration": iteration,
                    "validation_window": validation_window_payload,
                },
                "message": f"Running out-of-sample validation for iteration {iteration}",
            },
        )
        validation_request = service._build_backtest_request(
            draft,
            request,
            user_id=user_id,
            start_date=validation_window.validation_start,
            end_date=validation_window.validation_end,
            group_name_suffix=" 样本外验证",
        )
        try:
            validation_response = await service.strategy_service.backtest_copilot_draft(
                user_id, research_workspace.id, validation_request
            )
            if validation_response is None:
                raise ValueError(
                    "Research workspace or generated validation strategy was not found"
                )
            oos_state["unit"] = validation_response.unit
            oos_state["run_result"] = validation_response.run_result
            await _emit_research_progress(
                progress_callback,
                {
                    "current_stage": "validating",
                    "progress": min(
                        _research_loop_progress(iteration, request.max_iterations) + 2.0, 84.0
                    ),
                    "current_iteration": iteration,
                    "iteration_count": iterations_count,
                    "max_iterations": request.max_iterations,
                    "current_backtest_task_id": validation_response.run_result.task_id,
                    "latest_iteration": {
                        "iteration": iteration,
                        "validation_window": validation_window_payload,
                    },
                    "message": (
                        f"Out-of-sample validation task submitted for iteration {iteration}"
                    ),
                },
            )
            validation_unit_status, validation_wait_failure = await service._wait_for_unit_status(
                research_workspace.id,
                user_id,
                validation_response.unit.id,
                initial_status=validation_response.unit_status,
                timeout_seconds=request.backtest_timeout_seconds,
                poll_interval_seconds=request.poll_interval_seconds,
            )
            oos_state["unit_status"] = validation_unit_status
            validation_metrics = dict(
                validation_unit_status.metrics_snapshot if validation_unit_status else {}
            )
            validation_run_status = (
                validation_unit_status.run_status if validation_unit_status else None
            )
            oos_state["metrics"] = validation_metrics
            oos_state["gate_evaluations"] = _out_of_sample_gate_evaluations(
                request, validation_metrics, run_status=validation_run_status
            )
            validation_failures = _out_of_sample_failures(
                request, validation_metrics, run_status=validation_run_status
            )
            oos_state["failures"] = validation_failures
            oos_state["status"] = "passed" if not validation_failures else "failed"
            if validation_wait_failure and validation_run_status != "completed":
                oos_state["failure_reason"] = validation_wait_failure
            if validation_failures:
                oos_state["failure_reason"] = "; ".join(validation_failures)
                quality_gate_failures = [*quality_gate_failures, *validation_failures]
                failure_reason = oos_state["failure_reason"]
                passed = False
        except Exception as exc:
            start_error = f"Out-of-sample validation failed to start: {exc}"
            oos_state["status"] = "failed"
            oos_state["failure_reason"] = start_error
            oos_state["failures"] = [start_error]
            quality_gate_failures = [*quality_gate_failures, start_error]
            failure_reason = start_error
            passed = False

    if oos_state["status"]:
        await service._record_pipeline_event(
            user_id=user_id,
            run_id=run_id,
            request=request,
            workspace_id=research_workspace.id,
            stage="validating",
            status="completed" if oos_state["status"] == "passed" else "failed",
            iteration=iteration,
            summary=f"第 {iteration} 轮样本外验证{oos_state['status']}。",
            output_payload={
                "validation_status": oos_state["status"],
                "validation_window": validation_window_payload,
                "gate_evaluations": oos_state["gate_evaluations"],
                "failures": oos_state["failures"],
            },
            metrics=oos_state["metrics"],
            error=oos_state["failure_reason"],
        )
    return passed, quality_gate_failures, failure_reason, oos_state


async def run_iteration_robustness_validation(
    service: Any,
    *,
    user_id: str,
    run_id: str,
    request: AIStrategyResearchRunRequest,
    research_workspace: WorkspaceResponse,
    iteration: int,
    iterations_count: int,
    backtest_task_id: str | None,
    passed: bool,
    quality_gate_failures: list[str],
    failure_reason: str | None,
    progress_callback: ProgressCallback,
    robustness_service_factory: Callable[[], Any],
) -> tuple[bool, list[str], str | None, dict[str, Any]]:
    """Run robustness validation on a passed iteration when configured."""
    robust_state: dict[str, Any] = {
        "status": None,
        "result": {},
        "gate_evaluations": [],
        "failures": [],
        "failure_reason": None,
    }
    if not (passed and request.robustness_validation):
        return passed, quality_gate_failures, failure_reason, robust_state

    await service._record_pipeline_event(
        user_id=user_id,
        run_id=run_id,
        request=request,
        workspace_id=research_workspace.id,
        stage="robustness_validation",
        status="started",
        iteration=iteration,
        summary=f"开始第 {iteration} 轮稳健性验证。",
        input_payload={
            "backtest_id": backtest_task_id,
            "methods": request.robustness_methods,
            "min_robustness_score": request.min_robustness_score,
        },
    )
    await _emit_research_progress(
        progress_callback,
        {
            "current_stage": "robustness_validation",
            "progress": min(_research_loop_progress(iteration, request.max_iterations) + 1.5, 84.5),
            "current_iteration": iteration,
            "iteration_count": iterations_count,
            "max_iterations": request.max_iterations,
            "current_backtest_task_id": backtest_task_id,
            "latest_iteration": {"iteration": iteration, "robustness_status": "running"},
            "message": f"Running robustness validation for iteration {iteration}",
        },
    )
    robustness_status = "failed"
    try:
        task_id = str(backtest_task_id or "").strip()
        if not task_id:
            raise ValueError("Robustness validation requires a completed backtest task id")
        robustness = await robustness_service_factory().run_for_backtest(
            backtest_id=task_id,
            user_id=user_id,
            request=_robustness_validation_request(request, run_id=run_id),
        )
        robustness_result = robustness.model_dump(mode="json")
        robustness_status = robustness.status
        robust_state["result"] = robustness_result
        robust_state["status"] = robustness_status
        robust_state["gate_evaluations"] = _robustness_gate_payloads(robustness_result)
        robustness_failures = _robustness_failures_from_result(
            robustness_result, require_robustness=request.require_robustness_validation
        )
        robust_state["failures"] = robustness_failures
        if robustness_failures:
            robust_state["failure_reason"] = "; ".join(robustness_failures)
            if request.require_robustness_validation:
                quality_gate_failures = [*quality_gate_failures, *robustness_failures]
                failure_reason = robust_state["failure_reason"]
                passed = False
    except Exception as exc:
        error_msg = f"Robustness validation failed to run: {exc}"
        robust_state["status"] = "failed"
        robust_state["failure_reason"] = error_msg
        robust_state["failures"] = [error_msg]
        robust_state["result"] = {"status": "failed", "error_message": str(exc)}
        if request.require_robustness_validation:
            quality_gate_failures = [*quality_gate_failures, error_msg]
            failure_reason = error_msg
            passed = False

    await service._record_pipeline_event(
        user_id=user_id,
        run_id=run_id,
        request=request,
        workspace_id=research_workspace.id,
        stage="robustness_validation",
        status="completed" if not robust_state["failures"] else "failed",
        iteration=iteration,
        summary=f"第 {iteration} 轮稳健性验证{robust_state['status']}。",
        output_payload={
            "robustness_status": robust_state["status"],
            "gate_evaluations": robust_state["gate_evaluations"],
            "failures": robust_state["failures"],
            "result": robust_state["result"],
        },
        metrics=dict(robust_state["result"].get("metrics") or {}),
        error=robust_state["failure_reason"],
    )
    return passed, quality_gate_failures, failure_reason, robust_state


def assemble_iteration_record(
    *,
    request: AIStrategyResearchRunRequest,
    iteration: int,
    backtest_response: Any,
    unit_status: UnitStatusResponse | None,
    metrics: dict[str, Any],
    sharpe: float,
    total_trades: int,
    quality_score: float,
    quality_gate_evaluations: list[dict[str, Any]],
    quality_gate_failures: list[str],
    passed: bool,
    failure_reason: str | None,
    previous_iteration: AIStrategyResearchIteration | None,
    pending_generation_metadata: dict[str, Any],
    pending_improvement_notes: list[str],
    oos_state: dict[str, Any],
    robust_state: dict[str, Any],
) -> AIStrategyResearchIteration:
    """Assemble full iteration diagnostics and schema record after validation stages."""
    diagnostics = _iteration_diagnostics(
        request,
        iteration=iteration,
        metrics=metrics,
        run_status=unit_status.run_status if unit_status else None,
        quality_gate_failures=quality_gate_failures,
        quality_gate_evaluations=quality_gate_evaluations,
        failure_reason=failure_reason,
        previous_iteration=previous_iteration,
        quality_score=quality_score,
    )
    if request.out_of_sample_validation:
        diagnostics["out_of_sample_validation"] = {
            "status": oos_state["status"] or "not_required",
            "window": oos_state["window_payload"],
            "metrics": oos_state["metrics"],
            "gate_evaluations": oos_state["gate_evaluations"],
            "failures": oos_state["failures"],
            "failure_reason": oos_state["failure_reason"],
        }
        if oos_state["failures"]:
            diagnostics["promotion_ready"] = False
            diagnostics["summary"] = (
                f"第 {iteration} 轮训练样本达标，但样本外验证未通过："
                + "；".join(oos_state["failures"])
            )
    if request.robustness_validation:
        diagnostics["robustness_validation"] = {
            "status": robust_state["status"] or "not_required",
            "result": robust_state["result"],
            "gate_evaluations": robust_state["gate_evaluations"],
            "failures": robust_state["failures"],
            "failure_reason": robust_state["failure_reason"],
        }
        if robust_state["failures"]:
            diagnostics["promotion_ready"] = False
            diagnostics["summary"] = (
                f"第 {iteration} 轮训练/验证门槛达标，但稳健性验证未通过："
                + "；".join(robust_state["failures"])
            )
    generation_metadata = _strategy_generation_metadata(
        pending_generation_metadata, iteration=iteration
    )
    if generation_metadata:
        diagnostics["strategy_generation"] = generation_metadata
    improvement_plan = list(diagnostics.get("improvement_plan") or [])
    return AIStrategyResearchIteration(
        iteration=iteration,
        strategy=backtest_response.strategy,
        unit=backtest_response.unit,
        run_result=backtest_response.run_result,
        unit_status=unit_status,
        metrics=metrics,
        sharpe_ratio=sharpe,
        total_trades=total_trades,
        validation_unit=oos_state["unit"],
        validation_run_result=oos_state["run_result"],
        validation_unit_status=oos_state["unit_status"],
        validation_status=oos_state["status"],
        validation_window=oos_state["window_payload"],
        validation_metrics=oos_state["metrics"],
        validation_gate_evaluations=oos_state["gate_evaluations"],
        validation_failures=oos_state["failures"],
        validation_failure_reason=oos_state["failure_reason"],
        robustness_status=robust_state["status"],
        robustness_result=robust_state["result"],
        robustness_gate_evaluations=robust_state["gate_evaluations"],
        robustness_failures=robust_state["failures"],
        robustness_failure_reason=robust_state["failure_reason"],
        quality_score=quality_score,
        quality_gate_evaluations=quality_gate_evaluations,
        passed=passed,
        failure_reason=None if passed else failure_reason,
        quality_gate_failures=quality_gate_failures,
        diagnostics=diagnostics,
        improvement_plan=improvement_plan,
        improvement_notes=pending_improvement_notes,
        next_actions=_iteration_next_actions(
            iteration=iteration,
            max_iterations=request.max_iterations,
            passed=passed,
            run_status=unit_status.run_status if unit_status else None,
            quality_gate_failures=quality_gate_failures,
            failure_reason=failure_reason,
        ),
    )


async def run_paper_trading_stage(
    service: Any,
    *,
    user_id: str,
    run_id: str,
    request: AIStrategyResearchRunRequest,
    research_workspace: WorkspaceResponse,
    started_at: str,
    achieved: bool,
    result_iteration: AIStrategyResearchIteration | None,
    iterations: list[AIStrategyResearchIteration],
    best_iteration: AIStrategyResearchIteration | None,
    selected_iteration: AIStrategyResearchIteration | None,
    run_failures: list[str],
    progress_callback: ProgressCallback,
) -> tuple[AIStrategyPaperTradingStart | None, str | None]:
    """Start paper trading for an achieved strategy when requested."""
    if not (achieved and request.start_paper_trading and result_iteration is not None):
        return None, None

    await service._record_pipeline_event(
        user_id=user_id,
        run_id=run_id,
        request=request,
        workspace_id=research_workspace.id,
        stage="paper_trading",
        status="started",
        iteration=result_iteration.iteration,
        summary="达标策略开始进入模拟交易。",
    )
    await _emit_research_progress(
        progress_callback,
        {
            "current_stage": "paper_trading",
            "progress": 88.0,
            "iteration_count": len(iterations),
            "max_iterations": request.max_iterations,
            "latest_iteration": _compact_research_iteration(result_iteration),
            "message": "Starting paper trading for achieved strategy",
        },
    )
    paper_trading: AIStrategyPaperTradingStart | None = None
    paper_trading_error: str | None = None
    try:
        paper_trading = await service._start_paper_trading(
            user_id,
            request,
            result_iteration,
            run_id=run_id,
            research_workspace_id=research_workspace.id,
        )
        paper_trading_error = _paper_trading_start_error(paper_trading)
        if paper_trading_error:
            await service._record_pipeline_event(
                user_id=user_id,
                run_id=run_id,
                request=request,
                workspace_id=research_workspace.id,
                stage="paper_trading",
                status="failed",
                iteration=result_iteration.iteration,
                summary="模拟交易启动失败。",
                error=paper_trading_error,
            )
            await _emit_research_progress(
                progress_callback,
                {
                    "current_stage": "paper_trading_failed",
                    "progress": 92.0,
                    "iteration_count": len(iterations),
                    "max_iterations": request.max_iterations,
                    "latest_iteration": _compact_research_iteration(result_iteration),
                    "message": f"Paper trading start failed: {paper_trading_error}",
                },
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
    except Exception as exc:
        paper_trading_error = str(exc)
        await service._record_pipeline_event(
            user_id=user_id,
            run_id=run_id,
            request=request,
            workspace_id=research_workspace.id,
            stage="paper_trading",
            status="failed",
            iteration=result_iteration.iteration,
            summary="模拟交易启动异常。",
            error=paper_trading_error,
        )
        await _emit_research_progress(
            progress_callback,
            {
                "current_stage": "paper_trading_failed",
                "progress": 92.0,
                "iteration_count": len(iterations),
                "max_iterations": request.max_iterations,
                "latest_iteration": _compact_research_iteration(result_iteration),
                "message": f"Paper trading start failed: {paper_trading_error}",
            },
        )
    if paper_trading is not None and not paper_trading_error:
        await service._record_pipeline_event(
            user_id=user_id,
            run_id=run_id,
            request=request,
            workspace_id=research_workspace.id,
            stage="paper_trading",
            status="completed",
            iteration=result_iteration.iteration,
            summary="模拟交易已启动。",
            output_payload={
                "paper_workspace_id": paper_trading.workspace.id,
                "paper_unit_id": paper_trading.unit.id,
            },
        )
    return paper_trading, paper_trading_error


async def finalize_research_run(
    service: Any,
    *,
    user_id: str,
    run_id: str,
    request: AIStrategyResearchRunRequest,
    research_workspace: WorkspaceResponse,
    started_at: str,
    draft: AIStrategyDraft,
    iterations: list[AIStrategyResearchIteration],
    result_iteration: AIStrategyResearchIteration | None,
    achieved: bool,
    run_failures: list[str],
    paper_trading: AIStrategyPaperTradingStart | None,
    paper_trading_error: str | None,
    promotion_quality_score_fn: Callable[[AIStrategyResearchIteration | None], float],
    promotion_gate_evals_fn: Callable[[AIStrategyResearchIteration], list[dict[str, Any]]],
) -> AIStrategyResearchRunResponse:
    """Build final research run response, sign run record, record completion, and persist."""
    status = "achieved" if achieved else "max_iterations_reached"
    if (
        iterations
        and iterations[-1].unit_status
        and iterations[-1].unit_status.run_status == "timeout"
    ):
        status = "timeout"
    if not iterations and run_failures and not achieved:
        status = "backtest_submission_failed"
    best_metrics = dict(result_iteration.metrics) if result_iteration else {}
    run_failure_diagnostics = _run_failure_diagnostics(run_failures)
    fallback_strategy: StrategyResponse | None = None
    if result_iteration is None and run_failures:
        fallback_strategy = await service._persist_research_draft_strategy(
            user_id, draft, request, run_id=run_id
        )
    paper_monitoring_plan = (
        _paper_monitoring_plan(request, result_iteration)
        if achieved and result_iteration is not None
        else []
    )
    message = _research_completion_message(
        request=request,
        achieved=achieved,
        result_iteration=result_iteration,
        run_failures=run_failures,
    )
    completed_at = _utc_iso_now()
    next_actions = _run_next_actions(
        status=status,
        achieved=achieved,
        request=request,
        result_iteration=result_iteration,
        paper_trading=paper_trading,
        paper_trading_error=paper_trading_error,
        run_failures=run_failures,
    )
    pipeline = _pipeline_summary(
        status=status,
        achieved=achieved,
        iteration_count=len(iterations),
        max_iterations=request.max_iterations,
        out_of_sample_validation=request.out_of_sample_validation,
        validation_status=result_iteration.validation_status if result_iteration else None,
        robustness_validation=request.robustness_validation,
        robustness_status=result_iteration.robustness_status if result_iteration else None,
        paper_trading_started=bool(paper_trading.started) if paper_trading else False,
        paper_trading_error=paper_trading_error,
        paper_review_status=None,
        paper_review_ready_for_live=False,
        workflow_mode=request.workflow_mode,
        workflow_steps=[str(step) for step in request.workflow_steps],
    )
    response = AIStrategyResearchRunResponse(
        run_id=run_id,
        status=status,
        achieved=achieved,
        target_sharpe=request.target_sharpe,
        started_at=started_at,
        completed_at=completed_at,
        best_iteration=result_iteration.iteration if result_iteration else None,
        best_quality_score=promotion_quality_score_fn(result_iteration),
        best_quality_gate_evaluations=(
            promotion_gate_evals_fn(result_iteration) if result_iteration else []
        ),
        robustness_validation=_iteration_robustness_payload(result_iteration),
        best_diagnostics=(
            result_iteration.diagnostics if result_iteration else run_failure_diagnostics
        ),
        best_metrics=best_metrics,
        research_workspace=research_workspace,
        mandate_id=request.mandate_id,
        iterations=iterations,
        best_strategy=result_iteration.strategy if result_iteration else fallback_strategy,
        paper_trading=paper_trading,
        paper_monitoring_plan=paper_monitoring_plan,
        pipeline=pipeline,
        promotion_audit=[],
        next_actions=next_actions,
        message=message,
    )
    run_record = _build_research_run_record(
        run_id=run_id,
        request=request,
        response=response,
        started_at=started_at,
        completed_at=completed_at,
    )
    run_record = _apply_initial_paper_review_to_run_record(
        run_record, paper_trading=paper_trading, user_id=user_id
    )
    run_record = _apply_initial_live_handoff_to_run_record(run_record)
    run_record = sign_ai_research_run_record(
        run_record, user_id=user_id, workspace_id=str(research_workspace.id)
    )
    response_updates: dict[str, Any] = {}
    if run_record.pipeline != response.pipeline:
        response_updates["pipeline"] = run_record.pipeline
    if run_record.next_actions != response.next_actions:
        response_updates["next_actions"] = run_record.next_actions
    if run_record.promotion_audit != response.promotion_audit:
        response_updates["promotion_audit"] = run_record.promotion_audit
    if response_updates:
        response = response.model_copy(update=response_updates)
    await service._record_pipeline_event(
        user_id=user_id,
        run_id=run_id,
        request=request,
        workspace_id=research_workspace.id,
        stage=status,
        status="completed" if achieved else "failed",
        summary=message,
        output_payload={"pipeline": response.pipeline, "next_actions": response.next_actions},
        metrics=best_metrics,
        error=run_failures[-1] if run_failures and not achieved else paper_trading_error,
    )
    research_workspace = await service._persist_research_run_record(
        user_id, research_workspace, run_record
    )
    return response.model_copy(
        update={"research_workspace": research_workspace, "run_record": run_record}
    )
