"""Tests for the CI-sourced baseline freezer.

The tool's whole value is that the number it writes was printed by CI, so the parser and the
refusals are the part that must not drift. These tests feed synthetic job logs, including the
exact shape CI prints today, and pin the three ways it must refuse to produce a baseline.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "freeze_collection_baseline_from_ci.py"


def _load():
    spec = importlib.util.spec_from_file_location("freeze_from_ci", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CI_LINE = (
    "2026-11-06T16:41:59.0000000Z mypy_ratchet[collection]: advisory, no baseline yet - "
    "errors=101 checked=1108 (mypy 1.20.2 (compiled: yes))"
)


def test_parses_the_line_ci_actually_prints() -> None:
    readings = _load().parse_readings(CI_LINE)

    assert len(readings) == 1
    assert readings[0]["errors"] == 101
    assert readings[0]["scope_files"] == 1108
    assert readings[0]["mypy_version"] == "mypy 1.20.2 (compiled: yes"
    assert readings[0]["advisory"] is True


def test_the_timestamp_prefix_is_stripped_before_matching() -> None:
    module = _load()

    with_prefix = module.parse_readings(CI_LINE)[0]
    without = module.parse_readings(CI_LINE.split(" ", 1)[1])[0]

    # the raw line text differs by the stripped prefix; the parsed facts must not
    assert (
        with_prefix["errors"],
        with_prefix["scope_files"],
        with_prefix["mypy_version"],
    ) == (without["errors"], without["scope_files"], without["mypy_version"])


def test_a_second_identical_reading_is_accepted_as_one_value() -> None:
    module = _load()
    module.gh_raw = lambda url: f"{CI_LINE}\n{CI_LINE}"

    reading = module.read_plane_reading("owner/repo", {"id": 1})

    assert reading["errors"] == 101


def test_two_conflicting_readings_are_refused_rather_than_picked() -> None:
    module = _load()
    other = CI_LINE.replace("errors=101", "errors=7")
    module.gh_raw = lambda url: f"{CI_LINE}\n{other}"

    with pytest.raises(SystemExit) as excinfo:
        module.read_plane_reading("owner/repo", {"id": 1})

    assert "different readings" in str(excinfo.value)


def test_a_log_without_a_reading_is_refused() -> None:
    module = _load()
    module.gh_raw = lambda url: "some unrelated log output\nno plane line here"

    with pytest.raises(SystemExit) as excinfo:
        module.read_plane_reading("owner/repo", {"id": 1})

    assert "no parseable plane reading" in str(excinfo.value)


def test_the_written_baseline_carries_the_ci_provenance_and_no_local_number() -> None:
    module = _load()
    run = {"id": 42, "html_url": "https://example.invalid/runs/42"}
    job = {
        "id": 99,
        "html_url": "https://example.invalid/jobs/99",
        "name": "Backend - Mypy Ratchet (collection scripts, advisory)",
    }
    reading = module.parse_readings(CI_LINE)[-1]

    payload = module.build_payload(
        "owner/repo", "a" * 40, run, job, reading, "collection"
    )

    assert payload["baseline_errors"] == 101
    assert payload["scope_files"] == 1108
    assert payload["provenance"]["run_id"] == 42
    assert payload["provenance"]["job_id"] == 99
    assert payload["provenance"]["head_sha"] == "a" * 40
    assert reading["line"] in payload["provenance"]["reading_line"]
    assert "not a local run" in payload["_comment"]
