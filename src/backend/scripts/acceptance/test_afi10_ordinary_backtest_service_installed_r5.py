"""Run AFI's real BacktestService route with installed Backtrader and local bars.

This is an ordinary offline backtest check. It deliberately does not import
``app.main`` or start any service-v2 operator/provider lifecycle.
"""

from __future__ import annotations

import asyncio
import csv
import importlib.abc
import importlib.metadata
import json
import os
import re
import socket
import sys
import textwrap
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient


_OPTIONAL_DISTRIBUTIONS = {
    "bt-api-py",
    "bt-api-base",
    "bt-api-gateway",
    "bt-api-execution",
    "bt-api-risk",
    "bt-api-monitor",
    "bt-api-transport-zmq",
    "bt-api-okx",
    "bt-api-ctp",
    "bt-api-binance",
}
_OPTIONAL_IMPORT_PREFIXES = tuple(
    name.replace("-", "_")
    for name in (
        "bt-api-py",
        "bt-api-base",
        "bt-api-gateway",
        "bt-api-execution",
        "bt-api-risk",
        "bt-api-monitor",
        "bt-api-transport-zmq",
        "bt-api-okx",
        "bt-api-ctp",
        "bt-api-binance",
    )
)
_REPOSITORY_ROOTS = tuple(
    Path(path).resolve()
    for path in (
        r"D:\bt_api_py",
        r"D:\source_code\backtrader",
        r"D:\source_code\ai-for-investor\src\backend",
    )
)
_USER_ID = "ordinary-installed-backtest-user"
_BACKTRADER_WHEEL_SHA256 = "f48328ebba1d1bd7c259c135d6477e638f0e920c66f1b1ee3ab18f3721745561"
_AFI_WHEEL_SHA256 = "ae0ed4794ab775e00f9ac64c4b2a124ca7d40c1635714ed5a41d1c668a981fd0"


class _OptionalPackageBlocker(importlib.abc.MetaPathFinder):
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if any(
            fullname == prefix or fullname.startswith(prefix + ".")
            for prefix in _OPTIONAL_IMPORT_PREFIXES
        ):
            self.attempts.append(fullname)
            raise ModuleNotFoundError(
                f"Optional service package import blocked in ordinary-backtest check: {fullname}",
                name=fullname,
            )
        return None


def _distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _assert_no_repository_import_roots() -> None:
    for raw in sys.path:
        candidate = Path(raw or os.getcwd()).resolve()
        for root in _REPOSITORY_ROOTS:
            if candidate == root or root in candidate.parents:
                raise AssertionError(f"Repository source leaked onto sys.path: {candidate}")


def _write_fixture_bars(path: Path) -> tuple[int, date, date]:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[date, float]] = []
    current = date(2022, 11, 1)
    while len(rows) < 36:
        if current.weekday() < 5:
            rows.append((current, 10.0 + len(rows) * 0.1))
        current += timedelta(days=1)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for index, (day, close) in enumerate(rows):
            writer.writerow(
                [
                    day.isoformat(),
                    f"{close - 0.05:.2f}",
                    f"{close + 0.10:.2f}",
                    f"{close - 0.10:.2f}",
                    f"{close:.2f}",
                    str(1000 + index),
                ]
            )
    return len(rows), rows[0][0], rows[-1][0]


