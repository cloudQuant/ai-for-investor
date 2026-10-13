"""Write a flushed JSONL receipt for a pytest run.

Load with ``PYTHONPATH=<plugin-dir> pytest -p iter202_live_receipt`` and set
``ITER202_PYTEST_RECEIPT`` to an explicit output file path.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import pytest

_RUN_ID = uuid.uuid4().hex
_RECEIPT: TextIO | None = None
_COLLECTED_NODEIDS: list[str] = []
_REPORTS: dict[str, list[Any]] = {}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return repr(value)


def _write_event(event: str, **fields: Any) -> None:
    if _RECEIPT is None:
        raise RuntimeError("pytest receipt plugin was not configured")
    payload = {
        "event": event,
        "run_id": _RUN_ID,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    _RECEIPT.write(json.dumps(payload, ensure_ascii=False, default=repr) + "\n")
    _RECEIPT.flush()


def pytest_configure(config: pytest.Config) -> None:
    del config
    output_path = os.environ.get("ITER202_PYTEST_RECEIPT")
    if not output_path:
        raise pytest.UsageError(
            "ITER202_PYTEST_RECEIPT must name an explicit JSONL output path"
        )
    try:
        global _RECEIPT
        _RECEIPT = Path(output_path).expanduser().open("w", encoding="utf-8")
    except OSError as exc:
        raise pytest.UsageError(f"Cannot open ITER202_PYTEST_RECEIPT: {exc}") from exc
    _write_event("session_start", pytest_version=pytest.__version__)


def pytest_collection_finish(session: pytest.Session) -> None:
    items = list(session.items)
    _COLLECTED_NODEIDS[:] = [item.nodeid for item in items]
    tests = []
    for item in items:
        markers = [
            {
                "name": marker.name,
                "args": _json_value(marker.args),
                "kwargs": _json_value(marker.kwargs),
            }
            for marker in item.iter_markers()
        ]
        tests.append({"nodeid": item.nodeid, "markers": markers})
    _write_event("collection_finish", collected=len(items), tests=tests)


def pytest_runtest_logstart(nodeid: str, location: tuple[str, int | None, str]) -> None:
    _write_event("test_start", nodeid=nodeid, location=_json_value(location))


def pytest_runtest_logreport(report: Any) -> None:
    _REPORTS.setdefault(report.nodeid, []).append(report)
    fields: dict[str, Any] = {
        "nodeid": report.nodeid,
        "phase": report.when,
        "outcome": report.outcome,
        "duration_seconds": float(report.duration),
    }
    if report.failed or report.skipped:
        fields["longrepr"] = str(report.longrepr)
    if hasattr(report, "wasxfail"):
        fields["wasxfail"] = str(report.wasxfail)
    _write_event("test_phase", **fields)


def _test_outcome(reports: list[Any]) -> str:
    if any(report.failed for report in reports):
        return "failed"
    if any(report.skipped and hasattr(report, "wasxfail") for report in reports):
        return "xfailed"
    if any(report.skipped for report in reports):
        return "skipped"
    if any(report.passed and hasattr(report, "wasxfail") for report in reports):
        return "xpassed"
    if any(report.when == "call" and report.passed for report in reports):
        return "passed"
    return "not_run"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    outcomes = [
        _test_outcome(_REPORTS.get(nodeid, [])) for nodeid in _COLLECTED_NODEIDS
    ]
    counts = {
        "collected": len(_COLLECTED_NODEIDS),
        "passed": outcomes.count("passed"),
        "failed": outcomes.count("failed"),
        "skipped": outcomes.count("skipped"),
        "xfailed": outcomes.count("xfailed"),
        "xpassed": outcomes.count("xpassed"),
        "not_run": outcomes.count("not_run"),
        "pytest_testscollected": int(session.testscollected),
        "pytest_testsfailed": int(session.testsfailed),
    }
    _write_event("session_finish", exitstatus=int(exitstatus), counts=counts)
    if _RECEIPT is not None:
        _RECEIPT.close()


def pytest_unconfigure(config: pytest.Config) -> None:
    del config
    if _RECEIPT is not None and not _RECEIPT.closed:
        _RECEIPT.close()
