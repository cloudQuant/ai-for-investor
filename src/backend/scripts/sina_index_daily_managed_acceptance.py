#!/usr/bin/env python3
"""One-run managed acceptance for the reviewed Sina sh000001 daily history.

The default command is a database-free, network-free plan.  ``--apply`` is an
explicit, single-dispatch operation.  Its parent process persists the dispatch
identity and read-only preflight before starting a supervised child; the child
uses the normal AkShare scheduler, then independently re-decodes the newly
captured response and reads the canonical table back.  This file intentionally
does not install the producer/schema or change any scheduled task.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit

SCRIPT_ID = "stock_zh_index_daily"
SYMBOL = "sh000001"
SOURCE_NAME = "sina"
START_DATE = "19000101"
END_DATE = "20261020"
TASK_ID_TO_PROTECT = 650
EXPECTED_PERSISTENT_TASK_ROWS = 47
EXPECTED_TASK_CRON = "54 5 * * sun"
TARGET_TABLE = "INDEX_SINA_DAILY_HISTORY"
LEGACY_TABLE = "STOCK_ZH_INDEX_DAILY"
MODULE_PATH = "app.data_fetch.scripts.indexs.weekly.stock_zh_index_daily"
SOURCE_URL = "https://finance.sina.com.cn/realstock/company/sh000001/hisdata/klc_kl.js?d=2020_2_4"

SOURCE_TIMEOUT_SECONDS = 45
MANAGED_TIMEOUT_SECONDS = 120
POST_DISPATCH_READBACK_RESERVE_SECONDS = 45
CHILD_HARD_SECONDS = 170
OUTER_HARD_SECONDS = 180
TERM_GRACE_SECONDS = 5
KILL_GRACE_SECONDS = 5
EXPECTED_WRITER_BATCH_SIZE = 1000
EXPECTED_PRODUCER_SOURCE_SHA256 = "03b8a64f70b8a8409d304fdb09c5f69c1d571b62e5a0728d533199ae58b3551b"
EXPECTED_WRITER_SOURCE_SHA256 = "45655111f51b198bd0315eeadbfc883fd4328d4d8e9e958e4fbe829431ccfd1d"
EXPECTED_DATABASE_SOURCE_SHA256 = "e9b27c500cb21db84fafd9062f877693083516761a360478c868f47125ba09fb"
EXPECTED_2026_CALENDAR_AUDIT_SHA256 = (
    "0f8bd609e100f5e4c6e2f0671108eb92b11a6465f4729bedf6b55798f1035d32"
)
CALENDAR_AUDIT_RELATIVE_PATH = Path(
    "var/reports/iteration203/sse-index-calendar-authority-20261020/"
    "authority-and-2026-sequence-audit.json"
)
CALENDAR_CANDIDATE_START = date(2026, 1, 1)
CALENDAR_CANDIDATE_END = date(2026, 10, 19)

LOCAL_ONLY_COLUMNS = {"R_ID", "SOURCE_OBSERVED_AT_UTC", "CREATED_AT", "UPDATED_AT"}
COMPARE_COLUMNS = (
    "SOURCE",
    "INDEX_CODE",
    "MARKET_TYPE",
    "TRADE_DATE",
    "OPEN",
    "HIGH",
    "LOW",
    "CLOSE",
    "VOLUME",
    "VOLUME_UNIT",
    "ADJUSTMENT_BASIS",
    "SOURCE_RESPONSE_IDENTITY_VERIFIED",
    "SOURCE_HISTORY_COMPLETE",
    "SOURCE_INCEPTION_VERIFIED",
    "TRADING_CALENDAR_VERIFIED",
    "DECODED_PRECISION",
    "SOURCE_URL",
    "SOURCE_HTTP_STATUS",
    "SOURCE_RESPONSE_BYTES",
    "SOURCE_RESPONSE_SHA256",
    "SOURCE_ARTIFACT_ID",
    "AKSHARE_VERSION",
    "AKSHARE_INDEX_MODULE_SHA256",
    "AKSHARE_JS_DECODER_SHA256",
    "AKSHARE_INDEX_CONSTANTS_SHA256",
)
DECIMAL_SCALES = {"OPEN": 8, "HIGH": 8, "LOW": 8, "CLOSE": 8, "VOLUME": 8}
RUN_ID_RE = re.compile(r"\A[0-9]{8}T[0-9]{12}Z-[0-9a-f]{16}\Z")
SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_T = TypeVar("_T")


class AcceptanceError(RuntimeError):
    """The one-run acceptance could not establish its required evidence."""


@dataclass(frozen=True)
class DispatchIdentity:
    run_id: str
    script_id: str
    scheduler_source: str
    symbol: str
    start_date: str
    end_date: str
    mode: str
    task_id: None
    operator_id: None
    triggered_by: str
    period_key: str
    parameter_hash: str
    claim_key: str
    parameters: dict[str, Any]


def backend_root() -> Path:
    """Return this helper checkout's backend directory."""
    return Path(__file__).resolve().parents[1]


def project_root() -> Path:
    """Return the repository root shared with the reviewed producer."""
    return backend_root().parents[1]


def report_root() -> Path:
    return project_root() / "var" / "reports" / "iteration203" / "sina-index-managed-acceptance"