def _write_strategy_fixture(strategy_dir: Path) -> None:
    strategy_dir.mkdir(parents=True, exist_ok=True)
    (strategy_dir / "config.yaml").write_text(
        "strategy:\n  name: Installed ordinary backtest\n"
        "data:\n  symbol: 000001.SZ\n  timeframe: 1d\n"
        "backtest:\n  initial_cash: 100000\n  commission: 0.001\n",
        encoding="utf-8",
    )
    (strategy_dir / "run.py").write_text(
        textwrap.dedent(
            r'''
            from __future__ import annotations

            import csv
            import importlib.metadata
            import json
            import os
            import re
            import sys
            from pathlib import Path

            import backtrader as bt
            import pandas as pd
            import sitecustomize

            def _distribution_name(value):
                return re.sub(r"[-_.]+", "-", value).lower()

            optional = {
                "bt-api-py", "bt-api-base", "bt-api-gateway", "bt-api-execution",
                "bt-api-risk", "bt-api-monitor", "bt-api-transport-zmq", "bt-api-okx",
                "bt-api-ctp", "bt-api-binance",
            }
            installed = {
                _distribution_name(dist.metadata.get("Name", ""))
                for dist in importlib.metadata.distributions()
            }
            optional_dists = sorted(optional & installed)
            if optional_dists:
                raise RuntimeError("OPTIONAL_DISTRIBUTION_PRESENT")
            if sitecustomize.state["blocked_imports"]:
                raise RuntimeError("OPTIONAL_IMPORT_ATTEMPTED")
            if not sitecustomize.state["guard_installed"]:
                raise RuntimeError("CHILD_GUARD_NOT_INSTALLED")

            csv_path = Path(os.environ["AFI_ORDINARY_LOCAL_CSV"])
            frame = pd.read_csv(csv_path)
            if frame.empty:
                raise RuntimeError("SYNTHETIC_CSV_EMPTY")
            frame["datetime"] = pd.to_datetime(frame["datetime"])
            frame = frame.set_index("datetime")
            for name in ("open", "high", "low", "close", "volume"):
                frame[name] = pd.to_numeric(frame[name], errors="raise")

            class RecordEquity(bt.Strategy):
                def __init__(self):
                    self._log_path = Path(os.environ["BACKTRADER_LOG_DIR"]) / "value.log"
                    self._log_path.parent.mkdir(parents=True, exist_ok=True)
                    self._handle = self._log_path.open("w", encoding="utf-8", newline="")
                    self._writer = csv.writer(self._handle, delimiter="\t")
                    self._writer.writerow(["dt", "value", "cash"])

                def next(self):
                    day = self.data.datetime.datetime(0)
                    self._writer.writerow([
                        day.isoformat(sep=" "),
                        f"{self.broker.getvalue():.8f}",
                        f"{self.broker.getcash():.8f}",
                    ])
                    self._handle.flush()
                    if len(self) == 2 and not self.position:
                        self.buy(size=10)
                    elif len(self) == 8 and self.position:
                        self.close()

                def stop(self):
                    self._handle.close()

            cerebro = bt.Cerebro()
            cerebro.broker.setcash(100000.0)
            cerebro.broker.setcommission(commission=0.001)
            cerebro.adddata(bt.feeds.PandasData(dataname=frame))
            cerebro.addstrategy(RecordEquity)
            results = cerebro.run()
            if len(results) != 1:
                raise RuntimeError("CEREBRO_RESULT_COUNT_INVALID")
            if not Path(os.environ["BACKTRADER_LOG_DIR"], "value.log").is_file():
                raise RuntimeError("EQUITY_LOG_MISSING")

            module_path = Path(bt.__file__).resolve()
            site_packages = Path(sys.prefix, "Lib", "site-packages").resolve()
            if site_packages not in module_path.parents:
                raise RuntimeError("BACKTRADER_NOT_FROM_INSTALLED_SITE_PACKAGES")
            if any(root == path or root in path.parents for root in (
                Path(r"D:\bt_api_py").resolve(),
                Path(r"D:\source_code\backtrader").resolve(),
                Path(r"D:\source_code\ai-for-investor\src\backend").resolve(),
            ) for path in map(lambda entry: Path(entry or os.getcwd()).resolve(), sys.path)):
                raise RuntimeError("SOURCE_REPOSITORY_ON_CHILD_PATH")

            record = {
                "python": sys.executable,
                "backtrader_origin": str(module_path),
                "backtrader_version": importlib.metadata.version("backtrader"),
                "bars_seen": len(frame),
                "result_count": len(results),
                "blocked_imports": list(sitecustomize.state["blocked_imports"]),
                "network_attempts": sitecustomize.state["network_attempts"],
                "guard_installed": sitecustomize.state["guard_installed"],
            }
            destination = Path(os.environ["AFI_ORDINARY_CHILD_RESULT_JSON"])
            destination.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
            if record["network_attempts"] != 0:
                raise RuntimeError("NETWORK_ATTEMPTED")
            '''
        ).lstrip(),
        encoding="utf-8",
    )
    (strategy_dir / "sitecustomize.py").write_text(
        textwrap.dedent(
            r'''
            from __future__ import annotations

            import importlib.abc
            import json
            import os
            import socket
            import sys
            from pathlib import Path

            OPTIONAL_PREFIXES = (
                "bt_api_py", "bt_api_base", "bt_api_gateway", "bt_api_execution",
                "bt_api_risk", "bt_api_monitor", "bt_api_transport_zmq", "bt_api_okx",
                "bt_api_ctp", "bt_api_binance",
            )
            state = {"blocked_imports": [], "network_attempts": 0, "guard_installed": False}

            class _OptionalBlocker(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if any(fullname == prefix or fullname.startswith(prefix + ".")
                           for prefix in OPTIONAL_PREFIXES):
                        state["blocked_imports"].append(fullname)
                        raise ModuleNotFoundError("Optional service import blocked", name=fullname)
                    return None

            sys.meta_path.insert(0, _OptionalBlocker())

            def _deny_network(*args, **kwargs):
                state["network_attempts"] += 1
                raise OSError("network disabled in ordinary synthetic backtest")

            socket.create_connection = _deny_network
            socket.socket.connect = _deny_network
            socket.socket.connect_ex = _deny_network
            state["guard_installed"] = True
            Path(os.environ["AFI_ORDINARY_CHILD_RESULT_JSON"]).write_text(
                json.dumps(state, sort_keys=True), encoding="utf-8"
            )
            '''
        ).lstrip(),
        encoding="utf-8",
    )


