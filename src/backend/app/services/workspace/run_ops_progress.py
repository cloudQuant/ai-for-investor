"""Workspace unit-run progress projection."""

from __future__ import annotations

from app.models.backtest import BacktestTask


def task_runtime_info(task: BacktestTask | None) -> dict[str, object]:
    if task is None:
        return {}
    request_data: dict[str, object] = (
        task.request_data if isinstance(task.request_data, dict) else {}
    )
    runtime = request_data.get("_runtime")
    return runtime if isinstance(runtime, dict) else {}


def unit_run_progress(
    task: BacktestTask | None,
    run_status: str,
) -> tuple[float | None, str | None]:
    runtime = task_runtime_info(task)
    raw_progress = runtime.get("progress")
    progress = float(raw_progress) if isinstance(raw_progress, (int, float)) else None
    raw_message = runtime.get("message")
    message = raw_message if isinstance(raw_message, str) else None
    if progress is None:
        if run_status in {"queued", "idle"}:
            progress = 0.0
        elif run_status == "running":
            progress = 10.0
        elif run_status in {"completed", "failed", "cancelled"}:
            progress = 100.0
    if progress is not None:
        progress = max(0.0, min(progress, 100.0))
    return progress, message
