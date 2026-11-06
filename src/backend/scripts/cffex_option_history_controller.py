"""Plan and verify one bounded CFFEX option-history archive month at a time.

The default mode is an offline, SQL-free plan. ``--audit`` adds read-only
warehouse inventory. ``--apply`` is deliberately limited to one month and
uses the registered producer through the shared managed coordinator and write
fence. A month receives a verified archive-snapshot receipt only after the
actual response body is durably captured, parsed, and compared against a fresh
full-month SQL read. This does not prove contract lifecycle or exchange
calendar completeness.

Pure core (month math, hash-chained ledger, selection, digests, comparison,
capture accounting, artifact writing) is separated from the exchange/warehouse
adapters (CFFEX provider, MySQL reader, managed scheduler dispatch). The
adapters import their heavy modules lazily so the core stays testable without
the live warehouse or the exchange endpoint.

Exact per-contract identity is the stored object; the controller never
synthesizes a continuous/front-month series into the per-contract table and
never infers an expiry or settlement price the archive did not publish.
Missing official OHLC/settle fields stay NULL (no zero-fill, no carry-forward).

Examples (from ``src/backend``)::

    python scripts/cffex_option_history_controller.py
    python scripts/cffex_option_history_controller.py --audit --output /tmp/plan.json
    timeout --signal=TERM --kill-after=5s 200s \
        python scripts/cffex_option_history_controller.py --apply --max-minutes 3

The controller's total apply budget is soft. Use an outer process supervisor for
a hard stop: blocking SQL, Python executor shutdown, or an already-running
managed worker thread cannot be forcibly stopped by the in-process timeout.

The initial 201912 candidate month is based on observed archive evidence. It
is not represented as the beginning of the exchange's history or any option's
listing date.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import fcntl
import hashlib
import json
import os
import re
import sys
import threading
import time
from calendar import monthrange
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_ROOT.parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

SOURCE = "cffex"
SOURCE_TIME_ZONE = "Asia/Shanghai"
SOURCE_URL_TEMPLATE = "http://www.cffex.com.cn/sj/historysj/{month}/zip/{month}.zip"

SCRIPT_ID = "cffex_option_daily_history"
SCRIPT_SOURCE = "cffex"
SCRIPT_MODULE = "app.data_fetch.scripts.options.daily.cffex_option_daily_history"
SCRIPT_FUNCTION = "main"
TABLE_NAME = "OPTION_CFFEX_DAILY_HISTORY"
CANDIDATE_START_MONTH = "201912"

DEFAULT_SOURCE_TIMEOUT_SECONDS = 90
MAX_SOURCE_TIMEOUT_SECONDS = 90
MAX_APPLY_SECONDS = 180
MIN_APPLY_SECONDS = 120
RECOMMENDED_OUTER_TIMEOUT_SECONDS = 200
MANAGED_RECEIPT_RESERVE_SECONDS = 30
OUTER_WAIT_RESERVE_SECONDS = 5
FAILURE_COOLDOWN = timedelta(hours=24)
PROGRESS_SCHEMA_VERSION = 1
GENESIS_SHA256 = "0" * 64
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024

_MONTH_RE = re.compile(r"^\d{6}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_URL_AUTH_RE = re.compile(r"(?i)(https?://)[^/@\s]+:[^/@\s]+@")
_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|token|api[_-]?key|secret|authorization)(\s*[:=]\s*)[^\s,;&]+"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_CAPTURE_LOCK = threading.RLock()

UTC8 = timezone(timedelta(hours=8))

DEFAULT_REPORT_DIR = (
    _REPO_ROOT / "var" / "reports" / "iteration203" / "cffex-option-history-controller"
)
DEFAULT_PROGRESS_PATH = DEFAULT_REPORT_DIR / "progress.jsonl"
DEFAULT_ARTIFACT_DIR = DEFAULT_REPORT_DIR / "snapshots"

TABLE_FIELDS = (
    "SOURCE",
    "MARKET",
    "OPTION_PRODUCT",
    "SOURCE_SYMBOL",
    "CONTRACT_MONTH",
    "OPTION_SIDE",
    "STRIKE_PRICE",
    "TRADE_DATE",
    "OPEN_PRICE",
    "HIGH_PRICE",
    "LOW_PRICE",
    "CLOSE_PRICE",
    "SETTLEMENT_PRICE",
    "PREVIOUS_SETTLEMENT_PRICE",
    "CHANGE_1",
    "CHANGE_2",
    "VOLUME",
    "AMOUNT_SOURCE_VALUE",
    "AMOUNT_UNIT",
    "OPEN_INTEREST",
    "OPEN_INTEREST_CHANGE",
    "SOURCE_DELTA",
    "SOURCE_DELTA_RAW",
    "SOURCE_ROW_JSON",
    "SOURCE_ROW_SHA256",
    "SOURCE_URL",
    "SOURCE_ARCHIVE_MONTH",
    "SOURCE_ARCHIVE_SHA256",
    "SOURCE_ARCHIVE_MEMBER_COUNT",
    "SOURCE_MEMBER_NAME",
    "SOURCE_MEMBER_SHA256",
    "SOURCE_MEMBER_OPTION_ROW_COUNT",
    "OBSERVED_AT",
    "OBSERVED_AT_TIME_ZONE",
    "SOURCE_SCOPE",
    "SOURCE_SEQUENCE_COMPLETE",
    "SOURCE_COMPLETE",
    "QUALITY_STATUS",
)
# OBSERVED_AT is a local observation timestamp, not a source field; it is never
# compared and never allowed to masquerade as an exchange-published value.
COMPARE_FIELDS = tuple(field for field in TABLE_FIELDS if field != "OBSERVED_AT")
DECIMAL_FIELDS = frozenset(
    {
        "AMOUNT_SOURCE_VALUE",
        "CHANGE_1",
        "CHANGE_2",
        "CLOSE_PRICE",
        "HIGH_PRICE",
        "LOW_PRICE",
        "OPEN_PRICE",
        "PREVIOUS_SETTLEMENT_PRICE",
        "SETTLEMENT_PRICE",
        "SOURCE_DELTA",
        "STRIKE_PRICE",
    }
)
INTEGER_FIELDS = frozenset(
    {
        "OPEN_INTEREST",
        "OPEN_INTEREST_CHANGE",
        "SOURCE_ARCHIVE_MEMBER_COUNT",
        "SOURCE_COMPLETE",
        "SOURCE_MEMBER_OPTION_ROW_COUNT",
        "SOURCE_SEQUENCE_COMPLETE",
        "VOLUME",
    }
)


class WarehouseReader(Protocol):
    """Read-only operations needed for one exact archive-month work unit."""

    def __enter__(self) -> WarehouseReader: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None: ...

    def check_schema(self) -> Mapping[str, Any]: ...

    def read_month(self, month: str) -> list[dict[str, Any]]: ...

    def read_overview(self) -> Mapping[str, Any]: ...


class MySQLOptionHistoryReader:
    """SELECT-only reader for the predeployed exact option-history table."""

    def __init__(self) -> None:
        self._connection: Any | None = None

    def __enter__(self) -> MySQLOptionHistoryReader:
        import mysql.connector

        from app.data_fetch.configs.db_config import DB_CONFIG

        config = dict(DB_CONFIG)
        config["connection_timeout"] = min(int(config.get("connection_timeout", 10)), 10)
        self._connection = mysql.connector.connect(**config, **{"autocommit": True})
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _cursor(self) -> Any:
        if self._connection is None:
            raise RuntimeError("warehouse reader is not open")
        return self._connection.cursor(dictionary=True)

    def check_schema(self) -> Mapping[str, Any]:
        """Check the exact deployed contract without executing DDL."""
        import importlib.util

        planner_path = _BACKEND_ROOT / "scripts/deploy_cffex_option_history_schema.py"
        spec = importlib.util.spec_from_file_location("cffex_option_schema_plan", planner_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load schema planner at {planner_path}")
        planner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(planner)
        cursor = self._cursor()
        try:
            result = planner.inspect_plan(cursor)
            if result.get("statements"):
                raise RuntimeError(f"{TABLE_NAME} is not predeployed; no runtime DDL is allowed")
            return result
        finally:
            cursor.close()

    def read_month(self, month: str) -> list[dict[str, Any]]:
        start, end = month_bounds(month)
        cursor = self._cursor()
        try:
            fields = ", ".join(f"`{field}`" for field in TABLE_FIELDS)
            cursor.execute(
                f"SELECT {fields} FROM `{TABLE_NAME}`"
                " WHERE `SOURCE` = %s AND `TRADE_DATE` >= %s AND `TRADE_DATE` <= %s"
                " ORDER BY `TRADE_DATE`, `SOURCE_SYMBOL`",
                (SOURCE, start, end),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def read_overview(self) -> Mapping[str, Any]:
        cursor = self._cursor()
        try:
            cursor.execute(
                "SELECT `SOURCE_ARCHIVE_MONTH` AS archive_month, COUNT(*) AS row_count,"
                " MIN(`TRADE_DATE`) AS first_trade_date, MAX(`TRADE_DATE`) AS last_trade_date,"
                " COUNT(DISTINCT `SOURCE_SYMBOL`) AS distinct_symbols"
                f" FROM `{TABLE_NAME}` WHERE `SOURCE` = %s"
                " GROUP BY `SOURCE_ARCHIVE_MONTH` ORDER BY `SOURCE_ARCHIVE_MONTH`",
                (SOURCE,),
            )
            rows = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                f"SELECT COUNT(*) AS row_count FROM `{TABLE_NAME}` WHERE `SOURCE` = %s",
                (SOURCE,),
            )
            count_row = cursor.fetchone() or {}
            return {
                "table": TABLE_NAME,
                "total_rows": count_row.get("row_count", 0),
                "months": rows,
            }
        finally:
            cursor.close()


def shanghai_now() -> datetime:
    """Return the current timezone-aware market-zone time."""
    return datetime.now(ZoneInfo(SOURCE_TIME_ZONE))


def normalize_month(value: str) -> str:
    """Validate a YYYYMM archive identifier."""
    month = str(value)
    if not _MONTH_RE.fullmatch(month):
        raise ValueError("month must be YYYYMM")
    number, year = int(month[4:]), int(month[:4])
    if not 1 <= number <= 12 or year < 1900:
        raise ValueError("month must identify a valid month")
    return month


def month_bounds(month: str) -> tuple[date, date]:
    """Return the inclusive calendar-day bounds for one archive month."""
    month = normalize_month(month)
    number, year = int(month[4:]), int(month[:4])
    return date(year, number, 1), date(year, number, monthrange(year, number)[1])


def next_month(month: str) -> str:
    """Return the immediately following YYYYMM month."""
    month = normalize_month(month)
    number, year = int(month[4:]), int(month[:4])
    if number == 12:
        return f"{year + 1:04d}01"
    return f"{year:04d}{number + 1:02d}"


def month_sequence(start_month: str, end_month: str) -> list[str]:
    """Return every archive-month candidate within an inclusive bound."""
    start, end = normalize_month(start_month), normalize_month(end_month)
    if end < start:
        raise ValueError("end_month must be on or after start_month")
    result: list[str] = []
    value = start
    while value <= end:
        result.append(value)
        value = next_month(value)
    return result


def current_shanghai_month(now: datetime | None = None) -> str:
    """Resolve the live month only from an explicit/real aware Shanghai clock."""
    instant = shanghai_now() if now is None else now
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("controller clock must be timezone-aware")
    local = instant.astimezone(ZoneInfo(SOURCE_TIME_ZONE))
    return f"{local.year:04d}{local.month:02d}"


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
        allow_nan=False,
    ).encode("utf-8")


def _budget_semantics(seconds: int) -> dict[str, Any]:
    return {
        "kind": "soft_total_wall_budget",
        "seconds": seconds,
        "includes_best_effort": [
            "apply_one_month schema and preimage SQL reads",
            "managed dispatch and bounded asyncio wait",
            "source request, response capture, parse, and postimage SQL verification",
            "progress/report writes",
        ],
        "excludes_or_cannot_hard_stop": [
            "CLI startup, initial progress read, and apply-mode overview/schema SQL"
            " before apply_one_month",
            "blocking SQL calls that do not return to the controller",
            "already-running managed worker threads and asyncio default-executor shutdown",
        ],
        "outer_process_hard_stop_required": True,
        "recommended_outer_timeout_seconds": RECOMMENDED_OUTER_TIMEOUT_SECONDS,
    }


def _safe_text(value: Any, limit: int) -> str:
    """Redact accidental credential-shaped values before persisting a report."""
    text = str(value)
    text = _URL_AUTH_RE.sub(r"\1[redacted]@", text)
    text = _SECRET_RE.sub(r"\1\2[redacted]", text)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    return text[:limit]


def _event_sha256(record: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key != "event_sha256"}
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def read_progress(path: Path) -> list[dict[str, Any]]:
    """Read and validate the append-only hash-chained progress ledger."""
    if not path.exists():
        return []
    previous_hash = GENESIS_SHA256
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed progress JSONL line {line_number}") from exc
        if not isinstance(record, dict) or record.get("schema_version") != PROGRESS_SCHEMA_VERSION:
            raise ValueError(f"progress JSONL line {line_number} has an unsupported schema")
        try:
            normalize_month(str(record.get("month", "")))
        except ValueError as exc:
            raise ValueError(f"progress JSONL line {line_number} has an invalid month") from exc
        if record.get("previous_event_sha256") != previous_hash:
            raise ValueError(f"progress JSONL line {line_number} breaks the hash chain")
        expected = _event_sha256(record)
        if record.get("event_sha256") != expected:
            raise ValueError(f"progress JSONL line {line_number} has an invalid event hash")
        if parse_aware_timestamp(record.get("recorded_at_utc")) is None:
            raise ValueError(f"progress JSONL line {line_number} has an invalid timestamp")
        previous_hash = expected
        events.append(record)
    return events


def append_progress(path: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically append one durable, hash-chained event and fsync it."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    with path.open("a+", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0)
        existing = stream.read()
        previous_hash = GENESIS_SHA256
        if existing:
            events = read_progress(path)
            previous_hash = events[-1]["event_sha256"] if events else GENESIS_SHA256
        event = dict(record)
        event.setdefault("schema_version", PROGRESS_SCHEMA_VERSION)
        event.setdefault("event_id", uuid4().hex)
        event.setdefault("recorded_at_utc", datetime.now(UTC).isoformat(timespec="microseconds"))
        normalize_month(str(event.get("month", "")))
        if parse_aware_timestamp(event.get("recorded_at_utc")) is None:
            raise ValueError("recorded_at_utc must be a timezone-aware ISO timestamp")
        event["previous_event_sha256"] = previous_hash
        event["event_sha256"] = _event_sha256(event)
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps(event, ensure_ascii=False, default=_json_default, allow_nan=False))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    return event


def parse_aware_timestamp(value: Any) -> datetime | None:
    """Parse an ISO timestamp only when it includes an explicit timezone."""
    if not isinstance(value, str):
        return None
    candidate = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def latest_event_by_month(events: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """Return the last ledger event for each month."""
    latest: dict[str, Mapping[str, Any]] = {}
    for event in events:
        month = str(event.get("month", ""))
        if month:
            latest[month] = event
    return latest


def _latest_cursor_month(events: Sequence[Mapping[str, Any]]) -> str | None:
    for event in reversed(events):
        if event.get("status") == "attempt_started":
            return str(event["month"])
    return None


def _is_cooling_down(event: Mapping[str, Any] | None, now: datetime) -> bool:
    if not event:
        return False
    status = event.get("status")
    if status == "attempt_started":
        attempted = parse_aware_timestamp(event.get("recorded_at_utc"))
    elif status in {
        "managed_outcome_unknown",
        "managed_failed",
        "preflight_failed",
        "source_failed",
        "verification_failed",
        "source_invalid",
    }:
        attempted = parse_aware_timestamp(event.get("recorded_at_utc"))
    else:
        return False
    if attempted is None:
        return True
    instant = now.astimezone(UTC)
    return instant < attempted + FAILURE_COOLDOWN


def select_next_month(
    *,
    start_month: str,
    end_month: str,
    current_month: str,
    events: Sequence[Mapping[str, Any]],
    now: datetime,
) -> tuple[str | None, dict[str, Any]]:
    """Fairly choose one unverified month while allowing current-month refresh."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("selection clock must be timezone-aware")
    months = month_sequence(start_month, end_month)
    current = normalize_month(current_month)
    latest = latest_event_by_month(events)
    verified = {
        month
        for month, event in latest.items()
        if event.get("status") == "verified_source_archive_snapshot"
    }
    cursor = _latest_cursor_month(events)
    order = list(months)
    if cursor in months:
        start_at = (months.index(cursor) + 1) % len(months)
        order = months[start_at:] + months[:start_at]
    deferred: list[dict[str, Any]] = []
    for month in order:
        if month != current and month in verified:
            deferred.append({"month": month, "status": "verified_archive_snapshot_recorded"})
            continue
        event = latest.get(month)
        if _is_cooling_down(event, now):
            deferred.append(
                {
                    "month": month,
                    "status": (
                        "deferred_failure_cooldown"
                        if event and event.get("status") != "attempt_started"
                        else "deferred_unresolved_attempt"
                    ),
                    "previous_status": event.get("status") if event else None,
                }
            )
            continue
        return (
            month,
            {
                "selected_month": month,
                "selection_reason": (
                    "current_month_refresh_due"
                    if month == current
                    else "next_unverified_month_after_fairness_cursor"
                ),
                "fairness_cursor_month": cursor,
                "verified_month_count": len(verified),
                "deferred": deferred,
                "source_lifecycle": "unknown",
                "candidate_start_is_inception": False,
            },
        )
    return (
        None,
        {
            "selected_month": None,
            "selection_reason": "no_eligible_month_before_current_month_refresh_fallback",
            "fairness_cursor_month": cursor,
            "verified_month_count": len(verified),
            "deferred": deferred,
            "source_lifecycle": "unknown",
            "candidate_start_is_inception": False,
        },
    )


