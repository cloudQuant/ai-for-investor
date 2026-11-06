"""Tests for the AC11 runtime-evidence join.

Pure-function tests only: classification takes the census rows and an in-memory newest-
execution map, so no test touches the database. The refusal paths exit before any DB touch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from scripts.ops import ac11_runtime_evidence as mod

WINDOW = datetime(2026, 11, 5, 14, 3, tzinfo=timezone.utc)


def _stat(
    *,
    last: datetime | None = None,
    total: int = 1,
    completed: int = 1,
    grew: int = 1,
) -> dict[str, Any]:
    return {
        "total_executions": total,
        "completed_executions": completed,
        "grew_executions": grew,
        "last_created_at": last if last is not None else WINDOW,
    }


def _census(tasks: list[dict[str, Any]], *, armed: int | None = None) -> dict[str, Any]:
    scope: dict[str, Any] = {"armed_tasks": armed if armed is not None else len(tasks)}
    return {
        "generated_at_utc": "2026-11-06T14:17:19+00:00",
        "scope": scope,
        "tasks": tasks,
    }


class TestClassifyCensus:
    def test_completed_and_grew_is_counted(self) -> None:
        census_tasks = [{"task_id": 1, "family": "binds"}]
        rows = mod.classify_census(census_tasks, {1: _stat()}, window_start=WINDOW)
        assert rows == [{"task_id": 1, "family": "binds", "outcome": mod.OUTCOME_GREW}]

    def test_completed_zero_delta_is_a_different_bucket_than_grew(self) -> None:
        census_tasks = [
            {"task_id": 1, "family": "binds"},
            {"task_id": 2, "family": "binds"},
        ]
        stats = {1: _stat(grew=1), 2: _stat(grew=0)}
        rows = mod.classify_census(census_tasks, stats, window_start=WINDOW)
        outcomes = {row["task_id"]: row["outcome"] for row in rows}
        assert outcomes[1] == mod.OUTCOME_GREW
        assert outcomes[2] == mod.OUTCOME_NO_DELTA
        assert outcomes[1] != outcomes[2]

    def test_failed_only(self) -> None:
        census_tasks = [{"task_id": 7, "family": "unexpected_param"}]
        stats = {7: _stat(total=3, completed=0, grew=0)}
        rows = mod.classify_census(census_tasks, stats, window_start=WINDOW)
        assert rows[0]["outcome"] == mod.OUTCOME_FAILED_ONLY

    def test_task_absent_from_executions_lands_in_not_run_and_does_not_vanish(self) -> None:
        census_tasks = [{"task_id": 9, "family": "accepts_var_kwargs"}]
        rows = mod.classify_census(census_tasks, {}, window_start=WINDOW)
        assert len(rows) == 1
        assert rows[0]["outcome"] == mod.OUTCOME_NOT_RUN

    def test_execution_predating_the_window_is_not_run(self) -> None:
        census_tasks = [{"task_id": 3, "family": "binds"}]
        before = datetime(2026, 11, 5, 14, 2, 59, tzinfo=timezone.utc)
        rows = mod.classify_census(census_tasks, {3: _stat(last=before)}, window_start=WINDOW)
        assert rows[0]["outcome"] == mod.OUTCOME_NOT_RUN

    def test_naive_utc_last_created_at_is_comparable(self) -> None:
        census_tasks = [{"task_id": 4, "family": "binds"}]
        naive_after = datetime(2026, 11, 6, 1, 0)  # naive DB value, UTC semantics
        rows = mod.classify_census(census_tasks, {4: _stat(last=naive_after)}, window_start=WINDOW)
        assert rows[0]["outcome"] == mod.OUTCOME_GREW

    def test_every_census_row_is_classified_exactly_once(self) -> None:
        census_tasks = [
            {"task_id": tid, "family": "binds" if tid % 2 else "accepts_var_kwargs"}
            for tid in range(1, 21)
        ]
        stats = {tid: _stat() for tid in range(1, 21, 3)}
        rows = mod.classify_census(census_tasks, stats, window_start=WINDOW)
        assert len(rows) == len(census_tasks)
        assert {row["task_id"] for row in rows} == {t["task_id"] for t in census_tasks}


class TestBuildReport:
    def test_numerator_denominator_equals_population_read(self) -> None:
        census_tasks = [
            {"task_id": 1, "family": "binds"},
            {"task_id": 2, "family": "binds"},
            {"task_id": 3, "family": "accepts_var_kwargs"},
            {"task_id": 4, "family": "unexpected_param"},
        ]
        census = _census(census_tasks, armed=4)
        stats = {
            1: _stat(grew=2),
            2: _stat(grew=0),
            4: _stat(total=2, completed=0, grew=0),
        }
        rows = mod.classify_census(census_tasks, stats, window_start=WINDOW)
        report = mod.build_report(
            census,
            rows,
            window_start=WINDOW,
            database_label="select_only/test",
            read_only_mode="select_only",
        )
        numerator = report["numerator"]
        assert numerator["AC11_RUNTIME_EVIDENCED"] == 1
        assert numerator["population"] == 4
        assert numerator["ratio"] == "1/4"
        cells = sum(sum(row.values()) for row in report["family_x_outcome"].values())
        assert cells == numerator["population"]
        assert sum(report["outcome_totals"].values()) == numerator["population"]

    def test_matrix_keeps_all_four_outcome_columns(self) -> None:
        census_tasks = [{"task_id": 1, "family": "binds"}]
        rows = mod.classify_census(census_tasks, {}, window_start=WINDOW)
        matrix = mod.build_matrix(rows)
        assert set(matrix["binds"]) == set(mod.OUTCOMES)

    def test_assigned_line_is_declared_not_computed(self) -> None:
        census = _census([{"task_id": 1, "family": "binds"}])
        rows = mod.classify_census(census["tasks"], {}, window_start=WINDOW)
        report = mod.build_report(
            census,
            rows,
            window_start=WINDOW,
            database_label="select_only/test",
            read_only_mode="select_only",
        )
        assert report["assigned"]["value"] == "not computed here"
        assert "disposition ledger" in report["assigned"]["source"]

    def test_population_label_distinguishes_pre_and_post_retirement(self) -> None:
        census = _census([{"task_id": 1, "family": "binds"}])
        pre = dict(census, generated_at_utc="2026-11-06T13:25:57+00:00")
        label = mod.population_label(pre)["population_relative_to_retirement"]
        assert label.startswith("pre-retirement")
        post = dict(census, generated_at_utc="2026-11-06T14:17:19+00:00")
        label = mod.population_label(post)["population_relative_to_retirement"]
        assert label.startswith("post-retirement")


class TestRefusal:
    def test_missing_census_file_refuses(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as excinfo:
            mod.load_census(tmp_path / "absent.json")
        assert excinfo.value.code != 0

    def test_census_without_tasks_array_refuses(self, tmp_path: Path) -> None:
        path = tmp_path / "census.json"
        path.write_text('{"family_counts": {}}', encoding="utf-8")
        with pytest.raises(SystemExit) as excinfo:
            mod.load_census(path)
        assert "tasks" in str(excinfo.value)
        assert excinfo.value.code != 0

    def test_main_refuses_before_touching_database(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as excinfo:
            mod.main(["--census", str(tmp_path / "absent.json")])
        assert excinfo.value.code != 0


class TestHumanSummary:
    def test_summary_contains_numerator_assigned_and_as_of(self) -> None:
        census_tasks = [{"task_id": 1, "family": "binds"}, {"task_id": 2, "family": "binds"}]
        census = _census(census_tasks)
        rows = mod.classify_census(
            census_tasks, {1: _stat(), 2: _stat(total=1, completed=0, grew=0)}, window_start=WINDOW
        )
        report = mod.build_report(
            census,
            rows,
            window_start=WINDOW,
            database_label="select_only/test",
            read_only_mode="select_only",
        )
        summary = mod.human_summary(report)
        assert report["as_of_utc"] in summary
        assert "AC11_RUNTIME_EVIDENCED / population = 1 / 2" in summary
        assert "not computed here" in summary
        assert "disposition ledger" in summary
