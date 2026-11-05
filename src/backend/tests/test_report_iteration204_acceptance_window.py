"""Tests for the iteration-204 natural-cycle reporter.

No database, no clock dependency: every case feeds explicit rows so the counting
rules are provable. Several cases exist only to prove a rule cannot be quietly
loosened, which is what makes the reporter safe to quote in the ledger.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ops"
    / "report_iteration204_acceptance_window.py"
)


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("afi204_acceptance_window", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load()


def _task(task_id: int, expression: str) -> mod.TaskRow:
    return mod.TaskRow(
        task_id=task_id,
        script_id=f"script_{task_id}",
        schedule_type="cron",
        schedule_expression=expression,
        next_execution_at=None,
        is_active=True,
    )


def _row(
    created: datetime, status: str = "completed", rows_delta: int | None = 5, error: str = ""
) -> dict[str, Any]:
    return {
        "created_at": created,
        "status": status,
        "rows_delta": rows_delta,
        "error_message": error,
    }


def test_hourly_expression_is_hourly() -> None:
    assert mod.classify_cadence("3 * * * *") == "hourly"


def test_daily_weekly_monthly_shapes() -> None:
    assert mod.classify_cadence("10 8 * * *") == "daily"
    assert mod.classify_cadence("5 19 * * 1-5") == "weekday_daily"
    assert mod.classify_cadence("5 19 * * mon-fri") == "weekday_daily"
    assert mod.classify_cadence("5 19 * * 3") == "weekly"
    assert mod.classify_cadence("0 4 1 * *") == "monthly"


def test_multiple_fixed_hours_are_sub_daily_and_have_no_target() -> None:
    # `57 3,9,15,21 * * *` is four runs a day. Scoring it as daily (1 slot) or as
    # hourly (24 slots) would both be a false claim, so it gets no target at all.
    assert mod.classify_cadence("57 3,9,15,21 * * *") == "sub_daily"
    assert "sub_daily" not in mod.CYCLE_TARGETS


def test_weekday_daily_scores_against_the_daily_target() -> None:
    assert mod.CYCLE_TARGETS["weekday_daily"] == mod.CYCLE_TARGETS["daily"] == 7


def test_multi_value_hour_field_gets_no_target_rather_than_a_guess() -> None:
    # A real armed shape: `57 3,9,15,21 * * mon-fri` = four runs on five days. It is
    # enumerable, so slots are computed, but it matches none of AC14's four targets:
    # scoring it as daily (1 slot) or hourly (24) would both be a false claim.
    expression = "57 3,9,15,21 * * mon-fri"
    start = datetime(2026, 11, 5, tzinfo=UTC)
    end = datetime(2026, 11, 6, tzinfo=UTC)
    check = mod.expected_slots(expression, start, end)
    assert check.cadence == "weekday_sub_daily"
    assert check.unsupported_reason is None
    payload = mod.summarize([_task(1, expression)], {}, start, end)[0].to_dict()
    assert payload["target"] is None
    assert payload["target_met"] is False


def test_named_weekday_is_enumerable_for_slot_checks() -> None:
    start = datetime(2026, 11, 2, tzinfo=UTC)  # a Monday
    end = datetime(2026, 11, 8, 23, 59, tzinfo=UTC)
    check = mod.expected_slots("43 6 * * fri", start, end)
    assert check.cadence == "weekly"
    assert check.unsupported_reason is None
    assert len(check.expected_slots) == 1


def test_hourly_window_enumerates_one_slot_per_hour() -> None:
    start = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    end = datetime(2026, 11, 5, 23, 59, tzinfo=UTC)
    check = mod.expected_slots("3 * * * *", start, end)
    assert check.cadence == "hourly"
    assert len(check.expected_slots) == 24
    assert check.expected_slots[0] == start.replace(minute=3)
    assert [slot.hour for slot in check.expected_slots] == list(range(24))


def test_streak_counts_slots_not_rows_and_breaks_on_a_gap() -> None:
    start = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    slots = [start + timedelta(hours=i, minutes=3) for i in range(6)]
    completed = [slots[0], slots[1], slots[3], slots[4], slots[5]]
    # slots[2] is missing, so the run restarts: 2, then 3.
    assert mod.consecutive_completed_slots(slots, completed) == 3


def test_run_that_does_not_line_up_with_a_slot_does_not_extend_the_streak() -> None:
    # Counterfactual: widening this tolerance silently turns off-schedule manual
    # runs into "natural cycle" evidence, which AC14 forbids.
    slot = datetime(2026, 11, 5, 3, 3, tzinfo=UTC)
    assert mod.consecutive_completed_slots([slot], [slot + timedelta(minutes=20)]) == 0
    assert mod.consecutive_completed_slots([slot], [slot + timedelta(minutes=5)]) == 1


def test_naive_ledger_times_are_read_as_utc() -> None:
    naive = datetime(2026, 11, 5, 3, 3)
    aware = datetime(2026, 11, 5, 3, 3, tzinfo=UTC)
    assert mod._as_utc(naive) == aware


def test_zero_row_completed_run_is_idempotent_not_a_write() -> None:
    start = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    executions = {1: [_row(start.replace(minute=3), rows_delta=0)]}
    reports = mod.summarize([_task(1, "3 * * * *")], executions, start, end)
    assert reports[0].wrote_rows == 0
    assert reports[0].idempotent_zero_row_runs == 1
    assert reports[0].completed == 1


def test_failed_run_keeps_truncated_reason_and_never_echoes_params() -> None:
    start = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    executions = {
        1: [_row(start.replace(minute=3), status="failed", rows_delta=None, error="x" * 400)]
    }
    reports = mod.summarize([_task(1, "3 * * * *")], executions, start, end)
    assert len(reports[0].last_failure_reason or "") == mod._MAX_ERROR_CHARS
    payload = reports[0].to_dict()
    assert "params" not in payload and "result" not in payload


def test_target_is_only_met_when_slots_were_computed() -> None:
    start = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=48)
    task = _task(1049, "3 * * * *")
    executions = {1049: [_row(start + timedelta(hours=i, minutes=3)) for i in range(48)]}
    reports = mod.summarize([task], executions, start, end)
    payload = reports[0].to_dict()
    assert payload["consecutive_completed_slots"] == 48
    assert payload["target_met"] is True

    unavailable = mod.summarize(
        [_task(2, "57 3,9,15,21 * * mon-fri")], {2: [_row(start)]}, start, end
    )
    assert unavailable[0].to_dict()["target_met"] is False


def test_summary_declares_what_it_cannot_prove() -> None:
    start = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    reports = mod.summarize([_task(1, "3 * * * *")], {}, start, end)
    summary = mod.aggregate(reports)
    markdown = mod.render_markdown(summary, reports, start, end)
    assert "UTC" in markdown
    for claim in ("AC10", "AC13", "AC05"):
        assert any(claim in line for line in summary["not_proven_by_this_tool"])


def test_no_expected_slot_in_window_is_recorded_not_silently_zero() -> None:
    start = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    reports = mod.summarize([_task(1, "45 9 * * *")], {}, start, end)
    assert reports[0].slot_check == "computed"
    assert "no_expected_slot_in_window" in reports[0].notes
