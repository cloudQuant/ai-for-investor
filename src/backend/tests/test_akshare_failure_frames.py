"""The failure ledger records where a run died, never what it was carrying."""

from __future__ import annotations

import pytest

from app.services.akshare.execution import failure_frame_trace


def _raise_from_a_private_dsn() -> None:
    def inner() -> None:
        raise ValueError("dsn=mysql://user:secret@db.internal/app")

    inner()


def test_frame_trace_names_each_frame_without_the_message() -> None:
    with pytest.raises(ValueError) as caught:
        _raise_from_a_private_dsn()

    trace = failure_frame_trace(caught.value)

    assert "in inner" in trace
    assert "in _raise_from_a_private_dsn" in trace
    assert "in test_frame_trace_names_each_frame_without_the_message" in trace
    assert "user:secret@" not in trace
    assert "mysql://" not in trace
    assert "ValueError" not in trace


def test_frame_trace_truncates_and_says_so() -> None:
    def recurse(depth: int) -> None:
        if depth == 0:
            raise RecursionError("bottom")
        recurse(depth - 1)

    with pytest.raises(RecursionError) as caught:
        recurse(5)

    trace = failure_frame_trace(caught.value, limit=3)
    lines = trace.splitlines()

    assert len(lines) == 4
    assert lines[-1] == "... truncated after 3 frames"
    assert all(" in " in line for line in lines[:3])


def test_frame_trace_without_a_traceback_is_empty() -> None:
    assert failure_frame_trace(ValueError("never raised")) == ""