def build_plan(
    *,
    now: datetime | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
    start_month: str,
    end_month: str | None = None,
    warehouse_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an offline plan, optionally attaching explicitly requested SQL audit."""
    instant = shanghai_now() if now is None else now
    current = current_shanghai_month(instant)
    end = normalize_month(end_month) if end_month else current
    if end > current:
        end = current
    start = normalize_month(start_month)
    if start < CANDIDATE_START_MONTH:
        raise ValueError(f"start_month cannot precede candidate month {CANDIDATE_START_MONTH}")
    if end < start:
        raise ValueError("end_month must be on or after start_month")
    records = list(events or [])
    selected, decision = select_next_month(
        start_month=start,
        end_month=end,
        current_month=current,
        events=records,
        now=instant,
    )
    latest = latest_event_by_month(records)
    months: list[dict[str, Any]] = []
    warehouse_by_month = {
        str(row.get("archive_month")): row
        for row in (warehouse_audit or {}).get("months", [])
        if isinstance(row, Mapping) and row.get("archive_month")
    }
    for month in month_sequence(start, end):
        event = latest.get(month)
        month_state = "pending_candidate"
        if month == current:
            month_state = "refresh_candidate_current_month"
        elif event and event.get("status") == "verified_source_archive_snapshot":
            month_state = "verified_archive_snapshot_calendar_unknown"
        elif _is_cooling_down(event, instant):
            month_state = "cooldown_or_outcome_unknown"
        row = {
            "month": month,
            "month_start": month_bounds(month)[0].isoformat(),
            "month_end": month_bounds(month)[1].isoformat(),
            "plan_state": month_state,
            "latest_progress_status": event.get("status") if event else None,
            "archive_snapshot_verified": bool(
                event and event.get("status") == "verified_source_archive_snapshot"
            ),
            "exchange_calendar_coverage": "unknown",
            "contract_lifecycle_coverage": "unknown",
        }
        if month in warehouse_by_month:
            row["warehouse_audit"] = dict(warehouse_by_month[month])
        months.append(row)
    plan = {
        "schema_version": PROGRESS_SCHEMA_VERSION,
        "generated_at": instant.isoformat(timespec="seconds"),
        "timezone": SOURCE_TIME_ZONE,
        "mode": "read_only_plan",
        "script_id": SCRIPT_ID,
        "source": SOURCE,
        "table": TABLE_NAME,
        "candidate_start_month": start,
        "candidate_start_basis": (
            "observed archive candidate only; not verified inception/listing"
        ),
        "end_month": end,
        "current_month": current,
        "months": months,
        "selected_next_month": selected,
        "selection": decision,
        "progress_path": str(DEFAULT_PROGRESS_PATH),
        "source_completeness": False,
        "calendar_completeness": "unknown",
        "lifecycle_completeness": "unknown",
        "amount_unit": "unknown",
        "greek_semantics": "literal Delta only; no additional Greeks inferred",
        "execution_budget": _budget_semantics(MAX_APPLY_SECONDS),
        "audit_mode": "explicit_read_only_sql"
        if warehouse_audit is not None
        else "not_requested_db_free",
        "warehouse_audit": dict(warehouse_audit) if warehouse_audit is not None else None,
    }
    return plan


def _normalize_scalar(field: str, value: Any) -> Any:
    if value is None:
        # Normalized NULL stays NULL: never zero-filled, never carried forward.
        return None
    if field in DECIMAL_FIELDS:
        try:
            parsed = Decimal(str(value))
        except Exception as exc:
            raise ValueError(f"SQL {field} is not a decimal: {value!r}") from exc
        if not parsed.is_finite():
            raise ValueError(f"SQL {field} is not finite: {value!r}")
        if parsed.is_zero():
            return "0"
        canonical = format(parsed, "f")
        if "." in canonical:
            canonical = canonical.rstrip("0").rstrip(".")
        return canonical
    if field in INTEGER_FIELDS:
        parsed_int = int(value)
        if Decimal(str(value)) != parsed_int:
            raise ValueError(f"SQL {field} is not an integer: {value!r}")
        return parsed_int
    if field == "TRADE_DATE":
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, date):
            return value.isoformat()
        return date.fromisoformat(str(value)).isoformat()
    if field == "SOURCE_ROW_JSON" and not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _normalized_record(row: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    missing = set(fields) - set(row)
    if missing:
        raise ValueError("row is missing source fields: " + ", ".join(sorted(missing)))
    return {field: _normalize_scalar(field, row.get(field)) for field in fields}


def _rows_digest(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> str:
    normalized = [_normalized_record(row, fields) for row in rows]
    normalized.sort(key=lambda row: (str(row.get("TRADE_DATE")), str(row.get("SOURCE_SYMBOL"))))
    return hashlib.sha256(_canonical_bytes(normalized)).hexdigest()


def compare_source_rows_to_sql(
    source_rows: Sequence[Mapping[str, Any]],
    sql_rows: Sequence[Mapping[str, Any]],
    *,
    month: str,
) -> dict[str, Any]:
    """Compare exact month keys and producer source fields against fresh SQL."""
    month = normalize_month(month)
    source_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    sql_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    source_duplicates: list[tuple[str, str, str]] = []
    sql_duplicates: list[tuple[str, str, str]] = []
    for raw_row in source_rows:
        row = _normalized_record(raw_row, COMPARE_FIELDS)
        key = (str(row["SOURCE"]), str(row["SOURCE_SYMBOL"]), str(row["TRADE_DATE"]))
        trade_month = str(row["TRADE_DATE"])[:7].replace("-", "")
        if row["SOURCE_ARCHIVE_MONTH"] != month and trade_month != month:
            raise ValueError(f"source row escaped requested month {month}: {key!r}")
        if key in source_by_key:
            source_duplicates.append(key)
        source_by_key[key] = row
    for raw_row in sql_rows:
        row = _normalized_record(raw_row, COMPARE_FIELDS)
        key = (str(row["SOURCE"]), str(row["SOURCE_SYMBOL"]), str(row["TRADE_DATE"]))
        trade_month = str(row["TRADE_DATE"])[:7].replace("-", "")
        if row["SOURCE_ARCHIVE_MONTH"] != month and trade_month != month:
            raise ValueError(f"SQL row escaped requested month {month}: {key!r}")
        if key in sql_by_key:
            sql_duplicates.append(key)
        sql_by_key[key] = row
    source_keys = set(source_by_key)
    sql_keys = set(sql_by_key)
    missing = sorted(source_keys - sql_keys)
    warehouse_only = sorted(sql_keys - source_keys)
    mismatches: list[dict[str, Any]] = []
    for key in sorted(source_keys & sql_keys):
        for field in COMPARE_FIELDS:
            if source_by_key[key][field] != sql_by_key[key][field]:
                mismatches.append(
                    {
                        "key": key,
                        "field": field,
                        "source": source_by_key[key][field],
                        "sql": sql_by_key[key][field],
                    }
                )
    policy_errors: list[str] = []
    for rows, label in ((source_by_key.values(), "source"), (sql_by_key.values(), "sql")):
        for row in rows:
            if row["SOURCE"] != SOURCE or row["MARKET"] != "CFFEX":
                policy_errors.append(f"{label}_identity_mismatch")
                continue
            if row["AMOUNT_UNIT"] != "unknown":
                policy_errors.append(f"{label}_amount_unit_must_remain_unknown")
                continue
            if row["SOURCE_SEQUENCE_COMPLETE"] != 1 or row["SOURCE_COMPLETE"] != 0:
                policy_errors.append(f"{label}_completeness_flags_invalid")
                continue
            if row["QUALITY_STATUS"] != "partial":
                policy_errors.append(f"{label}_quality_status_invalid")
                continue
            if row["OBSERVED_AT_TIME_ZONE"] != SOURCE_TIME_ZONE:
                policy_errors.append(f"{label}_observation_timezone_invalid")
    return {
        "month": month,
        "source_key_count": len(source_keys),
        "sql_key_count": len(sql_keys),
        "source_duplicate_keys": [list(key) for key in source_duplicates],
        "sql_duplicate_keys": [list(key) for key in sql_duplicates],
        "missing_in_sql": [list(key) for key in missing],
        "sql_only_keys": [list(key) for key in warehouse_only],
        "field_mismatch_count": len(mismatches),
        "field_mismatches": mismatches[:50],
        "policy_errors": sorted(set(policy_errors)),
        "source_fields_sha256": _rows_digest(source_rows, COMPARE_FIELDS),
        "sql_fields_sha256": _rows_digest(sql_rows, COMPARE_FIELDS),
        "compared_fields": list(COMPARE_FIELDS),
        "observation_time_comparison": (
            "excluded; local observation timestamp is not a source field"
        ),
        "matched": not (
            source_duplicates
            or sql_duplicates
            or missing
            or warehouse_only
            or mismatches
            or policy_errors
        )
        and bool(source_keys),
    }


def _validate_final_url(url: str, month: str) -> bool:
    """Accept only the exact CFFEX monthly archive URL or its documented host redirect."""
    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"www.cffex.com.cn", "cffex.com.cn"}
        and parsed.username is None
        and parsed.password is None
        and parsed.path == f"/sj/historysj/{month}/zip/{month}.zip"
        and not parsed.query
        and not parsed.fragment
    )


def _redact_url(url: str) -> str:
    """Remove credentials and query values from a URL before persisting it."""
    parsed = urlparse(url)
    host = parsed.hostname or "unknown-host"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    query = "?[redacted]" if parsed.query else ""
    fragment = "#[redacted]" if parsed.fragment else ""
    return f"{parsed.scheme}://{host}{parsed.path}{query}{fragment}"


class WireCapture:
    """Capture the exact response-body chunks consumed by the real provider."""

    def __init__(
        self,
        *,
        month: str,
        directory: Path,
        run_id: str,
        as_of_date: date | None = None,
    ) -> None:
        self.month = normalize_month(month)
        self.directory = directory
        self.run_id = run_id
        self.as_of_date = as_of_date
        self.expected_url = SOURCE_URL_TEMPLATE.format(month=self.month)
        self.request_count = 0
        self.requested_url: str | None = None
        self.final_url: str | None = None
        self.status_code: int | None = None
        self.response_headers: dict[str, Any] = {}
        self.redirect_chain: list[dict[str, Any]] = []
        self.body_complete = False
        self.body_path: Path | None = None
        self.body_bytes = 0
        self.body_sha256: str | None = None
        self.capture_error: str | None = None
        self._buffer = bytearray()
        self._stream_finished = False
        self._manifest_path: Path | None = None
        self._lock = threading.RLock()

    def _safe_url(self, url: str) -> bool:
        parsed = urlparse(url)
        expected = urlparse(self.expected_url)
        return (
            parsed.scheme == expected.scheme
            and parsed.hostname == expected.hostname
            and parsed.username is None
            and parsed.password is None
            and parsed.path == expected.path
            and not parsed.query
            and not parsed.fragment
        )

    def begin_request(self, url: str) -> None:
        with self._lock:
            self.request_count += 1
            self.requested_url = url
            if self.request_count != 1 or not self._safe_url(url):
                self.capture_error = "request_count_or_exact_month_url_violation"
                raise RuntimeError("CFFEX controller permits one exact-month archive GET only")

    def response_started(self, response: Any) -> None:
        with self._lock:
            self.status_code = int(getattr(response, "status_code", 0) or 0)
            raw_final_url = str(getattr(response, "url", self.requested_url))
            self.final_url = _redact_url(raw_final_url)
            if not _validate_final_url(raw_final_url, self.month):
                self.capture_error = "unexpected_final_url"
            headers = getattr(response, "headers", {})
            if isinstance(headers, Mapping):
                for name in (
                    "Content-Type",
                    "Content-Length",
                    "Content-Encoding",
                    "Date",
                    "Last-Modified",
                    "ETag",
                ):
                    value = headers.get(name)
                    if value is not None:
                        self.response_headers[name.casefold()] = _safe_text(value, 300)
            history = getattr(response, "history", ()) or ()
            for item in history:
                item_url = str(getattr(item, "url", ""))
                allowed = _validate_final_url(item_url, self.month)
                self.redirect_chain.append(
                    {
                        "status_code": int(getattr(item, "status_code", 0) or 0),
                        "url": _redact_url(item_url),
                        "allowed_cffex_month_url": allowed,
                    }
                )
                if not allowed:
                    self.capture_error = "redirect_chain_contains_unexpected_url"

    def add_chunk(self, chunk: bytes) -> None:
        with self._lock:
            if len(self._buffer) + len(chunk) > MAX_ARCHIVE_BYTES:
                self.capture_error = "captured_body_exceeds_archive_size_bound"
                remaining = max(0, MAX_ARCHIVE_BYTES - len(self._buffer))
                self._buffer.extend(chunk[:remaining])
                return
            self._buffer.extend(chunk)

    def finish_stream(self, complete: bool) -> None:
        with self._lock:
            if self._stream_finished:
                return
            self._stream_finished = True
            self.body_complete = bool(complete) and self.capture_error is None
            body = bytes(self._buffer)
            self.body_bytes = len(body)
            self.body_sha256 = hashlib.sha256(body).hexdigest() if body else None
            if body:
                suffix = ".zip" if self.body_complete else ".partial"
                self.body_path = self.directory / f"source-response{suffix}"
                try:
                    _write_new_private_file(self.body_path, body)
                except Exception as exc:
                    self.capture_error = _safe_text(
                        f"archive_artifact_write_failed:{type(exc).__name__}:{exc}", 1000
                    )
                    self.body_path = None
                    self.body_complete = False

    def record_error(self, exc: BaseException) -> None:
        with self._lock:
            if self.capture_error is None:
                self.capture_error = _safe_text(f"{type(exc).__name__}: {exc}", 1000)

    def transport_is_verifiable(self) -> bool:
        return (
            self.request_count == 1
            and self.requested_url == self.expected_url
            and self.status_code == 200
            and self.final_url is not None
            and _validate_final_url(self.final_url, self.month)
            and self.body_complete
            and self.body_path is not None
            and self.body_sha256 is not None
            and self.capture_error is None
        )

    def finalize(self) -> dict[str, Any]:
        """Persist a protected capture manifest, including partial/error state."""
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.directory.chmod(0o700)
        except OSError:
            pass
        if not self._stream_finished and self._buffer:
            self.finish_stream(False)
        manifest = {
            "schema_version": 1,
            "run_id": self.run_id,
            "month": self.month,
            "controller_as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "expected_url": self.expected_url,
            "request_count": self.request_count,
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "response_headers": self.response_headers,
            "redirect_chain": self.redirect_chain,
            "body_complete": self.body_complete,
            "body_bytes": self.body_bytes,
            "body_sha256": self.body_sha256,
            "body_path": str(self.body_path) if self.body_path else None,
            "capture_error": self.capture_error,
            "transport_verifiable": self.transport_is_verifiable(),
            "recording_semantics": (
                "same real iter_content bytes delivered to the existing strict parser"
            ),
        }
        self._manifest_path = self.directory / "wire-capture.json"
        manifest_bytes = _canonical_bytes(manifest) + b"\n"
        _write_new_private_file(self._manifest_path, manifest_bytes)
        manifest["manifest_path"] = str(self._manifest_path)
        manifest["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        return manifest


def _write_new_private_file(path: Path, content: bytes) -> None:
    """Create a unique 0600 artifact without overwriting an earlier capture."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


class RecordingResponse:
    """Transparent response wrapper that copies bytes without changing iteration."""

    def __init__(self, response: Any, capture: WireCapture) -> None:
        self._response = response
        self._capture = capture
        self._capture.response_started(response)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)

    def raise_for_status(self) -> None:
        try:
            self._response.raise_for_status()
        except BaseException as exc:
            self._capture.record_error(exc)
            raise

    def iter_content(self, chunk_size: int = 1, *args: Any, **kwargs: Any) -> Iterable[bytes]:
        completed = False
        try:
            for chunk in self._response.iter_content(chunk_size, *args, **kwargs):
                if not chunk:
                    continue
                exact_chunk = bytes(chunk)
                self._capture.add_chunk(exact_chunk)
                yield chunk
            completed = True
        except BaseException as exc:
            self._capture.record_error(exc)
            raise
        finally:
            self._capture.finish_stream(completed)

    def close(self) -> None:
        self._response.close()


