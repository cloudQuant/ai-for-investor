"""Bounded process-pool execution for optimization trials."""

import json
import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor, TimeoutError, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.backtest import TaskStatus
from app.services.optimization.submission import BEST_RESULT_TIE_BREAK
from app.services.optimization.task_state import select_best_result

module_logger = logging.getLogger(__name__)
_CANCEL_POLL_INTERVAL_SECONDS = 0.25


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _trial_summary_entry(result: dict[str, Any]) -> dict[str, Any]:
    cancelled = bool(result.get("cancelled"))
    is_success = not cancelled and (bool(result.get("success")) or bool(result.get("metrics")))
    status = "cancelled" if cancelled else "success" if is_success else "failed"
    return {
        "trial_index": result.get("trial_index"),
        "success": is_success,
        "status": status,
        "params": dict(result.get("params", {}) or {}),
        "metrics": dict(result.get("metrics", {}) or {}),
        "error": result.get("error"),
        "exit_code": result.get("exit_code"),
        "artifact_path": result.get("artifact_path"),
    }


def _optimization_metadata(runtime_task: dict[str, Any] | None) -> dict[str, Any]:
    task = runtime_task or {}
    return {
        "objective": task.get("objective"),
        "direction": task.get("direction"),
        "tie_break": task.get("tie_break") or BEST_RESULT_TIE_BREAK,
    }


def _with_optimization_metadata(result: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    return {**result, "optimization": dict(metadata)}


def _update_artifact_manifest(
    artifact_root: str | None,
    *,
    task_id: str,
    grid: list[dict[str, Any]],
    runtime_task: dict[str, Any] | None,
    all_trial_results: list[dict[str, Any]],
    successful_results: list[dict[str, Any]],
    final_status: str | None = None,
    cleanup_confirmed: bool | None = None,
    cleanup_error: str | None = None,
    completed_override: int | None = None,
    failed_override: int | None = None,
) -> None:
    if not artifact_root:
        return

    artifact_root_path = Path(artifact_root)
    manifest_path = artifact_root_path / "manifest.json"
    summary_path = artifact_root_path / "summary.json"
    existing_manifest = _read_json(manifest_path)
    objective_metadata = _optimization_metadata(runtime_task)
    completed_count = len(successful_results) if completed_override is None else completed_override
    failed_count = (
        sum(
            1
            for item in all_trial_results
            if not item.get("cancelled")
            and not (bool(item.get("success")) or bool(item.get("metrics")))
        )
        if failed_override is None
        else failed_override
    )
    status = final_status or str(
        (runtime_task or {}).get("status") or existing_manifest.get("status") or "running"
    )
    updated_at = datetime.now(timezone.utc).isoformat()
    trial_entries = sorted(
        (_trial_summary_entry(item) for item in all_trial_results),
        key=lambda item: int(item.get("trial_index", -1) or -1),
    )
    best_result = select_best_result(
        successful_results,
        objective=objective_metadata["objective"],
        direction=objective_metadata["direction"],
    )

    manifest_payload = {
        **existing_manifest,
        "task_id": task_id,
        "artifact_root": str(artifact_root_path),
        "status": status,
        "objective": objective_metadata["objective"],
        "direction": objective_metadata["direction"],
        "tie_break": objective_metadata["tie_break"],
        "total_trials": len(grid),
        "completed": completed_count,
        "failed": failed_count,
        "updated_at": updated_at,
        "successful_trials": completed_count,
        "failed_trials": failed_count,
        "cleanup_confirmed": cleanup_confirmed,
        "cleanup_error": cleanup_error,
        "trial_artifacts": trial_entries,
    }
    _write_json(manifest_path, manifest_payload)

    summary_payload = {
        "task_id": task_id,
        "artifact_root": str(artifact_root_path),
        "status": status,
        "objective": objective_metadata["objective"],
        "direction": objective_metadata["direction"],
        "tie_break": objective_metadata["tie_break"],
        "total_trials": len(grid),
        "completed": completed_count,
        "failed": failed_count,
        "success_rate": round(completed_count / len(grid), 4) if grid else 0.0,
        "best_result": _trial_summary_entry(best_result) if best_result else None,
        "cleanup_confirmed": cleanup_confirmed,
        "cleanup_error": cleanup_error,
        "updated_at": updated_at,
    }
    _write_json(summary_path, summary_payload)


def _cancel_pending_futures(futures: Iterable[Any]) -> None:
    for future in futures:
        future.cancel()


def _finalize_terminal_status(
    task_id: str,
    requested_status: str,
    *,
    completed: int,
    failed: int,
    results: list[dict[str, Any]],
    error_message: str | None,
    persist_to_db: bool,
    persist_runtime_task_fn: Callable[..., bool],
    get_task_fn: Callable[[str], dict[str, Any] | None],
    update_task_fn: Callable[..., dict[str, Any] | None],
    is_cancelled_fn: Callable[[str, bool], bool],
    load_authoritative_task_fn: Callable[[str], dict[str, Any] | None] | None,
) -> dict[str, Any]:
    """Select a terminal winner in DB first, then mirror it into runtime state."""
    if persist_to_db:
        persisted = persist_runtime_task_fn(
            task_id,
            completed=completed,
            failed=failed,
            results=results,
            status=requested_status,
            error_message=error_message,
        )
        if persisted:
            update_task_fn(
                task_id,
                completed=completed,
                failed=failed,
                results=results,
                status=requested_status,
                error=error_message,
            )
            return {
                "status": requested_status,
                "completed": completed,
                "failed": failed,
                "results": results,
                "error": error_message,
            }

        is_cancelled_fn(task_id, persist_to_db)
        task = load_authoritative_task_fn(task_id) if load_authoritative_task_fn else None
        task = task or {}
        current_status = str(task.get("status") or "")
        if current_status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }:
            return task
        return {
            "status": "unconfirmed",
            "completed": completed,
            "failed": failed,
            "results": results,
            "error": "Could not confirm the database terminal task state after a failed CAS",
        }

    updated = update_task_fn(
        task_id,
        completed=completed,
        failed=failed,
        results=results,
        status=requested_status,
        error=error_message,
    )
    return (
        updated
        or get_task_fn(task_id)
        or {
            "status": requested_status,
            "completed": completed,
            "failed": failed,
            "results": results,
            "error": error_message,
        }
    )