def build_plan() -> dict[str, Any]:
    """Return a pure plan; it performs no filesystem, network, or database I/O."""
    return {
        "mode": "read_only_plan",
        "script_id": SCRIPT_ID,
        "symbol": SYMBOL,
        "requested_window": {"start_date": START_DATE, "end_date": END_DATE},
        "dispatch": {
            "task_id": None,
            "operator_id": None,
            "triggered_by": "manual",
            "ingest_mode": "backfill",
            "period_key": "unique per apply run; generated and persisted before dispatch",
            "claim_key": "computed from script source, unique period, and exact parameters",
        },
        "budgets_seconds": {
            "source_hard_timeout": SOURCE_TIMEOUT_SECONDS,
            "managed_call_timeout": MANAGED_TIMEOUT_SECONDS,
            "post_dispatch_readback_reserve": POST_DISPATCH_READBACK_RESERVE_SECONDS,
            "child_hard_limit": CHILD_HARD_SECONDS,
            "outer_process_group_limit": OUTER_HARD_SECONDS,
        },
        "protection_checks": {
            "legacy_table": LEGACY_TABLE,
            "canonical_other_symbols_table": TARGET_TABLE,
            "scheduled_task_id": TASK_ID_TO_PROTECT,
            "scheduled_task_must_remain_off": True,
            "expected_task_parameters": {},
            "expected_task_cron": EXPECTED_TASK_CRON,
            "persistent_scheduled_task_rows": EXPECTED_PERSISTENT_TASK_ROWS,
            "script_registry_count": "must be unchanged before/after",
        },
        "evidence_rules": [
            "Only a new capture manifest created after this dispatch qualifies; prior raw-probe bodies are baseline artifacts, not new fetches.",
            "The frozen producer enforces exactly one HTTP request and strict save_data acknowledgement == decoded frame rows; the helper independently checks one new capture and exact SQL rows.",
            "The independent decoder is the pinned AkShare decoder over the same new body, not an independent JavaScript algorithm or native-decimal proof.",
            "Compare all deterministic source/provenance fields and date/OHLCV; exclude R_ID and local observation/created/updated timestamps.",
            "A reconciled full returned sequence does not prove source retention, inception, calendar, units, adjustment semantics, or full-history completeness.",
            "The 2026 SSE candidate comparison is limited to 2026-01-01 through 2026-10-19 and is not a deployed runtime calendar policy or a full-history calendar proof.",
        ],
        "network_requests": 0,
        "database_reads": 0,
        "database_writes": 0,
        "task_or_service_changes": 0,
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _parameter_hash(parameters: dict[str, Any]) -> str:
    # Keep byte-for-byte parity with app.services.akshare.scheduler._parameter_hash.
    normalized = json.dumps(
        parameters,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _claim_key(script_id: str, source: str, period_key: str, parameter_hash: str) -> str:
    identity = json.dumps(
        [script_id, source, period_key, parameter_hash],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def new_dispatch_identity(
    *,
    scheduler_source: str,
    now: datetime | None = None,
    nonce: str | None = None,
    run_id: str | None = None,
) -> DispatchIdentity:
    """Build a unique, taskless manual claim identity for this exact backfill window."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("dispatch time must be timezone-aware")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", scheduler_source):
        raise ValueError("scheduler source label is invalid")
    if run_id is None:
        stamp = current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        suffix = nonce or uuid.uuid4().hex[:16]
        if not re.fullmatch(r"[0-9a-f]{16}", suffix):
            raise ValueError("dispatch nonce must be 16 lowercase hex characters")
        run_id = f"{stamp}-{suffix}"
    elif nonce is not None:
        raise ValueError("an explicit run ID cannot be combined with a nonce")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("constructed run ID is invalid")
    parameters: dict[str, Any] = {
        "symbol": SYMBOL,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "source_timeout_seconds": SOURCE_TIMEOUT_SECONDS,
        "_ingest_mode": "backfill",
    }
    period_key = f"manual:sina-index-history:{run_id}"
    parameter_hash = _parameter_hash(parameters)
    return DispatchIdentity(
        run_id=run_id,
        script_id=SCRIPT_ID,
        scheduler_source=scheduler_source,
        symbol=SYMBOL,
        start_date=START_DATE,
        end_date=END_DATE,
        mode="backfill",
        task_id=None,
        operator_id=None,
        triggered_by="manual",
        period_key=period_key,
        parameter_hash=parameter_hash,
        claim_key=_claim_key(SCRIPT_ID, scheduler_source, period_key, parameter_hash),
        parameters=parameters,
    )


def validate_protection_snapshot(snapshot: dict[str, Any]) -> list[str]:
    """Return fail-closed preflight discrepancies from a pure snapshot."""
    errors: list[str] = []
    if snapshot.get("persistent_scheduled_task_count") != EXPECTED_PERSISTENT_TASK_ROWS:
        errors.append(
            "persistent scheduled-task row count differs from the reviewed 47-job baseline"
        )
    task = snapshot.get("protected_task")
    if not isinstance(task, dict):
        errors.append("protected task 650 is missing")
    else:
        if task.get("id") != TASK_ID_TO_PROTECT:
            errors.append("protected task identity is not task 650")
        if task.get("script_id") != SCRIPT_ID:
            errors.append("task 650 no longer targets stock_zh_index_daily")
        if task.get("is_active") is not False:
            errors.append("task 650 must remain OFF")
        if task.get("parameters") != {}:
            errors.append("task 650 parameters differ from the reviewed empty object")
        if task.get("schedule_expression") != EXPECTED_TASK_CRON:
            errors.append("task 650 cron differs from the reviewed expression")
        if task.get("next_execution_at") is not None:
            errors.append("task 650 unexpectedly has a next execution")
    script = snapshot.get("script_registry_entry")
    if not isinstance(script, dict):
        errors.append("stock_zh_index_daily registry entry is missing")
    else:
        if script.get("script_id") != SCRIPT_ID:
            errors.append("registry entry identity mismatch")
        if script.get("source") != SOURCE_NAME:
            errors.append("registry source differs from the reviewed Sina source identity")
        if script.get("module_path") != MODULE_PATH:
            errors.append("registry does not resolve to the reviewed local Sina producer")
        if script.get("target_table") != TARGET_TABLE:
            errors.append("script registry target table differs from the reviewed canonical target")
        if script.get("function_name") not in {"main", "run"}:
            errors.append("registry entry does not resolve the reviewed local run/main function")
        if script.get("is_custom") is not False:
            errors.append("script registry is not the reviewed built-in AkShare entry")
        if script.get("is_active") is not True:
            errors.append("script registry entry must be active for the explicit one-time run")
    if not isinstance(snapshot.get("script_registry_count"), int):
        errors.append("script registry count is unavailable")
    for name in ("legacy_table", "canonical_other_symbols"):
        entry = snapshot.get(name)
        if not isinstance(entry, dict) or not SHA256_RE.fullmatch(str(entry.get("sha256", ""))):
            errors.append(f"{name} protection hash is missing or malformed")
    if not isinstance(snapshot.get("canonical_target_symbol_before"), dict):
        errors.append("canonical target-symbol preimage is unavailable")
    if snapshot.get("producer_source_sha256") != EXPECTED_PRODUCER_SOURCE_SHA256:
        errors.append("local producer source differs from the reviewed exact-ack implementation")
    writer_sha = str(snapshot.get("writer_source_sha256", ""))
    if not SHA256_RE.fullmatch(writer_sha):
        errors.append("legacy writer source fingerprint is missing or malformed")
    elif writer_sha != EXPECTED_WRITER_SOURCE_SHA256:
        errors.append("legacy MySQL writer differs from the reviewed exact-ack implementation")
    database_sha = str(snapshot.get("database_source_sha256", ""))
    if not SHA256_RE.fullmatch(database_sha):
        errors.append("database base source fingerprint is missing or malformed")
    elif database_sha != EXPECTED_DATABASE_SOURCE_SHA256:
        errors.append("database base batch-size contract differs from the reviewed implementation")
    return errors


def compare_protection_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare the protected database state without treating unrelated row counts as proof."""
    fields = (
        "persistent_scheduled_task_count",
        "script_registry_count",
        "protected_task",
        "script_registry_entry",
        "producer_source_sha256",
        "writer_source_sha256",
        "database_source_sha256",
        "legacy_table",
        "canonical_other_symbols",
    )
    changed = [name for name in fields if before.get(name) != after.get(name)]
    return {
        "unchanged": not changed,
        "changed_fields": changed,
        "jobs_basis": "persistent ak_scheduled_tasks row count; helper never starts or edits APScheduler",
        "before": before,
        "after": after,
    }


def _manifest_files(artifact_root: Path, suffix: str) -> set[str]:
    if not artifact_root.exists():
        return set()
    if artifact_root.is_symlink() or not artifact_root.is_dir():
        raise AcceptanceError("fixed Sina artifact root is not a regular directory")
    return {path.name for path in artifact_root.glob(f"*{suffix}") if path.is_file()}


def capture_inventory(artifact_root: Path) -> dict[str, list[str]]:
    """List existing manifests only; this never creates the source artifact directory."""
    return {
        suffix.removeprefix("."): sorted(_manifest_files(artifact_root, f".{suffix}"))
        for suffix in ("raw.json", "identity.json", "verified.json")
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError(f"capture manifest is not a regular file: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise AcceptanceError(f"capture manifest is unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise AcceptanceError(f"capture manifest is not an object: {path.name}")
    return value


def inspect_new_capture(
    *,
    artifact_root: Path,
    before_inventory: dict[str, list[str]],
    intent: DispatchIdentity,
    dispatch_started_at_utc: str,
) -> dict[str, Any]:
    """Require exactly one new raw/identity/verified capture triplet for this dispatch."""
    after = capture_inventory(artifact_root)
    deltas = {
        suffix: sorted(set(after[suffix]) - set(before_inventory.get(suffix, [])))
        for suffix in after
    }
    if any(len(deltas[name]) != 1 for name in ("raw.json", "identity.json", "verified.json")):
        raise AcceptanceError(
            "expected one newly captured raw/identity/verified manifest triplet; "
            f"found { {name: len(values) for name, values in deltas.items()} }"
        )
    raw_path, identity_path, verified_path = (
        artifact_root / deltas[name][0] for name in ("raw.json", "identity.json", "verified.json")
    )
    raw = _load_manifest(raw_path)
    identity = _load_manifest(identity_path)
    verified = _load_manifest(verified_path)
    started = datetime.fromisoformat(dispatch_started_at_utc)
    if started.tzinfo is None or started.utcoffset() is None:
        raise AcceptanceError("dispatch start time is not timezone-aware")
    capture_times = [
        datetime.fromisoformat(str(value))
        for value in (
            raw.get("captured_at_utc"),
            identity.get("captured_at_utc"),
            verified.get("captured_at_utc"),
        )
    ]
    if any(value.tzinfo is None or value.utcoffset() is None for value in capture_times):
        raise AcceptanceError("new capture manifests lack timezone-aware timestamps")
    if any(
        value.astimezone(timezone.utc) < started.astimezone(timezone.utc) for value in capture_times
    ):
        raise AcceptanceError("a prior capture was replayed; manifest predates this dispatch")
    if len({value.astimezone(timezone.utc) for value in capture_times}) != 1:
        raise AcceptanceError("raw, identity, and verified manifests refer to different captures")
    for manifest, status in (
        (raw, "raw_captured_before_decode"),
        (identity, "raw_captured_before_decode"),
        (verified, "strictly_normalized"),
    ):
        if manifest.get("capture_status") != status:
            raise AcceptanceError("new capture manifest has an unexpected validation status")
        if manifest.get("requested_symbol") != intent.symbol:
            raise AcceptanceError("new capture manifest is bound to another symbol")
        source_url = manifest.get("capture_source_url")
        if source_url is not None and source_url != SOURCE_URL:
            raise AcceptanceError("new capture URL differs from the fixed reviewed Sina endpoint")
    if raw.get("requested_window") != [intent.start_date, intent.end_date]:
        raise AcceptanceError("raw capture does not match the exact requested date window")
    if identity.get("requested_window") != [intent.start_date, intent.end_date]:
        raise AcceptanceError("identity manifest does not match the exact requested window")
    if verified.get("requested_window") != ["1900-01-01", "2026-10-20"]:
        raise AcceptanceError("verified manifest does not match the exact requested window")
    returned_window = verified.get("returned_window")
    if (
        not isinstance(returned_window, list)
        or len(returned_window) != 2
        or any(not isinstance(value, str) for value in returned_window)
    ):
        raise AcceptanceError("verified manifest returned_window is missing or malformed")
    try:
        returned_start, returned_end = (date.fromisoformat(value) for value in returned_window)
    except ValueError as exc:
        raise AcceptanceError("verified manifest returned_window has an invalid date") from exc
    if returned_start > returned_end or not (
        date(1900, 1, 1) <= returned_start <= date(2026, 10, 20)
        and date(1900, 1, 1) <= returned_end <= date(2026, 10, 20)
    ):
        raise AcceptanceError("verified manifest returned_window is outside the requested scope")
    normalized_count = verified.get("normalized_row_count")
    if type(normalized_count) is not int or normalized_count <= 0:
        raise AcceptanceError("verified manifest normalized row count is missing or invalid")
    if raw.get("http_status") != 200 or verified.get("http_status") != 200:
        raise AcceptanceError("new Sina response was not HTTP 200")
    if identity.get("response_identity_status") != "exact_symbol_assignment":
        raise AcceptanceError("Sina response assignment identity is not exact")
    if identity.get("response_identity_verified") is not True:
        raise AcceptanceError("Sina response assignment identity is not verified")
    if identity.get("response_wrapper_identifier") != f"KLC_KL_{intent.symbol}":
        raise AcceptanceError("Sina response wrapper does not name the exact requested symbol")
    if verified.get("response_identity_verified") is not True:
        raise AcceptanceError("verified manifest lacks exact response identity evidence")
    artifact_sha = str(raw.get("artifact_sha256", ""))
    if not SHA256_RE.fullmatch(artifact_sha):
        raise AcceptanceError("new capture SHA256 is malformed")
    if any(
        manifest.get("artifact_sha256") != artifact_sha
        or manifest.get("artifact_id") != artifact_sha
        or manifest.get("artifact_bytes") != raw.get("artifact_bytes")
        for manifest in (raw, identity, verified)
    ):
        raise AcceptanceError("capture manifests disagree on body SHA256")
    body_path = artifact_root / f"{artifact_sha}.body"
    if body_path.is_symlink() or not body_path.is_file():
        raise AcceptanceError("new source body is missing or is a symlink")
    body_sha = hashlib.sha256(body_path.read_bytes()).hexdigest()
    if body_sha != artifact_sha:
        raise AcceptanceError("new source body failed its content hash")
    try:
        body_text = body_path.read_bytes().decode("utf-8-sig")
    except UnicodeError as exc:
        raise AcceptanceError("new Sina body is not valid UTF-8") from exc
    assignment = re.match(
        r"\A\s*(?:(?:var|let|const)\s+)?(?P<identifier>[A-Za-z_$][A-Za-z0-9_$]*)\s*=",
        body_text,
    )
    if assignment is None or assignment.group("identifier") != f"KLC_KL_{intent.symbol}":
        raise AcceptanceError(
            "raw body assignment does not independently bind the requested symbol"
        )
    body_size = body_path.stat().st_size
    if body_size != raw.get("artifact_bytes") or body_size != verified.get("artifact_bytes"):
        raise AcceptanceError("capture body size differs from the manifests")
    if verified.get("source_history_complete") is not False:
        raise AcceptanceError("verified manifest overstates full-history completeness")
    if verified.get("source_inception_verified") is not False:
        raise AcceptanceError("verified manifest overstates source inception")
    if verified.get("calendar_verified") is not False:
        raise AcceptanceError("verified manifest overstates exchange-calendar completeness")
    if verified.get("source_units") != "unknown":
        raise AcceptanceError("verified manifest assigns unreviewed source units")
    if verified.get("adjustment_basis") != "unknown":
        raise AcceptanceError("verified manifest assigns unreviewed adjustment semantics")
    if verified.get("decoded_precision") != "akshare_pandas_float_unverified":
        raise AcceptanceError("verified manifest overstates source numeric precision")
    return {
        "artifact_id": artifact_sha,
        "artifact_path": str(body_path),
        "artifact_bytes": body_size,
        "captured_at_utc": capture_times[0].astimezone(timezone.utc).isoformat(),
        "source_url": verified.get("capture_source_url"),
        "requested_window": verified.get("requested_window"),
        "normalized_row_count": verified.get("normalized_row_count"),
        "returned_window": returned_window,
        "response_identity_verified": True,
        "response_wrapper_identifier": identity.get("response_wrapper_identifier"),
        "decoded_precision": verified.get("decoded_precision"),
        "source_units": verified.get("source_units"),
        "adjustment_basis": verified.get("adjustment_basis"),
        "source_history_complete": False,
        "source_inception_verified": False,
        "calendar_verified": False,
        "one_request_evidence": {
            "new_capture_triplet_count": 1,
            "frozen_producer_enforces_single_requests_get": True,
            "independent_wire_counter_persisted_by_producer": False,
        },
        "manifests": {
            "raw": str(raw_path),
            "identity": str(identity_path),
            "verified": str(verified_path),
        },
    }


def _parse_source_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text)
    if re.fullmatch(r"\d{8}", text):
        return datetime.strptime(text, "%Y%m%d").date()
    raise AcceptanceError(f"independent AkShare decoder returned invalid date {value!r}")


def _decimal_at_scale(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise AcceptanceError(f"independent decoder {name} is missing or boolean")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AcceptanceError(f"independent decoder {name} is not numeric") from exc
    if not number.is_finite():
        raise AcceptanceError(f"independent decoder {name} is non-finite")
    if number < 0:
        raise AcceptanceError(f"independent decoder {name} is negative")
    quantum = Decimal(1).scaleb(-DECIMAL_SCALES[name])
    try:
        with localcontext() as context:
            context.prec = max(50, len(number.as_tuple().digits) + DECIMAL_SCALES[name] + 4)
            normalized = number.quantize(quantum)
    except InvalidOperation as exc:
        raise AcceptanceError(f"independent decoder {name} exceeds target scale") from exc
    if normalized != number:
        raise AcceptanceError(f"independent decoder {name} changes at target scale")
    return normalized


def normalize_independent_frame(frame: Any, *, symbol: str = SYMBOL) -> list[dict[str, Any]]:
    """Normalize pinned AkShare output for comparison without claiming native precision."""
    columns = {str(column).casefold(): column for column in getattr(frame, "columns", ())}
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(columns):
        raise AcceptanceError("independent AkShare decoder schema is incomplete")
    rows: list[dict[str, Any]] = []
    previous: date | None = None
    for position, record in enumerate(frame.to_dict(orient="records")):
        trade_date = _parse_source_date(record[columns["date"]])
        if previous is not None and trade_date <= previous:
            raise AcceptanceError("independent AkShare source dates are not strictly increasing")
        previous = trade_date
        row: dict[str, Any] = {
            "SOURCE": SOURCE_NAME,
            "INDEX_CODE": symbol,
            "MARKET_TYPE": "sh",
            "TRADE_DATE": trade_date,
        }
        for name in ("open", "high", "low", "close", "volume"):
            row[name.upper()] = _decimal_at_scale(record[columns[name]], name=name.upper())
        if any(row[name] <= 0 for name in ("OPEN", "HIGH", "LOW", "CLOSE")):
            raise AcceptanceError(f"independent AkShare source row {position} has nonpositive OHLC")
        if row["HIGH"] < max(row["OPEN"], row["CLOSE"]) or row["LOW"] > min(
            row["OPEN"], row["CLOSE"]
        ):
            raise AcceptanceError(f"independent AkShare source row {position} has invalid OHLC")
        rows.append(row)
    if not rows:
        raise AcceptanceError("independent AkShare decoder returned no rows")
    return rows


class _CapturedResponse:
    def __init__(self, body: bytes, *, url: str):
        self.content = body
        self.text = body.decode("utf-8")
        self.encoding = "utf-8"
        self.url = url
        self.status_code = 200
        self.headers = {"Content-Type": "application/x-javascript"}

    def raise_for_status(self) -> None:
        return None


def decode_new_capture_with_pinned_akshare(
    capture: dict[str, Any], *, provider_function: Callable[..., Any] | None = None
) -> list[dict[str, Any]]:
    """Re-run the pinned AkShare decoder against the captured body with networking disabled.

    This is a separate decode of the same artifact, but it deliberately does not claim
    an independent JavaScript algorithm or source-native decimal precision.
    """
    body_path = Path(str(capture["artifact_path"]))
    body = body_path.read_bytes()
    if hashlib.sha256(body).hexdigest() != capture["artifact_id"]:
        raise AcceptanceError("pinned decoder input no longer matches the captured SHA256")
    import requests

    if provider_function is None:
        import akshare
        from akshare.index import cons as constants_module
        from akshare.index import index_stock_zh as provider_module
        from akshare.stock import cons as decoder_module

        from app.data_fetch.scripts.indexs.weekly import stock_zh_index_daily as producer

        fingerprints = producer._module_fingerprints(
            provider_module, decoder_module, constants_module
        )
        producer._validate_module_fingerprints(fingerprints)
        if akshare.__version__ != producer.EXPECTED_AKSHARE_VERSION:
            raise AcceptanceError("installed AkShare version differs from the reviewed decoder")
        expected_capture_fingerprints = {
            "akshare_version": akshare.__version__,
            "akshare_index_module_sha256": fingerprints["akshare_index_module_sha256"],
            "akshare_js_decoder_sha256": fingerprints["akshare_js_decoder_sha256"],
            "akshare_index_constants_sha256": fingerprints["akshare_index_constants_sha256"],
        }
        if any(capture.get(key) != value for key, value in expected_capture_fingerprints.items()):
            raise AcceptanceError("new capture fingerprints differ from the pinned decoder")
        provider_function = provider_module.stock_zh_index_daily

    expected_url = str(capture.get("source_url", ""))
    expected_parts = urlsplit(expected_url)
    requested: list[dict[str, Any]] = []
    original_get = requests.get

    def captured_get(url: str, *args: Any, **kwargs: Any) -> _CapturedResponse:
        request_url = str(url)
        params = kwargs.get("params")
        if (
            len(requested) != 0
            or request_url
            != f"{expected_parts.scheme}://{expected_parts.netloc}{expected_parts.path}"
            or params != {"d": "2020_2_4"}
        ):
            raise AcceptanceError("pinned AkShare decoder attempted an unexpected or extra request")
        requested.append({"url": request_url, "params": params})
        return _CapturedResponse(body, url=expected_url)

    requests.get = captured_get
    try:
        frame = provider_function(symbol=SYMBOL)
    finally:
        requests.get = original_get
    if len(requested) != 1:
        raise AcceptanceError(
            "pinned AkShare decoder did not consume exactly the captured response"
        )
    rows = normalize_independent_frame(frame, symbol=SYMBOL)
    requested_start = date.fromisoformat("1900-01-01")
    requested_end = date.fromisoformat("2026-10-20")
    if any(not requested_start <= row["TRADE_DATE"] <= requested_end for row in rows):
        raise AcceptanceError("pinned decoder returned a date outside the requested range")
    return rows


def _normalize_db_value(name: str, value: Any) -> Any:
    if name in DECIMAL_SCALES:
        return _decimal_at_scale(value, name=name)
    if name == "TRADE_DATE":
        return _parse_source_date(value)
    if name in {
        "SOURCE_RESPONSE_IDENTITY_VERIFIED",
        "SOURCE_HISTORY_COMPLETE",
        "SOURCE_INCEPTION_VERIFIED",
        "TRADING_CALENDAR_VERIFIED",
    }:
        if isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        raise AcceptanceError(f"warehouse {name} is not a boolean-like value")
    return value


def expected_comparable_row(decoder_row: dict[str, Any], capture: dict[str, Any]) -> dict[str, Any]:
    return {
        **decoder_row,
        "VOLUME_UNIT": "unknown",
        "ADJUSTMENT_BASIS": "unknown",
        "SOURCE_RESPONSE_IDENTITY_VERIFIED": True,
        "SOURCE_HISTORY_COMPLETE": False,
        "SOURCE_INCEPTION_VERIFIED": False,
        "TRADING_CALENDAR_VERIFIED": False,
        "DECODED_PRECISION": str(capture.get("decoded_precision")),
        "SOURCE_URL": capture.get("source_url"),
        "SOURCE_HTTP_STATUS": 200,
        "SOURCE_RESPONSE_BYTES": capture.get("artifact_bytes"),
        "SOURCE_RESPONSE_SHA256": capture.get("artifact_id"),
        "SOURCE_ARTIFACT_ID": capture.get("artifact_id"),
        "AKSHARE_VERSION": capture.get("akshare_version"),
        "AKSHARE_INDEX_MODULE_SHA256": capture.get("akshare_index_module_sha256"),
        "AKSHARE_JS_DECODER_SHA256": capture.get("akshare_js_decoder_sha256"),
        "AKSHARE_INDEX_CONSTANTS_SHA256": capture.get("akshare_index_constants_sha256"),
    }


def compare_source_rows_to_sql(
    *,
    decoder_rows: list[dict[str, Any]],
    warehouse_rows: list[dict[str, Any]],
    capture: dict[str, Any],
) -> dict[str, Any]:
    """Compare the full returned key sequence and deterministic columns at target precision."""
    expected_by_date = {
        row["TRADE_DATE"]: expected_comparable_row(row, capture) for row in decoder_rows
    }
    if len(expected_by_date) != len(decoder_rows):
        raise AcceptanceError("independent decoder returned duplicate trade dates")
    actual_by_date: dict[date, dict[str, Any]] = {}
    for row in warehouse_rows:
        date_value = _parse_source_date(_field(row, "TRADE_DATE"))
        if date_value in actual_by_date:
            raise AcceptanceError("canonical SQL returned duplicate source business keys")
        actual_by_date[date_value] = row

    expected_dates = set(expected_by_date)
    actual_dates = set(actual_by_date)
    missing_dates = sorted(expected_dates - actual_dates)
    extra_dates = sorted(actual_dates - expected_dates)
    diffs: list[dict[str, Any]] = []
    for trade_date in sorted(expected_dates & actual_dates):
        expected = expected_by_date[trade_date]
        actual = actual_by_date[trade_date]
        for column in COMPARE_COLUMNS:
            want = _normalize_db_value(column, expected.get(column))
            got = _normalize_db_value(column, _field(actual, column))
            if want != got:
                diffs.append(
                    {
                        "trade_date": trade_date.isoformat(),
                        "column": column,
                        "expected": str(want) if isinstance(want, Decimal) else want,
                        "actual": str(got) if isinstance(got, Decimal) else got,
                    }
                )
                if len(diffs) >= 100:
                    break
        if len(diffs) >= 100:
            break
    matched = not missing_dates and not extra_dates and not diffs
    return {
        "matched": matched,
        "source_row_count": len(decoder_rows),
        "warehouse_row_count": len(warehouse_rows),
        "source_key_count": len(expected_dates),
        "warehouse_key_count": len(actual_dates),
        "source_date_key_sha256": _date_key_hash(expected_dates),
        "warehouse_date_key_sha256": _date_key_hash(actual_dates),
        "source_first_date": min(expected_dates).isoformat() if expected_dates else None,
        "source_last_date": max(expected_dates).isoformat() if expected_dates else None,
        "warehouse_first_date": min(actual_dates).isoformat() if actual_dates else None,
        "warehouse_last_date": max(actual_dates).isoformat() if actual_dates else None,
        "missing_dates": [value.isoformat() for value in missing_dates[:100]],
        "extra_dates": [value.isoformat() for value in extra_dates[:100]],
        "value_diff_count_sampled": len(diffs),
        "value_diffs": diffs,
        "compared_columns": list(COMPARE_COLUMNS),
        "excluded_local_columns": sorted(LOCAL_ONLY_COLUMNS),
        "precision_contract": {
            "target": "MySQL DECIMAL(24,8) OHLC and DECIMAL(38,8) volume",
            "comparison": "exact after target-scale validation; no tolerance",
            "source": "pinned AkShare pandas numeric output; native decimal precision unverified",
        },
    }


def _date_key_hash(values: set[date]) -> str:
    payload = "\n".join(value.isoformat() for value in sorted(values)).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _calendar_audit_path() -> Path:
    return project_root() / CALENDAR_AUDIT_RELATIVE_PATH


def load_2026_calendar_candidates(
    audit_path: Path | None = None,
) -> tuple[set[date], dict[str, Any]]:
    """Load pinned SSE evidence and derive a bounded 2026 candidate date set.

    This validates a saved root audit file only. It does not fetch official pages or
    install a runtime calendar. The weekday-minus-holiday set ends on 2026-10-19 and
    is never treated as a source-retention or all-years completeness claim.
    """
    path = audit_path or _calendar_audit_path()
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError("pinned 2026 calendar audit is missing or unsafe")
    raw = path.read_bytes()
    audit_sha = hashlib.sha256(raw).hexdigest()
    if audit_sha != EXPECTED_2026_CALENDAR_AUDIT_SHA256:
        raise AcceptanceError("pinned 2026 calendar audit differs from the reviewed evidence")
    try:
        audit = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise AcceptanceError("pinned 2026 calendar audit is invalid JSON") from exc
    if not isinstance(audit, dict):
        raise AcceptanceError("pinned 2026 calendar audit is not an object")

    authority = audit.get("authority")
    publication = audit.get("publication_date_authority")
    required_flags = {
        "calendar_candidate_complete_for_all_years": False,
        "extraordinary_closure_independent_verification": False,
        "runtime_policy_deployed": False,
        "source_requests_by_this_offline_audit": 0,
        "business_writes": 0,
        "full_history_complete": False,
    }
    for key, expected in required_flags.items():
        actual = audit.get(key)
        if actual != expected or type(actual) is not type(expected):
            raise AcceptanceError("pinned calendar audit completeness or side-effect flags changed")
    if (
        not isinstance(authority, dict)
        or authority.get("actual_body_read") is not True
        or authority.get("published_date") != "2025-12-22"
        or not isinstance(authority.get("holiday_ranges"), list)
    ):
        raise AcceptanceError("pinned calendar audit lacks verified SSE holiday-body evidence")
    if (
        not isinstance(publication, dict)
        or publication.get("actual_body_read") is not True
        or publication.get("shanghai_composite_first_publication") != "1991-07-15"
        or publication.get("observed_Sina_source_start") != "1990-12-19"
        or publication.get("do_not_trim_prepublication_history") is not True
    ):
        raise AcceptanceError("pinned publication evidence no longer protects prepublication rows")

    closed_dates: set[date] = set()
    try:
        for bounds in authority["holiday_ranges"]:
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise ValueError("invalid holiday range")
            first, last = (date.fromisoformat(str(item)) for item in bounds)
            if last < first:
                raise ValueError("reversed holiday range")
            current = first
            while current <= last:
                closed_dates.add(current)
                current = date.fromordinal(current.toordinal() + 1)
        explicit_weekend_dates = {
            date.fromisoformat(str(value))
            for value in authority.get("additional_explicit_weekend_dates", [])
        }
    except (TypeError, ValueError) as exc:
        raise AcceptanceError("pinned SSE holiday ranges are malformed") from exc
    if any(value.weekday() < 5 for value in explicit_weekend_dates):
        raise AcceptanceError("pinned additional explicit closure is not a weekend date")

    candidates: set[date] = set()
    current = CALENDAR_CANDIDATE_START
    while current <= CALENDAR_CANDIDATE_END:
        if current.weekday() < 5 and current not in closed_dates:
            candidates.add(current)
        current = date.fromordinal(current.toordinal() + 1)
    if len(candidates) != 189 or audit.get("candidate_weekday_expected_count") != len(candidates):
        raise AcceptanceError("derived 2026 candidate sequence differs from the reviewed count")
    if (
        audit.get("source_2026_count") != len(candidates)
        or audit.get("candidate_matches_returned_source") is not True
        or audit.get("missing_in_source") != []
        or audit.get("source_only_dates") != []
        or audit.get("source_date_duplicates") != 0
        or audit.get("decoded_rows_sha256")
        != "29f3de5b0f353cb95ad2fb2bb39cd72f0e5a6c1e1d470a5b0964fb4ccd9d481a"
    ):
        raise AcceptanceError("pinned audit no longer records the reviewed 2026 sequence match")
    evidence = {
        "audit_path": str(path),
        "audit_sha256": audit_sha,
        "authority_url": authority.get("url"),
        "authority_body_read": True,
        "authority_published_date": authority.get("published_date"),
        "publication_authority_url": publication.get("url"),
        "publication_article_date": publication.get("article_date_displayed"),
        "publication_date": publication.get("shanghai_composite_first_publication"),
        "observed_source_start": publication.get("observed_Sina_source_start"),
        "do_not_trim_prepublication_history": True,
        "candidate_window": [
            CALENDAR_CANDIDATE_START.isoformat(),
            CALENDAR_CANDIDATE_END.isoformat(),
        ],
        "candidate_count": len(candidates),
        "historical_audit_sequence_match": True,
        "calendar_candidate_complete_for_all_years": False,
        "extraordinary_closure_independent_verification": False,
        "runtime_policy_deployed": False,
        "full_history_complete": False,
        "scope_note": "2026 weekday-minus-official-holiday candidate only through 2026-10-19; no inception, all-years, temporary-closure, or source-retention proof",
    }
    return candidates, evidence


def compare_2026_candidate_dates(
    rows: list[dict[str, Any]], candidates: set[date], *, row_source: str
) -> dict[str, Any]:
    """Compare one returned date set to the independently audited bounded candidates."""
    actual: set[date] = set()
    for row in rows:
        trade_date = _parse_source_date(_field(row, "TRADE_DATE"))
        if CALENDAR_CANDIDATE_START <= trade_date <= CALENDAR_CANDIDATE_END:
            actual.add(trade_date)
    missing = sorted(candidates - actual)
    extra = sorted(actual - candidates)
    return {
        "basis": row_source,
        "candidate_window": [
            CALENDAR_CANDIDATE_START.isoformat(),
            CALENDAR_CANDIDATE_END.isoformat(),
        ],
        "candidate_count": len(candidates),
        "observed_date_count": len(actual),
        "candidate_date_key_sha256": _date_key_hash(candidates),
        "observed_date_key_sha256": _date_key_hash(actual),
        "missing_candidate_dates": [value.isoformat() for value in missing],
        "extra_observed_dates": [value.isoformat() for value in extra],
        "matches_bounded_candidate": not missing and not extra,
        "calendar_verified": False,
        "full_history_complete": False,
    }


def calendar_candidate_comparison(
    *,
    source_rows: list[dict[str, Any]],
    warehouse_rows: list[dict[str, Any]],
    audit_path: Path | None = None,
) -> dict[str, Any]:
    candidates, evidence = load_2026_calendar_candidates(audit_path)
    return {
        "evidence": evidence,
        "source_rows": compare_2026_candidate_dates(
            source_rows,
            candidates,
            row_source="new returned source sequence decoded by pinned AkShare",
        ),
        "warehouse_rows": compare_2026_candidate_dates(
            warehouse_rows, candidates, row_source="fresh canonical SQL readback"
        ),
        "interpretation": "bounded independent date-set corroboration only; does not establish runtime calendar validity or all-history completeness",
    }


def _field(row: dict[str, Any], name: str) -> Any:
    if name in row:
        return row[name]
    wanted = name.casefold()
    for key, value in row.items():
        if str(key).casefold() == wanted:
            return value
    return None


def validate_execution_receipt(
    execution: dict[str, Any],
    intent: DispatchIdentity,
    *,
    source_row_count: int,
    capture: dict[str, Any],
) -> dict[str, Any]:
    """Require a real managed manual execution and its producer-level exact ack evidence."""
    errors: list[str] = []
    if execution.get("script_id") != SCRIPT_ID:
        errors.append("execution script_id mismatch")
    if execution.get("task_id") is not None:
        errors.append("execution unexpectedly used a scheduled task")
    if execution.get("operator_id") is not None:
        errors.append("execution unexpectedly has an operator")
    if str(execution.get("triggered_by", "")).casefold() != "manual":
        errors.append("execution was not manual")
    execution_id = str(execution.get("execution_id", ""))
    if not re.fullmatch(r"ak_exec_[0-9a-f]{12}", execution_id):
        errors.append("execution_id is not a persisted ak_exec_* identifier")
    if str(execution.get("status", "")).casefold() != "completed":
        errors.append("TaskExecution did not complete")
    params = execution.get("params")
    if not isinstance(params, dict):
        errors.append("TaskExecution parameters are missing")
    elif params != intent.parameters:
        errors.append("TaskExecution parameters differ from the exact one-time dispatch")
    result = execution.get("result")
    if not isinstance(result, dict):
        errors.append("TaskExecution result evidence is missing")
        result = {}
    if result.get("table_name") != TARGET_TABLE:
        errors.append("managed execution did not publish through the canonical producer target")
    if result.get("quality_status") != "partial" or result.get("source_complete") is not False:
        errors.append("execution must preserve partial/unknown full-history quality semantics")
    if capture.get("normalized_row_count") != source_row_count:
        errors.append("capture normalized row count differs from independent source decode")
    for count_name in ("source_row_count", "valid_row_count", "source_received_rows"):
        if type(result.get(count_name)) is not int or result.get(count_name) != source_row_count:
            errors.append(f"TaskExecution {count_name} does not match the decoded response")
    if result.get("source_expected_rows") is not None:
        errors.append("execution must not invent an independent source expected-row denominator")
    if result.get("source") != SOURCE_NAME:
        errors.append("TaskExecution source provenance is not Sina")
    raw_scope = result.get("source_scope")
    try:
        source_scope = json.loads(raw_scope) if isinstance(raw_scope, str) else None
    except ValueError:
        source_scope = None
    expected_scope = {
        "source": SOURCE_NAME,
        "symbol": SYMBOL,
        "requested_window": ["1900-01-01", "2026-10-20"],
        "returned_window": capture.get("returned_window"),
        "response_identity_status": "exact_symbol_assignment",
        "response_identity_verified": True,
        "response_wrapper_identifier": f"KLC_KL_{SYMBOL}",
        "decoded_precision": capture.get("decoded_precision"),
        "source_units": "unknown",
        "adjustment_basis": "unknown",
        "source_history_complete": False,
        "source_inception_verified": False,
        "calendar_verified": False,
        "response_sha256": capture.get("artifact_id"),
        "artifact_id": capture.get("artifact_id"),
    }
    if not isinstance(source_scope, dict):
        errors.append("TaskExecution source_scope is missing or invalid JSON")
    else:
        scope_diffs = [
            key for key, value in expected_scope.items() if source_scope.get(key) != value
        ]
        if scope_diffs:
            errors.append(
                "TaskExecution source_scope differs from the captured dispatch: "
                + ", ".join(scope_diffs)
            )
        if source_scope.get("source_history_complete") is True:
            errors.append("TaskExecution source_scope overstates history completeness")
    if result.get("calendar_verified") is True:
        errors.append("TaskExecution result overstates exchange-calendar verification")
    if (
        result.get("source_history_complete") is True
        or result.get("source_inception_verified") is True
    ):
        errors.append("TaskExecution overstates history or inception completeness")
    write_count = result.get("committed_write_count")
    raw_row_counts = result.get("committed_write_row_counts")
    expected_batches = math.ceil(source_row_count / EXPECTED_WRITER_BATCH_SIZE)
    if type(write_count) is not int or write_count != expected_batches:
        errors.append(
            "committed DML batch count differs from the reviewed writer batch-size contract"
        )
    if (
        not isinstance(raw_row_counts, list)
        or len(raw_row_counts) != expected_batches
        or any(type(value) is not int or value <= 0 for value in raw_row_counts)
    ):
        errors.append("committed writer batch rowcount evidence is incomplete or nonpositive")
    elif not source_row_count <= sum(raw_row_counts) <= 2 * source_row_count:
        errors.append("committed MySQL upsert rowcounts fall outside the insert/update bounds")
    publication_status = result.get("publication_status")
    if publication_status not in {"published", "committed"}:
        errors.append("execution did not report a positive committed publication")
    rows_before = execution.get("rows_before")
    rows_after = execution.get("rows_after")
    if type(rows_before) is not int or type(rows_after) is not int or rows_after < rows_before:
        errors.append("canonical table row-count receipt is missing or indicates data loss")
    if errors:
        return {
            "accepted": False,
            "status": "managed_receipt_invalid",
            "execution_id": execution_id or None,
            "errors": errors,
            "write_possible": True,
        }
    return {
        "accepted": True,
        "status": "managed_execution_completed_pending_independent_sql",
        "execution_id": execution_id,
        "producer_exact_ack_guard": "passed: producer raises unless save_data returns exactly decoded frame length",
        "source_row_count": source_row_count,
        "committed_dml_batch_count": write_count,
        "expected_dml_batch_count": expected_batches,
        "committed_mysql_cursor_rowcounts": raw_row_counts,
        "cursor_rowcount_sum": sum(raw_row_counts),
        "cursor_rowcount_semantics": "MySQL upsert affected-row counts can differ from input rows; exact source acknowledgement is producer save_data == len(frame) guard plus full SQL key/value reconciliation",
        "transaction_commit_instrumentation": "not separately exposed in TaskExecution; fenced committed-write witness and fresh SQL readback establish persisted rows",
        "canonical_table_rows_before": rows_before,
        "canonical_table_rows_after": rows_after,
        "write_possible": True,
    }


def classify_unknown_call(error: str, *, phase: str) -> dict[str, Any]:
    """Record a conservative outcome when a managed call or readback cannot be confirmed."""
    return {
        "status": "managed_outcome_unknown"
        if phase in {"managed", "commit"}
        else "readback_incomplete",
        "phase": phase,
        "error": error[:1000],
        "write_possible": True,
        "source_failed": False,
        "full_history_complete": False,
    }


def _ensure_private_run_directory(run_id: str) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise AcceptanceError("invalid acceptance run id")
    root = report_root()
    current = project_root()
    for part in ("var", "reports", "iteration203", "sina-index-managed-acceptance"):
        current = current / part
        if current.exists() and current.is_symlink():
            raise AcceptanceError("acceptance report path contains a symlink")
        current.mkdir(mode=0o700, exist_ok=True)
        if current != root:
            continue
    run_dir = root / run_id
    run_dir.mkdir(mode=0o700, exist_ok=False)
    os.chmod(run_dir, 0o700)
    return run_dir


def _safe_existing_run_directory(run_id: str) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise AcceptanceError("invalid acceptance run id")
    root = report_root()
    if root.is_symlink() or not root.is_dir():
        raise AcceptanceError("fixed acceptance report root is missing or unsafe")
    run_dir = root / run_id
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise AcceptanceError("acceptance run directory is missing or unsafe")
    if os.stat(run_dir).st_mode & 0o077:
        raise AcceptanceError("acceptance run directory is not private")
    return run_dir


def validate_dispatch_intent(intent: DispatchIdentity, *, run_id: str) -> list[str]:
    """Validate the worker receipt before it can authorize any scheduler call."""
    errors: list[str] = []
    if intent.run_id != run_id:
        errors.append("dispatch run id differs from the supervised worker id")
    if intent.script_id != SCRIPT_ID or intent.symbol != SYMBOL:
        errors.append("dispatch is not bound to the reviewed Sina index identity")
    if intent.start_date != START_DATE or intent.end_date != END_DATE:
        errors.append("dispatch window differs from the reviewed all-returned-history scope")
    if intent.mode != "backfill" or intent.task_id is not None or intent.operator_id is not None:
        errors.append("dispatch must be taskless/operatorless explicit backfill")
    if intent.triggered_by != "manual":
        errors.append("dispatch is not an explicit manual execution")
    if intent.scheduler_source != SOURCE_NAME:
        errors.append("dispatch scheduler source is not the reviewed Sina identity")
    expected_parameters = {
        "symbol": SYMBOL,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "source_timeout_seconds": SOURCE_TIMEOUT_SECONDS,
        "_ingest_mode": "backfill",
    }
    if intent.parameters != expected_parameters:
        errors.append("dispatch parameters differ from the fixed one-time scope")
    expected_period = f"manual:sina-index-history:{run_id}"
    if intent.period_key != expected_period:
        errors.append("dispatch period key is not unique to this run")
    expected_parameter_hash = _parameter_hash(expected_parameters)
    if intent.parameter_hash != expected_parameter_hash:
        errors.append("dispatch parameter hash differs from the fixed parameters")
    if intent.claim_key != _claim_key(
        SCRIPT_ID, intent.scheduler_source, expected_period, expected_parameter_hash
    ):
        errors.append("dispatch claim key does not bind the fixed scope and unique period")
    return errors


def _append_event(run_dir: Path, event: dict[str, Any]) -> None:
    path = run_dir / "events.jsonl"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "ab", closefd=True) as output:
            output.write(_canonical_json(event) + b"\n")
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        raise


def _write_exclusive_json(path: Path, value: Any) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb", closefd=True) as output:
        output.write(_canonical_json(value))
        output.flush()
        os.fsync(output.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    _write_exclusive_json(temporary, value)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _normalize_orm_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normalize_orm_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_orm_value(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


async def _read_management_snapshot(claim_key: str | None = None) -> dict[str, Any]:
    from sqlalchemy import func, select

    from app.db.database import async_session_maker
    from app.models.akshare_mgmt import AkshareTaskRunClaim, DataScript, ScheduledTask

    async with async_session_maker() as session:
        persistent_count = int(
            (await session.execute(select(func.count()).select_from(ScheduledTask))).scalar() or 0
        )
        registry_count = int(
            (await session.execute(select(func.count()).select_from(DataScript))).scalar() or 0
        )
        script_result = await session.execute(
            select(DataScript).where(DataScript.script_id == SCRIPT_ID)
        )
        script = script_result.scalar_one_or_none()
        task = await session.get(ScheduledTask, TASK_ID_TO_PROTECT)
        claim_exists = None
        if claim_key is not None:
            claim_exists = await session.get(AkshareTaskRunClaim, claim_key) is not None

        script_values = None
        if script is not None:
            script_values = {
                "script_id": script.script_id,
                "script_name": script.script_name,
                "category": script.category,
                "sub_category": script.sub_category,
                "frequency": _normalize_orm_value(script.frequency),
                "description": script.description,
                "source": script.source,
                "module_path": script.module_path,
                "function_name": script.function_name,
                "target_table": script.target_table,
                "dependencies": _normalize_orm_value(script.dependencies),
                "estimated_duration": script.estimated_duration,
                "timeout": script.timeout,
                "is_active": script.is_active,
                "is_custom": script.is_custom,
                "created_by": script.created_by,
                "updated_by": script.updated_by,
                "created_at": _normalize_orm_value(script.created_at),
                "updated_at": _normalize_orm_value(script.updated_at),
            }
        task_values = None
        if task is not None:
            task_values = {
                "id": task.id,
                "name": task.name,
                "script_id": task.script_id,
                "schedule_type": _normalize_orm_value(task.schedule_type),
                "schedule_expression": task.schedule_expression,
                "parameters": _normalize_orm_value(task.parameters),
                "is_active": task.is_active,
                "retry_on_failure": task.retry_on_failure,
                "max_retries": task.max_retries,
                "timeout": task.timeout,
                "last_execution_at": _normalize_orm_value(task.last_execution_at),
                "next_execution_at": _normalize_orm_value(task.next_execution_at),
                "created_at": _normalize_orm_value(task.created_at),
                "updated_at": _normalize_orm_value(task.updated_at),
            }
        return {
            "persistent_scheduled_task_count": persistent_count,
            "script_registry_count": registry_count,
            "script_registry_entry": script_values,
            "protected_task": task_values,
            "dispatch_claim_already_exists": claim_exists,
        }


async def _run_with_database_disposal(awaitable: Awaitable[_T]) -> _T:
    """Run one live async phase and dispose its lazily-created DB engine on that loop."""
    try:
        return await awaitable
    finally:
        # Import only for live phases; the default plan remains DB-module-free.
        from app.db import database

        engine = getattr(database, "_engine", None)
        if engine is not None:
            await engine.dispose()


def _quote_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise AcceptanceError("warehouse metadata returned an unsafe identifier")
    return f"`{value}`"


def _canonical_db_row(row: dict[str, Any]) -> bytes:
    normalized: dict[str, Any] = {}
    for key in sorted(row, key=lambda value: str(value).casefold()):
        value = row[key]
        if isinstance(value, (datetime, date)):
            normalized[str(key)] = value.isoformat()
        elif isinstance(value, Decimal):
            normalized[str(key)] = {"decimal": str(value)}
        elif isinstance(value, bytes):
            normalized[str(key)] = {
                "bytes_sha256": hashlib.sha256(value).hexdigest(),
                "bytes": len(value),
            }
        elif isinstance(value, float):
            if not math.isfinite(value):
                normalized[str(key)] = {"float": repr(value)}
            else:
                normalized[str(key)] = {"float": value.hex()}
        else:
            normalized[str(key)] = value
    return _canonical_json(normalized)


def _hash_table_query(cursor: Any, sql: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any]:
    cursor.execute(sql, parameters)
    digest = hashlib.sha256()
    count = 0
    for row in cursor:
        digest.update(_canonical_db_row(row))
        digest.update(b"\n")
        count += 1
    return {"row_count": count, "sha256": digest.hexdigest()}


def _connect_warehouse() -> Any:
    import pymysql
    from pymysql.cursors import SSDictCursor

    from app.data_fetch.configs.db_config import DB_CONFIG

    config = dict(DB_CONFIG)
    return pymysql.connect(
        **config,
        cursorclass=SSDictCursor,
        autocommit=True,
        connect_timeout=10,
        read_timeout=20,
        write_timeout=10,
    )


def _read_table_columns(cursor: Any, table: str) -> list[str]:
    cursor.execute(f"SHOW COLUMNS FROM {_quote_identifier(table)}")
    rows = cursor.fetchall()
    names = [str(row.get("Field") or row.get("field") or "") for row in rows]
    if not names or any(not re.fullmatch(r"[A-Za-z0-9_]+", name) for name in names):
        raise AcceptanceError(f"could not safely inspect table {table}")
    return names


def _order_clause(columns: list[str]) -> str:
    return ", ".join(_quote_identifier(column) for column in columns)


def _table_full_hash(cursor: Any, table: str) -> dict[str, Any]:
    columns = _read_table_columns(cursor, table)
    sql = f"SELECT * FROM {_quote_identifier(table)} ORDER BY {_order_clause(columns)}"
    return _hash_table_query(cursor, sql)


def _table_filtered_hash(
    cursor: Any, table: str, *, where: str, parameters: tuple[Any, ...]
) -> dict[str, Any]:
    columns = _read_table_columns(cursor, table)
    sql = (
        f"SELECT * FROM {_quote_identifier(table)} WHERE {where} ORDER BY {_order_clause(columns)}"
    )
    return _hash_table_query(cursor, sql, parameters)


def _read_current_symbol_rows(cursor: Any) -> list[dict[str, Any]]:
    cursor.execute(
        f"SELECT * FROM {_quote_identifier(TARGET_TABLE)} "
        "WHERE `SOURCE`=%s AND `INDEX_CODE`=%s ORDER BY `TRADE_DATE`",
        (SOURCE_NAME, SYMBOL),
    )
    return list(cursor.fetchall())


def _warehouse_protection_snapshot(*, include_target_rows: bool = False) -> dict[str, Any]:
    connection = _connect_warehouse()
    try:
        with connection.cursor() as cursor:
            legacy = _table_full_hash(cursor, LEGACY_TABLE)
            other_symbols = _table_filtered_hash(
                cursor,
                TARGET_TABLE,
                where="(`SOURCE` IS NULL OR `SOURCE` <> %s OR `INDEX_CODE` IS NULL OR `INDEX_CODE` <> %s)",
                parameters=(SOURCE_NAME, SYMBOL),
            )
            target_before = _table_filtered_hash(
                cursor,
                TARGET_TABLE,
                where="`SOURCE`=%s AND `INDEX_CODE`=%s",
                parameters=(SOURCE_NAME, SYMBOL),
            )
            snapshot: dict[str, Any] = {
                "legacy_table": legacy,
                "canonical_other_symbols": other_symbols,
                "canonical_target_symbol_before": target_before,
            }
            if include_target_rows:
                snapshot["canonical_target_symbol_rows"] = _read_current_symbol_rows(cursor)
            return snapshot
    finally:
        connection.close()


def _producer_source_sha256() -> str:
    path = (
        backend_root()
        / "app"
        / "data_fetch"
        / "scripts"
        / "indexs"
        / "weekly"
        / "stock_zh_index_daily.py"
    )
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError("reviewed local Sina producer source is missing or a symlink")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _writer_source_sha256() -> str:
    path = backend_root() / "app" / "data_fetch" / "core" / "mysql_base.py"
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError("legacy MySQL writer source is missing or a symlink")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _database_source_sha256() -> str:
    path = backend_root() / "app" / "data_fetch" / "core" / "database.py"
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError("reviewed database base source is missing or a symlink")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_canonical_rows() -> list[dict[str, Any]]:
    connection = _connect_warehouse()
    try:
        with connection.cursor() as cursor:
            return _read_current_symbol_rows(cursor)
    finally:
        connection.close()


async def _read_execution_and_claim(
    intent: DispatchIdentity, execution_id: str | None
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.database import async_session_maker
    from app.models.akshare_mgmt import AkshareTaskRunClaim, TaskExecution

    async with async_session_maker() as session:
        claim = await session.get(AkshareTaskRunClaim, intent.claim_key)
        execution = None
        if execution_id:
            result = await session.execute(
                select(TaskExecution).where(TaskExecution.execution_id == execution_id)
            )
            execution = result.scalar_one_or_none()
        claim_values = None
        if claim is not None:
            claim_values = {
                "claim_key": claim.claim_key,
                "task_id": claim.task_id,
                "script_id": claim.script_id,
                "source": claim.source,
                "period_key": claim.period_key,
                "parameter_hash": claim.parameter_hash,
                "status": claim.status,
                "execution_id": claim.execution_id,
                "attempt_count": claim.attempt_count,
                "last_error": claim.last_error,
                "completed_at": _normalize_orm_value(claim.completed_at),
            }
        execution_values = None
        if execution is not None:
            execution_values = {
                "execution_id": execution.execution_id,
                "script_id": execution.script_id,
                "task_id": execution.task_id,
                "operator_id": execution.operator_id,
                "triggered_by": _normalize_orm_value(execution.triggered_by),
                "status": _normalize_orm_value(execution.status),
                "params": _normalize_orm_value(execution.params),
                "result": _normalize_orm_value(execution.result),
                "rows_before": execution.rows_before,
                "rows_after": execution.rows_after,
                "error_message": execution.error_message,
                "start_time": _normalize_orm_value(execution.start_time),
                "end_time": _normalize_orm_value(execution.end_time),
            }
        return {"claim": claim_values, "execution": execution_values}


def _expected_capture_metadata(verified: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "decoded_precision": verified.get("decoded_precision"),
        "akshare_version": verified.get("akshare_version"),
        "akshare_index_module_sha256": verified.get("akshare_index_module_sha256"),
        "akshare_js_decoder_sha256": verified.get("akshare_js_decoder_sha256"),
        "akshare_index_constants_sha256": verified.get("akshare_index_constants_sha256"),
        "capture_source_url": verified.get("capture_source_url"),
        "artifact_bytes": raw.get("artifact_bytes"),
    }


def _load_verified_capture_metadata(capture: dict[str, Any]) -> dict[str, Any]:
    verified_path = Path(capture["manifests"]["verified"])
    raw_path = Path(capture["manifests"]["raw"])
    return _expected_capture_metadata(_load_manifest(verified_path), _load_manifest(raw_path))


def evaluate_acceptance(
    *,
    intent: DispatchIdentity,
    execution: dict[str, Any] | None,
    claim: dict[str, Any] | None,
    capture: dict[str, Any] | None,
    source_rows: list[dict[str, Any]] | None,
    warehouse_rows: list[dict[str, Any]] | None,
    protection_before: dict[str, Any],
    protection_after: dict[str, Any],
) -> dict[str, Any]:
    """Purely reconcile the returned sequence, managed receipt, SQL, and protections."""
    protection = compare_protection_snapshots(protection_before, protection_after)
    if execution is None:
        managed = classify_unknown_call("no persisted TaskExecution could be read", phase="managed")
    elif capture is None or source_rows is None or warehouse_rows is None:
        managed = classify_unknown_call(
            "source capture or SQL readback is unavailable", phase="commit"
        )
    else:
        receipt = validate_execution_receipt(
            execution,
            intent,
            source_row_count=len(source_rows),
            capture=capture,
        )
        sql = compare_source_rows_to_sql(
            decoder_rows=source_rows,
            warehouse_rows=warehouse_rows,
            capture=capture,
        )
        claim_ok = bool(
            isinstance(claim, dict)
            and claim.get("claim_key") == intent.claim_key
            and claim.get("script_id") == SCRIPT_ID
            and claim.get("source") == intent.scheduler_source
            and claim.get("period_key") == intent.period_key
            and claim.get("parameter_hash") == intent.parameter_hash
            and claim.get("task_id") is None
            and claim.get("status") == "completed"
            and claim.get("execution_id") == execution.get("execution_id")
        )
        managed = {
            **receipt,
            "claim_reconciled": claim_ok,
            "claim": claim,
            "sql_comparison": sql,
            "status": (
                "verified_full_returned_sequence"
                if receipt.get("accepted") and claim_ok and sql["matched"]
                else "acceptance_verification_failed"
            ),
            "write_possible": True,
            "source_history_complete": False,
            "source_inception_verified": False,
            "calendar_verified": False,
        }
    if not protection["unchanged"]:
        managed["status"] = "protection_state_changed"
        managed["protection_write_possible"] = True
    managed["protected_state"] = protection
    managed["full_history_complete"] = False
    managed["history_completeness_claim"] = "not_proven"
    return managed


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _prepare_live_dispatch(
    run_id: str,
) -> tuple[dict[str, Any], DispatchIdentity, dict[str, Any]]:
    run_dir = report_root() / run_id
    start = _utc_now()
    calendar_preflight: dict[str, Any] | None = None
    try:
        _, calendar_preflight = load_2026_calendar_candidates()
    except AcceptanceError as exc:
        calendar_error = str(exc)
    else:
        calendar_error = None
    management = await _read_management_snapshot()
    warehouse = _warehouse_protection_snapshot()
    before = {**management, **warehouse}
    before["producer_source_sha256"] = _producer_source_sha256()
    before["writer_source_sha256"] = _writer_source_sha256()
    before["database_source_sha256"] = _database_source_sha256()
    issues = validate_protection_snapshot(before)
    if calendar_error:
        issues.append(f"bounded 2026 calendar-evidence preflight failed: {calendar_error}")
    else:
        before["calendar_candidate_audit"] = calendar_preflight
    if management.get("dispatch_claim_already_exists") is not None:
        issues.append("new claim key must be checked after identity construction")
    source = (
        management.get("script_registry_entry", {}).get("source")
        if isinstance(management.get("script_registry_entry"), dict)
        else None
    )
    if source != SOURCE_NAME:
        issues.append("registry scheduler source label is not the reviewed Sina identity")
    if issues:
        _append_event(
            run_dir,
            {
                "event": "preflight_failed",
                "at_utc": _utc_now(),
                "issues": issues,
                "source_or_write_possible": False,
            },
        )
        raise AcceptanceError("read-only safety preflight failed: " + "; ".join(issues))
    intent = new_dispatch_identity(scheduler_source=source, run_id=run_id)
    claim_snapshot = await _read_management_snapshot(intent.claim_key)
    if claim_snapshot.get("dispatch_claim_already_exists") is not False:
        _append_event(
            run_dir,
            {"event": "preexisting_claim", "at_utc": _utc_now(), "claim_key": intent.claim_key},
        )
        raise AcceptanceError("unique dispatch claim key already exists; refusing possible replay")
    before["dispatch_claim_already_exists"] = False
    before["preflight_started_at_utc"] = start
    before["dispatch_started_at_utc"] = _utc_now()
    _append_event(
        run_dir,
        {
            "event": "dispatch_identity_persisted",
            "at_utc": _utc_now(),
            "intent": asdict(intent),
            "protection_before": before,
            "source_calls_or_writes_after_marker": True,
        },
    )
    _write_exclusive_json(
        run_dir / "dispatch.json", {"intent": asdict(intent), "protection_before": before}
    )
    return before, intent, {"dispatch_started_at_utc": before["dispatch_started_at_utc"]}


async def _run_managed(intent: DispatchIdentity) -> dict[str, Any]:
    from app.db.database import async_session_maker
    from app.models.akshare_mgmt import TriggeredBy
    from app.services.akshare.scheduler import get_akshare_scheduler

    scheduler = get_akshare_scheduler()
    async with async_session_maker() as session:
        execution = await scheduler.run_script_now(
            intent.script_id,
            parameters=dict(intent.parameters),
            operator_id=None,
            db=session,
            task_id=None,
            triggered_by=TriggeredBy.MANUAL,
            timeout_seconds=MANAGED_TIMEOUT_SECONDS,
            _claim_key=intent.claim_key,
            _period_key=intent.period_key,
        )
        return {
            "execution_id": execution.execution_id,
            "script_id": execution.script_id,
            "task_id": execution.task_id,
            "operator_id": execution.operator_id,
            "triggered_by": getattr(execution.triggered_by, "value", execution.triggered_by),
            "status": getattr(execution.status, "value", execution.status),
            "params": _normalize_orm_value(execution.params),
            "result": _normalize_orm_value(execution.result),
            "rows_before": execution.rows_before,
            "rows_after": execution.rows_after,
            "error_message": execution.error_message,
            "start_time": _normalize_orm_value(execution.start_time),
            "end_time": _normalize_orm_value(execution.end_time),
        }


async def _worker_main(run_id: str) -> int:
    if not RUN_ID_RE.fullmatch(run_id):
        raise AcceptanceError("invalid worker run id")
    run_dir = _safe_existing_run_directory(run_id)
    dispatch_path = run_dir / "dispatch.json"
    if dispatch_path.is_symlink() or not dispatch_path.is_file():
        raise AcceptanceError("dispatch receipt is missing or unsafe")
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    intent_data = dispatch.get("intent")
    before = dispatch.get("protection_before")
    if not isinstance(intent_data, dict) or not isinstance(before, dict):
        raise AcceptanceError("dispatch receipt is malformed")
    try:
        intent = DispatchIdentity(**intent_data)
    except TypeError as exc:
        raise AcceptanceError("dispatch identity schema is malformed") from exc
    intent_errors = validate_dispatch_intent(intent, run_id=run_id)
    if intent_errors:
        raise AcceptanceError(
            "worker dispatch identity failed validation: " + "; ".join(intent_errors)
        )
    protection_errors = validate_protection_snapshot(before)
    if protection_errors:
        raise AcceptanceError(
            "worker preflight receipt failed validation: " + "; ".join(protection_errors)
        )
    calendar_preflight = before.get("calendar_candidate_audit")
    _, calendar_evidence = load_2026_calendar_candidates()
    if not isinstance(calendar_preflight, dict) or calendar_preflight.get(
        "audit_sha256"
    ) != calendar_evidence.get("audit_sha256"):
        raise AcceptanceError("worker calendar-evidence receipt differs from reviewed audit")
    worker_started = _utc_now()
    artifact_root = project_root() / "var" / "source-artifacts" / "sina-index-daily"
    inventory_before = capture_inventory(artifact_root)
    _append_event(run_dir, {"event": "managed_worker_started", "at_utc": worker_started})
    execution: dict[str, Any] | None = None
    call_error: str | None = None
    try:
        execution = await asyncio.wait_for(
            _run_managed(intent),
            timeout=min(
                MANAGED_TIMEOUT_SECONDS, CHILD_HARD_SECONDS - POST_DISPATCH_READBACK_RESERVE_SECONDS
            ),
        )
        _append_event(
            run_dir,
            {
                "event": "managed_call_returned",
                "at_utc": _utc_now(),
                "execution_id": execution.get("execution_id"),
                "status": execution.get("status"),
            },
        )
    except BaseException as exc:
        call_error = f"{type(exc).__name__}: {exc}"
        _append_event(
            run_dir,
            {
                "event": "managed_call_not_confirmed",
                "at_utc": _utc_now(),
                "error": call_error[:1000],
                "write_possible": True,
            },
        )
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise

    execution_id = execution.get("execution_id") if execution else None
    try:
        claim_execution = await _read_execution_and_claim(intent, execution_id)
    except Exception as exc:
        claim_execution = {"claim": None, "execution": None}
        _append_event(
            run_dir,
            {
                "event": "managed_readback_error",
                "at_utc": _utc_now(),
                "error": f"{type(exc).__name__}: {exc}"[:1000],
            },
        )
    # If run_script_now raised, recover its persisted execution_id from the claim.
    if execution_id is None and claim_execution.get("claim"):
        execution_id = claim_execution["claim"].get("execution_id")
        if execution_id:
            claim_execution = await _read_execution_and_claim(intent, execution_id)
    execution_readback = claim_execution.get("execution")
    if execution is None:
        execution = execution_readback

    capture: dict[str, Any] | None = None
    source_rows: list[dict[str, Any]] | None = None
    warehouse_rows: list[dict[str, Any]] | None = None
    calendar_check: dict[str, Any] | None = None
    capture_error: str | None = None
    try:
        dispatch_event_time = str(before.get("dispatch_started_at_utc"))
        capture = inspect_new_capture(
            artifact_root=artifact_root,
            before_inventory=inventory_before,
            intent=intent,
            dispatch_started_at_utc=dispatch_event_time,
        )
        metadata = _load_verified_capture_metadata(capture)
        capture.update(metadata)
        source_rows = decode_new_capture_with_pinned_akshare(capture)
        if len(source_rows) != capture.get("normalized_row_count"):
            raise AcceptanceError(
                "independent pinned decoder row count differs from producer manifest"
            )
        decoded_window = [
            min(row["TRADE_DATE"] for row in source_rows).isoformat(),
            max(row["TRADE_DATE"] for row in source_rows).isoformat(),
        ]
        if capture.get("returned_window") != decoded_window:
            raise AcceptanceError("independent decoder dates differ from capture returned_window")
        warehouse_rows = _read_canonical_rows()
        calendar_check = calendar_candidate_comparison(
            source_rows=source_rows,
            warehouse_rows=warehouse_rows,
        )
        _append_event(
            run_dir,
            {
                "event": "new_capture_and_sql_readback",
                "at_utc": _utc_now(),
                "capture": capture,
                "source_rows": len(source_rows),
                "warehouse_rows": len(warehouse_rows),
                "calendar_candidate_comparison": calendar_check,
            },
        )
    except Exception as exc:
        capture_error = f"{type(exc).__name__}: {exc}"
        _append_event(
            run_dir,
            {
                "event": "capture_or_sql_readback_incomplete",
                "at_utc": _utc_now(),
                "error": capture_error[:1000],
                "write_possible": True,
            },
        )

    try:
        management_after = await _read_management_snapshot(intent.claim_key)
        warehouse_after = _warehouse_protection_snapshot()
        after = {
            **management_after,
            **warehouse_after,
            "producer_source_sha256": _producer_source_sha256(),
            "writer_source_sha256": _writer_source_sha256(),
            "database_source_sha256": _database_source_sha256(),
        }
    except Exception as exc:
        after = {"readback_error": f"{type(exc).__name__}: {exc}"}
    report = evaluate_acceptance(
        intent=intent,
        execution=execution,
        claim=claim_execution.get("claim"),
        capture=capture,
        source_rows=source_rows,
        warehouse_rows=warehouse_rows,
        protection_before=before,
        protection_after=after,
    )
    report["calendar_candidate_comparison"] = calendar_check
    if call_error:
        report["managed_call_error"] = call_error
        report["source_failed"] = False
        report["write_possible"] = True
        if report.get("status") == "verified_full_returned_sequence":
            report["status"] = "returned_sequence_verified_but_call_outcome_was_unknown"
    if capture_error:
        report["capture_or_readback_error"] = capture_error
        report["write_possible"] = True
        if report.get("status") == "verified_full_returned_sequence":
            report["status"] = "capture_or_readback_failed"
    report.update(
        {
            "run_id": run_id,
            "intent": asdict(intent),
            "managed_execution": execution,
            "dispatch_claim": claim_execution.get("claim"),
            "budgets_seconds": {
                "managed_timeout": MANAGED_TIMEOUT_SECONDS,
                "child_hard_limit": CHILD_HARD_SECONDS,
                "outer_process_group_limit": OUTER_HARD_SECONDS,
                "post_dispatch_readback_reserve": POST_DISPATCH_READBACK_RESERVE_SECONDS,
            },
            "source_request_count_claim": "one request by the frozen producer's enforced call_count==1 invariant; no separate wire counter in TaskExecution",
            "producer_source_sha256": EXPECTED_PRODUCER_SOURCE_SHA256,
            "source_history_complete": False,
            "source_inception_verified": False,
            "calendar_verified": False,
            "source_units": "unknown",
            "adjustment_basis": "unknown",
            "native_decimal_precision_verified": False,
            "independent_js_algorithm": False,
            "previous_raw_probe_reused_as_new_fetch": False,
            "completed_at_utc": _utc_now(),
        }
    )
    _atomic_write_json(run_dir / "summary.json", report)
    _append_event(
        run_dir,
        {
            "event": "worker_finished",
            "at_utc": _utc_now(),
            "status": report.get("status"),
            "write_possible": report.get("write_possible", True),
        },
    )
    return 0 if report.get("status") == "verified_full_returned_sequence" else 3


def _kill_child_group(
    child: subprocess.Popen[Any], *, deadline_monotonic: float
) -> dict[str, bool]:
    state = {"term_sent": False, "kill_sent": False, "child_reaped": child.poll() is not None}
    if child.poll() is not None:
        return state
    state["term_sent"] = True
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=max(0.0, min(TERM_GRACE_SECONDS, deadline_monotonic - time.monotonic())))
    except subprocess.TimeoutExpired:
        state["kill_sent"] = True
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            child.wait(
                timeout=max(0.0, min(KILL_GRACE_SECONDS, deadline_monotonic - time.monotonic()))
            )
        except subprocess.TimeoutExpired:
            pass
    state["child_reaped"] = child.poll() is not None
    return state


def _launch_supervised_apply() -> int:
    outer_deadline = time.monotonic() + OUTER_HARD_SECONDS
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + f"-{uuid.uuid4().hex[:16]}"
    run_dir = _ensure_private_run_directory(run_id)
    _append_event(
        run_dir,
        {
            "event": "run_created",
            "at_utc": _utc_now(),
            "mode": "explicit_apply",
            "network_or_write_possible": False,
            "period_key_and_claim_key": "pending read-only preflight",
        },
    )
    preflight_remaining = max(0.0, outer_deadline - time.monotonic())
    try:
        before, intent, _ = asyncio.run(
            _run_with_database_disposal(
                asyncio.wait_for(_prepare_live_dispatch(run_id), timeout=preflight_remaining)
            )
        )
    except TimeoutError:
        _append_event(
            run_dir,
            {
                "event": "read_only_preflight_budget_exhausted",
                "at_utc": _utc_now(),
                "status": "deferred_before_dispatch",
                "source_failed": False,
                "write_possible": False,
            },
        )
        return 3
    # _prepare_live_dispatch persists the dispatch identity before this child can call the scheduler.
    wait_budget = min(
        CHILD_HARD_SECONDS,
        max(0.0, outer_deadline - time.monotonic() - TERM_GRACE_SECONDS - KILL_GRACE_SECONDS),
    )
    if wait_budget <= 0:
        _append_event(
            run_dir,
            {
                "event": "managed_budget_exhausted_before_child_launch",
                "at_utc": _utc_now(),
                "status": "deferred_before_dispatch",
                "source_failed": False,
                "write_possible": False,
                "claim_key": intent.claim_key,
            },
        )
        return 3
    stdout_path = run_dir / "worker.stdout.log"
    stderr_path = run_dir / "worker.stderr.log"
    command = [sys.executable, str(Path(__file__).resolve()), "--_worker-run-id", run_id]
    _append_event(
        run_dir,
        {
            "event": "supervised_child_dispatch",
            "at_utc": _utc_now(),
            "command": command,
            "outer_hard_seconds": OUTER_HARD_SECONDS,
            "child_wait_budget_seconds": wait_budget,
            "source_or_write_possible": True,
        },
    )
    timed_out = False
    supervision: dict[str, Any] = {"term_sent": False, "kill_sent": False}
    try:
        with stdout_path.open("xb") as stdout_stream, stderr_path.open("xb") as stderr_stream:
            os.chmod(stdout_path, 0o600)
            os.chmod(stderr_path, 0o600)
            child = subprocess.Popen(
                command,
                cwd=backend_root(),
                stdin=subprocess.DEVNULL,
                stdout=stdout_stream,
                stderr=stderr_stream,
                start_new_session=True,
            )
            try:
                child.wait(timeout=wait_budget)
            except subprocess.TimeoutExpired:
                timed_out = True
                supervision = _kill_child_group(child, deadline_monotonic=outer_deadline)
    except OSError as exc:
        _append_event(
            run_dir,
            {
                "event": "child_launch_failed",
                "at_utc": _utc_now(),
                "error": f"{type(exc).__name__}: {exc}"[:1000],
                "write_possible": False,
            },
        )
        return 2
    if timed_out:
        _append_event(
            run_dir,
            {
                "event": "outer_process_group_timeout",
                "at_utc": _utc_now(),
                "status": "managed_outcome_unknown",
                "write_possible": True,
                "source_failed": False,
                "supervision": supervision,
                "outer_elapsed_seconds": round(
                    OUTER_HARD_SECONDS - max(0.0, outer_deadline - time.monotonic()), 3
                ),
                "claim_key": intent.claim_key,
                "execution_status": "unknown until independent readback",
            },
        )
        return 3
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        _append_event(
            run_dir,
            {
                "event": "worker_summary_missing",
                "at_utc": _utc_now(),
                "status": "managed_outcome_unknown",
                "write_possible": True,
                "source_failed": False,
            },
        )
        return 3
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        _append_event(
            run_dir,
            {
                "event": "worker_summary_unreadable",
                "at_utc": _utc_now(),
                "error": f"{type(exc).__name__}: {exc}"[:1000],
                "status": "managed_outcome_unknown",
                "write_possible": True,
            },
        )
        return 3
    if not isinstance(summary, dict):
        return 3
    _append_event(
        run_dir,
        {
            "event": "supervised_child_returned",
            "at_utc": _utc_now(),
            "worker_status": summary.get("status"),
            "run_id": run_id,
        },
    )
    return 0 if summary.get("status") == "verified_full_returned_sequence" else 3


def _main(argv: list[str] | None = None) -> int:
    backend_path = str(backend_root())
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="dispatch one explicit managed run")
    parser.add_argument("--_worker-run-id", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._worker_run_id:
        return asyncio.run(_run_with_database_disposal(_worker_main(args._worker_run_id)))
    if args.apply:
        return _launch_supervised_apply()
    print(json.dumps(build_plan(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