class RecordingSession:
    """Provider-scoped session proxy over a real requests.Session."""

    def __init__(self, capture: WireCapture, session_factory: Callable[[], Any] | None = None):
        if session_factory is None:
            import importlib

            requests_module = importlib.import_module("requests")
            session_factory = requests_module.Session
        self._capture = capture
        self._session = session_factory()

    def get(self, url: str, *args: Any, **kwargs: Any) -> RecordingResponse:
        self._capture.begin_request(str(url))
        try:
            response = self._session.get(url, *args, **kwargs)
        except BaseException as exc:
            self._capture.record_error(exc)
            raise
        return RecordingResponse(response, self._capture)

    def close(self) -> None:
        self._session.close()


def _provider_symbols() -> tuple[Any, ...]:
    """Lazily bind the frozen provider parser (never a second implementation)."""
    from app.data_fetch.providers.cffex_option_history_source import (  # noqa: F401
        CffexOptionSourceError,
        normalize_date,
        parse_monthly_archive,
    )

    return CffexOptionSourceError, normalize_date, parse_monthly_archive


class ProviderCapturePatch(AbstractContextManager["ProviderCapturePatch"]):
    """Temporarily route only the producer's provider call through a recorder."""

    def __init__(
        self,
        capture: WireCapture,
        producer_module: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.capture = capture
        self.producer_module = producer_module
        self.session_factory = session_factory
        self.original: Any | None = None
        self._retained = False

    def __enter__(self) -> ProviderCapturePatch:
        _CAPTURE_LOCK.acquire()
        if self.producer_module is None:
            import importlib

            self.producer_module = importlib.import_module(SCRIPT_MODULE)
        self.original = self.producer_module.fetch_cffex_option_history
        original = self.original

        def recorded_fetch(start_date: Any, end_date: Any, **kwargs: Any) -> Any:
            if "session" in kwargs:
                self.capture.record_error(RuntimeError("producer passed an unreviewed session"))
                raise RuntimeError("controller requires its own real-session recorder")
            _, normalize_date, _ = _provider_symbols()
            requested_start = normalize_date(start_date)
            requested_end = normalize_date(end_date)
            expected_start, expected_end = month_bounds(self.capture.month)
            if (requested_start, requested_end) != (expected_start, expected_end):
                self.capture.record_error(RuntimeError("producer requested a non-month date range"))
                raise RuntimeError(
                    "CFFEX managed request must cover exactly one full archive month"
                )
            session = RecordingSession(self.capture, session_factory=self.session_factory)
            try:
                records = original(start_date, end_date, session=session, **kwargs)
                _reject_future_source_dates(records, self.capture.as_of_date)
                return records
            except Exception as exc:
                self.capture.record_error(exc)
                raise
            finally:
                session.close()

        self.producer_module.fetch_cffex_option_history = recorded_fetch
        return self

    def retain_until_process_exit(self) -> None:
        """Keep capture active if a timed-out managed worker may still be running."""
        self._retained = True
        atexit.register(self.restore)

    def restore(self) -> None:
        if self.original is not None and self.producer_module is not None:
            self.producer_module.fetch_cffex_option_history = self.original
            self.original = None
            _CAPTURE_LOCK.release()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        if not self._retained:
            self.restore()


def _safe_execution_summary(execution: Any) -> dict[str, Any]:
    """Extract only bounded, noncredential managed-execution fields."""
    if isinstance(execution, Mapping):
        raw = dict(execution)
    else:
        raw = {
            key: getattr(execution, key, None)
            for key in ("execution_id", "status", "error_message", "result")
        }
    status = raw.get("status")
    status_text = str(getattr(status, "value", status or "unknown")).casefold()
    result = raw.get("result")
    if not isinstance(result, Mapping):
        result = {}
    return {
        "execution_id": raw.get("execution_id"),
        "status": status_text,
        "error_message": _safe_text(str(raw.get("error_message") or ""), 500) or None,
        "result": {
            key: result.get(key)
            for key in (
                "run_mode",
                "row_count",
                "rows_before",
                "rows_after",
                "rows_delta",
                "table_name",
                "quality_status",
                "source_complete",
                "valid_row_count",
                "source_row_count",
                "source_scope",
                "source_note",
                "committed_write_count",
            )
            if key in result
        },
    }


def _reject_future_source_dates(records: Any, as_of_date: date | None) -> None:
    """Fail before producer save if the monthly source contains dates beyond its frozen as-of."""
    if as_of_date is None:
        return None
    if isinstance(records, Sequence) and not isinstance(records, (str, bytes, bytearray)):
        pass
    else:
        error, _, _ = _provider_symbols()
        raise error("CFFEX source result cannot be checked against controller as-of")
    _, normalize_date, _ = _provider_symbols()
    for index, row in enumerate(records):
        if not isinstance(row, Mapping) or "TRADE_DATE" not in row:
            error, _, _ = _provider_symbols()
            raise error(f"CFFEX source row {index} has no checkable TRADE_DATE")
        try:
            trade_date = normalize_date(row["TRADE_DATE"])
        except (TypeError, ValueError) as exc:
            error, _, _ = _provider_symbols()
            raise error(f"CFFEX source row {index} has an invalid TRADE_DATE") from exc
        if trade_date > as_of_date:
            error, _, _ = _provider_symbols()
            raise error(
                "CFFEX archive returned a future TRADE_DATE beyond the controller as-of: "
                f"{trade_date.isoformat()} > {as_of_date.isoformat()}"
            )
    return None


async def _load_active_registration() -> dict[str, str]:
    """Read the exact active managed registration before dispatch."""
    from sqlalchemy import select

    from app.db.database import async_session_maker
    from app.models.akshare_mgmt import DataScript

    async with async_session_maker() as session:
        script = await session.scalar(select(DataScript).where(DataScript.script_id == SCRIPT_ID))
        if script is None or not script.is_active:
            raise RuntimeError(f"managed producer {SCRIPT_ID} is missing or inactive")
        result = {
            "script_id": str(script.script_id),
            "source": str(script.source),
            "module_path": str(script.module_path),
            "function_name": str(script.function_name),
            "target_table": str(script.target_table),
        }
    expected = {
        "script_id": SCRIPT_ID,
        "source": SCRIPT_SOURCE,
        "module_path": SCRIPT_MODULE,
        "function_name": SCRIPT_FUNCTION,
        "target_table": TABLE_NAME,
    }
    if result != expected:
        raise RuntimeError(
            "active CFFEX registration does not match the reviewed producer contract"
        )
    return result


def managed_parameters(month: str, *, source_timeout_seconds: int) -> dict[str, Any]:
    """Build the exact one-month managed producer parameters."""
    month = normalize_month(month)
    if not 1 <= source_timeout_seconds <= MAX_SOURCE_TIMEOUT_SECONDS:
        raise ValueError(f"source timeout must be between 1 and {MAX_SOURCE_TIMEOUT_SECONDS}")
    start, end = month_bounds(month)
    return {
        "start_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "max_codes": 1,
        "source_timeout_seconds": float(source_timeout_seconds),
        "_ingest_mode": "backfill",
    }


async def _managed_month_call(
    month: str,
    run_id: str,
    capture: WireCapture,
    budget_seconds: int,
    source_timeout_seconds: int,
) -> tuple[Any | None, dict[str, Any], bool]:
    """Dispatch one month through the shared claim/fence with bounded waits."""
    from app.services.akshare import scheduler as scheduler_module

    identity_key = getattr(scheduler_module, "_identity_key", None)
    parameter_hash_fn = getattr(scheduler_module, "_parameter_hash", None)
    get_scheduler = getattr(scheduler_module, "get_akshare_scheduler", None)
    if identity_key is None or parameter_hash_fn is None or get_scheduler is None:
        raise RuntimeError(
            "the extended akshare scheduler claim/fence API is unavailable; "
            "CFFEX option apply is refused rather than dispatched unclaimed"
        )

    registration = await _load_active_registration()
    parameters = managed_parameters(month, source_timeout_seconds=source_timeout_seconds)
    managed_timeout = min(
        MAX_APPLY_SECONDS - MANAGED_RECEIPT_RESERVE_SECONDS,
        budget_seconds - MANAGED_RECEIPT_RESERVE_SECONDS,
    )
    if managed_timeout < source_timeout_seconds + 10:
        raise ValueError(
            "wall-clock budget leaves insufficient time for source and managed receipt"
        )
    period_key = f"cffex-month-controller-v1:{month}:{run_id}"
    parameter_hash = parameter_hash_fn(parameters)
    claim_key = identity_key(SCRIPT_ID, registration["source"], period_key, parameter_hash)
    dispatch = {
        "registration": registration,
        "parameters": parameters,
        "operator_id": None,
        "task_id": None,
        "managed_timeout_seconds": managed_timeout,
        "outer_wait_timeout_seconds": managed_timeout + OUTER_WAIT_RESERVE_SECONDS,
        "period_key": period_key,
        "parameter_hash": parameter_hash,
        "claim_key": claim_key,
        "claim_reuse_policy": "unique run id; no completed claim reused for refresh",
    }
    scheduler = get_scheduler()
    patch = ProviderCapturePatch(capture)
    timed_out = False
    with patch:
        try:
            execution = await asyncio.wait_for(
                scheduler.run_script_now(
                    SCRIPT_ID,
                    parameters,
                    operator_id=None,
                    task_id=None,
                    timeout_seconds=managed_timeout,
                    _claim_key=claim_key,
                    _period_key=period_key,
                ),
                timeout=managed_timeout + OUTER_WAIT_RESERVE_SECONDS,
            )
        except TimeoutError:
            timed_out = True
            patch.retain_until_process_exit()
            execution = None
    return execution, dispatch, timed_out


def _managed_status(execution: Any) -> str:
    if execution is None:
        return "managed_outcome_unknown"
    if isinstance(execution, Mapping):
        status = execution.get("status")
    else:
        status = getattr(execution, "status", None)
    return str(getattr(status, "value", status or "unknown")).casefold()


def _execution_quality_matches(
    execution_summary: Mapping[str, Any] | None,
    *,
    source_row_count: int,
    month_sql_row_count: int,
    month: str,
) -> tuple[bool, list[str]]:
    """Check the managed receipt agrees with the one parsed archive sequence."""
    result = execution_summary.get("result") if execution_summary else None
    if not isinstance(result, Mapping):
        return False, ["managed_result_missing"]
    expected_start, expected_end = month_bounds(month)
    expected_scope = (
        f"cffex:option-history:monthly-archive:"
        f"{expected_start.strftime('%Y%m%d')}-{expected_end.strftime('%Y%m%d')}"
    )
    expected_values = {
        "table_name": TABLE_NAME,
        "run_mode": "backfill",
        "quality_status": "partial",
        "source_complete": False,
        "source_row_count": source_row_count,
        "valid_row_count": source_row_count,
        "source_scope": expected_scope,
    }
    errors = [
        f"{field}_receipt_mismatch"
        for field, expected in expected_values.items()
        if result.get(field) != expected
    ]
    table_row_count: Any = result.get("row_count")
    rows_after: Any = result.get("rows_after")
    try:
        parsed_table_count = int(table_row_count)
        parsed_rows_after = int(rows_after)
        if isinstance(table_row_count, bool) or str(parsed_table_count) != str(table_row_count):
            raise ValueError("row_count is not an integer")
        if isinstance(rows_after, bool) or str(parsed_rows_after) != str(rows_after):
            raise ValueError("rows_after is not an integer")
        if parsed_table_count < 0 or parsed_rows_after < 0:
            raise ValueError("table row counts cannot be negative")
        if parsed_table_count != parsed_rows_after:
            errors.append("row_count_rows_after_receipt_mismatch")
        if parsed_rows_after < month_sql_row_count:
            errors.append("rows_after_less_than_month_sql_rows")
    except (TypeError, ValueError, OverflowError):
        errors.append("table_row_count_receipt_invalid")
    return not errors, errors


def _read_and_parse_capture(
    capture: WireCapture, month: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Independently invoke the frozen strict parser on the saved real body."""
    _, _, parse_monthly_archive = _provider_symbols()
    if not capture.transport_is_verifiable() or capture.body_path is None:
        raise RuntimeError("wire_capture_incomplete_or_invalid")
    body = capture.body_path.read_bytes()
    actual_hash = hashlib.sha256(body).hexdigest()
    if actual_hash != capture.body_sha256:
        raise RuntimeError("wire_archive_sha256_mismatch_after_persistence")
    start, end = month_bounds(month)
    parsed = parse_monthly_archive(
        body,
        archive_month=month,
        start_date=start,
        end_date=end,
        source_url=SOURCE_URL_TEMPLATE.format(month=month),
    )
    attrs = parsed.attrs
    if attrs.get("source_archive_sha256") != actual_hash:
        raise RuntimeError("parser_archive_sha256_differs_from_captured_body")
    if attrs.get("source_sequence_complete") is not True:
        raise RuntimeError("parser_did_not_certify_requested_archive_sequence")
    if attrs.get("source_complete") is not False:
        raise RuntimeError("parser completeness semantics changed unexpectedly")
    parsed_rows = list(parsed)
    _reject_future_source_dates(parsed_rows, capture.as_of_date)
    return parsed_rows, dict(attrs)


def _preimage_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    return _rows_digest(rows, COMPARE_FIELDS)


def _safe_month_evidence(attrs: Mapping[str, Any]) -> dict[str, Any]:
    """Keep source evidence needed to understand a month without claiming lifecycle."""
    return {
        "source_archive_month": attrs.get("source_archive_month"),
        "source_archive_sha256": attrs.get("source_archive_sha256"),
        "source_member_count": attrs.get("source_member_count"),
        "source_row_count": attrs.get("source_row_count"),
        "source_member_date_start": attrs.get("source_member_date_start"),
        "source_member_date_end": attrs.get("source_member_date_end"),
        "source_member_inventory": attrs.get("source_member_inventory"),
        "source_ignored_row_counts": attrs.get("source_ignored_row_counts"),
        "source_archive_ignored_row_counts": attrs.get("source_archive_ignored_row_counts"),
        "source_sequence_complete": attrs.get("source_sequence_complete"),
        "source_complete": attrs.get("source_complete"),
        "source_date_basis": attrs.get("source_date_basis"),
        "source_lifecycle_complete": attrs.get("source_lifecycle_complete"),
        "amount_unit": attrs.get("amount_unit"),
    }


async def apply_one_month(
    month: str,
    *,
    progress_path: Path,
    artifact_root: Path,
    time_budget_seconds: int,
    source_timeout_seconds: int,
    reader_factory: Callable[[], WarehouseReader] | None = None,
    managed_runner: Callable[..., Any] | None = None,
    now: Callable[[], datetime] = shanghai_now,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run and independently verify exactly one monthly archive work unit."""
    reader = reader_factory if reader_factory is not None else MySQLOptionHistoryReader
    month = normalize_month(month)
    if not MIN_APPLY_SECONDS <= time_budget_seconds <= MAX_APPLY_SECONDS:
        raise ValueError(f"time budget must be {MIN_APPLY_SECONDS}..{MAX_APPLY_SECONDS} seconds")
    if not 1 <= source_timeout_seconds <= MAX_SOURCE_TIMEOUT_SECONDS:
        raise ValueError(f"source timeout must be 1..{MAX_SOURCE_TIMEOUT_SECONDS} seconds")
    started_monotonic = monotonic()
    run_id = uuid4().hex
    clock_value = now()
    if clock_value.tzinfo is None or clock_value.utcoffset() is None:
        raise ValueError("controller as-of clock must be timezone-aware")
    as_of_date = clock_value.astimezone(ZoneInfo(SOURCE_TIME_ZONE)).date()
    attempt_at = clock_value.astimezone(UTC)
    capture_dir = artifact_root / month / run_id
    capture_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        capture_dir.chmod(0o700)
    except OSError:
        pass
    capture = WireCapture(
        month=month,
        directory=capture_dir,
        run_id=run_id,
        as_of_date=as_of_date,
    )

    base = {
        "month": month,
        "run_id": run_id,
        "attempted_at_utc": attempt_at.isoformat(timespec="microseconds"),
        "controller_as_of_date": as_of_date.isoformat(),
        "request_scope": "one exact full calendar month archive; no trading calendar imputation",
        "candidate_start_month_is_inception": False,
        "source_lifecycle": "unknown",
        "source_complete": False,
        "calendar_coverage": "unknown",
        "execution_budget": _budget_semantics(time_budget_seconds),
    }

    try:
        with reader() as warehouse:
            schema = dict(warehouse.check_schema())
            before_rows = warehouse.read_month(month)
    except Exception as exc:
        event = append_progress(
            progress_path,
            {
                **base,
                "status": "preflight_failed",
                "failure_phase": "schema_or_preimage_read",
                "error": _safe_text(f"{type(exc).__name__}: {exc}", 1000),
            },
        )
        return {
            **base,
            "status": "preflight_failed",
            "schema": None,
            "preimage_sha256": None,
            "progress_event_sha256": event["event_sha256"],
        }
    before_hash = _preimage_digest(before_rows)

    append_progress(
        progress_path,
        {
            **base,
            "status": "attempt_started",
            "schema_sha256": schema.get("sha256"),
            "preimage_sql_rows": len(before_rows),
            "preimage_fields_sha256": before_hash,
            "artifact_directory": str(capture_dir),
            "source_timeout_seconds": source_timeout_seconds,
            "wall_clock_budget_seconds": time_budget_seconds,
        },
    )

    dispatch: dict[str, Any] = {}
    execution: Any = None
    timed_out = False
    call_error: str | None = None
    managed_invoked = False
    try:
        remaining_budget = time_budget_seconds - (monotonic() - started_monotonic)
        if remaining_budget < source_timeout_seconds + MANAGED_RECEIPT_RESERVE_SECONDS:
            raise TimeoutError("insufficient remaining wall budget before managed dispatch")
        managed_invoked = True
        if managed_runner is None:
            execution, dispatch, timed_out = await _managed_month_call(
                month=month,
                run_id=run_id,
                capture=capture,
                budget_seconds=int(remaining_budget),
                source_timeout_seconds=source_timeout_seconds,
            )
        else:
            maybe = managed_runner(
                month=month,
                run_id=run_id,
                capture=capture,
                budget_seconds=time_budget_seconds,
                source_timeout_seconds=source_timeout_seconds,
            )
            outcome = await maybe if asyncio.iscoroutine(maybe) else maybe
            if isinstance(outcome, tuple) and len(outcome) == 3:
                execution, dispatch, timed_out = outcome
            else:
                execution = outcome
    except Exception as exc:
        call_error = _safe_text(f"{type(exc).__name__}: {exc}", 1000)
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) and managed_invoked:
            # A pre-dispatch soft-budget stop is a deferral, not a managed wait
            # timeout; it must not be recorded as timed_out (worker contract).
            timed_out = True
        capture.record_error(exc)

    try:
        capture_manifest = capture.finalize()
    except Exception as exc:
        capture_manifest = {
            "transport_verifiable": False,
            "capture_error": _safe_text(f"manifest_write_failed:{type(exc).__name__}:{exc}", 1000),
        }

    try:
        with reader() as warehouse:
            after_rows = warehouse.read_month(month)
        post_read_error: str | None = None
    except Exception as exc:
        after_rows = []
        post_read_error = _safe_text(f"{type(exc).__name__}: {exc}", 1000)

    execution_summary = _safe_execution_summary(execution) if execution is not None else None
    terminal = {
        **base,
        "schema_sha256": schema.get("sha256"),
        "preimage_sql_rows": len(before_rows),
        "preimage_fields_sha256": before_hash,
        "postimage_sql_rows": len(after_rows),
        "postimage_fields_sha256": None if post_read_error else _preimage_digest(after_rows),
        "database_write_possible": bool(
            (execution_summary or {}).get("result", {}).get("committed_write_count")
        )
        or managed_invoked,
        "dispatch": dispatch,
        "execution": execution_summary,
        "timed_out": timed_out,
        "managed_call_error": call_error,
        "post_sql_read_error": post_read_error,
        "wire_capture": capture_manifest,
        "archive_sha256": capture_manifest.get("body_sha256"),
        "independent_parser": (
            "same frozen strict parser called separately on persisted capture;"
            " not a second parser implementation"
        ),
        "calendar_coverage": "unknown",
        "contract_lifecycle": "unknown",
        "source_complete": False,
    }

    parse_error: str | None = None
    parsed_rows: list[dict[str, Any]] = []
    parser_attrs: dict[str, Any] = {}
    if capture_manifest.get("transport_verifiable"):
        try:
            parsed_rows, parser_attrs = _read_and_parse_capture(capture, month)
            terminal["source_month_evidence"] = _safe_month_evidence(parser_attrs)
        except Exception as exc:
            parse_error = _safe_text(f"{type(exc).__name__}: {exc}", 1000)
    else:
        parse_error = capture_manifest.get("capture_error") or "wire_capture_not_verifiable"
    terminal["independent_parse_error"] = parse_error

    if post_read_error:
        status: str = "verification_failed"
        terminal["failure_phase"] = "fresh_sql_reread"
    elif not managed_invoked:
        status = "deferred_budget"
        terminal["failure_phase"] = "wall_clock_budget_before_managed_dispatch"
    elif timed_out:
        status = "managed_outcome_unknown"
        terminal["failure_phase"] = "managed_execution_timeout"
    elif parse_error:
        preimage_unchanged = _preimage_digest(after_rows) == before_hash
        if call_error and capture_manifest.get("request_count", 0) == 0:
            status = "managed_failed"
            terminal["failure_phase"] = "managed_registration_or_dispatch"
            terminal["preimage_unchanged_after_failed_month"] = preimage_unchanged
        elif preimage_unchanged and _managed_status(execution) != "completed":
            status = "source_invalid" if capture_manifest.get("body_complete") else "source_failed"
            terminal["preimage_unchanged_after_failed_month"] = True
            terminal["source_failure_cooldown_hours"] = FAILURE_COOLDOWN.total_seconds() / 3600
        else:
            status = "verification_failed"
            terminal["failure_phase"] = "archive_parse_or_capture"
            terminal["preimage_unchanged_after_failed_month"] = preimage_unchanged
    else:
        if _managed_status(execution) != "completed" or timed_out or call_error:
            status = (
                "managed_outcome_unknown" if timed_out or execution is None else "managed_failed"
            )
            terminal["failure_phase"] = "managed_execution"
        else:
            comparison = compare_source_rows_to_sql(parsed_rows, after_rows, month=month)
            terminal["source_sql_comparison"] = comparison
            quality_matches, quality_errors = _execution_quality_matches(
                execution_summary,
                source_row_count=len(parsed_rows),
                month_sql_row_count=len(after_rows),
                month=month,
            )
            terminal["managed_quality_receipt_matches_parser"] = quality_matches
            terminal["managed_quality_receipt_errors"] = quality_errors
            if comparison["matched"] and quality_matches:
                status = "verified_source_archive_snapshot"
                terminal.update(
                    {
                        "verified_at_utc": now().astimezone(UTC).isoformat(timespec="microseconds"),
                        "source_sequence_complete": True,
                        "source_complete": False,
                        "archive_snapshot_verified": True,
                        "month_calendar_coverage_verified": False,
                        "candidate_inception_verified": False,
                    }
                )
            else:
                status = "verification_failed"
                terminal["failure_phase"] = "source_sql_comparison"

    terminal["status"] = status
    terminal["elapsed_seconds"] = round(monotonic() - started_monotonic, 3)
    event = append_progress(progress_path, terminal)
    terminal["progress_event_sha256"] = event["event_sha256"]
    return terminal


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write a review report atomically; progress remains separate append-only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    rendered = (
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default, allow_nan=False)
        + "\n"
    )
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _paths_alias(first: Path, second: Path) -> bool:
    """Detect identical, symlinked, or hard-linked output and ledger paths."""
    if first.resolve() == second.resolve():
        return True
    try:
        return first.exists() and second.exists() and first.samefile(second)
    except OSError:
        return False