def run_optimization_thread(
    task_id: str,
    strategy_dir: str,
    grid: list[dict[str, Any]],
    n_workers: int,
    persist_to_db: bool = True,
    artifact_root: str | None = None,
    *,
    run_single_trial_fn: Callable[..., dict[str, Any]],
    is_cancelled_fn: Callable[[str, bool], bool],
    persist_runtime_task_fn: Callable[..., bool],
    get_task_fn: Callable[[str], dict[str, Any] | None],
    update_task_fn: Callable[..., dict[str, Any] | None],
    load_authoritative_task_fn: Callable[[str], dict[str, Any] | None] | None = None,
    process_pool_executor_cls: type[ProcessPoolExecutor] = ProcessPoolExecutor,
    as_completed_fn: Callable[..., Any] = as_completed,
    mkdtemp_fn: Callable[..., str],
    rmtree_fn: Callable[..., Any],
    logger: logging.Logger | None = None,
) -> None:
    log = logger or module_logger
    tmp_base = mkdtemp_fn(prefix=f"opt_{task_id[:8]}_")
    tmp_base_path = Path(tmp_base)
    cancel_marker = tmp_base_path / "cancel.requested"
    successful_results: list[dict[str, Any]] = []
    all_trial_results: list[dict[str, Any]] = []
    failed_count = 0
    next_trial_index = 0
    cancellation_seen = False
    cleanup_attempted = False
    cleanup_error: str | None = None

    def _cleanup_temp_dir() -> str | None:
        nonlocal cleanup_attempted, cleanup_error
        if cleanup_attempted:
            return cleanup_error
        cleanup_attempted = True
        try:
            rmtree_fn(tmp_base)
        except Exception as exc:
            cleanup_error = f"Temporary optimization directory cleanup failed: {exc}"
        if tmp_base_path.exists():
            cleanup_error = cleanup_error or "Temporary optimization directory still exists"
        if cleanup_error:
            log.error("%s for task %s", cleanup_error, task_id)
        return cleanup_error

    def _cancel_now() -> None:
        nonlocal cancellation_seen
        if cancellation_seen:
            return
        cancellation_seen = True
        try:
            cancel_marker.touch(exist_ok=True)
        except OSError as exc:
            log.error("Failed to write optimization cancellation marker for %s: %s", task_id, exc)

    def _adopt_terminal_snapshot(task_state: dict[str, Any]) -> tuple[str, int, int]:
        nonlocal failed_count
        status = str(task_state.get("status") or "unconfirmed")
        terminal_results = task_state.get("results")
        if isinstance(terminal_results, list):
            successful_results[:] = [item for item in terminal_results if isinstance(item, dict)]
            all_trial_results[:] = list(successful_results)
        completed = int(task_state.get("completed", len(successful_results)) or 0)
        failed_count = int(task_state.get("failed", failed_count) or 0)
        return status, completed, failed_count

    try:
        with process_pool_executor_cls(max_workers=max(1, n_workers)) as executor:
            pending: dict[Any, int] = {}

            def _dispatch_available() -> None:
                nonlocal next_trial_index
                while (
                    not cancellation_seen
                    and len(pending) < max(1, n_workers)
                    and next_trial_index < len(grid)
                ):
                    if is_cancelled_fn(task_id, persist_to_db):
                        _cancel_now()
                        _cancel_pending_futures(pending)
                        return
                    trial_index = next_trial_index
                    next_trial_index += 1
                    future = executor.submit(
                        run_single_trial_fn,
                        strategy_dir,
                        grid[trial_index],
                        trial_index,
                        tmp_base,
                        artifact_root,
                        str(cancel_marker),
                    )
                    pending[future] = trial_index

            _dispatch_available()
            while pending:
                if not cancellation_seen and is_cancelled_fn(task_id, persist_to_db):
                    _cancel_now()
                    _cancel_pending_futures(pending)

                try:
                    completed_future = next(
                        iter(as_completed_fn(tuple(pending), timeout=_CANCEL_POLL_INTERVAL_SECONDS))
                    )
                except TimeoutError:
                    continue
                except StopIteration:
                    continue

                trial_index = pending.pop(completed_future)
                if callable(getattr(completed_future, "cancelled", None)) and (
                    completed_future.cancelled()
                ):
                    continue
                try:
                    trial_result = completed_future.result()
                except Exception as exc:
                    trial_result = {
                        "success": False,
                        "trial_index": trial_index,
                        "params": grid[trial_index],
                        "error": f"worker exception: {exc}",
                    }

                # Results that had not been observed before cancellation are not
                # added after the cancellation CAS; this keeps API and artifact
                # summaries aligned with the persisted winner's snapshot.
                if cancellation_seen:
                    continue
                if not isinstance(trial_result, dict):
                    trial_result = {
                        "success": False,
                        "trial_index": trial_index,
                        "params": grid[trial_index],
                        "error": "worker returned an invalid result",
                    }
                trial_result.setdefault("trial_index", trial_index)
                trial_result.setdefault("params", grid[trial_index])
                current_task = get_task_fn(task_id) or {}
                metadata = _optimization_metadata(current_task)
                trial_result = _with_optimization_metadata(trial_result, metadata)
                trial_succeeded = bool(trial_result.get("success")) or bool(
                    trial_result.get("metrics")
                )
                if trial_result.get("cancelled"):
                    _cancel_now()
                    _cancel_pending_futures(pending)
                    continue

                all_trial_results.append(trial_result)
                if trial_succeeded:
                    successful_results.append(trial_result)
                else:
                    failed_count += 1

                updated = update_task_fn(
                    task_id,
                    completed=len(successful_results),
                    failed=failed_count,
                    results=list(successful_results),
                )
                if updated and updated.get("status") in {
                    TaskStatus.CANCELLED.value,
                    TaskStatus.COMPLETED.value,
                    TaskStatus.FAILED.value,
                }:
                    all_trial_results.pop()
                    if trial_succeeded:
                        successful_results.pop()
                    else:
                        failed_count -= 1
                    if updated.get("status") == TaskStatus.CANCELLED.value:
                        _cancel_now()
                        _cancel_pending_futures(pending)
                    continue

                if persist_to_db:
                    persisted = persist_runtime_task_fn(task_id)
                    if not persisted and is_cancelled_fn(task_id, persist_to_db):
                        all_trial_results.pop()
                        if trial_succeeded:
                            successful_results.pop()
                        else:
                            failed_count -= 1
                        _cancel_now()
                        _cancel_pending_futures(pending)
                        continue

                _update_artifact_manifest(
                    artifact_root,
                    task_id=task_id,
                    grid=grid,
                    runtime_task=get_task_fn(task_id),
                    all_trial_results=all_trial_results,
                    successful_results=successful_results,
                )
                _dispatch_available()

            if not cancellation_seen and is_cancelled_fn(task_id, persist_to_db):
                _cancel_now()

        cleanup_error = _cleanup_temp_dir()
        task = get_task_fn(task_id) or {}
        requested_status = (
            TaskStatus.CANCELLED.value
            if cancellation_seen or task.get("status") == TaskStatus.CANCELLED.value
            else TaskStatus.FAILED.value
            if cleanup_error
            else TaskStatus.COMPLETED.value
        )
        terminal_state = _finalize_terminal_status(
            task_id,
            requested_status,
            completed=len(successful_results),
            failed=failed_count,
            results=successful_results,
            error_message=cleanup_error,
            persist_to_db=persist_to_db,
            persist_runtime_task_fn=persist_runtime_task_fn,
            get_task_fn=get_task_fn,
            update_task_fn=update_task_fn,
            is_cancelled_fn=is_cancelled_fn,
            load_authoritative_task_fn=load_authoritative_task_fn,
        )
        final_status, final_completed, final_failed = _adopt_terminal_snapshot(terminal_state)
        manifest_task = {**(get_task_fn(task_id) or {}), **terminal_state}

        _update_artifact_manifest(
            artifact_root,
            task_id=task_id,
            grid=grid,
            runtime_task=manifest_task,
            all_trial_results=all_trial_results,
            successful_results=successful_results,
            final_status=final_status,
            cleanup_confirmed=cleanup_error is None,
            cleanup_error=cleanup_error,
            completed_override=final_completed,
            failed_override=final_failed,
        )

        log.info(
            "Optimization %s %s: %s/%s successful",
            task_id,
            final_status,
            len(successful_results),
            len(grid),
        )

    except Exception as exc:
        log.error("Optimization task failed %s: %s", task_id, exc)
        cleanup_error = _cleanup_temp_dir()
        requested_status = TaskStatus.FAILED.value
        terminal_state = _finalize_terminal_status(
            task_id,
            requested_status,
            completed=len(successful_results),
            failed=failed_count,
            results=successful_results,
            error_message=f"{exc}; {cleanup_error}" if cleanup_error else str(exc),
            persist_to_db=persist_to_db,
            persist_runtime_task_fn=persist_runtime_task_fn,
            get_task_fn=get_task_fn,
            update_task_fn=update_task_fn,
            is_cancelled_fn=is_cancelled_fn,
            load_authoritative_task_fn=load_authoritative_task_fn,
        )
        final_status, final_completed, final_failed = _adopt_terminal_snapshot(terminal_state)
        manifest_task = {**(get_task_fn(task_id) or {}), **terminal_state}
        _update_artifact_manifest(
            artifact_root,
            task_id=task_id,
            grid=grid,
            runtime_task=manifest_task,
            all_trial_results=all_trial_results,
            successful_results=successful_results,
            final_status=final_status,
            cleanup_confirmed=cleanup_error is None,
            cleanup_error=cleanup_error,
            completed_override=final_completed,
            failed_override=final_failed,
        )
    finally:
        _cleanup_temp_dir()
