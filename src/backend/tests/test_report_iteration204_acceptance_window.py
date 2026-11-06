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
    created: datetime,
    status: str = "completed",
    rows_delta: int | None = 5,
    error: str = "",
    triggered: str = "scheduler",
) -> dict[str, Any]:
    return {
        "created_at": created,
        "status": status,
        "triggered_by": triggered,
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


def test_cron_slots_are_enumerated_in_the_scheduler_zone_not_utc() -> None:
    # Grounded in the live ledger: task 11 `bond_china_yield`, cron `20 19 * * *`, whose
    # completed rows are stamped 2026-10-22 11:20 UTC (= 19:20 Asia/Shanghai), because
    # APScheduler gets settings.AKSHARE_SCHEDULER_TIMEZONE while created_at is UTC.
    # Enumerating the cron in UTC would place the expected slot at 19:20Z, 8 hours from
    # every real run, so daily/weekly/monthly streaks would read 0 forever.
    start = datetime(2026, 10, 22, tzinfo=UTC)
    end = datetime(2026, 10, 25, tzinfo=UTC)
    shanghai = mod.expected_slots("20 19 * * *", start, end)
    assert shanghai.cadence == "daily"
    assert [slot.isoformat() for slot in shanghai.expected_slots] == [
        "2026-10-22T11:20:00+00:00",
        "2026-10-23T11:20:00+00:00",
        "2026-10-24T11:20:00+00:00",
    ]
    runs = [datetime(2026, 10, day, 11, 20, tzinfo=UTC) for day in (22, 23, 24)]
    assert mod.consecutive_completed_slots(shanghai.expected_slots, runs) == 3

    # Counterfactual: reading the same cron as UTC misses every run that actually fired.
    as_utc = mod.expected_slots("20 19 * * *", start, end, cron_tz="UTC")
    assert [slot.hour for slot in as_utc.expected_slots] == [19, 19, 19]
    assert mod.consecutive_completed_slots(as_utc.expected_slots, runs) == 0


def test_weekday_range_that_crosses_into_the_weekend_is_still_scoreable() -> None:
    # 17 armed tasks use `tue-sat` shapes (task 95 `42 3 * * tue-sat`, 1084-1099 `30 6 * * tue-sat`).
    # Requiring the dow set to be a subset of Mon-Fri labelled them unclassifiable, which
    # dropped those tasks from AC14 as "slot check unavailable" instead of scoring them.
    assert mod.classify_cadence("42 3 * * tue-sat") == "weekday_daily"
    assert mod.classify_cadence("41 6,9 * * tue-sat") == "weekday_sub_daily"
    start = datetime(2026, 11, 3, tzinfo=UTC)  # a Tuesday
    end = datetime(2026, 11, 9, 23, 59, tzinfo=UTC)
    check = mod.expected_slots("42 3 * * tue-sat", start, end)
    assert check.unsupported_reason is None
    assert len(check.expected_slots) == 5  # Tue..Sat, one wall-clock 03:42 each
    payload = mod.summarize([_task(95, "42 3 * * tue-sat")], {}, start, end)[0].to_dict()
    assert payload["cadence"] == "weekday_daily"
    assert payload["target"] == 7


def test_manual_runs_cannot_satisfy_a_cron_slot() -> None:
    # AC14 is a natural-cycle criterion, and this project's rule is that a manual run must
    # not consume a cron occurrence (the B29 failure). Measured on the live ledger: 26,437
    # manual vs 5,422 scheduler execution rows, so without this split a hand-triggered run
    # landing inside a slot would silently extend a streak that never happened on its own.
    start = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=4)
    stamps = [start + timedelta(hours=i, minutes=3) for i in range(4)]
    manual = mod.summarize(
        [_task(1049, "3 * * * *")],
        {1049: [_row(s, triggered="manual") for s in stamps]},
        start,
        end,
    )[0].to_dict()
    assert manual["completed"] == 4
    assert manual["manual_completed"] == 4
    assert manual["natural_completed"] == 0
    assert manual["consecutive_completed_slots"] == 0
    assert manual["target_met"] is False

    # Counterfactual: the same four timestamps, scheduler-triggered, do satisfy every slot.
    natural = mod.summarize(
        [_task(1049, "3 * * * *")],
        {1049: [_row(s) for s in stamps]},
        start,
        end,
    )[0].to_dict()
    assert natural["natural_completed"] == 4
    assert natural["consecutive_completed_slots"] == 4

    # An unlabelled row is not evidence of a natural cycle either: the count fails closed.
    unknown = mod.summarize(
        [_task(1049, "3 * * * *")],
        {1049: [{**_row(s), "triggered_by": None} for s in stamps]},
        start,
        end,
    )[0].to_dict()
    assert unknown["consecutive_completed_slots"] == 0


def test_all_zero_row_completions_satisfy_status_only_but_not_the_target() -> None:
    start = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=48)
    executions = {
        1049: [_row(start + timedelta(hours=i, minutes=3), rows_delta=0) for i in range(48)]
    }
    payload = mod.summarize([_task(1049, "3 * * * *")], executions, start, end)[0].to_dict()
    assert payload["consecutive_completed_slots"] == 48
    assert payload["consecutive_slots_with_rows"] == 0
    assert payload["target_met_status_only"] is True
    assert payload["target_met"] is False
    assert payload["idempotent_zero_row_runs"] == 48
    assert any("zero_row_or_unknown_completions" in n for n in payload["notes"])


def test_a_null_delta_completion_is_unknown_and_breaks_the_data_bearing_streak() -> None:
    start = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=4)
    executions = {
        7: [
            _row(start + timedelta(minutes=3), rows_delta=None),
            _row(start + timedelta(hours=1, minutes=3), rows_delta=4),
            _row(start + timedelta(hours=2, minutes=3), rows_delta=None),
        ]
    }
    payload = mod.summarize([_task(7, "3 * * * *")], executions, start, end)[0].to_dict()
    assert payload["unknown_delta_completed_slots"] == 2
    assert payload["consecutive_completed_slots"] == 3
    assert payload["consecutive_slots_with_rows"] == 1
    # NULL must not be read as a zero-row run: it is a separate, counted unknown.
    assert payload["idempotent_zero_row_runs"] == 0


def test_daily_target_needs_seven_data_bearing_occurrences() -> None:
    # `0 2 * * *` is enumerated in the scheduler zone (Asia/Shanghai), so a ledger row
    # at 18:00 UTC is the 02:00 CST slot. Aligning the fixture with UTC instead would
    # assert against the wrong thing.
    start = datetime(2026, 10, 29, 18, 0, tzinfo=UTC)
    end = start + timedelta(days=7, hours=1)
    rows = [_row(start + timedelta(days=i), rows_delta=9 if i else 0) for i in range(7)]
    payload = mod.summarize([_task(650, "0 2 * * *")], {650: rows}, start, end)[0].to_dict()
    assert payload["consecutive_completed_slots"] == 7
    assert payload["target_met_status_only"] is True
    assert payload["consecutive_slots_with_rows"] == 6
    assert payload["target_met"] is False
