"""Focused iteration 202 acceptance tests for optimization boundaries and summaries."""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.optimization.submission import (
    MAX_GRID_COMBINATIONS,
    count_param_grid_combinations,
    submit_optimization,
)
from app.services.optimization.task_state import (
    build_results_response,
    get_runtime_task,
    set_runtime_task,
    update_runtime_task,
)
from app.services.optimization.thread_runner import run_optimization_thread


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        pytest.param(
            {"start": 0, "end": 2, "step": -1}, "step must be positive", id="negative-step"
        ),
        pytest.param(
            {"start": 0, "end": 2, "step": float("nan")},
            "finite number",
            id="nan-step",
        ),
        pytest.param(
            {"start": 0, "end": 2, "step": float("inf")},
            "finite number",
            id="infinite-step",
        ),
        pytest.param(
            {"start": 10_000_000_000_000_000, "end": 10_000_000_000_000_002, "step": 1},
            "does not advance numerically",
            id="float-step-does-not-advance",
        ),
        pytest.param(
            {"start": 0, "end": 2.5, "step": 1, "type": "int"},
            "requires integer",
            id="integer-fractional-end",
        ),
        pytest.param(
            {"start": 0, "end": 2, "step": 1.5, "type": "int"},
            "requires integer",
            id="integer-fractional-step",
        ),
    ],
)
def test_grid_rejects_invalid_step_progress_and_integer_bounds(
    spec: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        count_param_grid_combinations({"period": spec})


def test_single_axis_exact_cap_is_accepted_and_one_over_is_rejected() -> None:
    assert (
        count_param_grid_combinations(
            {"period": {"start": 0, "end": MAX_GRID_COMBINATIONS - 1, "step": 1, "type": "int"}}
        )
        == MAX_GRID_COMBINATIONS
    )

    with pytest.raises(ValueError, match="combination limit"):
        count_param_grid_combinations(
            {"period": {"start": 0, "end": MAX_GRID_COMBINATIONS, "step": 1, "type": "int"}}
        )


def test_cross_axis_exact_cap_is_accepted_and_one_over_is_rejected() -> None:
    exact_cap = {
        name: {"start": 0, "end": 99, "step": 1, "type": "int"} for name in ("fast", "slow")
    }
    assert count_param_grid_combinations(exact_cap) == MAX_GRID_COMBINATIONS

    over_cap = {
        "fast": {"start": 0, "end": 100, "step": 1, "type": "int"},
        "slow": {"start": 0, "end": 99, "step": 1, "type": "int"},
    }
    with pytest.raises(ValueError, match="combination limit"):
        count_param_grid_combinations(over_cap)


@pytest.mark.parametrize(
    "param_ranges",
    [
        pytest.param(
            {"period": {"start": 0, "end": 2, "step": -1, "type": "int"}},
            id="negative-step",
        ),
        pytest.param(
            {
                "fast": {"start": 0, "end": 100, "step": 1, "type": "int"},
                "slow": {"start": 0, "end": 99, "step": 1, "type": "int"},
            },
            id="cross-axis-over-cap",
        ),
    ],
)
@pytest.mark.asyncio
async def test_api_rejects_invalid_grid_before_task_creation(
    param_ranges: dict[str, dict[str, Any]],
) -> None:
    from app.api.optimization_api import submit_optimization_task_internal

    manager = AsyncMock()
    with (
        patch("app.api.optimization_api.get_template_by_id", return_value=object()),
        patch(
            "app.services.optimization.execution_manager.get_optimization_execution_manager",
            return_value=manager,
        ) as get_manager,
        patch("app.services.param_optimization_service.generate_param_grid") as generate_grid,
        pytest.raises(HTTPException) as exc_info,
    ):
        await submit_optimization_task_internal(
            strategy_id="harmless-local-strategy",
            param_ranges=param_ranges,
            n_workers=1,
            user_id="local-test-user",
        )

    assert 400 <= exc_info.value.status_code < 500
    get_manager.assert_not_called()
    generate_grid.assert_not_called()
    manager.create_task.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_blocked_thread_runner_does_not_block_asyncio_heartbeat(tmp_path: Path) -> None:
    runner_started = threading.Event()
    release_runner = threading.Event()
    runner_finished = threading.Event()
    runner_wait_timed_out = threading.Event()
    threads: list[threading.Thread] = []

    def _blocked_runner(
        _task_id: str,
        _strategy_dir: str,
        _grid: list[dict[str, Any]],
        _n_workers: int,
        _persist_to_db: bool,
        _artifact_root: str | None,
    ) -> None:
        runner_started.set()
        if not release_runner.wait(timeout=60):
            runner_wait_timed_out.set()
        runner_finished.set()

    def _thread_factory(**kwargs: Any) -> threading.Thread:
        thread = threading.Thread(**kwargs)
        threads.append(thread)
        return thread

    strategy_dir = tmp_path / "strategy"
    strategy_dir.mkdir()
    (strategy_dir / "run.py").write_text("# harmless local test strategy\n", encoding="utf-8")

    def _unexpected_strategy_resolver(_strategy_id: str) -> Path:
        raise AssertionError("strategy_dir_override should bypass strategy lookup")

    try:
        task_id = submit_optimization(
            "harmless-local-strategy",
            {"period": {"start": 1, "end": 1, "step": 1, "type": "int"}},
            objective="sharpe_ratio",
            direction="maximize",
            get_strategy_dir=_unexpected_strategy_resolver,
            strategy_dir_override=strategy_dir,
            generate_param_grid_fn=lambda _ranges: [{"period": 1}],
            set_task_fn=lambda _task_id, _task: None,
            build_initial_runtime_task_fn=lambda **task: task,
            created_at_fn=lambda: "2026-10-12T00:00:00+00:00",
            running_status="running",
            thread_cls=_thread_factory,
            run_optimization_thread_fn=_blocked_runner,
            task_id_factory=lambda: "heartbeat-test-task",
        )
        assert task_id == "heartbeat-test-task"
        assert await asyncio.to_thread(runner_started.wait, 60)

        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=60)

        assert not runner_finished.is_set()
        assert not runner_wait_timed_out.is_set()
    finally:
        release_runner.set()
        if threads:
            await asyncio.to_thread(threads[0].join, 10)

    assert threads
    assert not threads[0].is_alive()
    assert runner_finished.is_set()
    assert not runner_wait_timed_out.is_set()