def _read_ledger_or_raise(path: Path) -> list[dict[str, Any]]:
    return read_progress(path)


async def _cli_async(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    progress = _read_ledger_or_raise(args.progress)
    current = current_shanghai_month()
    audit: dict[str, Any] | None = None
    if args.audit or args.apply:
        with MySQLOptionHistoryReader() as reader:
            if args.apply:
                schema = reader.check_schema()
                audit = dict(reader.read_overview())
                audit["schema"] = dict(schema)
            else:
                audit = dict(reader.read_overview())
    if not args.apply:
        plan = build_plan(
            events=progress,
            start_month=args.start_month,
            end_month=args.end_month,
            warehouse_audit=audit,
        )
        plan["progress_path"] = str(args.progress)
        return plan, 0
    budget = args.max_minutes * 60
    month, selection = select_next_month(
        start_month=args.start_month,
        end_month=min(args.end_month or current, current),
        current_month=current,
        events=progress,
        now=shanghai_now(),
    )
    if month is None:
        return (
            {
                "mode": "apply",
                "selected_month": None,
                "selection": selection,
                "status": "no_eligible_month",
                "execution_budget": _budget_semantics(budget),
            },
            0,
        )
    result = await apply_one_month(
        month,
        progress_path=args.progress,
        artifact_root=args.artifacts,
        time_budget_seconds=budget,
        source_timeout_seconds=args.source_timeout_seconds,
    )
    return (
        {"mode": "apply", "selection": selection, "result": result},
        0 if result.get("status") == "verified_source_archive_snapshot" else 1,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="run one managed monthly archive fetch"
    )
    parser.add_argument(
        "--audit", action="store_true", help="add a read-only SQL monthly inventory"
    )
    parser.add_argument("--start-month", default=CANDIDATE_START_MONTH)
    parser.add_argument(
        "--end-month",
        help="plan bound; never extends apply past Shanghai current month",
    )
    parser.add_argument(
        "--max-minutes",
        type=int,
        default=3,
        help="soft apply wall budget, bounded to 2..3 minutes; use a 200s outer hard timeout",
    )
    parser.add_argument(
        "--source-timeout-seconds",
        type=int,
        default=DEFAULT_SOURCE_TIMEOUT_SECONDS,
        help="one request timeout; bounded to 90 seconds",
    )
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS_PATH)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--output", type=Path, help="atomically save this JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    output_path: Path | None = args.output
    if output_path is not None and _paths_alias(output_path, args.progress):
        report: dict[str, Any] = {
            "mode": "error",
            "status": "failed_closed",
            "error": "--output must not alias the append-only --progress ledger",
        }
        exit_code = 2
        output_path = None
    else:
        try:
            normalize_month(args.start_month)
            if args.end_month:
                normalize_month(args.end_month)
            if not 2 <= args.max_minutes <= 3:
                raise ValueError("--max-minutes must be 2 or 3 to leave source and receipt budget")
            if not 1 <= args.source_timeout_seconds <= MAX_SOURCE_TIMEOUT_SECONDS:
                raise ValueError("--source-timeout-seconds must be between 1 and 90")
            report, exit_code = asyncio.run(_cli_async(args))
        except Exception as exc:
            report = {
                "mode": "error",
                "status": "failed_closed",
                "error": _safe_text(f"{type(exc).__name__}: {exc}", 1000),
            }
            exit_code = 2
    if output_path:
        _atomic_write_json(output_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
