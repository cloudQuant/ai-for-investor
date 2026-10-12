"""Lifecycle evidence for bounded optimization dispatch and cancellation."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.models.optimization import OptimizationTask
from app.models.user import User
from app.schemas.workspace import ApplyBestParamsRequest
from app.services.optimization import execution_manager
from app.services.optimization.task_state import (
    build_results_response,
    build_runtime_task_from_db_task,
    get_runtime_task,
    set_runtime_task,
    transition_runtime_task,
    update_runtime_task,
)
from app.services.optimization.thread_runner import run_optimization_thread
from app.services.optimization.trial_runner import run_single_trial

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_OLD_HEAD = "20260911_market_data_b2_completeness_evidence"
_OBJECTIVE_REVISION = "20261012_optimization_objective_direction"


class _SingleWorkerProcessPool(ProcessPoolExecutor):
    """Use a real process pool with one worker to keep the second job queued."""

    def __init__(self, *, max_workers: int) -> None:
        assert max_workers == 2
        super().__init__(max_workers=1)


def _run_real_trial_with_marker(
    strategy_dir: str,
    params: dict[str, Any],
    trial_index: int,
    tmp_base: str,
    artifact_root: str | None,
    cancellation_marker: str,
) -> dict[str, Any]:
    return run_single_trial(
        strategy_dir,
        params,
        trial_index,
        tmp_base,
        artifact_root,
        cancellation_marker=cancellation_marker,
    )


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _upgrade_objective_revision(engine: Engine, database_url: str) -> None:
    config = _alembic_config(database_url)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, _OBJECTIVE_REVISION)


def test_objective_migration_upgrades_existing_sqlite_task_rows(tmp_path: Path) -> None:
    script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
    assert script.get_heads() == [_OBJECTIVE_REVISION]
    revision = script.get_revision(_OBJECTIVE_REVISION)
    assert revision is not None and revision.down_revision == _OLD_HEAD

    database_url = f"sqlite:///{tmp_path / 'optimization-migration.db'}"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE optimization_tasks "
                    "(id VARCHAR(36) PRIMARY KEY, status VARCHAR(20) NOT NULL)"
                )
            )
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(255) NOT NULL PRIMARY KEY)")
            )
            connection.execute(
                text("INSERT INTO optimization_tasks (id, status) VALUES ('legacy', 'completed')")
            )
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": _OLD_HEAD},
            )

            config = _alembic_config(database_url)
            config.attributes["connection"] = connection
            command.upgrade(config, _OBJECTIVE_REVISION)

        columns = {
            column["name"]: column for column in inspect(engine).get_columns("optimization_tasks")
        }
        assert columns["objective"]["nullable"] is True
        assert columns["direction"]["nullable"] is True
        with engine.connect() as connection:
            legacy = connection.execute(
                text("SELECT objective, direction FROM optimization_tasks WHERE id = 'legacy'")
            ).one()
            current_revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert legacy == (None, None)
        assert current_revision == _OBJECTIVE_REVISION
    finally:
        engine.dispose()


def test_objective_migration_preserves_compatible_current_model_columns(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'optimization-current-model.db'}"
    engine = create_engine(database_url)
    try:
        User.__table__.create(engine)
        OptimizationTask.__table__.create(engine)
        with engine.begin() as connection:
            connection.execute(
                User.__table__.insert().values(
                    id="user-1",
                    username="optimization-migration",
                    email="optimization-migration@example.invalid",
                    hashed_password="test-only",
                )
            )
            connection.execute(
                OptimizationTask.__table__.insert().values(
                    id="task-1",
                    user_id="user-1",
                    strategy_id="strategy-1",
                    status="completed",
                    total=1,
                    completed=1,
                    failed=0,
                    results=[],
                    n_workers=1,
                    objective="max_drawdown",
                    direction="minimize",
                )
            )
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(255) NOT NULL PRIMARY KEY)")
            )
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": _OLD_HEAD},
            )

        _upgrade_objective_revision(engine, database_url)

        with engine.connect() as connection:
            task = connection.execute(
                text("SELECT objective, direction FROM optimization_tasks WHERE id = 'task-1'")
            ).one()
        assert task == ("max_drawdown", "minimize")
    finally:
        engine.dispose()


def test_objective_migration_adds_a_missing_compatible_column(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'optimization-partial-model.db'}"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE optimization_tasks ("
                    "id VARCHAR(36) PRIMARY KEY, objective VARCHAR(64) NULL)"
                )
            )
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(255) NOT NULL PRIMARY KEY)")
            )
            connection.execute(
                text(
                    "INSERT INTO optimization_tasks (id, objective) VALUES ('task-1', 'sharpe_ratio')"
                )
            )
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": _OLD_HEAD},
            )

        _upgrade_objective_revision(engine, database_url)

        columns = {
            column["name"]: column for column in inspect(engine).get_columns("optimization_tasks")
        }
        assert columns["objective"]["type"].length == 64
        assert columns["objective"]["nullable"] is True
        assert columns["direction"]["type"].length == 16
        assert columns["direction"]["nullable"] is True
        with engine.connect() as connection:
            value = connection.execute(
                text("SELECT objective FROM optimization_tasks WHERE id = 'task-1'")
            ).scalar_one()
        assert value == "sharpe_ratio"
    finally:
        engine.dispose()


def test_objective_migration_rejects_incompatible_schema_before_adding_any_column(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'optimization-incompatible-model.db'}"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE optimization_tasks ("
                    "id VARCHAR(36) PRIMARY KEY, direction VARCHAR(8) NULL)"
                )
            )
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(255) NOT NULL PRIMARY KEY)")
            )
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": _OLD_HEAD},
            )

        with pytest.raises(RuntimeError, match="OPTIMIZATION_OBJECTIVE_SCHEMA_CONFLICT"):
            _upgrade_objective_revision(engine, database_url)

        columns = {column["name"] for column in inspect(engine).get_columns("optimization_tasks")}
        assert "objective" not in columns
        assert "direction" in columns
        with engine.connect() as connection:
            current_revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert current_revision == _OLD_HEAD
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_task_creation_round_trips_objective_before_any_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'optimization-roundtrip.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
            await connection.run_sync(OptimizationTask.__table__.create)

        maker = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(execution_manager, "async_session_maker", maker)
        async with maker() as session:
            session.add(
                User(
                    id="user-1",
                    username="optimization-test",
                    email="optimization-test@example.invalid",
                    hashed_password="test-only",
                )
            )
            await session.commit()

        manager = execution_manager.OptimizationExecutionManager()
        created = await manager.create_task(
            user_id="user-1",
            strategy_id="harmless-local-strategy",
            total=2,
            param_ranges={"value": {"start": 1, "end": 2, "step": 1, "type": "int"}},
            n_workers=1,
            objective="sharpe_ratio",
            direction="maximize",
        )
        async with maker() as session:
            reloaded = await session.get(OptimizationTask, created.id)

        assert reloaded is not None
        assert reloaded.objective == "sharpe_ratio"
        assert reloaded.direction == "maximize"
        runtime_task = build_runtime_task_from_db_task(reloaded)
        assert runtime_task["objective"] == "sharpe_ratio"
        assert runtime_task["direction"] == "maximize"
        assert runtime_task["results"] == []
    finally:
        await engine.dispose()


def test_runtime_terminal_status_is_first_writer_wins_under_race() -> None:
    for index in range(10):
        task_id = f"terminal-race-{index}"
        set_runtime_task(task_id, {"status": "running", "completed": 0})
        barrier = threading.Barrier(3)
        outcomes: list[dict[str, Any] | None] = []

        def _transition(
            status: str,
            task_id: str = task_id,
            barrier: threading.Barrier = barrier,
            outcomes: list[dict[str, Any] | None] = outcomes,
        ) -> None:
            barrier.wait()
            outcomes.append(transition_runtime_task(task_id, status, completed=1))

        cancellation = threading.Thread(target=_transition, args=("cancelled",))
        completion = threading.Thread(target=_transition, args=("completed",))
        cancellation.start()
        completion.start()
        barrier.wait()
        cancellation.join(timeout=2)
        completion.join(timeout=2)

        final = get_runtime_task(task_id)
        assert not cancellation.is_alive()
        assert not completion.is_alive()
        assert final is not None and final["status"] in {"cancelled", "completed"}
        assert all(
            outcome is not None and outcome["status"] == final["status"] for outcome in outcomes
        )


def test_dispatch_is_bounded_and_artifact_best_matches_api(tmp_path: Path) -> None:
    task_id = "bounded-task"
    task: dict[str, Any] = {
        "status": "running",
        "strategy_id": "harmless-local-strategy",
        "param_ranges": {"score": {"start": 0, "end": 3, "step": 1, "type": "int"}},
        "total": 4,
        "completed": 0,
        "failed": 0,
        "results": [],
        "n_workers": 2,
        "objective": "sharpe_ratio",
        "direction": "maximize",
        "tie_break": "lowest_trial_index",
    }
    base = tmp_path / "dispatch-temp"
    base.mkdir()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    max_pending: list[int] = []

    class _ImmediateExecutor:
        def __init__(self, *, max_workers: int) -> None:
            assert max_workers == 2

        def __enter__(self) -> _ImmediateExecutor:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def submit(self, function: Any, *args: Any) -> Future[dict[str, Any]]:
            future: Future[dict[str, Any]] = Future()
            future.set_result(function(*args))
            return future

    def _trial(
        _strategy_dir: str,
        params: dict[str, int],
        trial_index: int,
        _tmp_base: str,
        _artifact_root: str | None,
        _cancel_marker: str,
    ) -> dict[str, Any]:
        score = 5.0 if params["score"] in {1, 2} else 1.0
        return {
            "success": True,
            "trial_index": trial_index,
            "params": params,
            "metrics": {"sharpe_ratio": score},
        }

    def _completed_one(futures: tuple[Future[dict[str, Any]], ...], *, timeout: float) -> list[Any]:
        del timeout
        max_pending.append(len(futures))
        return [next(future for future in futures if future.done())]

    def _update(_task_id: str, **changes: Any) -> dict[str, Any]:
        task.update(changes)
        return dict(task)

    def _persist(_task_id: str, **changes: Any) -> bool:
        if changes:
            if task["status"] not in {"pending", "queued", "running"}:
                return False
            task.update(changes)
        return True

    run_optimization_thread(
        task_id,
        "unused-strategy-path",
        [{"score": value} for value in range(4)],
        2,
        persist_to_db=True,
        artifact_root=str(artifact_root),
        run_single_trial_fn=_trial,
        is_cancelled_fn=lambda _task_id, _persist: task["status"] == "cancelled",
        persist_runtime_task_fn=_persist,
        get_task_fn=lambda _task_id: dict(task),
        update_task_fn=_update,
        process_pool_executor_cls=_ImmediateExecutor,
        as_completed_fn=_completed_one,
        mkdtemp_fn=lambda **_kwargs: str(base),
        rmtree_fn=shutil.rmtree,
    )

    assert max(max_pending) == 2
    assert task["status"] == "completed"
    assert not base.exists()
    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["cleanup_confirmed"] is True
    assert summary["objective"] == "sharpe_ratio"
    assert summary["direction"] == "maximize"
    assert summary["best_result"]["trial_index"] == 1
    response = build_results_response(task_id, task)
    assert response["best"]["trial_index"] == summary["best_result"]["trial_index"]
    assert response["best"]["result_index"] == 1


def test_failed_terminal_cas_uses_database_winner_for_artifact_summary(tmp_path: Path) -> None:
    task_id = f"cas-winner-{threading.get_ident()}"
    runtime_task = {
        "status": "cancelled",
        "strategy_id": "harmless-local-strategy",
        "param_ranges": {"score": {"start": 1, "end": 1, "step": 1, "type": "int"}},
        "total": 1,
        "completed": 0,
        "failed": 0,
        "results": [],
        "n_workers": 1,
        "objective": "sharpe_ratio",
        "direction": "maximize",
        "tie_break": "lowest_trial_index",
    }
    set_runtime_task(task_id, runtime_task)
    database_result = {
        "trial_index": 0,
        "params": {"score": 1},
        "metrics": {"sharpe_ratio": 2.5},
        "success": True,
    }
    database_winner = {
        **runtime_task,
        "status": "completed",
        "completed": 1,
        "failed": 0,
        "results": [database_result],
    }
    persisted_statuses: list[str] = []
    artifact_root = tmp_path / "cas-winner-artifacts"
    artifact_root.mkdir()
    temp_root = tmp_path / "cas-winner-temp"
    temp_root.mkdir()

    def _lose_terminal_cas(_task_id: str, **changes: Any) -> bool:
        if changes.get("status"):
            persisted_statuses.append(str(changes["status"]))
            return False
        return True

    run_optimization_thread(
        task_id,
        "unused-strategy-path",
        [{"score": 1}],
        1,
        persist_to_db=True,
        artifact_root=str(artifact_root),
        run_single_trial_fn=lambda *_args: pytest.fail("stale runtime state must stop dispatch"),
        is_cancelled_fn=lambda _task_id, _persist: True,
        persist_runtime_task_fn=_lose_terminal_cas,
        get_task_fn=lambda _task_id: get_runtime_task(task_id),
        update_task_fn=lambda _task_id, **changes: update_runtime_task(task_id, **changes),
        load_authoritative_task_fn=lambda _task_id: dict(database_winner),
        mkdtemp_fn=lambda prefix: str(temp_root),
        rmtree_fn=shutil.rmtree,
    )

    assert persisted_statuses == ["cancelled"]
    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "completed"
    assert summary["completed"] == 1
    assert summary["objective"] == "sharpe_ratio"
    assert summary["best_result"]["trial_index"] == 0
    assert summary["best_result"]["metrics"]["sharpe_ratio"] == 2.5


@pytest.fixture
def apply_best_params_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, Any, Any, Any]:
    from app.services.workspace import optimization as workspace_optimization
    from app.services.workspace_service import WorkspaceService

    class _SessionContext:
        def __init__(self) -> None:
            self.commits = 0

        async def __aenter__(self) -> _SessionContext:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def commit(self) -> None:
            self.commits += 1

    session = _SessionContext()
    unit = SimpleNamespace(
        id="unit-1",
        last_optimization_task_id="task-1",
        strategy_id="strategy-1",
        params={"existing": True},
        trading_mode="paper",
        unit_settings={},
    )
    results = [
        {
            "trial_index": 0,
            "params": {"value": 0},
            "metrics": {"sharpe_ratio": 0.1},
        },
        {
            "trial_index": 1,
            "params": {"value": 1},
            "metrics": {"sharpe_ratio": 0.9},
        },
    ]
    task = SimpleNamespace(
        results=results,
        strategy_id="strategy-1",
        objective="sharpe_ratio",
        direction="maximize",
    )
    manager = SimpleNamespace(get_task=AsyncMock(return_value=task))
    monkeypatch.setattr(workspace_optimization, "async_session_maker", lambda: session)
    monkeypatch.setattr(
        WorkspaceService,
        "_load_workspace",
        staticmethod(AsyncMock(return_value=object())),
    )
    monkeypatch.setattr(
        WorkspaceService,
        "_get_unit",
        staticmethod(AsyncMock(return_value=unit)),
    )
    monkeypatch.setattr(
        workspace_optimization,
        "get_optimization_execution_manager",
        lambda: manager,
    )
    return workspace_optimization, session, unit, task


@pytest.mark.asyncio
async def test_apply_without_index_selects_configured_best_by_db_result_position(
    apply_best_params_runtime: tuple[Any, Any, Any, Any],
) -> None:
    workspace_optimization, session, unit, _task = apply_best_params_runtime
    result = await workspace_optimization.apply_best_params(
        "workspace-1",
        "user-1",
        ApplyBestParamsRequest(unit_id="unit-1", optimization_task_id="task-1"),
    )

    assert result is not None
    assert result["applied_params"] == {"value": 1}
    assert unit.params == {"existing": True, "value": 1}
    assert session.commits == 1


@pytest.mark.asyncio
async def test_legacy_task_requires_explicit_result_index(
    apply_best_params_runtime: tuple[Any, Any, Any, Any],
) -> None:
    workspace_optimization, session, unit, task = apply_best_params_runtime
    task.objective = None
    task.direction = None

    result = await workspace_optimization.apply_best_params(
        "workspace-1",
        "user-1",
        ApplyBestParamsRequest(unit_id="unit-1", optimization_task_id="task-1"),
    )

    assert result is not None
    assert "specify result_index explicitly" in result["error"]
    assert unit.params == {"existing": True}
    assert session.commits == 0


@pytest.mark.asyncio
async def test_legacy_task_accepts_explicit_db_result_index(
    apply_best_params_runtime: tuple[Any, Any, Any, Any],
) -> None:
    workspace_optimization, session, unit, task = apply_best_params_runtime
    task.objective = None
    task.direction = None

    result = await workspace_optimization.apply_best_params(
        "workspace-1",
        "user-1",
        ApplyBestParamsRequest(unit_id="unit-1", optimization_task_id="task-1", result_index=1),
    )

    assert result is not None
    assert result["applied_params"] == {"value": 1}
    assert unit.params == {"existing": True, "value": 1}
    assert session.commits == 1


def test_apply_request_rejects_negative_result_index() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ApplyBestParamsRequest(unit_id="unit-1", optimization_task_id="task-1", result_index=-1)


def test_trial_cancellation_stops_local_process_group_and_cleans_trial_dir(tmp_path: Path) -> None:
    strategy_dir = tmp_path / "harmless-strategy"
    strategy_dir.mkdir()
    (strategy_dir / "config.yaml").write_text("params: {}\n", encoding="utf-8")
    (strategy_dir / "run.py").write_text(
        "import signal\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "from pathlib import Path\n"
        "child_holder = {}\n"
        "def stop(_signum, _frame):\n"
        "    child_holder['child'].wait(timeout=5)\n"
        "    raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "child_holder['child'] = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "Path('child.pid').write_text(str(child_holder['child'].pid), encoding='utf-8')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    tmp_base = tmp_path / "trial-temp"
    tmp_base.mkdir()
    cancel_marker = tmp_base / "cancel.requested"
    trial_dir = tmp_base / "trial_0"

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            run_single_trial,
            str(strategy_dir),
            {"value": 1},
            0,
            str(tmp_base),
            None,
            parse_trial_logs_fn=lambda _trial_dir: None,
            cancellation_marker=str(cancel_marker),
        )
        deadline = time.monotonic() + 8
        while not (trial_dir / "child.pid").is_file() and time.monotonic() < deadline:
            if future.done():
                pytest.fail(f"trial exited before cancellation: {future.result()}")
            time.sleep(0.05)
        assert (trial_dir / "child.pid").is_file()
        child_pid = int((trial_dir / "child.pid").read_text(encoding="utf-8"))
        cancel_marker.touch()
        result = future.result(timeout=8)

    assert result["cancelled"] is True
    assert not trial_dir.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_real_process_pool_cancellation_stops_running_and_skips_queued_trial(
    tmp_path: Path,
) -> None:
    strategy_dir = tmp_path / "process-pool-strategy"
    strategy_dir.mkdir()
    artifact_root = tmp_path / "process-pool-artifacts"
    artifact_root.mkdir()
    (strategy_dir / "config.yaml").write_text("params: {}\n", encoding="utf-8")
    (strategy_dir / "run.py").write_text(
        "import signal\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "from pathlib import Path\n"
        "import yaml\n"
        f"artifact_root = Path({str(artifact_root)!r})\n"
        "trial_index = int(yaml.safe_load(Path('config.yaml').read_text())['params']['trial_index'])\n"
        "(artifact_root / f'started_{trial_index}').touch()\n"
        "if trial_index == 0:\n"
        "    child_holder = {}\n"
        "    def stop(_signum, _frame):\n"
        "        child_holder['child'].wait(timeout=5)\n"
        "        raise SystemExit(0)\n"
        "    signal.signal(signal.SIGTERM, stop)\n"
        "    child_holder['child'] = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "    Path('child.pid').write_text(str(child_holder['child'].pid), encoding='utf-8')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    task_id = f"process-pool-cancel-{threading.get_ident()}"
    set_runtime_task(
        task_id,
        {
            "status": "running",
            "strategy_id": "harmless-local-strategy",
            "param_ranges": {"trial_index": {"start": 0, "end": 2, "step": 1, "type": "int"}},
            "total": 3,
            "completed": 0,
            "failed": 0,
            "results": [],
            "n_workers": 2,
            "objective": "sharpe_ratio",
            "direction": "maximize",
            "tie_break": "lowest_trial_index",
        },
    )
    cancellation_requested = threading.Event()
    tmp_base = tmp_path / "process-pool-temp"
    tmp_base.mkdir()
    child_pid_path = tmp_base / "trial_0" / "child.pid"
    cancel_marker = tmp_base / "cancel.requested"
    runner_finished = threading.Event()
    runner_errors: list[BaseException] = []

    def _run_optimization() -> None:
        try:
            run_optimization_thread(
                task_id,
                str(strategy_dir),
                [{"trial_index": 0}, {"trial_index": 1}, {"trial_index": 2}],
                2,
                persist_to_db=False,
                artifact_root=str(artifact_root),
                run_single_trial_fn=_run_real_trial_with_marker,
                is_cancelled_fn=lambda _task_id, _persist: cancellation_requested.is_set(),
                persist_runtime_task_fn=lambda *_args, **_kwargs: True,
                get_task_fn=lambda task_key: get_runtime_task(task_key),
                update_task_fn=lambda task_key, **changes: update_runtime_task(task_key, **changes),
                process_pool_executor_cls=_SingleWorkerProcessPool,
                mkdtemp_fn=lambda prefix: str(tmp_base),
                rmtree_fn=shutil.rmtree,
            )
        except BaseException as exc:
            runner_errors.append(exc)
        finally:
            runner_finished.set()

    runner_thread = threading.Thread(target=_run_optimization, daemon=True)
    runner_thread.start()
    try:
        deadline = time.monotonic() + 30
        while not child_pid_path.is_file() and time.monotonic() < deadline:
            if runner_finished.is_set():
                pytest.fail(
                    f"optimization ended before the harmless local child started: {runner_errors}"
                )
            time.sleep(0.05)
        if not child_pid_path.is_file():
            cancellation_requested.set()
            cancel_marker.touch(exist_ok=True)
            assert runner_finished.wait(timeout=10), (
                "optimization did not stop after startup timeout"
            )
            pytest.fail("harmless local child did not start before the bounded startup deadline")

        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        cancel_started_at = time.monotonic()
        cancellation_requested.set()
        assert runner_finished.wait(timeout=10), "optimization cancellation exceeded 10 seconds"
        runner_thread.join(timeout=0)
        assert not runner_thread.is_alive()
        assert not runner_errors, f"optimization runner failed: {runner_errors}"
        cancel_elapsed = time.monotonic() - cancel_started_at
    finally:
        if runner_thread.is_alive():
            cancellation_requested.set()
            cancel_marker.touch(exist_ok=True)
            runner_thread.join(timeout=10)

    final_task = get_runtime_task(task_id)
    assert not runner_thread.is_alive(), "optimization runner did not exit within the cleanup bound"
    assert cancel_elapsed < 10
    assert final_task is not None and final_task["status"] == "cancelled"
    assert (artifact_root / "started_0").is_file()
    assert not (artifact_root / "started_1").exists()
    assert not tmp_base.exists()
    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "cancelled"
    assert summary["cleanup_confirmed"] is True
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