async def _cancel_and_reap_owned_execution(service: Any, task_id: str) -> list[str]:
    """Use the real service's local cancel path and wait on its exact handles."""
    runner = service.task_runner
    task = runner.get_task(task_id)
    process = runner.get_process(task_id)

    failures: list[str] = []
    task_refs: list[Any] = []
    process_refs: list[Any] = []

    def _remember(current_task: Any, current_process: Any) -> None:
        if current_task is not None and all(current_task is not item for item in task_refs):
            task_refs.append(current_task)
        if current_process is not None and all(current_process is not item for item in process_refs):
            process_refs.append(current_process)

    _remember(task, process)
    deadline = time.monotonic() + 12.0
    quiet_since: float | None = None
    cancelled_late_handles: set[tuple[int | None, int | None]] = set()
    cancel_required = False
    try:
        # Ask the public service to cancel even when the runner has not yet
        # registered a local handle: a still-pending DB task is cancellable
        # through this exact task/user authorization path.
        cancelled = await service.cancel_task(task_id, _USER_ID)
        if not cancelled:
            status = await service.get_task_status(task_id, _USER_ID)
            status_value = getattr(status, "value", None)
            cancel_required = status is not None and status_value not in {
                "completed",
                "failed",
                "cancelled",
            }
    except BaseException as exc:
        failures.append(f"service_cancel:{type(exc).__name__}")
        cancel_required = True

    while time.monotonic() < deadline:
        known_task_ids = {id(item) for item in task_refs}
        known_process_ids = {id(item) for item in process_refs}
        current_task = runner.get_task(task_id)
        current_process = runner.get_process(task_id)
        current_pair = (
            id(current_task) if current_task is not None else None,
            id(current_process) if current_process is not None else None,
        )
        is_new_handle = (
            (current_task is not None and id(current_task) not in known_task_ids)
            or (current_process is not None and id(current_process) not in known_process_ids)
        )
        _remember(current_task, current_process)
        if (
            (cancel_required or is_new_handle)
            and current_pair not in cancelled_late_handles
            and (current_task is not None or current_process is not None)
        ):
            cancelled_late_handles.add(current_pair)
            try:
                # This is the runner's exact-task local cleanup used by
                # BacktestService.cancel_task; it catches a handle registered
                # just after the service cancellation's first map snapshot.
                runner.cancel_local_execution(task_id)
                cancel_required = False
            except BaseException as exc:
                failures.append(f"runner_cancel:{type(exc).__name__}")

        refs_finished = all(task_ref.done() for task_ref in task_refs) and all(
            process_ref.poll() is not None for process_ref in process_refs
        )
        handles_absent = runner.get_task(task_id) is None and runner.get_process(task_id) is None
        if refs_finished and handles_absent and quiet_since is None and not cancel_required:
            quiet_since = time.monotonic()
        elif (
            refs_finished
            and handles_absent
            and quiet_since is not None
            and time.monotonic() - quiet_since >= 0.2
            and not cancel_required
        ):
            break
        else:
            quiet_since = None
        await asyncio.sleep(0.05)

    for task_ref in task_refs:
        if not task_ref.done():
            failures.append("execution_task_not_done")
    for process_ref in process_refs:
        if process_ref.poll() is None:
            failures.append("subprocess_not_reaped")
        else:
            try:
                process_ref.wait(timeout=0)
            except BaseException as exc:
                failures.append(f"process_reap:{type(exc).__name__}")
    if runner.get_task(task_id) is not None or runner.get_process(task_id) is not None:
        failures.append("runner_handles_remain")
    if cancel_required:
        failures.append("execution_cancel_unconfirmed")
    return failures


