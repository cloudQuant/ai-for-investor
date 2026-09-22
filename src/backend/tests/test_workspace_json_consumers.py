from types import SimpleNamespace

import pytest

from app.models.workspace import WorkspaceJSONMapping
from app.services.workspace import optimization, reports


class _AsyncSessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> bool:
        return False


def test_optimization_config_merge_preserves_valid_nested_json_and_replaces_run_fields():
    current: WorkspaceJSONMapping = {
        "objective": "sharpe_max",
        "saved_options": {"enabled": True, "thresholds": [0.2, 0.8]},
        "param_ranges": {"old": {"start": 1.0, "end": 2.0, "step": 1.0}},
    }
    param_ranges: WorkspaceJSONMapping = {
        "fast": {"start": 3.0, "end": 7.0, "step": 2.0, "type": "float"}
    }

    merged = optimization._merge_optimization_config(
        current,
        param_ranges=param_ranges,
        n_workers=4,
        artifact_root="/tmp/workspace/optimization",
        submitted_at="2026-09-20T12:00:00+00:00",
    )

    assert merged["objective"] == "sharpe_max"
    assert merged["saved_options"] == {"enabled": True, "thresholds": [0.2, 0.8]}
    assert merged["param_ranges"] == param_ranges
    assert merged["n_workers"] == 4
    assert merged["artifact_root"] == "/tmp/workspace/optimization"
    assert merged["submitted_at"] == "2026-09-20T12:00:00+00:00"


def test_optimization_config_merge_discards_non_mapping_or_non_json_state():
    merged = optimization._merge_optimization_config(
        ["malformed"],
        param_ranges={"fast": {"start": 1.0, "end": 3.0, "step": 1.0}},
        n_workers=2,
        artifact_root="/tmp/workspace/optimization",
        submitted_at="2026-09-20T12:00:00+00:00",
    )

    assert "objective" not in merged
    assert merged["param_ranges"] == {"fast": {"start": 1.0, "end": 3.0, "step": 1.0}}


@pytest.mark.asyncio
async def test_workspace_report_ignores_malformed_json_and_non_numeric_metrics(monkeypatch):
    malformed_unit = SimpleNamespace(
        id="bad-shape",
        strategy_name="Malformed",
        strategy_id="malformed",
        symbol="BAD",
        timeframe="1d",
        symbol_name="",
        group_name="",
        category="",
        run_status="completed",
        run_count=1,
        last_run_time=None,
        last_task_id=None,
        data_config=["not", "a", "mapping"],
        metrics_snapshot=["not", "a", "mapping"],
    )
    invalid_metrics_unit = SimpleNamespace(
        id="bad-values",
        strategy_name="Invalid metrics",
        strategy_id="invalid-metrics",
        symbol="BAD2",
        timeframe="1d",
        symbol_name="",
        group_name="",
        category="",
        run_status="completed",
        run_count=1,
        last_run_time=None,
        last_task_id=None,
        data_config={"start_date": ["not", "a", "date"]},
        metrics_snapshot={
            "initial_cash": "not-a-number",
            "total_return": {"nested": "not-a-number"},
            "trading_days": [252],
            "max_drawdown": float("nan"),
            "total_trades": True,
        },
    )
    workspace = SimpleNamespace(
        name="Malformed metrics",
        strategy_units=[malformed_unit, invalid_metrics_unit],
    )

    async def load_workspace(
        _session: object, _workspace_id: str, _user_id: str, *, load_units: bool
    ) -> SimpleNamespace:
        assert load_units is True
        return workspace

    monkeypatch.setattr(reports, "async_session_maker", _AsyncSessionContext)

    result = await reports.get_workspace_report(
        workspace_id="workspace-1",
        user_id="user-1",
        load_workspace=load_workspace,
        weight_mode="custom",
    )

    assert result is not None
    assert result["summary"]["total_units"] == 2
    assert result["summary"]["completed_units"] == 1
    assert result["summary"]["total_trades"] is None
    assert result["summary"]["avg_total_return"] is None
    assert result["units"][0]["start_date"] is None
    assert result["units"][0]["initial_cash"] is None
    assert result["units"][0]["total_return"] is None
    assert result["units"][1]["start_date"] is None
    assert result["units"][1]["total_return"] is None


@pytest.mark.asyncio
async def test_workspace_report_aggregates_valid_metrics_with_custom_cash_weights(monkeypatch):
    first_unit = SimpleNamespace(
        id="unit-first",
        strategy_name="First strategy",
        strategy_id="first",
        symbol="AAA",
        timeframe="1d",
        symbol_name="AAA",
        group_name="group-a",
        category="stock",
        run_status="completed",
        run_count=1,
        last_run_time=12.5,
        last_task_id="task-first",
        data_config={"start_date": "2025-01-01", "end_date": "2025-06-30"},
        metrics_snapshot={
            "initial_cash": 100.0,
            "total_return": 0.1,
            "trading_days": 126,
            "total_trades": 2,
            "max_drawdown": -0.2,
        },
    )
    second_unit = SimpleNamespace(
        id="unit-second",
        strategy_name="Second strategy",
        strategy_id="second",
        symbol="BBB",
        timeframe="1d",
        symbol_name="BBB",
        group_name="group-b",
        category="stock",
        run_status="completed",
        run_count=2,
        last_run_time=24.0,
        last_task_id="task-second",
        data_config={"start_date": "2025-03-01", "end_date": "2025-12-31"},
        metrics_snapshot={
            "initial_cash": 300.0,
            "total_return": 0.3,
            "trading_days": 252,
            "total_trades": 5,
            "max_drawdown": -0.5,
        },
    )
    workspace = SimpleNamespace(
        name="Valid report metrics",
        strategy_units=[first_unit, second_unit],
    )

    async def load_workspace(
        _session: object, _workspace_id: str, _user_id: str, *, load_units: bool
    ) -> SimpleNamespace:
        assert load_units is True
        return workspace

    monkeypatch.setattr(reports, "async_session_maker", _AsyncSessionContext)

    result = await reports.get_workspace_report(
        workspace_id="workspace-valid",
        user_id="user-1",
        load_workspace=load_workspace,
        calc_method="simple",
        annual_days=252,
        weight_mode="custom",
    )

    assert result is not None
    summary = result["summary"]
    assert summary["completed_units"] == 2
    assert summary["avg_total_return"] == 0.25
    assert summary["avg_annual_return"] == 0.275
    assert summary["total_trades"] == 7
    assert result["units"][0]["start_date"] == "2025-01-01"
    assert result["units"][1]["start_date"] == "2025-03-01"
    assert result["units"][0]["annual_return"] == 0.2
    assert result["units"][1]["annual_return"] == 0.3
    assert summary["best_return_unit"]["id"] == "unit-second"
    assert summary["best_return_unit"]["value"] == 0.3
    assert summary["worst_drawdown_unit"]["id"] == "unit-second"
    assert summary["worst_drawdown_unit"]["value"] == -0.5
