"""ZIP download coverage for objective-aware optimization summaries."""

from __future__ import annotations

import io
import json
import shutil
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.responses import StreamingResponse

from app.api.workspace_optimization_api import download_unit_optimization_result_artifact
from app.services.optimization.task_state import (
    build_results_response,
    get_runtime_task,
    set_runtime_task,
    update_runtime_task,
)
from app.services.optimization.thread_runner import run_optimization_thread
from app.services.workspace._helpers import build_optimization_artifact_metadata
from app.services.workspace_service import WorkspaceService


def _controlled_local_trial(
    _strategy_dir: str,
    params: dict[str, Any],
    trial_index: int,
    tmp_base: str,
    artifact_root: str | None,
    _cancellation_marker: str,
) -> dict[str, Any]:
    """Return a deterministic local result after both process workers have started."""
    temp_path = Path(tmp_base)
    (temp_path / f"started_{trial_index}").touch()
    peer_started = temp_path / f"started_{1 - trial_index}"
    deadline = time.monotonic() + 60
    while not peer_started.is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("both local optimization workers did not start")
        time.sleep(0.01)

    if bool(params["wait_for_release"]):
        release_marker = temp_path / "release_later_trial"
        deadline = time.monotonic() + 60
        while not release_marker.is_file():
            if time.monotonic() >= deadline:
                raise TimeoutError("runner did not release the gated local trial")
            time.sleep(0.01)

    if artifact_root is None:
        raise ValueError("artifact root is required for this test")

    trial_artifact = Path(artifact_root) / f"trial_{trial_index + 1:04d}"
    trial_artifact.mkdir(parents=True, exist_ok=True)
    metric_name = str(params["metric_name"])
    result = {
        "success": True,
        "trial_index": trial_index,
        "params": dict(params),
        "metrics": {metric_name: float(params["metric_value"])},
        "artifact_path": str(trial_artifact),
    }
    (trial_artifact / "result.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    return result


@pytest.mark.parametrize(
    (
        "objective",
        "direction",
        "scores",
        "later_trial",
        "expected_completion_order",
    ),
    [
        pytest.param(
            "total_return",
            "maximize",
            (1.0, 3.0),
            0,
            (1, 0),
            id="maximize-trial-1-finishes-first",
        ),
        pytest.param(
            "max_drawdown",
            "minimize",
            (8.0, 2.0),
            1,
            (0, 1),
            id="minimize-trial-0-finishes-first",
        ),
    ],
)
@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_downloaded_zip_summary_best_matches_objective_api_result(
    tmp_path: Path,
    objective: str,
    direction: str,
    scores: tuple[float, float],
    later_trial: int,
    expected_completion_order: tuple[int, int],
) -> None:
    task_id = f"artifact-download-{uuid4().hex}"
    artifact_root = tmp_path / "optimization_runs" / task_id
    artifact_root.mkdir(parents=True)
    temp_root = tmp_path / "worker-temp"
    task: dict[str, Any] = {
        "status": "running",
        "strategy_id": "harmless-local-strategy",
        "param_ranges": {"trial": {"start": 0, "end": 1, "step": 1, "type": "int"}},
        "total": 2,
        "completed": 0,
        "failed": 0,
        "results": [],
        "n_workers": 2,
        "objective": objective,
        "direction": direction,
        "tie_break": "lowest_trial_index",
    }
    set_runtime_task(task_id, task)

    def _make_temp_dir(*, prefix: str) -> str:
        del prefix
        temp_root.mkdir()
        return str(temp_root)

    grid = []
    for index in range(2):
        grid.append(
            {
                "metric_name": objective,
                "metric_value": scores[index],
                "wait_for_release": index == later_trial,
            }
        )

    first_trial = 1 - later_trial
    gate_released = False

    def _update_task(task_key: str, **changes: Any) -> dict[str, Any] | None:
        nonlocal gate_released
        updated = update_runtime_task(task_key, **changes)
        if gate_released or not temp_root.is_dir():
            return updated
        results = (updated or {}).get("results")
        if isinstance(results, list) and any(
            isinstance(result, dict) and result.get("trial_index") == first_trial
            for result in results
        ):
            (temp_root / "release_later_trial").touch(exist_ok=True)
            gate_released = True
        return updated

    run_optimization_thread(
        task_id,
        "unused-harmless-strategy-path",
        grid,
        n_workers=2,
        persist_to_db=False,
        artifact_root=str(artifact_root),
        run_single_trial_fn=_controlled_local_trial,
        is_cancelled_fn=lambda _task_id, _persist: False,
        persist_runtime_task_fn=lambda *_args, **_kwargs: True,
        get_task_fn=get_runtime_task,
        update_task_fn=_update_task,
        mkdtemp_fn=_make_temp_dir,
        rmtree_fn=shutil.rmtree,
    )

    completed_task = get_runtime_task(task_id)
    assert completed_task is not None
    assert completed_task["status"] == "completed"
    completion_order = tuple(int(result["trial_index"]) for result in completed_task["results"])
    assert completion_order == expected_completion_order

    api_results = build_results_response(task_id, completed_task)
    api_best = api_results["best"]
    assert api_best is not None
    assert api_best["trial_index"] == 1

    class _ArtifactMetadataService:
        async def get_unit_optimization_result_artifact_metadata(
            self,
            workspace_id: str,
            user_id: str,
            unit_id: str,
            result_index: int,
        ) -> dict[str, Any] | None:
            assert workspace_id == "workspace-local-test"
            assert user_id == "user-local-test"
            assert unit_id == "unit-local-test"
            return build_optimization_artifact_metadata(
                task_id,
                result_index,
                completed_task["results"][result_index],
            )

    archive_response = await download_unit_optimization_result_artifact(
        "workspace-local-test",
        "unit-local-test",
        int(api_best["result_index"]),
        current_user=SimpleNamespace(sub="user-local-test"),
        service=cast(WorkspaceService, _ArtifactMetadataService()),
    )
    assert isinstance(archive_response, StreamingResponse)

    archive_chunks = [chunk async for chunk in archive_response.body_iterator]
    with zipfile.ZipFile(io.BytesIO(b"".join(archive_chunks))) as archive:
        summary_members = [name for name in archive.namelist() if name.endswith("/summary.json")]
        assert summary_members == [f"{task_id}/summary.json"]
        task_summary = json.loads(archive.read(summary_members[0]))

    best_summary = task_summary["best_result"]
    assert task_summary["objective"] == objective
    assert task_summary["direction"] == direction
    assert best_summary["trial_index"] == api_best["trial_index"]
    assert best_summary["params"] == api_best["params"]
    assert best_summary["metrics"][objective] == api_best[objective]