async def _exercise_installed_afi_backtest_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: dict[str, Any],
) -> None:
    """POST/status/result use the installed AFI service and installed BT wheel."""
    db_path = tmp_path / "ordinary-backtest.sqlite3"
    data_root = tmp_path / "data" / "datas"
    csv_path = data_root / "stock" / "sz000001_D1.csv"
    strategy_root = tmp_path / "strategies"
    strategy_dir = strategy_root / "ordinary-installed"
    child_result = tmp_path / "child-result.json"
    bar_count, fixture_start, fixture_end = _write_fixture_bars(csv_path)
    _write_strategy_fixture(strategy_dir)

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("AFI_ORDINARY_LOCAL_CSV", str(csv_path))
    monkeypatch.setenv("AFI_ORDINARY_CHILD_RESULT_JSON", str(child_result))
    for name in (
        "SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON",
        "SERVICE_MARKET_DEPLOYMENT_JSON",
        "SERVICE_READ_DEPLOYMENT_JSON",
    ):
        if os.environ.get(name):
            raise AssertionError(f"service-v2 must stay disabled for this ordinary node: {name}")

    blocker = _OptionalPackageBlocker()
    monkeypatch.setattr(sys, "meta_path", [blocker, *sys.meta_path])
    parent_network_attempts: list[bool] = []

    def _deny_parent_network(*args: Any, **kwargs: Any) -> Any:
        parent_network_attempts.append(True)
        raise OSError("network disabled in ordinary synthetic backtest")

    monkeypatch.setattr(socket, "create_connection", _deny_parent_network)
    monkeypatch.setattr(socket.socket, "connect", _deny_parent_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny_parent_network)

    from app import config

    assert config.get_settings().DATABASE_URL == f"sqlite+aiosqlite:///{db_path.as_posix()}"
    from app import models
    from app.api import backtest_enhanced as backtest_api
    from app.db import cache as db_cache
    from app.db import database
    from app.models.user import User
    from app.services import market_data_coverage_service
    from app.services.backtest.service import BacktestService
    from app.services.market_data_precheck_service import MarketDataPrecheckService
    from app.services.strategy import core as strategy_core
    from app.utils import response_cache
    from fastapi import FastAPI

    assert models is not None
    _assert_no_repository_import_roots()
    installed_names = {
        _distribution_name(dist.metadata.get("Name", ""))
        for dist in importlib.metadata.distributions()
    }
    assert not (_OPTIONAL_DISTRIBUTIONS & installed_names)

    monkeypatch.setattr(db_cache, "_cache_instance", db_cache.MemoryCache())
    monkeypatch.setattr(response_cache, "_cache_backend", response_cache.MemoryCacheBackend())
    monkeypatch.setattr(market_data_coverage_service, "_DATA_ROOT", data_root)
    monkeypatch.setattr(strategy_core, "STRATEGIES_DIR", strategy_root)

    db_engine = database._get_engine()
    state["db_engine"] = db_engine
    # Match the normal installed-model schema; result retrieval queries the
    # robustness table even when no robustness row exists.
    assert "robustness_test_results" in database.Base.metadata.tables
    async with db_engine.begin() as connection:
        await connection.run_sync(database.Base.metadata.create_all)
    async with database.async_session_maker() as session:
        session.add(
            User(
                id=_USER_ID,
                username="ordinary-installed-backtest",
                email="ordinary-installed-backtest@example.invalid",
                hashed_password="unused-test-value",
                principal_kind="HUMAN",
            )
        )
        await session.commit()

    coverage = market_data_coverage_service.MarketDataCoverageService()
    precheck = MarketDataPrecheckService(coverage_service=coverage)
    from app.api.deps import get_current_user

    app = FastAPI()
    app.include_router(backtest_api.router, prefix="/api/v1/backtests")
    app.dependency_overrides[get_current_user] = lambda: type("CurrentUser", (), {"sub": _USER_ID})()
    service = BacktestService()
    state["service"] = service
    state["baseline_task_ids"] = set(service.task_runner._tasks)
    state["baseline_process_ids"] = set(service.task_runner._processes)
    app.dependency_overrides[backtest_api.get_backtest_service] = lambda: service
    from app.services.backtest import service as backtest_service_module

    monkeypatch.setattr(backtest_service_module, "get_market_data_precheck_service", lambda: precheck)

    assert Path(backtest_api.__file__).resolve().is_relative_to(
        (Path(sys.prefix) / "Lib" / "site-packages").resolve()
    )
    assert importlib.metadata.version("backtrader") == "1.4.0"
    assert importlib.metadata.distribution("backtrader").read_text("direct_url.json")
    backtrader_direct_url = json.loads(
        importlib.metadata.distribution("backtrader").read_text("direct_url.json") or "{}"
    )
    afi_direct_url = json.loads(
        importlib.metadata.distribution("ai-for-investor-backend").read_text("direct_url.json")
        or "{}"
    )
    assert backtrader_direct_url["archive_info"]["hashes"]["sha256"] == _BACKTRADER_WHEEL_SHA256
    assert afi_direct_url["archive_info"]["hashes"]["sha256"] == _AFI_WHEEL_SHA256

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://afi.test") as client:
        submitted = await client.post(
            "/api/v1/backtests/run",
            json={
                "strategy_id": "ordinary-installed",
                "symbol": "000001.SZ",
                "start_date": f"{fixture_start.isoformat()}T00:00:00",
                "end_date": f"{fixture_end.isoformat()}T00:00:00",
                "initial_cash": 100000,
                "commission": 0.001,
                "timeframe": "1d",
                "timeframe_n": 1,
                "asset_type": "stock",
                "data_provider": "local_csv",
                "require_data_precheck": False,
                "params": {},
            },
        )
        assert submitted.status_code == 200, submitted.text
        task_id = submitted.json()["task_id"]
        state["task_id"] = task_id

        deadline = time.monotonic() + 24.0
        status_response = None
        while time.monotonic() < deadline:
            status_response = await client.get(f"/api/v1/backtests/{task_id}/status")
            assert status_response.status_code == 200, status_response.text
            if status_response.json()["status"] in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.05)
        assert status_response is not None
        assert status_response.json()["status"] == "completed", status_response.text

        runner_task = service.task_runner.get_task(task_id)
        runner_deadline = time.monotonic() + 10.0
        while runner_task is not None and not runner_task.done() and time.monotonic() < runner_deadline:
            await asyncio.sleep(0.01)
            runner_task = service.task_runner.get_task(task_id)
        assert runner_task is None or runner_task.done(), "backtest runner task did not finish"

        result_response = await client.get(f"/api/v1/backtests/{task_id}")
        assert result_response.status_code == 200, result_response.text
        result = result_response.json()

    assert result["status"] == "completed"
    assert len(result["equity_curve"]) == bar_count
    assert result["data_precheck"]["provider"] == "local_csv"
    assert result["data_precheck"]["coverage"]["source_path"] == str(csv_path)
    assert result["data_precheck"]["coverage"]["start_date"] == fixture_start.isoformat()
    assert result["data_precheck"]["coverage"]["end_date"] == fixture_end.isoformat()
    assert service.task_runner.get_process(task_id) is None
    assert service.task_runner.get_task(task_id) is None
    assert child_result.is_file()
    child = json.loads(child_result.read_text(encoding="utf-8"))
    assert child["python"] == sys.executable
    assert child["backtrader_version"] == "1.4.0"
    assert Path(child["backtrader_origin"]).resolve().is_relative_to(
        (Path(sys.prefix) / "Lib" / "site-packages").resolve()
    )
    assert child["bars_seen"] == bar_count
    assert child["result_count"] == 1
    assert child["blocked_imports"] == []
    assert child["network_attempts"] == 0
    assert child["guard_installed"] is True
    assert not blocker.attempts
    assert not parent_network_attempts


