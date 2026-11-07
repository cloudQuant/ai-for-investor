#!/usr/bin/env python3
"""Run or plan one explicitly bounded CFFEX option-history date range.

This CLI is separate from the full-month controller. It has no automatic range
selection: default invocation is a read-only plan, while ``--apply`` requires
both date bounds and performs one supervised, managed archive request. A
verified range is only a range snapshot; it never verifies a full month,
calendar, contract lifecycle, source inception, or amount units.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.data_fetch.providers.cffex_option_history_source import (  # noqa: E402
    SOURCE,
    SOURCE_URL_TEMPLATE,
    normalize_date,
    parse_monthly_archive,
)

from scripts import cffex_option_history_controller as full_month  # noqa: E402
from scripts import cffex_option_native_range_verifier as native_verifier  # noqa: E402

SCRIPT_ID = full_month.SCRIPT_ID
SCRIPT_SOURCE = full_month.SCRIPT_SOURCE
SCRIPT_MODULE = full_month.SCRIPT_MODULE
SCRIPT_FUNCTION = full_month.SCRIPT_FUNCTION
TABLE_NAME = full_month.TABLE_NAME
TABLE_FIELDS = full_month.TABLE_FIELDS
COMPARE_FIELDS = full_month.COMPARE_FIELDS
LEGACY_TABLES = (
    "OPTION_CURRENT_EM",
    "OPTION_CFFEX_HS300_DAILY_SINA",
    "OPTION_CFFEX_SZ50_DAILY_SINA",
    "OPTION_CFFEX_ZZ1000_DAILY_SINA",
)
LEDGER_SCOPE = "cffex-option-date-range-v1"
LEDGER_SCHEMA_VERSION = 1
DISPATCH_SCHEMA_VERSION = 1
GENESIS_SHA256 = "0" * 64
SOFT_SECONDS = 180
TERM_SECONDS = 190
KILL_SECONDS = 200
SOURCE_TIMEOUT_SECONDS = 90
MANAGED_TIMEOUT_SECONDS = 150
DEFAULT_LEDGER = full_month.DEFAULT_REPORT_DIR / "range-progress.jsonl"
DEFAULT_ARTIFACTS = full_month.DEFAULT_ARTIFACT_DIR / "range-runs"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=full_month._json_default,
        allow_nan=False,
    ).encode("utf-8")


def _event_hash(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        _canonical({key: value for key, value in record.items() if key != "event_sha256"})
    ).hexdigest()


def normalize_range(start_text: str, end_text: str) -> tuple[str, date, date]:
    """Validate one inclusive exact YYYYMMDD range within a single archive month."""
    if not re.fullmatch(r"\d{8}", str(start_text)) or not re.fullmatch(r"\d{8}", str(end_text)):
        raise ValueError("date bounds must use exact YYYYMMDD text")
    start = normalize_date(start_text)
    end = normalize_date(end_text)
    if start.strftime("%Y%m%d") != str(start_text) or end.strftime("%Y%m%d") != str(end_text):
        raise ValueError("date bounds must use exact YYYYMMDD text")
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    if start.strftime("%Y%m") != end.strftime("%Y%m"):
        raise ValueError("a date-range request must stay within one CFFEX archive month")
    return start.strftime("%Y%m"), start, end


def _range_id(start: date, end: date) -> str:
    return f"cffex-date-range-v1:{start:%Y%m%d}-{end:%Y%m%d}"


def read_range_ledger(path: Path) -> list[dict[str, Any]]:
    """Read and verify the independent append-only range ledger."""
    if not path.exists():
        return []
    if path.is_symlink():
        raise ValueError("range ledger must not be a symlink")
    previous = GENESIS_SHA256
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed range ledger JSONL line {line_number}") from exc
        if not isinstance(event, dict) or event.get("schema_version") != LEDGER_SCHEMA_VERSION:
            raise ValueError(f"unsupported range ledger event at line {line_number}")
        if event.get("ledger_scope") != LEDGER_SCOPE:
            raise ValueError(f"wrong range ledger scope at line {line_number}")
        try:
            month, start, end = normalize_range(
                str(event.get("start_date", "")), str(event.get("end_date", ""))
            )
        except ValueError as exc:
            raise ValueError(f"invalid range ledger dates at line {line_number}") from exc
        if event.get("month") != month or event.get("range_id") != _range_id(start, end):
            raise ValueError(f"range ledger identity mismatch at line {line_number}")
        if event.get("sequence") != len(events) + 1:
            raise ValueError(f"range ledger sequence mismatch at line {line_number}")
        if event.get("previous_event_sha256") != previous:
            raise ValueError(f"range ledger chain breaks at line {line_number}")
        expected_hash = _event_hash(event)
        if event.get("event_sha256") != expected_hash:
            raise ValueError(f"range ledger event hash mismatch at line {line_number}")
        recorded_at = full_month.parse_aware_timestamp(event.get("recorded_at_utc"))
        if recorded_at is None:
            raise ValueError(f"range ledger timestamp is invalid at line {line_number}")
        previous = expected_hash
        events.append(event)
    return events


def append_range_event(path: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    """Fsync one range event under an exclusive lock; never rewrites history."""
    month, start, end = normalize_range(
        str(record.get("start_date", "")), str(record.get("end_date", ""))
    )
    if path.is_symlink():
        raise ValueError("range ledger must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.seek(0)
            existing = stream.read()
            previous_events = read_range_ledger(path) if existing else []
            event = dict(record)
            event.update(
                {
                    "schema_version": LEDGER_SCHEMA_VERSION,
                    "ledger_scope": LEDGER_SCOPE,
                    "sequence": len(previous_events) + 1,
                    "month": month,
                    "start_date": f"{start:%Y%m%d}",
                    "end_date": f"{end:%Y%m%d}",
                    "range_id": _range_id(start, end),
                    "previous_event_sha256": (
                        previous_events[-1]["event_sha256"] if previous_events else GENESIS_SHA256
                    ),
                    "recorded_at_utc": datetime.now(timezone.utc).isoformat(
                        timespec="microseconds"
                    ),
                }
            )
            event["event_sha256"] = _event_hash(event)
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(event, ensure_ascii=False, default=str, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            return event
    except Exception:
        # fdopen owns the descriptor after it succeeds; os.close is harmlessly guarded.
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _private_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _digest_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    lines = sorted(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        for row in rows
    )
    return {
        "row_count": len(lines),
        "all_fields_sha256": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
    }


def _row_date(row: Mapping[str, Any]) -> date | None:
    value = row.get("TRADE_DATE")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    try:
        return normalize_date(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _target_snapshot_summary(
    target_rows: list[dict[str, Any]], month: str, start: date, end: date
) -> dict[str, Any]:
    exact_rows = []
    outside_rows = []
    for row in target_rows:
        trade_date = _row_date(row)
        exact = (
            row.get("SOURCE") == SOURCE
            and row.get("SOURCE_ARCHIVE_MONTH") == month
            and trade_date is not None
            and start <= trade_date <= end
        )
        (exact_rows if exact else outside_rows).append(row)
    return {
        "all_target_rows": _digest_rows(target_rows),
        "exact_range_rows": _digest_rows(exact_rows),
        "outside_exact_range_rows": _digest_rows(outside_rows),
    }


def _read_warehouse_snapshot(
    month: str,
    start: date,
    end: date,
    *,
    connect_factory: Any | None = None,
) -> dict[str, Any]:
    """Read target and legacy-table protection hashes in one read-only snapshot."""
    if connect_factory is None:
        import mysql.connector

        from app.data_fetch.configs.db_config import DB_CONFIG

        config = dict(DB_CONFIG)
        config["connection_timeout"] = min(int(config.get("connection_timeout", 10)), 10)

        def connect_factory() -> Any:
            return mysql.connector.connect(**config, autocommit=True)

    connection = connect_factory()
    connection.autocommit = True
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction(readonly=True, consistent_snapshot=True)
        cursor.execute(f"SELECT * FROM `{TABLE_NAME}`")
        target_rows = [dict(row) for row in cursor.fetchall()]
        legacy_rows: dict[str, list[dict[str, Any]]] = {}
        for table in LEGACY_TABLES:
            cursor.execute(f"SELECT * FROM `{table}`")
            legacy_rows[table] = [dict(row) for row in cursor.fetchall()]
        connection.rollback()
    finally:
        cursor.close()
        connection.close()
    return {
        "target_rows": target_rows,
        "target": _target_snapshot_summary(target_rows, month, start, end),
        "legacy": {name: _digest_rows(rows) for name, rows in legacy_rows.items()},
    }


def _full_month_progress_hash(path: Path = full_month.DEFAULT_PROGRESS_PATH) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": None, "sha256": None}
    body = path.read_bytes()
    return {
        "path": str(path),
        "exists": True,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _progress_hash_unchanged(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return all(before.get(key) == after.get(key) for key in ("exists", "bytes", "sha256"))


def _range_sql_rows(
    rows: Sequence[Mapping[str, Any]], start: date, end: date
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if row.get("SOURCE") == SOURCE
        and _row_date(row) is not None
        and start <= _row_date(row) <= end
    ]


def build_plan(
    start_text: str | None = None,
    end_text: str | None = None,
    *,
    ledger_path: Path = DEFAULT_LEDGER,
) -> dict[str, Any]:
    """Build a plan without SQL, network, scheduler, or ledger mutation."""
    if (start_text is None) != (end_text is None):
        raise ValueError("both --start-date and --end-date are required together")
    request: dict[str, Any]
    if start_text is None:
        request = {"selected_range": None, "apply_requires_explicit_range": True}
    else:
        month, start, end = normalize_range(str(start_text), str(end_text))
        request = {
            "selected_range": {
                "month": month,
                "start_date": f"{start:%Y%m%d}",
                "end_date": f"{end:%Y%m%d}",
            },
            "max_codes": 1,
            "source_timeout_seconds": SOURCE_TIMEOUT_SECONDS,
            "managed_timeout_seconds": MANAGED_TIMEOUT_SECONDS,
            "ingest_mode": "backfill",
            "operator_id": None,
            "task_id": None,
            "unique_claim_per_attempt": True,
        }
    return {
        "mode": "plan",
        "status": "not_started",
        "request": request,
        "source_calls": 0,
        "business_writes": 0,
        "ledger": {"path": str(ledger_path), "separate_from_full_month_progress": True},
        "supervision": {
            "soft_child_deadline_seconds": SOFT_SECONDS,
            "send_sigterm_at_seconds": TERM_SECONDS,
            "send_sigkill_at_seconds": KILL_SECONDS,
            "one_archive_get": True,
            "process_group_cleanup": True,
            "dispatch_marker_before_popen": True,
        },
        "comparison": {
            "compared_fields": list(COMPARE_FIELDS),
            "compared_field_count": len(COMPARE_FIELDS),
            "protect_all_target_rows_outside_exact_range": True,
            "protect_all_fields_in_legacy_tables": list(LEGACY_TABLES),
            "full_month_progress_hash_checked_unchanged": True,
        },
        "known_candidates_for_explicit_review_only": [
            {
                "start_date": "20191223",
                "end_date": "20191223",
                "evidence": "candidate has 168 source rows; target may already contain this date",
            },
            {
                "start_date": "20191225",
                "end_date": "20191231",
                "evidence": "seven observed archive dates; requires a fresh bounded acceptance",
            },
            {
                "start_date": "20200301",
                "end_date": "20200330",
                "evidence": "separate verified partial-range proof is importable; month remains invalid/unverified",
            },
        ],
        "completeness": {
            "range_only": True,
            "month_verified": False,
            "source_complete": False,
            "calendar": "unknown",
            "contract_lifecycle_and_inception": "unknown",
            "amount_unit": "unknown",
        },
    }


class _RangeCapturePatch:
    """Route exactly one explicit range GET through the existing wire recorder."""

    def __init__(self, capture: Any, start: date, end: date, producer: Any) -> None:
        self.capture = capture
        self.start = start
        self.end = end
        self.producer = producer
        self.original: Any | None = None
        self.retained = False

    def __enter__(self) -> _RangeCapturePatch:
        full_month._CAPTURE_LOCK.acquire()
        self.original = self.producer.fetch_cffex_option_history
        original = self.original

        def recorded_fetch(start_date: Any, end_date: Any, **kwargs: Any) -> Any:
            if "session" in kwargs:
                self.capture.record_error(RuntimeError("producer passed an unreviewed session"))
                raise RuntimeError("range controller must own the source session")
            requested = (normalize_date(start_date), normalize_date(end_date))
            if requested != (self.start, self.end):
                self.capture.record_error(RuntimeError("producer request escaped approved range"))
                raise RuntimeError("producer request differs from approved exact date range")
            session = full_month.RecordingSession(self.capture)
            try:
                rows = original(start_date, end_date, session=session, **kwargs)
                full_month._reject_future_source_dates(rows, self.capture.as_of_date)
                return rows
            except BaseException as exc:
                self.capture.record_error(exc)
                raise
            finally:
                session.close()

        self.producer.fetch_cffex_option_history = recorded_fetch
        return self

    def retain_until_process_exit(self) -> None:
        import atexit

        self.retained = True
        atexit.register(self.restore)

    def restore(self) -> None:
        if self.original is not None:
            self.producer.fetch_cffex_option_history = self.original
            self.original = None
            full_month._CAPTURE_LOCK.release()

    def __exit__(self, *_exc: object) -> None:
        if not self.retained:
            self.restore()


def _receipt_checks(
    receipt: Mapping[str, Any],
    *,
    status: str,
    range_scope: str,
    source_key_count: int,
    wire: Mapping[str, Any],
) -> dict[str, bool]:
    committed = receipt.get("committed_write_count")
    return {
        "execution_completed": status == "completed",
        "run_mode_backfill": receipt.get("run_mode") == "backfill",
        "target_table_matches": receipt.get("table_name") == TABLE_NAME,
        "committed_write_count_positive": (
            isinstance(committed, int) and not isinstance(committed, bool) and committed > 0
        ),
        "managed_scope_exact": receipt.get("source_scope") == range_scope,
        "quality_partial": receipt.get("quality_status") == "partial",
        "source_complete_false": receipt.get("source_complete") is False,
        "source_row_count_matches": receipt.get("source_row_count") == source_key_count,
        "valid_row_count_matches": receipt.get("valid_row_count") == source_key_count,
        "source_is_nonempty": source_key_count > 0,
        "one_http_200": wire.get("request_count") == 1 and wire.get("status_code") == 200,
        "wire_capture_verifiable": wire.get("transport_verifiable") is True,
    }


REQUIRED_RECEIPT_CHECKS = frozenset(
    {
        "execution_completed",
        "run_mode_backfill",
        "target_table_matches",
        "committed_write_count_positive",
        "managed_scope_exact",
        "quality_partial",
        "source_complete_false",
        "source_row_count_matches",
        "valid_row_count_matches",
        "source_is_nonempty",
        "one_http_200",
        "wire_capture_verifiable",
    }
)
LEGACY_MARCH_REQUIRED_RECEIPT_CHECKS = frozenset(
    {
        "execution_completed",
        "managed_call_started",
        "run_mode_backfill",
        "target_table_matches",
        "committed_write_count_positive",
        "managed_scope_matches_exact_range",
        "quality_status_partial",
        "source_complete_false",
        "source_row_count_matches_normalizer",
        "valid_row_count_matches_normalizer",
        "per_row_month_scope_preserved",
        "source_sequence_complete_for_exact_range",
        "source_completeness_false",
        "archive_sha_matches_capture",
        "one_http_200",
        "transport_verifiable",
    }
)


def _receipt_checks_complete(checks: Any) -> bool:
    return _required_gate_set_passes(checks, REQUIRED_RECEIPT_CHECKS)


def _required_gate_set_passes(checks: Any, required: frozenset[str]) -> bool:
    return (
        isinstance(checks, Mapping)
        and required.issubset(checks)
        and all(checks.get(key) is True for key in required)
        and all(value is True for value in checks.values())
    )


def _dispatch_receipt_payload(
    *,
    run_id: str,
    source: str,
    parameters: Mapping[str, Any],
    managed_timeout: int,
    period: str,
    parameter_hash: str,
    claim_key: str,
) -> dict[str, Any]:
    """Build the minimal durable dispatch identity without runtime secrets."""
    return {
        "schema_version": DISPATCH_SCHEMA_VERSION,
        "record_type": "cffex_option_range_managed_dispatch",
        "run_id": run_id,
        "script_id": SCRIPT_ID,
        "source": source,
        "parameters": dict(parameters),
        "operator_id": None,
        "task_id": None,
        "managed_timeout_seconds": managed_timeout,
        "period_key": period,
        "parameter_hash": parameter_hash,
        "claim_key": claim_key,
        "persisted_before_managed_await": True,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
    }


async def _managed_range_call(
    *,
    start: date,
    end: date,
    month: str,
    run_id: str,
    capture: Any,
    dispatch_path: Path,
    source_timeout_seconds: int,
) -> tuple[Any | None, dict[str, Any], bool]:
    from app.services.akshare.scheduler import _identity_key, _parameter_hash, get_akshare_scheduler

    registration = await full_month._load_active_registration()
    parameters = {
        "start_date": f"{start:%Y%m%d}",
        "end_date": f"{end:%Y%m%d}",
        "max_codes": 1,
        "source_timeout_seconds": float(source_timeout_seconds),
        "_ingest_mode": "backfill",
    }
    period = f"cffex-date-range-controller-v1:{start:%Y%m%d}-{end:%Y%m%d}:{run_id}"
    parameter_hash = _parameter_hash(parameters)
    claim_key = _identity_key(SCRIPT_ID, registration["source"], period, parameter_hash)
    managed_timeout = MANAGED_TIMEOUT_SECONDS
    dispatch = {
        "run_id": run_id,
        "script_id": SCRIPT_ID,
        "source": registration["source"],
        "registration": registration,
        "parameters": parameters,
        "operator_id": None,
        "task_id": None,
        "managed_timeout_seconds": managed_timeout,
        "period_key": period,
        "parameter_hash": parameter_hash,
        "claim_key": claim_key,
    }
    dispatch_receipt = _dispatch_receipt_payload(
        run_id=run_id,
        source=str(registration["source"]),
        parameters=parameters,
        managed_timeout=managed_timeout,
        period=period,
        parameter_hash=parameter_hash,
        claim_key=claim_key,
    )
    _private_json(dispatch_path, dispatch_receipt)
    from app.data_fetch.scripts.options.daily import cffex_option_daily_history as producer

    scheduler = get_akshare_scheduler()
    patch = _RangeCapturePatch(capture, start, end, producer)
    timed_out = False
    with patch:
        try:
            execution = await asyncio.wait_for(
                scheduler.run_script_now(
                    SCRIPT_ID,
                    parameters=parameters,
                    operator_id=None,
                    task_id=None,
                    timeout_seconds=managed_timeout,
                    _claim_key=claim_key,
                    _period_key=period,
                ),
                timeout=managed_timeout + 5,
            )
        except TimeoutError:
            timed_out = True
            patch.retain_until_process_exit()
            execution = None
    return execution, dispatch, timed_out


def _managed_status(execution: Any | None) -> str:
    if execution is None:
        return "unknown"
    if isinstance(execution, Mapping):
        value = execution.get("status")
    else:
        value = getattr(execution, "status", None)
    return str(getattr(value, "value", value or "unknown")).casefold()


def _worker(directory: Path, parent_pid: int) -> int:
    """Internal worker: exactly one managed date-range run and one archive GET."""
    if os.getppid() != parent_pid:
        raise RuntimeError("internal worker must be started by the supervised parent")
    invocation = json.loads((directory / "invocation.json").read_text(encoding="utf-8"))
    month, start, end = normalize_range(invocation["start_date"], invocation["end_date"])
    run_id = str(invocation["run_id"])
    wire_dir = directory / "wire"
    wire_dir.mkdir(mode=0o700, exist_ok=False)
    now = full_month.shanghai_now().astimezone(full_month.UTC)
    capture = full_month.WireCapture(
        month=month,
        directory=wire_dir,
        run_id=run_id,
        as_of_date=now.astimezone(full_month.SHANGHAI).date(),
    )
    execution: Any | None = None
    dispatch: dict[str, Any] = {}
    call_error: str | None = None
    managed_started = False
    try:
        managed_started = True
        execution, dispatch, timed_out = asyncio.run(
            _managed_range_call(
                start=start,
                end=end,
                month=month,
                run_id=run_id,
                capture=capture,
                dispatch_path=directory / "dispatch.json",
                source_timeout_seconds=int(invocation["source_timeout_seconds"]),
            )
        )
    except BaseException as exc:
        timed_out = isinstance(exc, (TimeoutError, asyncio.TimeoutError))
        call_error = full_month._safe_text(f"{type(exc).__name__}: {exc}")
        capture.record_error(exc)
    try:
        wire = capture.finalize()
    except BaseException as exc:
        wire = {
            "transport_verifiable": False,
            "capture_error": full_month._safe_text(f"{type(exc).__name__}: {exc}"),
            "request_count": capture.request_count,
            "status_code": capture.status_code,
        }
    source_rows: list[dict[str, Any]] = []
    source_evidence: dict[str, Any] = {"status": "not_parsed"}
    if wire.get("transport_verifiable") and wire.get("body_path"):
        try:
            body = Path(str(wire["body_path"])).read_bytes()
            if hashlib.sha256(body).hexdigest() != wire.get("body_sha256"):
                raise RuntimeError("captured archive hash changed after persistence")
            parsed = parse_monthly_archive(
                body,
                archive_month=month,
                start_date=start,
                end_date=end,
                source_url=SOURCE_URL_TEMPLATE.format(month=month),
            )
            if parsed.attrs.get("source_sequence_complete") is not True:
                raise RuntimeError("strict parser did not certify the requested range sequence")
            if parsed.attrs.get("source_complete") is not False:
                raise RuntimeError("strict parser completeness contract changed")
            source_rows = list(parsed)
            source_evidence = {
                "status": "parsed",
                "source_key_count": len(source_rows),
                "source_fields_sha256": full_month._preimage_digest(source_rows),
                "source_scope_per_row": parsed.attrs.get("source_scope"),
                "source_sequence_complete": parsed.attrs.get("source_sequence_complete"),
                "source_complete": parsed.attrs.get("source_complete"),
                "source_archive_sha256": parsed.attrs.get("source_archive_sha256"),
                "source_member_count": parsed.attrs.get("source_member_count"),
                "source_member_date_start": parsed.attrs.get("source_member_date_start"),
                "source_member_date_end": parsed.attrs.get("source_member_date_end"),
                "source_archive_matches_capture": parsed.attrs.get("source_archive_sha256")
                == wire.get("body_sha256"),
            }
        except BaseException as exc:
            source_evidence = {
                "status": "failed_closed",
                "error": full_month._safe_text(f"{type(exc).__name__}: {exc}"),
            }
    status = _managed_status(execution)
    execution_summary = (
        full_month._safe_execution_summary(execution) if execution is not None else None
    )
    receipt = (execution_summary or {}).get("result", {})
    start_text, end_text = f"{start:%Y%m%d}", f"{end:%Y%m%d}"
    expected_scope = f"cffex:option-history:monthly-archive:{start_text}-{end_text}"
    checks = _receipt_checks(
        receipt,
        status=status,
        range_scope=expected_scope,
        source_key_count=len(source_rows),
        wire=wire,
    )
    checks.update(
        {
            "managed_call_started": managed_started,
            "source_parser_nonempty": len(source_rows) > 0,
            "source_row_hash_recorded": source_evidence.get("status") == "parsed",
            "range_scope_per_row_month": source_evidence.get("source_scope_per_row")
            == f"cffex:option-history:monthly-archive:{month}",
            "source_sequence_complete": source_evidence.get("source_sequence_complete") is True,
            "source_archive_not_complete": source_evidence.get("source_complete") is False,
            "archive_hash_matches_capture": source_evidence.get("source_archive_matches_capture")
            is True,
        }
    )
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "month": month,
        "start_date": start_text,
        "end_date": end_text,
        "range_id": _range_id(start, end),
        "dispatch": dispatch,
        "managed_status": status,
        "managed_call_started": managed_started,
        "managed_call_error": call_error,
        "timed_out": timed_out,
        "execution": execution_summary,
        "wire_capture": wire,
        "source_evidence": source_evidence,
        "receipt_checks": checks,
        "source_complete": False,
        "range_sequence_complete": bool(source_evidence.get("source_sequence_complete")),
        "month_verified": False,
        "calendar_and_lifecycle": "unknown",
        "amount_unit": "unknown",
    }
    _private_json(directory / "worker-result.json", result)
    return 0 if all(checks.values()) else 1


def _spawn_child(command: list[str], directory: Path, stdout: Any, stderr: Any) -> Any:
    _private_json(
        directory / "dispatch-may-start.json",
        {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "popen_not_yet_called": True,
            "source_or_write_possible_after_marker": True,
        },
    )
    return subprocess.Popen(
        command,
        cwd=BACKEND,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )


def _supervise_child(child: Any) -> dict[str, bool]:
    state = {"timed_out": False, "term_sent": False, "kill_sent": False}
    try:
        try:
            child.wait(timeout=SOFT_SECONDS)
        except subprocess.TimeoutExpired:
            state["timed_out"] = True
            try:
                child.wait(timeout=TERM_SECONDS - SOFT_SECONDS)
            except subprocess.TimeoutExpired:
                state["term_sent"] = True
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=KILL_SECONDS - TERM_SECONDS)
                except subprocess.TimeoutExpired:
                    state["kill_sent"] = True
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait(timeout=5)
    finally:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                state["kill_sent"] = True
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=5)
    return state


def _read_managed_claim(claim_key: str, period_key: str) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.db.database import async_session_maker, engine
    from app.models.akshare_mgmt import AkshareTaskRunClaim, TaskExecution

    async def read() -> list[dict[str, Any]]:
        try:
            async with async_session_maker() as session:
                claim = await session.scalar(
                    select(AkshareTaskRunClaim).where(
                        AkshareTaskRunClaim.claim_key == claim_key,
                        AkshareTaskRunClaim.period_key == period_key,
                    )
                )
                if claim is None:
                    return []
                execution = await session.scalar(
                    select(TaskExecution).where(TaskExecution.execution_id == claim.execution_id)
                )
                claim_status = getattr(claim.status, "value", claim.status)
                execution_status = getattr(getattr(execution, "status", None), "value", None)
                return [
                    {
                        "claim_key": claim.claim_key,
                        "period_key": claim.period_key,
                        "claim_status": str(claim_status),
                        "execution_id": claim.execution_id,
                        "execution_status": (
                            str(execution_status) if execution_status is not None else None
                        ),
                        "task_id": getattr(execution, "task_id", None),
                        "operator_id": getattr(execution, "operator_id", None),
                    }
                ]
        finally:
            await engine.dispose()

    return asyncio.run(read())


def _load_dispatch_receipt(
    directory: Path,
    *,
    run_id: str,
    start: date,
    end: date,
    source_timeout_seconds: int,
) -> dict[str, Any] | None:
    """Read the fsynced identity written before the managed scheduler await."""
    path = directory / "dispatch.json"
    if not path.exists():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("persisted managed dispatch receipt is unreadable") from exc
    if not isinstance(receipt, dict):
        raise ValueError("persisted managed dispatch receipt must be an object")
    expected_period = f"cffex-date-range-controller-v1:{start:%Y%m%d}-{end:%Y%m%d}:{run_id}"
    expected_parameters = {
        "start_date": f"{start:%Y%m%d}",
        "end_date": f"{end:%Y%m%d}",
        "max_codes": 1,
        "source_timeout_seconds": float(source_timeout_seconds),
        "_ingest_mode": "backfill",
    }
    if (
        receipt.get("schema_version") != DISPATCH_SCHEMA_VERSION
        or receipt.get("record_type") != "cffex_option_range_managed_dispatch"
        or receipt.get("run_id") != run_id
        or receipt.get("script_id") != SCRIPT_ID
        or receipt.get("source") != SCRIPT_SOURCE
        or receipt.get("parameters") != expected_parameters
        or receipt.get("operator_id") is not None
        or receipt.get("task_id") is not None
        or receipt.get("managed_timeout_seconds") != MANAGED_TIMEOUT_SECONDS
        or receipt.get("period_key") != expected_period
        or not isinstance(receipt.get("parameter_hash"), str)
        or not receipt.get("parameter_hash")
        or not isinstance(receipt.get("claim_key"), str)
        or not receipt.get("claim_key")
        or receipt.get("persisted_before_managed_await") is not True
        or full_month.parse_aware_timestamp(receipt.get("recorded_at_utc")) is None
    ):
        raise ValueError("persisted managed dispatch receipt failed identity validation")
    return receipt


def _resolve_parent_dispatch(
    directory: Path,
    worker: Mapping[str, Any],
    *,
    run_id: str,
    start: date,
    end: date,
    source_timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any] | None, str, bool | None]:
    """Prefer durable pre-await dispatch data when a child result is missing."""
    persisted = _load_dispatch_receipt(
        directory,
        run_id=run_id,
        start=start,
        end=end,
        source_timeout_seconds=source_timeout_seconds,
    )
    raw_worker_dispatch = worker.get("dispatch")
    worker_dispatch = dict(raw_worker_dispatch) if isinstance(raw_worker_dispatch, Mapping) else {}
    if persisted is None:
        if worker_dispatch:
            return worker_dispatch, None, "missing", False
        return {}, None, "not_written", None
    if not worker_dispatch:
        status = (
            "persisted_worker_dispatch_missing" if worker else "persisted_worker_result_missing"
        )
        return persisted, persisted, status, None
    identity_fields = (
        "run_id",
        "script_id",
        "source",
        "parameters",
        "operator_id",
        "task_id",
        "managed_timeout_seconds",
        "period_key",
        "parameter_hash",
        "claim_key",
    )
    matches = all(worker_dispatch.get(key) == persisted.get(key) for key in identity_fields)
    return persisted, persisted, "persisted", matches


def _read_claim_for_dispatch(dispatch: Mapping[str, Any]) -> list[dict[str, Any]]:
    claim_key = dispatch.get("claim_key")
    period_key = dispatch.get("period_key")
    if not isinstance(claim_key, str) or not claim_key:
        return []
    if not isinstance(period_key, str) or not period_key:
        return []
    return _read_managed_claim(claim_key, period_key)


def _native_range_compare(
    worker: Mapping[str, Any], sql_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    wire = worker.get("wire_capture", {})
    body_path = wire.get("body_path") if isinstance(wire, Mapping) else None
    if not body_path:
        return {"matched": False, "status": "no_captured_body", "source_key_count": 0}
    month, start, end = normalize_range(str(worker["start_date"]), str(worker["end_date"]))
    body = Path(str(body_path)).read_bytes()
    if hashlib.sha256(body).hexdigest() != wire.get("body_sha256"):
        return {"matched": False, "status": "archive_hash_mismatch", "source_key_count": 0}
    try:
        comparison = native_verifier.compare_native_range(
            body,
            _range_sql_rows(sql_rows, start, end),
            month=month,
            start=start,
            end=end,
        )
    except Exception as exc:
        return {
            "matched": False,
            "status": "independent_native_csv_parse_failed_closed",
            "error": full_month._safe_text(exc),
            "source_key_count": 0,
            "sql_key_count": len(_range_sql_rows(sql_rows, start, end)),
            "compared_field_count": len(COMPARE_FIELDS),
            "requested_range": [f"{start:%Y%m%d}", f"{end:%Y%m%d}"],
            "source_complete": False,
            "month_verified": False,
        }
    comparison.update(
        {
            "matched": comparison.get("matched") is True,
            "requested_range": [f"{start:%Y%m%d}", f"{end:%Y%m%d}"],
            "source_complete": False,
            "month_verified": False,
        }
    )
    return comparison


def _import_proof(proof_path: Path, ledger_path: Path) -> dict[str, Any]:
    """Import a separately reviewed exact-range receipt without new source or SQL access."""
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("proof report must be a JSON object")
    scope = payload.get("source_scope")
    if not isinstance(scope, Mapping):
        raise ValueError("proof report has no exact source_scope object")
    selected = scope.get("selected_date_range")
    if not isinstance(selected, list) or len(selected) != 2:
        raise ValueError("proof report has no exact selected date range")
    start_text, end_text = (str(item).replace("-", "") for item in selected)
    month, start, end = normalize_range(start_text, end_text)
    legacy_march_range = (
        month == "202003" and start.isoformat() == "2020-03-01" and end.isoformat() == "2020-03-30"
    )
    wire = payload.get("wire_capture")
    managed_readback = payload.get("managed_readback")
    checks = payload.get("managed_receipt_checks")
    native = payload.get("independent_native_csv_fresh_sql_comparison")
    protections = payload.get("protection_hashes")
    if not isinstance(wire, Mapping):
        raise ValueError("proof wire_capture must be an object")
    if not isinstance(managed_readback, list) or len(managed_readback) != 1:
        raise ValueError("proof managed_readback must contain exactly one durable identity")
    expected_claim = managed_readback[0]
    if not isinstance(expected_claim, Mapping):
        raise ValueError("proof managed_readback entry must be an object")
    if not isinstance(checks, Mapping):
        raise ValueError("proof managed_receipt_checks must be an object")
    current_check_set_present = REQUIRED_RECEIPT_CHECKS.issubset(checks)
    legacy_march_check_set_present = (
        legacy_march_range and LEGACY_MARCH_REQUIRED_RECEIPT_CHECKS.issubset(checks)
    )
    if not current_check_set_present and not legacy_march_check_set_present:
        raise ValueError("proof managed_receipt_checks is incomplete")
    if not isinstance(native, Mapping):
        raise ValueError("proof independent native comparison must be an object")
    if not isinstance(protections, Mapping):
        raise ValueError("proof protection_hashes must be an object")

    body_path = Path(str(wire.get("body_path", "")))
    body_hash_ok = body_path.is_file() and hashlib.sha256(
        body_path.read_bytes()
    ).hexdigest() == wire.get("body_sha256")
    checks_ok = _receipt_checks_complete(checks) or (
        legacy_march_range
        and _required_gate_set_passes(checks, LEGACY_MARCH_REQUIRED_RECEIPT_CHECKS)
    )
    source_count = native.get("source_key_count")
    sql_count = native.get("sql_month_row_count")
    field_comparisons = native.get("field_comparisons")
    mismatch_count = native.get("mismatch_count")
    native_ok = (
        native.get("matched") is True
        and isinstance(source_count, int)
        and not isinstance(source_count, bool)
        and source_count > 0
        and isinstance(sql_count, int)
        and not isinstance(sql_count, bool)
        and sql_count == source_count
        and isinstance(field_comparisons, int)
        and not isinstance(field_comparisons, bool)
        and field_comparisons == source_count * len(COMPARE_FIELDS)
        and isinstance(mismatch_count, int)
        and not isinstance(mismatch_count, bool)
        and mismatch_count == 0
        and native.get("source_requested_date_range") == [start.isoformat(), end.isoformat()]
    )
    protections_ok = (
        protections.get("target_outside_exact_scope_unchanged") is True
        and protections.get("four_legacy_tables_unchanged") is True
        and protections.get("canonical_full_month_progress_unchanged") is True
    )
    if not (
        payload.get("status") == "range_verified_partial_archive"
        and payload.get("range_verified") is True
        and payload.get("source_complete") is False
        and payload.get("full_month_verified") is False
        and wire.get("transport_verifiable") is True
        and wire.get("request_count") == 1
        and wire.get("status_code") == 200
        and body_hash_ok
        and payload.get("durable_managed_identity_matches") is True
        and isinstance(expected_claim.get("period_key"), str)
        and expected_claim.get("period_key", "").startswith(
            f"cffex-date-range-controller-v1:{start:%Y%m%d}-{end:%Y%m%d}:"
        )
        and expected_claim.get("claim_status") == "completed"
        and expected_claim.get("execution_status") == "completed"
        and expected_claim.get("task_id") is None
        and expected_claim.get("operator_id") is None
        and checks_ok
        and native_ok
        and protections_ok
    ):
        raise ValueError("proof receipt does not satisfy the exact-range acceptance contract")
    proof_sha = hashlib.sha256(proof_path.read_bytes()).hexdigest()
    prior = read_range_ledger(ledger_path)
    if any(event.get("external_proof_sha256") == proof_sha for event in prior):
        raise ValueError("this external proof has already been imported into the range ledger")
    event = append_range_event(
        ledger_path,
        {
            "status": "range_verified_partial_external_proof_imported",
            "attempt_id": payload.get("run_id"),
            "start_date": f"{start:%Y%m%d}",
            "end_date": f"{end:%Y%m%d}",
            "external_proof_path": str(proof_path.resolve()),
            "external_proof_sha256": proof_sha,
            "source_archive_sha256": wire.get("body_sha256"),
            "source_key_count": native["source_key_count"],
            "sql_field_comparisons": native["field_comparisons"],
            "month_verified": False,
            "source_complete": False,
            "source_calls": 0,
            "business_writes": 0,
        },
    )
    return {
        "mode": "import_proof",
        "status": event["status"],
        "source_calls": 0,
        "business_writes": 0,
        "month_verified": False,
        "source_complete": False,
        "ledger_event_sha256": event["event_sha256"],
        "proof_sha256": proof_sha,
        "range_id": event["range_id"],
    }


def _worker_committed_write_count(worker: Mapping[str, Any]) -> int | None:
    execution = worker.get("execution")
    result = execution.get("result") if isinstance(execution, Mapping) else None
    count = result.get("committed_write_count") if isinstance(result, Mapping) else None
    return count if type(count) is int and count >= 0 else None


def _worker_source_call_count(
    worker: Mapping[str, Any], *, request_may_have_started: bool
) -> int | str:
    wire = worker.get("wire_capture")
    count = wire.get("request_count") if isinstance(wire, Mapping) else None
    if type(count) is int and count > 0:
        return count
    # An interrupted child may have captured a zero before its source call began.
    # Only a pre-dispatch path can certify that no request was made.
    return "unknown" if request_may_have_started else 0


def _confirmed_committed_write_count(
    worker: Mapping[str, Any],
    *,
    business_write_possible: bool,
    raw_count: int | None,
) -> int | None:
    if raw_count is not None and raw_count > 0:
        return raw_count
    if not business_write_possible:
        return 0
    if worker.get("managed_status") == "completed" and raw_count == 0:
        return 0
    return None


def _business_write_commit_state(
    *, business_write_possible: bool, committed_write_count: int | None
) -> bool | None:
    if committed_write_count is not None:
        return committed_write_count > 0
    return None if business_write_possible else False


def _apply_range(
    start: date,
    end: date,
    *,
    ledger_path: Path,
    artifact_root: Path,
    source_timeout_seconds: int,
) -> dict[str, Any]:
    month = start.strftime("%Y%m")
    start_text, end_text = f"{start:%Y%m%d}", f"{end:%Y%m%d}"
    run_id = uuid4().hex
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = artifact_root / f"range-{start_text}-{end_text}-{timestamp}-{run_id[:8]}"
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    directory.chmod(0o700)
    before_progress = _full_month_progress_hash()
    base_event = {
        "attempt_id": run_id,
        "start_date": start_text,
        "end_date": end_text,
        "status": "attempt_started",
        "month_verified": False,
        "source_complete": False,
        "artifact_directory": str(directory),
        "source_timeout_seconds": source_timeout_seconds,
        "supervisor_seconds": {"soft": SOFT_SECONDS, "term": TERM_SECONDS, "kill": KILL_SECONDS},
    }
    progress_event: dict[str, Any] | None = None
    child_started = False
    worker: dict[str, Any] = {}
    try:
        events = read_range_ledger(ledger_path)
        del events
        with full_month.MySQLOptionHistoryReader() as reader:
            schema = dict(reader.check_schema())
        before = _read_warehouse_snapshot(month, start, end)
        before_summary = {key: value for key, value in before.items() if key != "target_rows"}
        _private_json(directory / "before-hashes.json", before_summary)
        invocation = {
            "run_id": run_id,
            "month": month,
            "start_date": start_text,
            "end_date": end_text,
            "source_timeout_seconds": source_timeout_seconds,
            "schema_sha256": schema.get("sha256"),
            "full_month_progress_before": before_progress,
        }
        _private_json(directory / "invocation.json", invocation)
        progress_event = append_range_event(
            ledger_path,
            {
                **base_event,
                "status": "attempt_started",
                "source_calls": 0,
                "business_writes": 0,
                "schema_sha256": schema.get("sha256"),
                "preimage_target": before_summary["target"],
                "preimage_legacy": before_summary["legacy"],
                "full_month_progress_before": before_progress,
            },
        )
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            str(directory),
            "--parent-pid",
            str(os.getpid()),
        ]
        started = time.monotonic()
        with (
            (directory / "stdout.log").open("xb") as stdout,
            (directory / "stderr.log").open("xb") as stderr,
        ):
            os.chmod(directory / "stdout.log", 0o600)
            os.chmod(directory / "stderr.log", 0o600)
            child = _spawn_child(command, directory, stdout, stderr)
            child_started = True
            supervisor = _supervise_child(child)
        after = _read_warehouse_snapshot(month, start, end)
        after_summary = {key: value for key, value in after.items() if key != "target_rows"}
        _private_json(directory / "after-hashes.json", after_summary)
        after_progress = _full_month_progress_hash()
        worker_path = directory / "worker-result.json"
        raw_worker = (
            json.loads(worker_path.read_text(encoding="utf-8")) if worker_path.exists() else {}
        )
        worker = raw_worker if isinstance(raw_worker, dict) else {}
        wire = worker.get("wire_capture", {})
        comparison = _native_range_compare(worker, after.get("target_rows", []))
        dispatch, dispatch_receipt, dispatch_receipt_status, dispatch_matches_worker = (
            _resolve_parent_dispatch(
                directory,
                worker,
                run_id=run_id,
                start=start,
                end=end,
                source_timeout_seconds=source_timeout_seconds,
            )
        )
        claim_key = dispatch.get("claim_key")
        period_key = dispatch.get("period_key")
        claim_readback = _read_claim_for_dispatch(dispatch)
        identity = claim_readback[0] if len(claim_readback) == 1 else {}
        durable_identity_matches = (
            identity.get("claim_key") == claim_key
            and identity.get("period_key") == period_key
            and identity.get("claim_status") == "completed"
            and identity.get("execution_status") == "completed"
            and identity.get("task_id") is None
            and identity.get("operator_id") is None
        )
        protections = {
            "target_outside_exact_range_unchanged": before_summary["target"][
                "outside_exact_range_rows"
            ]
            == after_summary["target"]["outside_exact_range_rows"],
            "legacy_tables_unchanged": before_summary["legacy"] == after_summary["legacy"],
            "target_before": before_summary["target"],
            "target_after": after_summary["target"],
            "legacy_before": before_summary["legacy"],
            "legacy_after": after_summary["legacy"],
            "full_month_progress_before": before_progress,
            "full_month_progress_after": after_progress,
            "full_month_progress_unchanged": _progress_hash_unchanged(
                before_progress, after_progress
            ),
        }
        raw_receipt_checks = worker.get("receipt_checks", {})
        receipt_checks = dict(raw_receipt_checks) if isinstance(raw_receipt_checks, Mapping) else {}
        receipt_checks_complete = _receipt_checks_complete(receipt_checks)
        successful = (
            not supervisor["timed_out"]
            and child.returncode == 0
            and receipt_checks_complete
            and dispatch_receipt_status == "persisted"
            and dispatch_matches_worker is True
            and durable_identity_matches
            and comparison.get("matched") is True
            and protections["target_outside_exact_range_unchanged"]
            and protections["legacy_tables_unchanged"]
            and protections["full_month_progress_unchanged"]
        )
        business_write_possible = bool(worker.get("managed_call_started") or child_started)
        committed_write_count = _confirmed_committed_write_count(
            worker,
            business_write_possible=business_write_possible,
            raw_count=_worker_committed_write_count(worker),
        )
        business_writes = (
            committed_write_count
            if committed_write_count is not None
            else None
            if business_write_possible
            else 0
        )
        business_write_committed = _business_write_commit_state(
            business_write_possible=business_write_possible,
            committed_write_count=committed_write_count,
        )
        summary = {
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "apply",
            "status": "range_verified_partial_archive"
            if successful
            else "managed_outcome_unknown_write_possible"
            if supervisor["timed_out"] or not worker
            else "range_acceptance_failed_closed",
            "range_id": _range_id(start, end),
            "month": month,
            "start_date": start_text,
            "end_date": end_text,
            "run_id": run_id,
            "artifact_directory": str(directory),
            "range_ledger_attempt_event_sha256": (
                progress_event.get("event_sha256") if progress_event else None
            ),
            "child_returncode": child.returncode,
            "child_elapsed_seconds": round(time.monotonic() - started, 3),
            "supervisor": {
                "soft_seconds": SOFT_SECONDS,
                "term_seconds": TERM_SECONDS,
                "kill_seconds": KILL_SECONDS,
                **supervisor,
            },
            "wire_capture": wire,
            "managed_dispatch_receipt": dispatch_receipt,
            "managed_dispatch_receipt_status": dispatch_receipt_status,
            "managed_dispatch_matches_worker_result": dispatch_matches_worker,
            "managed_readback": claim_readback,
            "durable_managed_identity_matches": durable_identity_matches,
            "receipt_checks": receipt_checks,
            "receipt_checks_complete": receipt_checks_complete,
            "native_37_field_fresh_sql_comparison": comparison,
            "protection_hashes": protections,
            "source_calls": _worker_source_call_count(
                worker, request_may_have_started=business_write_possible
            ),
            "business_write_possible": business_write_possible,
            "business_writes": business_writes,
            "committed_write_count": committed_write_count,
            "business_write_committed": business_write_committed,
            "source_complete": False,
            "month_verified": False,
            "calendar_and_lifecycle": "unknown",
            "amount_unit": "unknown",
        }
        summary["range_verified"] = successful
        _private_json(directory / "acceptance-summary.json", summary)
        terminal_event = append_range_event(
            ledger_path,
            {
                **base_event,
                "status": "range_verified_partial_archive" if successful else summary["status"],
                "attempt_id": run_id,
                "summary_path": str(directory / "acceptance-summary.json"),
                "summary_sha256": hashlib.sha256(
                    (directory / "acceptance-summary.json").read_bytes()
                ).hexdigest(),
                "source_calls": summary["source_calls"],
                "business_write_possible": summary["business_write_possible"],
                "business_writes": summary["business_writes"],
                "committed_write_count": summary["committed_write_count"],
                "business_write_committed": summary["business_write_committed"],
                "source_key_count": comparison.get("source_key_count"),
                "sql_key_count": comparison.get("sql_key_count"),
                "comparison_matched": comparison.get("matched"),
                "source_complete": False,
                "month_verified": False,
            },
        )
        summary["range_ledger_terminal_event_sha256"] = terminal_event["event_sha256"]
        return summary
    except BaseException as exc:
        worker_path = directory / "worker-result.json"
        if not worker and worker_path.is_file():
            try:
                raw_worker = json.loads(worker_path.read_text(encoding="utf-8"))
                worker = raw_worker if isinstance(raw_worker, dict) else {}
            except (OSError, json.JSONDecodeError):
                worker = {}
        dispatch_receipt_path = directory / "dispatch.json"
        try:
            dispatch_receipt_sha256 = (
                hashlib.sha256(dispatch_receipt_path.read_bytes()).hexdigest()
                if dispatch_receipt_path.is_file()
                else None
            )
        except OSError:
            dispatch_receipt_sha256 = None
        dispatch_may_have_started = (
            child_started or (directory / "dispatch-may-start.json").exists()
        )
        business_write_possible = bool(
            worker.get("managed_call_started") or dispatch_may_have_started
        )
        committed_write_count = _confirmed_committed_write_count(
            worker,
            business_write_possible=business_write_possible,
            raw_count=_worker_committed_write_count(worker),
        )
        business_writes = (
            committed_write_count
            if committed_write_count is not None
            else None
            if business_write_possible
            else 0
        )
        business_write_committed = _business_write_commit_state(
            business_write_possible=business_write_possible,
            committed_write_count=committed_write_count,
        )
        failure = {
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "apply",
            "status": "failed_closed_write_possible"
            if dispatch_may_have_started or worker.get("managed_call_started")
            else "failed_closed_before_dispatch",
            "range_id": _range_id(start, end),
            "month": month,
            "start_date": start_text,
            "end_date": end_text,
            "run_id": run_id,
            "artifact_directory": str(directory),
            "managed_dispatch_receipt_path": str(dispatch_receipt_path),
            "managed_dispatch_receipt_sha256": dispatch_receipt_sha256,
            "error_type": type(exc).__name__,
            "error": full_month._safe_text(exc),
            "source_calls": _worker_source_call_count(
                worker, request_may_have_started=business_write_possible
            ),
            "business_write_possible": business_write_possible,
            "business_writes": business_writes,
            "committed_write_count": committed_write_count
            if committed_write_count is not None
            else None
            if business_write_possible
            else 0,
            "business_write_committed": business_write_committed,
            "source_complete": False,
            "month_verified": False,
        }
        if not (directory / "acceptance-summary.json").exists():
            _private_json(directory / "acceptance-summary.json", failure)
        if progress_event is not None:
            try:
                append_range_event(
                    ledger_path,
                    {
                        **base_event,
                        "status": failure["status"],
                        "attempt_id": run_id,
                        "summary_path": str(directory / "acceptance-summary.json"),
                        "source_calls": failure["source_calls"],
                        "business_write_possible": failure["business_write_possible"],
                        "business_writes": failure["business_writes"],
                        "committed_write_count": failure["committed_write_count"],
                        "business_write_committed": failure["business_write_committed"],
                        "source_complete": False,
                        "month_verified": False,
                    },
                )
            except Exception:
                pass
        return failure


def import_external_proof(proof_path: Path, ledger_path: Path = DEFAULT_LEDGER) -> dict[str, Any]:
    return _import_proof(proof_path.resolve(), ledger_path)


def _validate_cli_paths(ledger_path: Path) -> None:
    full_month_progress = full_month.DEFAULT_PROGRESS_PATH.resolve()
    selected_ledger = ledger_path.resolve()
    hardlink_alias = False
    if selected_ledger.exists() and full_month_progress.exists():
        try:
            hardlink_alias = os.path.samefile(selected_ledger, full_month_progress)
        except OSError:
            hardlink_alias = False
    if selected_ledger == full_month_progress or hardlink_alias:
        raise ValueError("range ledger must remain separate from full-month progress.jsonl")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="run one exact managed range")
    mode.add_argument(
        "--import-proof", type=Path, help="import a separately verified range receipt"
    )
    parser.add_argument("--start-date", help="inclusive YYYYMMDD; required with --apply")
    parser.add_argument("--end-date", help="inclusive YYYYMMDD; required with --apply")
    parser.add_argument("--source-timeout-seconds", type=int, default=SOURCE_TIMEOUT_SECONDS)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    dispatch_may_have_started = False
    try:
        if args.worker is not None:
            if args.parent_pid is None:
                parser.error("internal worker mode requires parent pid")
            return _worker(args.worker.resolve(), args.parent_pid)
        _validate_cli_paths(args.ledger)
        if args.import_proof:
            result = import_external_proof(args.import_proof, args.ledger)
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0
        if not args.apply:
            if (args.start_date is None) != (args.end_date is None):
                raise ValueError("both --start-date and --end-date are required together")
            report = build_plan(args.start_date, args.end_date, ledger_path=args.ledger)
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            return 0
        if args.start_date is None or args.end_date is None:
            raise ValueError("--apply requires explicit --start-date and --end-date")
        if not 1 <= args.source_timeout_seconds <= SOURCE_TIMEOUT_SECONDS:
            raise ValueError("source timeout must be between 1 and 90 seconds")
        _, start, end = normalize_range(args.start_date, args.end_date)
        dispatch_may_have_started = True
        result = _apply_range(
            start,
            end,
            ledger_path=args.ledger,
            artifact_root=args.artifacts,
            source_timeout_seconds=args.source_timeout_seconds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("range_verified") else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "mode": "error",
                    "status": "failed_closed_write_possible"
                    if dispatch_may_have_started
                    else "failed_closed_before_dispatch",
                    "error_type": type(exc).__name__,
                    "error": full_month._safe_text(exc),
                    "source_calls": "unknown" if dispatch_may_have_started else 0,
                    "business_write_possible": dispatch_may_have_started,
                    "business_write_committed": None if dispatch_may_have_started else False,
                    "source_complete": False,
                    "month_verified": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