def _always_fail_local_trial(
    _strategy_dir: str,
    params: dict[str, Any],
    trial_index: int,
    _tmp_base: str,
    _artifact_root: str | None,
    _cancellation_marker: str,
) -> dict[str, Any]:
    return {
        "success": False,
        "trial_index": trial_index,
        "params": params,
        "metrics": {},
        "error": "controlled local failure",
    }


def test_actual_runner_all_failures_has_no_summary_or_api_best(tmp_path: Path) -> None:
    task_id = f"all-failed-{uuid4().hex}"
    artifact_root = tmp_path / "artifacts" / task_id
    artifact_root.mkdir(parents=True)
    runtime_task = {
        "status": "running",
        "strategy_id": "harmless-local-strategy",
        "param_ranges": {"period": {"start": 1, "end": 2, "step": 1}},
        "total": 2,
        "completed": 0,
        "failed": 0,
        "results": [],
        "n_workers": 2,
        "objective": "sharpe_ratio",
        "direction": "maximize",
        "tie_break": "lowest_trial_index",
    }
    set_runtime_task(task_id, runtime_task)

    temp_root = tmp_path / f"workers-{task_id}"

    def _make_temp_dir(*, prefix: str) -> str:
        del prefix
        temp_root.mkdir()
        return str(temp_root)

    run_optimization_thread(
        task_id,
        "unused-harmless-strategy-path",
        [{"period": 1}, {"period": 2}],
        n_workers=2,
        persist_to_db=False,
        artifact_root=str(artifact_root),
        run_single_trial_fn=_always_fail_local_trial,
        is_cancelled_fn=lambda _task_id, _persist: False,
        persist_runtime_task_fn=lambda *_args, **_kwargs: True,
        get_task_fn=get_runtime_task,
        update_task_fn=update_runtime_task,
        mkdtemp_fn=_make_temp_dir,
        rmtree_fn=shutil.rmtree,
    )

    final_task = get_runtime_task(task_id)
    assert final_task is not None
    assert final_task["failed"] == 2
    assert final_task["results"] == []
    assert not temp_root.exists()

    summary_path = artifact_root / "summary.json"
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["best_result"] is None
    assert build_results_response(task_id, final_task)["best"] is None


def test_nonempty_results_without_finite_objective_candidate_have_no_api_best() -> None:
    response = build_results_response(
        "missing-objective-candidate",
        {
            "status": "completed",
            "objective": "sharpe_ratio",
            "direction": "maximize",
            "results": [
                {
                    "trial_index": 0,
                    "success": True,
                    "params": {"period": 1},
                    "metrics": {"sharpe_ratio": float("nan")},
                },
                {
                    "trial_index": 1,
                    "success": True,
                    "params": {"period": 2},
                    "metrics": {"total_return": 0.2},
                },
            ],
        },
    )

    assert len(response["rows"]) == 2
    assert response["best"] is None