@pytest.mark.asyncio
async def test_installed_afi_backtest_service_runs_offline_through_real_cerebro(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {}
    primary_error: BaseException | None = None
    cleanup_errors: list[str] = []
    try:
        await _exercise_installed_afi_backtest_service(tmp_path, monkeypatch, state)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        service = state.get("service")
        if service is not None and primary_error is not None:
            runner = service.task_runner
            task_ids = set(state.get("baseline_task_ids", set()))
            process_ids = set(state.get("baseline_process_ids", set()))
            candidate_ids = (set(runner._tasks) - task_ids) | (set(runner._processes) - process_ids)
            task_id = state.get("task_id")
            if task_id:
                candidate_ids.add(task_id)
            for owned_task_id in sorted(candidate_ids):
                try:
                    cleanup_errors.extend(
                        await _cancel_and_reap_owned_execution(service, owned_task_id)
                    )
                except BaseException as exc:
                    cleanup_errors.append(f"execution_cleanup:{type(exc).__name__}")

        db_engine = state.get("db_engine")
        if db_engine is not None:
            try:
                await db_engine.dispose()
            except BaseException as exc:
                cleanup_errors.append(f"database_dispose:{type(exc).__name__}")

        if cleanup_errors:
            summary = ",".join(cleanup_errors)
            if primary_error is not None:
                primary_error.add_note(f"test cleanup incomplete: {summary}")
            else:
                raise AssertionError(f"test cleanup incomplete: {summary}")
