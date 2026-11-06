"""The clock repair must classify rows, not blanket-shift them."""

from datetime import datetime, timedelta

from scripts.ops.normalize_scheduler_clock import _in_clause, classify_last

NEWEST = datetime(2026, 11, 6, 5, 0)


def _task(task_id: int, last: datetime | None) -> dict:
    return {
        "id": task_id,
        "name": f"t{task_id}",
        "is_active": 1,
        "last_execution_at": last,
        "next_execution_at": None,
    }


def test_local_clock_shape_is_separated_from_the_utc_shape():
    rows = [
        _task(1, NEWEST + timedelta(hours=8)),  # written by run_task_now's datetime.now()
        _task(2, NEWEST + timedelta(minutes=3)),  # written by the execution service
        _task(3, NEWEST - timedelta(days=1)),  # column not maintained
        _task(4, NEWEST + timedelta(hours=8)),  # has a value but no execution row at all
    ]
    buckets = classify_last(rows, {1: NEWEST, 2: NEWEST, 3: NEWEST})

    assert buckets["shift"] == [1]
    assert buckets["already-utc"] == [2]
    assert buckets["stale-column"] == [3]
    assert buckets["no-execution"] == [4]


def test_only_the_measured_eight_hour_signature_is_shifted():
    shifted = classify_last([_task(9, NEWEST + timedelta(hours=11))], {9: NEWEST})
    unshifted = classify_last([_task(9, NEWEST + timedelta(hours=4))], {9: NEWEST})

    assert shifted["shift"] == [] and shifted["unclassified"] == [9]
    assert unshifted["shift"] == [] and unshifted["unclassified"] == [9]


def test_in_clause_placeholder_count_matches_the_values():
    assert _in_clause([1, 2, 3]).count("%s") == 3
    assert _in_clause([]) == "()"
