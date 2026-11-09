"""Read-only plan and explicitly bounded managed recovery for convertible-bond history.

Without ``--apply`` this controller only reads the warehouse inventory and its
append-only progress ledger.  Apply mode probes the complete exact-symbol Sina
history in a killable child process, stores an immutable content-addressed
source snapshot, compares it against a read-only SQL snapshot, and routes an
observed difference through the existing akshare managed script service.  It
never infers listing dates, source retention, or full-history completeness.

The convertible-bond leg of the AC05 full-history recovery is a runtime asset:
the supervising worker (``scripts/ops/run_full_history_recovery_worker.py``)
shells out to this exact path with ``--apply --max-codes --time-budget-seconds
--source-timeout-seconds --progress-file --snapshot-dir --report``.

Unattributable legacy rows
--------------------------
``BOND_ZH_HS_COV_DAILY`` carries a legacy series whose ``symbol`` is null (and
rows whose ``source`` is empty).  Their real business date lives in ``date``
while ``data_date`` is only the legacy load/collection date.  Those rows are
never attributed to an instrument by price or sequence matching: every per-code
read is parameterized by the exact stored symbol, so an unattributable row
cannot enter a per-code ledger at all.  They are preserved and reported as
aggregate evidence (unique-value versus duplicate-row counts plus date
semantics) and excluded from every per-code completeness claim.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import math
import multiprocessing
import os
import re
import sys
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

UTC = timezone.utc

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_ROOT.parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

SCRIPT_ID = "bond_zh_hs_cov_daily"
SOURCE_IDENTITY = "akshare:bond_zh_hs_cov_daily:sina"
REPORT_VERSION = "bond-convertible-history-controller-v1"
SOURCE_SNAPSHOT_SCHEMA = "bond-convertible-source-snapshot-v1"
WAREHOUSE_SNAPSHOT_SCHEMA = "bond-convertible-warehouse-snapshot-v1"
CONVERTIBLE_HISTORY_TABLE = "BOND_ZH_HS_COV_DAILY"
CONVERTIBLE_SNAPSHOT_TABLE = "BOND_ZH_HS_COV_SPOT"

MAX_APPLY_CODES = 10
DEFAULT_APPLY_CODES = 5
MAX_APPLY_SECONDS = 600
DEFAULT_APPLY_SECONDS = 420
MAX_SOURCE_TIMEOUT_SECONDS = 90
DEFAULT_SOURCE_TIMEOUT_SECONDS = 45
MIN_MANAGED_REMAINING_SECONDS = 3.0
MANAGED_DISPATCH_RESERVE_SECONDS = 5.0
FAILURE_COOLDOWN_HOURS = 24.0
DATE_LIST_LIMIT = 400
COOLDOWN_OUTCOME_LIMIT = 50

_ARTIFACT_DIR = (
    _REPO_ROOT / "var" / "reports" / "iteration203" / "bond-convertible-history-controller"
)
DEFAULT_PROGRESS_FILE = _ARTIFACT_DIR / "progress.jsonl"
DEFAULT_SNAPSHOT_DIR = _ARTIFACT_DIR / "snapshots"

EXIT_ALL_VERIFIED = 0
EXIT_SOURCE_FAILURE = 1
EXIT_ATTENTION_REQUIRED = 2
EXIT_DEFERRED = 3

SUCCESS_STATUSES = frozenset({"verified_unchanged", "verified_source_sequence"})
SOURCE_FAILURE_STATUSES = frozenset({"source_failed", "source_invalid"})
NORMAL_INCOMPLETE_STATUSES = frozenset(
    {"source_empty_unverified", "deferred_budget", "deferred_failure_cooldown"}
)
ATTENTION_STATUSES = frozenset(
    {
        "source_worker_crashed",
        "verification_failed",
        "managed_preflight_failed",
        "managed_preflight_timed_out",
        "managed_execution_pending",
        "managed_execution_failed",
        "managed_outcome_unknown",
        "post_write_mismatch",
    }
)
_PROBE_TRACKED_STATUSES = (
    SUCCESS_STATUSES | SOURCE_FAILURE_STATUSES | frozenset({"source_empty_unverified"})
)

_URL_AUTH = re.compile(r"(?i)(https?://)[^/@\s]+:[^/@\s]+@")
_SECRET_VALUE = re.compile(
    r"(?i)\b(password|passwd|token|api[_-]?key|secret|authorization)(\s*[:=]\s*)[^\s,;&]+"
)
_BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_SYMBOL_PREFIXES = ("sh", "sz", "bj")
_CANONICAL_OHLC_FIELDS = ("open", "high", "low", "close")
_LEDGER_FIELDS = ("open", "high", "low", "close", "volume")
_EXCHANGE_SUFFIXES = {"SH": "sh", "SZ": "sz", "BJ": "bj", "XSHG": "sh", "XSHE": "sz"}
_OVERVIEW_METRIC_FIELDS = (
    "row_count",
    "date_key_count",
    "first_date",
    "last_date",
    "duplicate_date_rows",
    "incomplete_ohlc_rows",
)

# ---------------------------------------------------------------------------
# Report hygiene helpers.
# ---------------------------------------------------------------------------


def _safe_error(value: Any) -> str:
    """Render a failure without leaking credentials or connection strings."""

    rendered = str(value)
    rendered = _URL_AUTH.sub(r"\1[REDACTED]@", rendered)
    rendered = _SECRET_VALUE.sub(r"\1\2[REDACTED]", rendered)
    rendered = _BEARER_VALUE.sub("Bearer [REDACTED]", rendered)
    return rendered[:1200]


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def canonical_json_bytes(value: Any) -> bytes:
    """Deterministic canonical JSON used by every content hash in this file."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


# ---------------------------------------------------------------------------
# Pure core: instrument identity and normalization.
# ---------------------------------------------------------------------------


def normalize_bond_symbol(value: Any) -> str:
    """Return the canonical lowercase ``sh/sz/bj`` plus six-digit bond code.

    Accepts the forms the warehouse and the vendor emit (``sh110077``,
    ``SH110077``, ``110077``, ``110077.SH``, ``110077.0``).  Anything that is
    not an exact convertible code raises ``ValueError``; a code is never
    inferred from a price series.
    """

    raw = str(value or "").strip()
    if not raw:
        raise ValueError("empty convertible-bond symbol")
    if raw.endswith(".0") and raw[:-2].isdigit():
        raw = raw[:-2]
    for separator in (".", "_", "-"):
        if separator not in raw:
            continue
        left, _, right = raw.partition(separator)
        if right.upper() in _EXCHANGE_SUFFIXES and left.isdigit():
            raw = left
        elif left.upper() in {"SH", "SZ", "BJ"} and right.isdigit():
            raw = left.lower() + right
    text = raw.lower()
    if text[:2] in _SYMBOL_PREFIXES and len(text) == 8 and text[2:].isdigit():
        return text
    if text.isdigit() and len(text) == 6:
        if text.startswith("11"):
            return f"sh{text}"
        if text.startswith("12"):
            return f"sz{text}"
        if text.startswith(("81", "82", "43", "92")):
            return f"bj{text}"
    raise ValueError(f"unrecognized convertible-bond symbol: {value!r}")


def try_normalize_bond_symbol(value: Any) -> str | None:
    try:
        return normalize_bond_symbol(value)
    except (TypeError, ValueError):
        return None


def market_for_symbol(symbol: str) -> str:
    return normalize_bond_symbol(symbol)[:2].upper()


def _as_day(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text[:10] if text else None


def _price(value: Any) -> float | None:
    """Return the finite stored value, or null; a missing price is never invented."""

    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        value = text
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        parsed = round(float(value), 8)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _ordered_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    columns = [str(column) for column in payload.get("columns", [])]
    rows: list[dict[str, Any]] = []
    for record in payload.get("rows", []):
        if isinstance(record, Mapping):
            rows.append({str(key): value for key, value in record.items()})
        elif isinstance(record, list | tuple):
            rows.append(dict(zip(columns, record, strict=False)))
        else:
            raise ValueError("convertible source frame rows must be records or sequences")
    return rows


def normalize_daily_frame(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Normalize a returned source frame into the producer's daily ledger.

    Returns the ledger rows and the number of duplicate business dates the
    producer drops.  Source-native nulls are preserved as null.
    """

    rows = _ordered_payload(payload)
    ledger: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for row in rows:
        day = _as_day(row.get("data_date", row.get("date")))
        if day is None:
            continue
        if day in ledger:
            duplicates += 1
            continue
        values: dict[str, Any] = {"data_date": day}
        for field in _LEDGER_FIELDS:
            values[field] = _price(row.get(field))
        ledger[day] = values
    return sorted(ledger.values(), key=lambda item: item["data_date"]), duplicates


@dataclass(frozen=True)
class SourceSnapshot:
    """Raw returned source frame plus the producer-normalized daily ledger."""

    symbol: str
    market: str
    raw_payload: Mapping[str, Any]
    raw_content_sha256: str
    normalized_ledger: tuple[dict[str, Any], ...]
    normalized_ledger_sha256: str
    first_source_date: str | None
    last_source_date: str | None
    captured_at_utc: str
    source_row_count: int
    duplicate_source_dates: int


def normalize_source_payload(
    symbol: str,
    raw_payload: Mapping[str, Any],
    *,
    captured_at: datetime | None = None,
) -> SourceSnapshot:
    """Hash the returned frame exactly as received, then normalize it."""

    canonical = normalize_bond_symbol(symbol)
    if not isinstance(raw_payload.get("columns"), list) or not isinstance(
        raw_payload.get("rows"), list
    ):
        raise ValueError("raw convertible source payload must contain columns and rows")
    payload: dict[str, Any] = {
        "columns": [str(column) for column in raw_payload["columns"]],
        "rows": _ordered_payload(raw_payload),
    }
    ledger, duplicates = normalize_daily_frame(payload)
    captured = (captured_at or datetime.now(UTC)).astimezone(UTC)
    return SourceSnapshot(
        symbol=canonical,
        market=market_for_symbol(canonical),
        raw_payload=payload,
        raw_content_sha256=sha256_hex(payload),
        normalized_ledger=tuple(ledger),
        normalized_ledger_sha256=sha256_hex(ledger),
        first_source_date=ledger[0]["data_date"] if ledger else None,
        last_source_date=ledger[-1]["data_date"] if ledger else None,
        captured_at_utc=captured.isoformat(timespec="microseconds"),
        source_row_count=len(payload["rows"]),
        duplicate_source_dates=duplicates,
    )


# ---------------------------------------------------------------------------
# Pure core: comparison, gap classification, snapshot payloads, checkpoints.
# ---------------------------------------------------------------------------


def _day_ledger(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, tuple[Any, ...]], int]:
    """Index OHLC values by business date and count duplicate date keys."""

    indexed: dict[str, tuple[Any, ...]] = {}
    duplicates = 0
    for row in rows:
        day = _as_day(row.get("data_date", row.get("date")))
        if day is None:
            continue
        values = tuple(_price(row.get(name)) for name in _CANONICAL_OHLC_FIELDS)
        if day in indexed:
            duplicates += 1
            continue
        indexed[day] = values
    return indexed, duplicates


def compare_daily_ledgers(
    source_rows: Iterable[Mapping[str, Any]],
    warehouse_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare actual business-date keys and OHLC values for one exact code.

    ``warehouse_rows`` must already be the symbol-parameterized read; this
    function performs no matching beyond the stored business date.
    """

    source, source_duplicates = _day_ledger(source_rows)
    warehouse, warehouse_duplicates = _day_ledger(warehouse_rows)
    source_only = sorted(set(source) - set(warehouse))
    warehouse_only = sorted(set(warehouse) - set(source))
    mismatches = [
        {"date": day, "source_ohlc": list(source[day]), "warehouse_ohlc": list(warehouse[day])}
        for day in sorted(set(source) & set(warehouse))
        if source[day] != warehouse[day]
    ]
    return {
        "source_observation_count": len(source),
        "warehouse_observation_count": len(warehouse),
        "source_duplicate_rows": source_duplicates,
        "warehouse_duplicate_rows": warehouse_duplicates,
        "source_first_date": min(source) if source else None,
        "source_last_date": max(source) if source else None,
        "source_only_count": len(source_only),
        "source_only_dates": source_only[:DATE_LIST_LIMIT],
        "warehouse_only_count": len(warehouse_only),
        "warehouse_only_dates": warehouse_only[:DATE_LIST_LIMIT],
        "ohlc_mismatch_count": len(mismatches),
        "ohlc_mismatches": mismatches[:DATE_LIST_LIMIT],
        "date_key_and_ohlc_match": not source_only and not warehouse_only and not mismatches,
        "history_completeness": "not_certified",
        "listing_boundary": "unknown",
        "source_retention": "unknown",
    }


def classify_source_only_dates(
    comparison: Mapping[str, Any],
    warehouse_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Split source-only dates into head/internal/tail without closing any gap."""

    rows = list(warehouse_rows)
    warehouse_dates = sorted(
        day for day in (_as_day(row.get("data_date", row.get("date"))) for row in rows) if day
    )
    known = set(warehouse_dates)
    missing = sorted(
        day for day in map(str, comparison.get("source_only_dates", [])) if day not in known
    )
    if not warehouse_dates:
        return {
            "warehouse_first_date": None,
            "warehouse_last_date": None,
            "head_count": 0,
            "internal_count": 0,
            "tail_count": 0,
            "unclassified_no_warehouse_baseline_count": len(missing),
            "head_dates": [],
            "internal_dates": [],
            "tail_dates": [],
            "unclassified_dates": missing[:DATE_LIST_LIMIT],
        }
    first_warehouse = warehouse_dates[0]
    last_warehouse = warehouse_dates[-1]
    head = [day for day in missing if day < first_warehouse]
    tail = [day for day in missing if day > last_warehouse]
    internal = [day for day in missing if first_warehouse <= day <= last_warehouse]
    return {
        "warehouse_first_date": first_warehouse,
        "warehouse_last_date": last_warehouse,
        "head_count": len(head),
        "internal_count": len(internal),
        "tail_count": len(tail),
        "unclassified_no_warehouse_baseline_count": 0,
        "head_dates": head[:DATE_LIST_LIMIT],
        "internal_dates": internal[:DATE_LIST_LIMIT],
        "tail_dates": tail[:DATE_LIST_LIMIT],
        "unclassified_dates": [],
    }


def warehouse_snapshot_payload(
    symbol: str, stage: str, rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Build the read-only SQL snapshot payload for one code and stage."""

    safe_rows = [
        {str(key): _json_default(value) for key, value in sorted(row.items())} for row in rows
    ]
    return {
        "schema_version": WAREHOUSE_SNAPSHOT_SCHEMA,
        "symbol": normalize_bond_symbol(symbol),
        "market": market_for_symbol(symbol),
        "stage": stage,
        "read_only_select": True,
        "key_fields": ["symbol", "data_date"],
        "compared_fields": list(_CANONICAL_OHLC_FIELDS),
        "row_count": len(safe_rows),
        "rows": safe_rows,
    }


def warehouse_provenance(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Report per-code row provenance by stored source label."""

    row_list = list(rows)
    counts: dict[str, int] = {}
    for row in row_list:
        source = str(row.get("source") or "").strip().casefold() or "legacy_unknown"
        counts[source] = counts.get(source, 0) + 1
    return {
        "row_count_by_source": dict(sorted(counts.items())),
        "legacy_unknown_row_count": counts.get("legacy_unknown", 0),
        "sina_row_count": counts.get("sina", 0),
        "source_field_available": bool(row_list) and all("source" in row for row in row_list),
    }


def make_checkpoint_key(symbol: str) -> str:
    """Bind resumable status to the exact code and the complete-source request scope."""

    canonical = normalize_bond_symbol(symbol)
    return sha256_hex(
        {
            "schema_version": REPORT_VERSION,
            "source_identity": SOURCE_IDENTITY,
            "market": market_for_symbol(canonical),
            "symbol": canonical,
            "requested_window": "complete_source_response",
            "normalizer_version": REPORT_VERSION,
        }
    )


def make_scope_hash(symbols: Sequence[str], universe: Sequence[Mapping[str, Any]]) -> str:
    universe_payload = sorted(
        (
            {
                "symbol": str(row.get("symbol", "")),
                "origins": sorted(str(origin) for origin in row.get("origins", [])),
            }
            for row in universe
        ),
        key=lambda row: (row["symbol"], row["origins"]),
    )
    return sha256_hex(
        {
            "schema_version": REPORT_VERSION,
            "source_identity": SOURCE_IDENTITY,
            "normalizer_version": REPORT_VERSION,
            "requested_window": "complete_source_response",
            "universe": universe_payload,
            "selected_symbols": sorted({normalize_bond_symbol(symbol) for symbol in symbols}),
        }
    )


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


# ---------------------------------------------------------------------------
# Pure core: universe selection.
# ---------------------------------------------------------------------------


def build_convertible_universe(
    snapshot_symbols: Iterable[Any],
    history_rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Union the latest snapshot batch with every historical code, including BJ."""

    origins: dict[str, set[str]] = {}
    invalid: dict[str, list[str]] = {"latest_sina_snapshot": [], "historical_daily": []}
    history_values = list(history_rows)
    for origin, values in (
        ("latest_sina_snapshot", list(snapshot_symbols)),
        ("historical_daily", history_values),
    ):
        for value in values:
            raw = value.get("symbol") if isinstance(value, Mapping) else value
            symbol = try_normalize_bond_symbol(raw)
            if symbol is None:
                if raw is not None and str(raw).strip():
                    invalid[origin].append(str(raw).strip())
                continue
            origins.setdefault(symbol, set()).add(origin)
    universe = [
        {
            "symbol": symbol,
            "origins": sorted(origins[symbol]),
            "exchange": symbol[:2].upper(),
            "warehouse_status": "inventory_only",
            "listing_boundary": "unknown",
            "source_retention": "unknown",
            "head_gap_status": "unverified",
            "internal_gap_status": "unverified",
            "tail_gap_status": "unverified",
        }
        for symbol in sorted(origins)
    ]
    return universe, {key: sorted(set(values)) for key, values in invalid.items()}


def merge_universe(
    universe: Sequence[Mapping[str, Any]],
    extras: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Union inventory symbols with issuance evidence; never replace progress."""

    merged: dict[str, dict[str, Any]] = {
        str(row["symbol"]): dict(row) for row in universe if row.get("symbol")
    }
    added = 0
    enriched = 0
    for extra in extras:
        symbol = str(extra.get("symbol", ""))
        existing = merged.get(symbol)
        if existing is None:
            merged[symbol] = dict(extra)
            added += 1
            continue
        origins = set(existing.get("origins", []))
        origins.update(str(origin) for origin in extra.get("origins", []))
        existing["origins"] = sorted(origins)
        for key, value in extra.items():
            if key in {"symbol", "origins"} or value in (None, "", []):
                continue
            existing.setdefault(key, value)
        enriched += 1
    return sorted(merged.values(), key=lambda row: str(row["symbol"])), added, enriched


def load_extra_universe(path: Path) -> list[dict[str, Any]]:
    """Load exact-symbol issuance evidence without claiming source boundaries."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("universe file must contain a JSON object")
    supported = {REPORT_VERSION, "bond-convertible-issuance-universe-v1"}
    if str(payload.get("schema_version", "")) not in supported:
        raise ValueError("universe file has an unsupported schema_version")
    entries = payload.get("symbols")
    if not isinstance(entries, list) or not entries:
        raise ValueError("universe file must contain a non-empty symbols list")
    rows: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("universe symbols must be objects")
        symbol = normalize_bond_symbol(entry.get("symbol"))
        issuance = entry.get("issuance_master")
        if not isinstance(issuance, Mapping):
            issuance = {
                key: entry.get(key)
                for key in (
                    "source",
                    "source_secucode",
                    "listing_date",
                    "bond_start_date",
                    "issue_date",
                    "value_date",
                    "expiry_date",
                    "delist_date",
                    "name",
                    "listing_date_semantics",
                )
            }
        rows.append(
            {
                "symbol": symbol,
                "origins": ["em_issuance_master"],
                "exchange": market_for_symbol(symbol),
                "warehouse_status": "not_in_warehouse_inventory",
                "listing_boundary": "unknown",
                "source_retention": "unknown",
                "head_gap_status": "unverified",
                "internal_gap_status": "unverified",
                "tail_gap_status": "unverified",
                "issuance_master": dict(issuance),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Append-only progress ledger and bounded selection.
# ---------------------------------------------------------------------------


def read_progress(path: Path) -> list[dict[str, Any]]:
    """Read append-only checkpoints and fail closed on malformed or unkeyed rows."""

    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed progress JSONL line {line_number}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"progress JSONL line {line_number} must be an object")
        symbol = record.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise ValueError(f"progress JSONL line {line_number} must have a symbol")
        expected = make_checkpoint_key(symbol)
        stated = record.get("checkpoint_key")
        if stated is not None and stated != expected:
            raise ValueError(f"progress JSONL line {line_number} has a mismatched checkpoint key")
        record["checkpoint_key"] = expected
        result.append(record)
    return result


def append_progress(path: Path, record: Mapping[str, Any]) -> None:
    """Append one durable checkpoint; the ledger is never rewritten or truncated."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(dict(record), ensure_ascii=False, default=_json_default, allow_nan=False)
            + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())


def latest_progress_by_symbol(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        symbol = record.get("symbol")
        if isinstance(symbol, str) and symbol:
            latest[symbol] = dict(record)
    return latest


def progress_clocks_by_symbol(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Derive attempt and actual source-probe clocks from append-only progress."""

    states: dict[str, dict[str, Any]] = {}
    trackable = _PROBE_TRACKED_STATUSES
    for record in records:
        symbol = record.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            continue
        state = states.setdefault(symbol, {"symbol": symbol})
        attempted_at = _timestamp(record.get("attempted_at_utc") or record.get("recorded_at_utc"))
        if attempted_at is not None:
            current = state.get("latest_attempt_at")
            if current is None or attempted_at > current:
                state["latest_attempt_at"] = attempted_at
        status = record.get("status")
        if not isinstance(status, str) or status not in trackable:
            continue
        if not (record.get("raw_content_sha256") or record.get("source_snapshot_path")):
            continue
        probe_at = _timestamp(record.get("source_probe_at_utc")) or attempted_at
        if probe_at is None:
            continue
        current_probe = state.get("latest_source_probe_at")
        if current_probe is None or probe_at > current_probe:
            state["latest_source_probe_at"] = probe_at
            state["latest_source_status"] = status
    return states


def _active_cooldown(record: Mapping[str, Any] | None, now: datetime) -> datetime | None:
    """Return the cooldown horizon for a real source failure, or ``None``."""

    if record is None or str(record.get("status", "")) not in SOURCE_FAILURE_STATUSES:
        return None
    attempted = _timestamp(record.get("source_probe_at_utc")) or _timestamp(
        record.get("recorded_at_utc")
    )
    if attempted is None:
        return None
    until = attempted + timedelta(hours=FAILURE_COOLDOWN_HOURS)
    return until if until > now else None


def _fairness_key(
    states: Mapping[str, Mapping[str, Any]], symbol: str
) -> tuple[int, float, float, int]:
    """Attempted-never first, then the oldest attempt and probe; success rotates last."""

    state = states.get(symbol, {})
    attempt_at = state.get("latest_attempt_at")
    source_at = state.get("latest_source_probe_at")
    attempt_order = 1 if str(state.get("latest_source_status") or "") in SUCCESS_STATUSES else 0
    return (
        0 if attempt_at is None else 1,
        float(attempt_at.timestamp()) if attempt_at is not None else 0.0,
        float(source_at.timestamp()) if source_at is not None else 0.0,
        attempt_order,
    )


def _validate_ordered_symbols(symbols: Sequence[Any]) -> list[str]:
    """Validate exact symbols while preserving the operator-specified order."""

    normalized: list[str] = []
    seen: set[str] = set()
    for value in symbols:
        symbol = normalize_bond_symbol(value)
        if symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    if not normalized:
        raise ValueError("explicitly provide at least one convertible-bond symbol")
    if len(normalized) > MAX_APPLY_CODES:
        raise ValueError(f"a single apply may include at most {MAX_APPLY_CODES} symbols")
    return normalized


def select_apply_symbols(
    candidates: Sequence[str],
    requested: Sequence[str] | None,
    max_codes: int,
    previous: Mapping[str, Mapping[str, Any]],
    now: datetime,
    retry_failed: bool,
    progress_records: Iterable[Mapping[str, Any]] | None = None,
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """Fairly prioritize unverified inventory; never infer source membership."""

    if not 1 <= max_codes <= MAX_APPLY_CODES:
        raise ValueError(f"max_codes must be between 1 and {MAX_APPLY_CODES}")
    candidate_set = set(candidates)
    records = list(progress_records or [])
    states = progress_clocks_by_symbol(records)
    inventory_outcomes: list[dict[str, Any]] = []

    if requested is None:
        ordered = sorted(candidate_set)
    else:
        ordered = []
        for symbol in _validate_ordered_symbols(requested):
            if symbol in candidate_set:
                ordered.append(symbol)
                continue
            inventory_outcomes.append(
                {
                    "symbol": symbol,
                    "status": "explicit_not_in_warehouse_inventory",
                    "listing_boundary": "unknown",
                    "inventory_membership": "not_observed",
                }
            )

    runnable: list[str] = []
    cooled: list[tuple[str, datetime, str]] = []
    for symbol in ordered:
        previous_row = previous.get(symbol)
        cooldown = None if retry_failed else _active_cooldown(previous_row, now)
        if cooldown is None:
            runnable.append(symbol)
            continue
        failed_status = str(
            states.get(symbol, {}).get("latest_source_status")
            or (previous_row or {}).get("status")
            or "source_failed"
        )
        cooled.append((symbol, cooldown, failed_status))

    if requested is None:
        runnable.sort(key=lambda symbol: _fairness_key(states, symbol))
    selected = runnable[:max_codes]
    deferred = runnable[max_codes:]

    for symbol, until, failed_status in sorted(cooled)[:COOLDOWN_OUTCOME_LIMIT]:
        inventory_outcomes.append(
            {
                "symbol": symbol,
                "status": "deferred_failure_cooldown",
                "retry_after_utc": until.astimezone(UTC).isoformat(timespec="seconds"),
                "previous_failure_status": failed_status,
            }
        )
    if len(cooled) > COOLDOWN_OUTCOME_LIMIT:
        inventory_outcomes.append(
            {
                "symbol": "",
                "status": "deferred_failure_cooldown_summary",
                "deferred_count": len(cooled),
                "omitted_count": len(cooled) - COOLDOWN_OUTCOME_LIMIT,
                "sample_symbols": sorted(symbol for symbol, _, _ in cooled)[
                    :COOLDOWN_OUTCOME_LIMIT
                ],
            }
        )
    return selected, inventory_outcomes, deferred


def _base_record(
    *,
    symbol: str,
    scope_hash: str,
    status: str,
    now: datetime,
) -> dict[str, Any]:
    canonical = normalize_bond_symbol(symbol)
    return {
        "schema_version": REPORT_VERSION,
        "recorded_at_utc": now.astimezone(UTC).isoformat(timespec="seconds"),
        "scope_hash": scope_hash,
        "checkpoint_key": make_checkpoint_key(canonical),
        "source_identity": SOURCE_IDENTITY,
        "source": "sina",
        "symbol": canonical,
        "market": market_for_symbol(canonical),
        "requested_window": "complete_source_response",
        "normalizer_version": REPORT_VERSION,
        "status": status,
        "listing_boundary": "unknown",
        "source_retention": "unknown",
        "history_completeness": "not_certified",
        "first_source_date_is_listing_boundary": False,
    }


# ---------------------------------------------------------------------------
# Adapters: owned artifact storage.
# ---------------------------------------------------------------------------


def _atomic_json_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = (
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default, allow_nan=False)
        + "\n"
    )
    temporary = path.with_suffix(".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, path)


def _persist_json_artifact(path: Path, rendered: str) -> Path:
    """Write a content-addressed artifact, refusing a hash collision."""

    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise ValueError(
                f"content-addressed snapshot exists with different content: {path.name}"
            )
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return path


def _source_snapshot_path(directory: Path, snapshot: SourceSnapshot) -> Path:
    return directory / f"{snapshot.symbol}-{snapshot.raw_content_sha256}.json"


def _persist_source_snapshot(directory: Path, snapshot: SourceSnapshot) -> Path:
    """Write the immutable, content-addressed source frame for one code."""

    payload = {
        "schema_version": SOURCE_SNAPSHOT_SCHEMA,
        "source_identity": SOURCE_IDENTITY,
        "symbol": snapshot.symbol,
        "market": snapshot.market,
        "source_window": {
            "kind": "complete_source_response",
            "first_observed_source_date": snapshot.first_source_date,
            "last_observed_source_date": snapshot.last_source_date,
            "first_date_is_listing_boundary": False,
        },
        "source_row_count": snapshot.source_row_count,
        "raw_content_sha256": snapshot.raw_content_sha256,
        "raw_content_hash_semantics": (
            "canonical JSON hash of the full DataFrame returned by AKShare, before controller "
            "normalization; not a wire-byte hash"
        ),
        "normalized_ledger_sha256": snapshot.normalized_ledger_sha256,
        "normalizer_version": REPORT_VERSION,
        "raw_source_frame": snapshot.raw_payload,
        "normalized_ledger": list(snapshot.normalized_ledger),
    }
    rendered = (
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default, allow_nan=False)
        + "\n"
    )
    return _persist_json_artifact(_source_snapshot_path(directory, snapshot), rendered)


def _persist_sql_snapshot(
    directory: Path,
    symbol: str,
    stage: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[Path, str]:
    """Write the content-addressed read-only SQL snapshot for one code and stage."""

    payload = warehouse_snapshot_payload(symbol, stage, rows)
    content_hash = sha256_hex(
        {key: value for key, value in payload.items() if key != "snapshot_sha256"}
    )
    stored = {**payload, "snapshot_sha256": content_hash}
    rendered = (
        json.dumps(stored, ensure_ascii=False, indent=2, default=_json_default, allow_nan=False)
        + "\n"
    )
    path = directory / f"{payload['symbol']}-warehouse-{stage}-{content_hash}.json"
    return _persist_json_artifact(path, rendered), content_hash


# ---------------------------------------------------------------------------
# Adapters: warehouse reads.
# ---------------------------------------------------------------------------


class ConvertibleReader(Protocol):
    """Read-only exact-code warehouse interface used by the controller."""

    def __enter__(self) -> ConvertibleReader: ...

    def __exit__(self, _exc: object, _value: object, _traceback: object) -> None: ...

    def read_convertible_snapshot_symbols(self) -> tuple[list[Any], dict[str, Any]]: ...

    def read_convertible_history_overview(self) -> tuple[list[dict[str, Any]], dict[str, Any]]: ...

    def read_convertible_bars_with_provenance(self, symbol: str) -> list[dict[str, Any]]: ...


class MySQLConvertibleReader:
    """SELECT-only MySQL reader for the convertible-bond history inventory.

    Every per-code read is parameterized by the exact stored symbol, which is
    what keeps the legacy null-symbol series out of per-code evidence.
    """

    _ALLOWED_TABLES = frozenset({CONVERTIBLE_HISTORY_TABLE, CONVERTIBLE_SNAPSHOT_TABLE})
    _REQUIRED_COLUMNS = frozenset({"symbol", "data_date", "open", "high", "low", "close"})

    def __init__(self, connection: Any = None) -> None:
        self.connection = connection
        self._column_cache: dict[str, set[str]] = {}

    def __enter__(self) -> MySQLConvertibleReader:
        if self.connection is None:
            import pymysql

            from app.data_fetch.configs.db_config import DB_CONFIG

            self.connection = pymysql.connect(
                **DB_CONFIG,
                charset="utf8mb4",
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )
        return self

    def __exit__(self, _exc: object, _value: object, _traceback: object) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _execute(self, sql: str, parameters: Sequence[Any] = ()) -> list[dict[str, Any]]:
        if self.connection is None:
            raise RuntimeError("MySQLConvertibleReader must be used as a context manager")
        statement = sql.strip().upper()
        if not statement.startswith("SELECT ") or any(
            marker in sql for marker in ("--", "/*", "#", ";")
        ):
            raise ValueError("convertible history controller permits SELECT statements only")
        with self.connection.cursor() as cursor:
            # pymysql %-formats the statement whenever args is not None, even for an
            # empty tuple, so a literal DATE_FORMAT '%Y-%m-%d' raises "not enough
            # arguments for format string". Parameterless statements must pass None.
            cursor.execute(sql, tuple(parameters) if parameters else None)
            return list(cursor.fetchall())

    def _table_columns(self, table: str) -> set[str]:
        if table in self._column_cache:
            return self._column_cache[table]
        if table not in self._ALLOWED_TABLES:
            raise ValueError(f"unsupported warehouse table {table!r}")
        rows = self._execute(
            "SELECT COLUMN_NAME AS column_name FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            (table,),
        )
        columns = {str(row.get("column_name", "")).casefold() for row in rows}
        self._column_cache[table] = columns
        return columns

    def read_convertible_snapshot_symbols(self) -> tuple[list[Any], dict[str, Any]]:
        table = CONVERTIBLE_SNAPSHOT_TABLE
        columns = self._table_columns(table)
        if not columns:
            return [], {"table": table, "status": "table_missing"}
        if not {"symbol", "observed_at"}.issubset(columns):
            return [], {
                "table": table,
                "status": "schema_mismatch",
                "missing_columns": sorted({"symbol", "observed_at"} - columns),
            }
        latest = self._execute(f"SELECT MAX(observed_at) AS snapshot_at FROM {table}")
        snapshot_at = latest[0].get("snapshot_at") if latest else None
        if snapshot_at is None:
            return [], {
                "table": table,
                "status": "no_observations",
                "snapshot_at": None,
                "selection": "symbols at the latest exact observed_at batch",
            }
        rows = self._execute(
            f"SELECT DISTINCT symbol FROM {table} WHERE observed_at = %s ORDER BY symbol",
            (snapshot_at,),
        )
        return (
            [row["symbol"] for row in rows],
            {
                "table": table,
                "status": "read",
                "snapshot_at": _json_default(snapshot_at),
                "raw_symbol_count": len(rows),
                "selection": "symbols at the latest exact observed_at batch",
            },
        )

    def _provenance_by_symbol(self, table: str) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
        rows = self._execute(
            "SELECT symbol, COALESCE(NULLIF(source, ''), 'legacy_unknown') AS source, "
            f"COUNT(*) AS row_count FROM {table} GROUP BY symbol, source"
        )
        totals: dict[str, int] = {}
        unrecognized: dict[str, int] = {}
        per_symbol: dict[str, dict[str, int]] = {}
        status_counts: dict[str, int] = {}
        for row in rows:
            source = str(row.get("source") or "legacy_unknown")
            count = int(row.get("row_count") or 0)
            totals[source] = totals.get(source, 0) + count
            raw_symbol = row.get("symbol")
            if try_normalize_bond_symbol(raw_symbol) is None:
                unrecognized[source] = unrecognized.get(source, 0) + count
                continue
            key = normalize_bond_symbol(raw_symbol)
            per_symbol.setdefault(key, {})[source] = count
        for counts in per_symbol.values():
            legacy_count = counts.get("legacy_unknown", 0)
            canonical_count = sum(
                count for source, count in counts.items() if source != "legacy_unknown"
            )
            if legacy_count and canonical_count:
                status = "mixed_canonical_and_legacy_unknown"
            elif legacy_count:
                status = "legacy_unknown_only"
            else:
                status = "canonical_only"
            status_counts[status] = status_counts.get(status, 0) + 1
        summary = {
            "source_field_available": "source" in self._table_columns(table),
            "row_count_by_source": dict(sorted(totals.items())),
            "valid_history_symbols_by_provenance_status": dict(sorted(status_counts.items())),
            "unrecognized_symbol_row_count_by_source": dict(sorted(unrecognized.items())),
            "canonical_source_semantics": (
                "any non-empty source other than legacy_unknown is reported as canonical provenance; "
                "it does not certify source completeness"
            ),
        }
        return summary, per_symbol

    def _unattributable_rows(self, table: str) -> dict[str, Any]:
        """Aggregate the legacy series that carries no usable instrument key."""

        columns = self._table_columns(table)
        unattributable = (
            "symbol IS NULL OR symbol = '' OR LOWER(LEFT(symbol, 2)) NOT IN ('sh', 'sz', 'bj')"
        )
        groups = self._execute(
            "SELECT COALESCE(NULLIF(symbol, ''), '<no-symbol>') AS symbol_key, "
            "COALESCE(NULLIF(source, ''), 'legacy_unknown') AS source, COUNT(*) AS row_count "
            f"FROM {table} WHERE {unattributable} GROUP BY symbol_key, source ORDER BY symbol_key"
        )
        distinct_values = sorted({str(row.get("symbol_key")) for row in groups})
        total_rows = sum(int(row.get("row_count") or 0) for row in groups)
        by_source: dict[str, int] = {}
        null_symbol_rows = 0
        for row in groups:
            source = str(row.get("source") or "legacy_unknown")
            count = int(row.get("row_count") or 0)
            by_source[source] = by_source.get(source, 0) + count
            if str(row.get("symbol_key")) == "<no-symbol>":
                null_symbol_rows += count
        evidence: dict[str, Any] = {
            "row_count": total_rows,
            "unique_symbol_value_count": len(distinct_values),
            "duplicate_row_count": total_rows - len(distinct_values),
            "no_symbol_row_count": null_symbol_rows,
            "row_count_by_source": dict(sorted(by_source.items())),
            "attribution_policy": (
                "rows without a recognized instrument symbol are preserved as aggregate evidence only; "
                "they are never attributed to a code by price or sequence matching and are excluded "
                "from every per-code completeness claim"
            ),
        }
        if "date" in columns:
            legacy = self._execute(
                "SELECT COUNT(*) AS row_count, "
                "COUNT(DISTINCT CASE WHEN `date` IS NOT NULL AND `date` <> '' THEN `date` END) "
                "AS distinct_business_dates, "
                "MIN(CASE WHEN `date` IS NOT NULL AND `date` <> '' THEN `date` END) AS first_business_date, "
                "MAX(CASE WHEN `date` IS NOT NULL AND `date` <> '' THEN `date` END) AS last_business_date, "
                "MIN(data_date) AS first_collection_date, MAX(data_date) AS last_collection_date, "
                "SUM(CASE WHEN `date` IS NOT NULL AND `date` <> '' AND data_date IS NOT NULL "
                "AND `date` <> DATE_FORMAT(data_date, '%Y-%m-%d') THEN 1 ELSE 0 END) "
                f"AS rows_where_data_date_differs FROM {table} WHERE symbol IS NULL"
            )
            row = legacy[0] if legacy else {}
            evidence["business_date_evidence"] = {
                "row_count": int(row.get("row_count") or 0),
                "distinct_business_dates": int(row.get("distinct_business_dates") or 0),
                "first_business_date": _json_default(row.get("first_business_date")),
                "last_business_date": _json_default(row.get("last_business_date")),
                "first_collection_date": _json_default(row.get("first_collection_date")),
                "last_collection_date": _json_default(row.get("last_collection_date")),
                "rows_where_data_date_differs_from_business_date": int(
                    row.get("rows_where_data_date_differs") or 0
                ),
                "semantics": (
                    "rows without a symbol keep the source business date in `date`; data_date is the "
                    "legacy load/collection date and is not treated as the business date"
                ),
            }
        return evidence

    def read_convertible_history_overview(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        table = CONVERTIBLE_HISTORY_TABLE
        columns = self._table_columns(table)
        if not columns:
            return [], {"table": table, "status": "table_missing"}
        if not self._REQUIRED_COLUMNS.issubset(columns):
            return [], {
                "table": table,
                "status": "schema_mismatch",
                "missing_columns": sorted(self._REQUIRED_COLUMNS - columns),
            }
        rows = self._execute(
            "SELECT symbol, COUNT(*) AS row_count, COUNT(DISTINCT data_date) AS date_key_count, "
            "COUNT(*) - COUNT(DISTINCT data_date) AS duplicate_date_rows, "
            "MIN(data_date) AS first_date, MAX(data_date) AS last_date, "
            "SUM(CASE WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL "
            f"THEN 1 ELSE 0 END) AS incomplete_ohlc_rows FROM {table} GROUP BY symbol ORDER BY symbol"
        )
        summary, per_symbol = self._provenance_by_symbol(table)
        recognized: list[dict[str, Any]] = []
        for row in rows:
            symbol = try_normalize_bond_symbol(row.get("symbol"))
            if symbol is None:
                continue
            row["symbol"] = symbol
            counts = per_symbol.get(symbol, {})
            row["row_count_by_source"] = dict(sorted(counts.items()))
            row["canonical_row_count"] = sum(
                count for source, count in counts.items() if source != "legacy_unknown"
            )
            row["legacy_unknown_row_count"] = counts.get("legacy_unknown", 0)
            row["source_field_available"] = "source" in columns
            if not counts:
                row["provenance_status"] = "provenance_unavailable"
            elif row["legacy_unknown_row_count"] and row["canonical_row_count"]:
                row["provenance_status"] = "mixed_canonical_and_legacy_unknown"
            elif row["legacy_unknown_row_count"]:
                row["provenance_status"] = "legacy_unknown_only"
            else:
                row["provenance_status"] = "canonical_only"
            recognized.append(row)
        evidence = {
            "table": table,
            "status": "read",
            "source_provenance": summary,
            "unattributable_rows": self._unattributable_rows(table),
            "business_date_semantics": (
                "canonical rows use data_date; rows with no symbol and a native `date` value use that "
                "source business date instead of the legacy load/collection date stored in data_date"
            ),
            "coverage_semantics": "inventory only: first/last dates do not establish gap-free coverage",
        }
        return recognized, evidence

    def read_convertible_bars_with_provenance(self, symbol: str) -> list[dict[str, Any]]:
        table = CONVERTIBLE_HISTORY_TABLE
        canonical = normalize_bond_symbol(symbol)
        columns = self._table_columns(table)
        missing = self._REQUIRED_COLUMNS - columns
        if missing:
            raise RuntimeError(
                f"{table} lacks columns required for exact verification: {sorted(missing)}"
            )
        source_expression = (
            "COALESCE(NULLIF(source, ''), 'legacy_unknown') AS source"
            if "source" in columns
            else "'legacy_unknown' AS source"
        )
        volume_expression = "volume" if "volume" in columns else "NULL AS volume"
        return self._execute(
            f"SELECT data_date, open, high, low, close, {volume_expression}, {source_expression} "
            f"FROM {table} WHERE symbol = %s ORDER BY data_date",
            (canonical,),
        )


# ---------------------------------------------------------------------------
# Adapters: killable source probe and managed repair.
# ---------------------------------------------------------------------------


class SourceWorkerCrashedError(RuntimeError):
    """The source child exited without returning a result payload."""


def _run_killable_probe(
    target: Any,
    args: Sequence[Any],
    timeout_seconds: int,
    start_method: str = "spawn",
) -> dict[str, Any]:
    """Run ``target`` in a terminable child and return its JSON payload.

    Production always uses the ``spawn`` context so the child cannot inherit the
    parent's database handles; ``start_method`` stays a parameter because the
    timeout boundary itself must be testable without a vendor call.
    """

    if timeout_seconds <= 0:
        raise ValueError("source timeout must be positive")
    context: Any = multiprocessing.get_context(start_method)
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(target=target, args=(sending, *args), daemon=True)
    process.start()
    sending.close()
    try:
        if not receiving.poll(timeout=timeout_seconds):
            process.terminate()
            process.join(timeout=1)
            raise TimeoutError(f"convertible full-history probe exceeded {timeout_seconds} seconds")
        payload: Any = receiving.recv()
    except EOFError as exc:
        process.join(timeout=1)
        exit_code = process.exitcode
        raise SourceWorkerCrashedError(
            f"convertible source worker exited without a result (exit_code={exit_code})"
        ) from exc
    finally:
        receiving.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("convertible source worker returned a malformed frame")
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    if not isinstance(payload.get("rows"), list):
        raise ValueError("convertible source worker returned a malformed frame")
    payload.setdefault("columns", sorted({key for row in payload["rows"] for key in row}))
    return payload


def _raw_convertible_source_worker(connection: Any, symbol: str) -> None:
    """Fetch one full source frame in a killable process and return its raw columns."""

    try:
        import akshare as ak

        frame = ak.bond_zh_hs_cov_daily(symbol=symbol)
        payload = {
            "columns": [str(column) for column in frame.columns],
            "rows": json.loads(frame.to_json(orient="records", force_ascii=False)),
        }
        connection.send(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    except BaseException as exc:
        reason = f"{type(exc).__name__}: {str(exc)[:2000]}"
        connection.send(json.dumps({"error": reason}, ensure_ascii=False, separators=(",", ":")))
    finally:
        connection.close()


def fetch_raw_convertible_source(symbol: str, timeout_seconds: int) -> dict[str, Any]:
    """Fetch a full-history Sina source frame with a terminable process timeout."""

    canonical = normalize_bond_symbol(symbol)
    return _run_killable_probe(_raw_convertible_source_worker, (canonical,), timeout_seconds)


async def _load_active_script_source() -> str:
    """Load the active producer's registered source for its shared claim identity."""

    from sqlalchemy import select

    from app.db.database import async_session_maker
    from app.models.akshare_mgmt import DataScript

    async with async_session_maker() as session:
        script = (
            await session.execute(select(DataScript).where(DataScript.script_id == SCRIPT_ID))
        ).scalar_one_or_none()
    if script is None or not script.is_active:
        raise RuntimeError(f"{SCRIPT_ID} is missing or inactive")
    return str(script.source)


def _claim_identity(
    snapshot: SourceSnapshot,
    source_timeout_seconds: int,
) -> tuple[str, str, dict[str, Any]]:
    """Build the shared claim identity for the exact-symbol managed repair."""

    parameters = {
        "symbol": snapshot.symbol,
        "_call_timeout": max(1, min(int(source_timeout_seconds), MAX_SOURCE_TIMEOUT_SECONDS)),
        "_ingest_mode": "backfill",
    }
    source_window = {
        "symbol": snapshot.symbol,
        "market": snapshot.market,
        "source_identity": SOURCE_IDENTITY,
        "requested_window": "complete_source_response",
        "first_observed_source_date": snapshot.first_source_date,
        "last_observed_source_date": snapshot.last_source_date,
        "raw_content_sha256": snapshot.raw_content_sha256,
        "normalized_ledger_sha256": snapshot.normalized_ledger_sha256,
        "normalizer_version": REPORT_VERSION,
    }
    period_key = "backfill"
    claim_key = "bond-convertible-history:v1:" + sha256_hex(
        {"parameters": parameters, "source_window": source_window, "period_key": period_key}
    )
    return claim_key, period_key, {"parameters": parameters, "source_window": source_window}


async def _managed_repair(
    symbol: str,
    source: str,
    snapshot: SourceSnapshot,
    *,
    timeout_seconds: float,
    source_timeout_seconds: int,
    dispatch_receipt: Mapping[str, Any] | None = None,
) -> Any:
    """Run the existing exact-symbol producer through the managed script service."""

    from app.db.database import async_session_maker
    from app.services.akshare.script import AkshareScriptService

    claim_key, period_key, identity = _claim_identity(snapshot, source_timeout_seconds)
    parameters: dict[str, Any] = {
        **identity["parameters"],
        "source": source,
        "claim_key": claim_key,
        "period_key": period_key,
        "source_identity": SOURCE_IDENTITY,
        "raw_content_sha256": snapshot.raw_content_sha256,
        "normalized_ledger_sha256": snapshot.normalized_ledger_sha256,
        "first_source_date": snapshot.first_source_date,
        "last_source_date": snapshot.last_source_date,
    }
    if dispatch_receipt is not None:
        parameters["dispatch_receipt"] = dict(dispatch_receipt)
    async with async_session_maker() as session:
        service = AkshareScriptService(session)
        return await service.run_script(
            SCRIPT_ID,
            parameters=parameters,
            operator_id=None,
            task_id=None,
            timeout_seconds=timeout_seconds,
        )


def _execution_status(execution: Any) -> str:
    raw = getattr(execution, "status", None)
    if raw is None:
        raw = getattr(execution, "value", None)
    return str(getattr(raw, "value", raw) or "unknown").casefold()


def _is_pending(execution: Any) -> bool:
    return _execution_status(execution) in frozenset({"pending", "queued", "running", "waiting"})


# ---------------------------------------------------------------------------
# Budget accounting.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchBudget:
    """Soft total wall-clock deadline for one bounded apply batch."""

    time_budget_seconds: int
    source_timeout_seconds: int
    started_at: float
    monotonic: Any = time.monotonic

    def remaining_seconds(self) -> float:
        return max(0.0, self.started_at + self.time_budget_seconds - self.monotonic())

    def clamped_source_timeout(self, remaining: float) -> int | None:
        """Bound vendor traffic by both the per-code timeout and the batch deadline.

        The managed repair plus its post-write SQL verification must still fit in the
        batch, so the probe may only use what is left after that reservation.
        """

        allowed = remaining - MANAGED_DISPATCH_RESERVE_SECONDS
        if allowed < 1:
            return None
        return max(1, min(self.source_timeout_seconds, int(allowed)))

    def managed_timeout(self, remaining: float) -> float | None:
        """Reserve time for the managed call plus the post-write SQL verification."""

        if remaining < MIN_MANAGED_REMAINING_SECONDS:
            return None
        available = remaining - MANAGED_DISPATCH_RESERVE_SECONDS
        if available < 0.1:
            return None
        return min(float(self.source_timeout_seconds), available)


BUDGET_ENFORCEMENT = {
    "kind": "soft_total_wall_clock_deadline",
    "includes": [
        "CLI inventory snapshot and history overview reads when launched through main()",
        "source probes",
        "read-only SQL verification",
        "managed coordinator claim wait and execution",
        "post-write SQL verification",
    ],
    "hard_stop_enforced_by_controller": False,
    "outer_process_hard_stop_required": True,
    "recommended_outer_timeout_seconds": DEFAULT_APPLY_SECONDS + 20,
    "note": (
        "The supervising process must enforce the hard stop and preserve unknown commit state "
        "on timeout."
    ),
}

LIFECYCLE_POLICY = (
    "source earliest observation is not listing date; empty responses, legacy/unknown rows, and "
    "source absence do not prove expiry, source retention, or full history"
)
VOLUME_UNIT_POLICY = "volume unit is not asserted by this controller"
RAW_HASH_SEMANTICS = (
    "canonical JSON hash of the full AKShare DataFrame response, before controller normalization; "
    "not a wire-byte hash"
)


def _source_metadata(snapshot: SourceSnapshot, artifact: Path) -> dict[str, Any]:
    return {
        "source_identity": SOURCE_IDENTITY,
        "source_first_observed_date": snapshot.first_source_date,
        "source_last_observed_date": snapshot.last_source_date,
        "source_first_date_is_listing_boundary": False,
        "source_row_count": snapshot.source_row_count,
        "normalized_observation_count": len(snapshot.normalized_ledger),
        "source_duplicate_rows_deduplicated_by_producer_normalizer": snapshot.duplicate_source_dates,
        "raw_content_sha256": snapshot.raw_content_sha256,
        "raw_content_hash_semantics": RAW_HASH_SEMANTICS,
        "normalized_ledger_sha256": snapshot.normalized_ledger_sha256,
        "source_snapshot_path": str(artifact),
        "captured_at_utc": snapshot.captured_at_utc,
    }


def _apply_exit_code(outcomes: Sequence[Mapping[str, Any]]) -> int:
    """Map outcome statuses to the exit code the recovery worker classifies."""

    statuses = {str(row.get("status", "")) for row in outcomes}
    if not statuses:
        return EXIT_ALL_VERIFIED
    if statuses & ATTENTION_STATUSES:
        return EXIT_ATTENTION_REQUIRED
    if statuses & SOURCE_FAILURE_STATUSES:
        if statuses <= SUCCESS_STATUSES | SOURCE_FAILURE_STATUSES:
            return EXIT_SOURCE_FAILURE
        return EXIT_ATTENTION_REQUIRED
    if statuses & NORMAL_INCOMPLETE_STATUSES:
        return EXIT_DEFERRED
    if statuses <= SUCCESS_STATUSES:
        return EXIT_ALL_VERIFIED
    return EXIT_ATTENTION_REQUIRED


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------


async def _resolve(value: Any) -> Any:
    resolved = await value if inspect.isawaitable(value) else value
    return resolved


async def _reconcile_symbol(
    symbol: str,
    *,
    scope_hash: str,
    budget: BatchBudget,
    progress_path: Path,
    snapshot_dir: Path,
    reader: ConvertibleReader,
    source_fetcher: Any,
    scheduler_run: Any,
    source_resolver: Any,
    utc_now: Any,
    monotonic: Any,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Probe one exact code, repair a real difference, then re-verify with fresh SQL."""

    started_clock = monotonic()
    remaining = budget.remaining_seconds()
    source_timeout = budget.clamped_source_timeout(remaining)
    if source_timeout is None:
        return _finish(
            progress_path,
            _base_record(
                symbol=symbol, scope_hash=scope_hash, status="deferred_budget", now=utc_now()
            ),
            reason="insufficient_wall_clock_budget_before_source_probe",
            remaining_seconds=round(remaining, 3),
        )

    attempt_id = uuid.uuid4().hex
    attempted_at = utc_now().astimezone(UTC).isoformat(timespec="seconds")
    append_progress(
        progress_path,
        {
            **_base_record(
                symbol=symbol, scope_hash=scope_hash, status="attempt_started", now=utc_now()
            ),
            "attempt_id": attempt_id,
            "attempted_at_utc": attempted_at,
        },
    )
    state["source_requests_made"] = True

    try:
        raw_payload = await _resolve(source_fetcher(symbol, source_timeout))
    except SourceWorkerCrashedError as exc:
        return _finish(
            progress_path,
            _base_record(
                symbol=symbol, scope_hash=scope_hash, status="source_worker_crashed", now=utc_now()
            ),
            attempt_id=attempt_id,
            attempted_at_utc=attempted_at,
            failure_phase="source_worker_exit",
            error=_safe_error(exc),
            source_timeout_seconds=source_timeout,
            source_elapsed_seconds=round(monotonic() - started_clock, 3),
        )
    except Exception as exc:
        return _finish(
            progress_path,
            _base_record(
                symbol=symbol, scope_hash=scope_hash, status="source_failed", now=utc_now()
            ),
            attempt_id=attempt_id,
            attempted_at_utc=attempted_at,
            failure_phase="source_fetch_or_normalization",
            error=_safe_error(exc),
            source_timeout_seconds=source_timeout,
            source_elapsed_seconds=round(monotonic() - started_clock, 3),
        )

    source_probe_at = utc_now().astimezone(UTC).isoformat(timespec="seconds")
    append_progress(
        progress_path,
        {
            **_base_record(
                symbol=symbol,
                scope_hash=scope_hash,
                status="source_response_received",
                now=utc_now(),
            ),
            "attempt_id": attempt_id,
            "attempted_at_utc": attempted_at,
            "source_probe_at_utc": source_probe_at,
        },
    )
    source_elapsed = round(monotonic() - started_clock, 3)

    try:
        snapshot = normalize_source_payload(symbol, raw_payload, captured_at=utc_now())
    except Exception as exc:
        return _finish(
            progress_path,
            _base_record(
                symbol=symbol, scope_hash=scope_hash, status="source_invalid", now=utc_now()
            ),
            attempt_id=attempt_id,
            attempted_at_utc=attempted_at,
            failure_phase="source_response_validation",
            error=_safe_error(exc),
            source_timeout_seconds=source_timeout,
            source_elapsed_seconds=source_elapsed,
            source_probe_at_utc=source_probe_at,
        )

    try:
        artifact = _persist_source_snapshot(snapshot_dir, snapshot)
    except Exception as exc:
        return _finish(
            progress_path,
            _base_record(
                symbol=symbol, scope_hash=scope_hash, status="verification_failed", now=utc_now()
            ),
            attempt_id=attempt_id,
            attempted_at_utc=attempted_at,
            failure_phase="source_snapshot_persistence",
            error=_safe_error(exc),
            source_timeout_seconds=source_timeout,
            source_elapsed_seconds=source_elapsed,
            source_probe_at_utc=source_probe_at,
        )

    record = _base_record(
        symbol=symbol, scope_hash=scope_hash, status="source_response_received", now=utc_now()
    )
    record.update(
        {
            "attempt_id": attempt_id,
            "attempted_at_utc": attempted_at,
            "source_timeout_seconds": source_timeout,
            "source_elapsed_seconds": source_elapsed,
            "source_probe_at_utc": source_probe_at,
        }
    )
    record.update(_source_metadata(snapshot, artifact))
    record["source_window_claim"] = {
        "requested_window": "complete_source_response",
        "first_observed_source_date": snapshot.first_source_date,
        "last_observed_source_date": snapshot.last_source_date,
        "source_raw_content_sha256": snapshot.raw_content_sha256,
        "normalizer_version": REPORT_VERSION,
        "is_listing_boundary_claim": False,
    }

    if not snapshot.normalized_ledger:
        return _finish(
            progress_path,
            record,
            status="source_empty_unverified",
            error="empty source response is unresolved; no date or lifecycle boundary is inferred",
        )

    try:
        before_rows = reader.read_convertible_bars_with_provenance(snapshot.symbol)
        before_path, before_hash = _persist_sql_snapshot(
            snapshot_dir, snapshot.symbol, "before", before_rows
        )
    except Exception as exc:
        return _finish(
            progress_path,
            record,
            status="verification_failed",
            failure_phase="pre_write_sql_verification",
            error=_safe_error(exc),
        )

    comparison_before = compare_daily_ledgers(snapshot.normalized_ledger, before_rows)
    record["warehouse_before_snapshot_path"] = str(before_path)
    record["warehouse_before_snapshot_sha256"] = before_hash
    record["warehouse_provenance_before"] = warehouse_provenance(before_rows)
    record["comparison_before"] = comparison_before
    record["source_only_gap_distribution_before"] = classify_source_only_dates(
        comparison_before, before_rows
    )

    if comparison_before["date_key_and_ohlc_match"]:
        return _finish(
            progress_path,
            record,
            status="verified_unchanged",
            verification="fresh_autocommit_sql_exact_keys_and_ohlc",
            write_attempted=False,
        )

    remaining = budget.remaining_seconds()
    managed_timeout = budget.managed_timeout(remaining)
    if managed_timeout is None:
        return _finish(
            progress_path,
            record,
            status="deferred_budget",
            reason="insufficient_budget_for_managed_dispatch_and_post_write_sql",
            remaining_seconds=round(remaining, 3),
        )

    if state.get("resolved_source") is None:
        try:
            state["resolved_source"] = str(await _resolve(source_resolver()))
        except Exception as exc:
            return _finish(
                progress_path,
                record,
                status="managed_preflight_failed",
                failure_phase="registered_source_resolution",
                error=_safe_error(exc),
                database_write_may_have_occurred=False,
                managed_scheduler_invoked=False,
            )
    source = str(state["resolved_source"])

    claim_key, period_key, identity = _claim_identity(snapshot, source_timeout)
    dispatch_receipt = {
        "attempt_id": attempt_id,
        "scope_hash": scope_hash,
        "checkpoint_key": record["checkpoint_key"],
        "claim_key": claim_key,
    }
    record["managed_claim"] = {
        "claim_key": claim_key,
        "period_key": period_key,
        "source_identity": SOURCE_IDENTITY,
        "raw_content_sha256": snapshot.raw_content_sha256,
        "normalized_ledger_sha256": snapshot.normalized_ledger_sha256,
        "first_source_date": snapshot.first_source_date,
        "last_source_date": snapshot.last_source_date,
        "identity": identity,
    }
    record["managed_scheduler_invoked"] = True
    record["managed_wall_clock_timeout_seconds"] = round(managed_timeout, 3)
    record["database_write_may_have_occurred"] = True
    state["managed_invoked"] = True
    state["database_write_possible"] = True

    try:
        invocation = scheduler_run(
            snapshot.symbol,
            source,
            snapshot,
            timeout_seconds=managed_timeout,
            source_timeout_seconds=source_timeout,
            dispatch_receipt=dispatch_receipt,
        )
        if inspect.isawaitable(invocation):
            execution = await asyncio.wait_for(invocation, timeout=managed_timeout + 1.0)
        else:
            execution = invocation
    except (TimeoutError, asyncio.TimeoutError):
        return _finish(
            progress_path,
            record,
            status="managed_outcome_unknown",
            failure_phase="managed_call",
            error="managed call exceeded the controller's total wall-clock budget; commit state is unknown",
            managed_timeout=True,
        )
    except Exception as exc:
        return _finish(
            progress_path,
            record,
            status="managed_execution_failed",
            failure_phase="managed_call",
            error=_safe_error(exc),
            managed_timeout=False,
        )

    record["managed_timeout"] = False
    record["execution_id"] = getattr(execution, "execution_id", None) or getattr(
        execution, "id", None
    )
    record["execution_status"] = _execution_status(execution)
    record["execution_error"] = getattr(execution, "error_message", None)
    if _is_pending(execution):
        return _finish(progress_path, record, status="managed_execution_pending")
    if record["execution_status"] == "unknown":
        return _finish(
            progress_path,
            record,
            status="managed_outcome_unknown",
            error="managed scheduler returned no execution receipt",
        )
    if record["execution_status"] != "completed":
        return _finish(progress_path, record, status="managed_execution_failed")

    try:
        after_rows = reader.read_convertible_bars_with_provenance(snapshot.symbol)
        after_path, after_hash = _persist_sql_snapshot(
            snapshot_dir, snapshot.symbol, "after", after_rows
        )
    except Exception as exc:
        return _finish(
            progress_path,
            record,
            status="verification_failed",
            failure_phase="post_write_sql_verification",
            error=_safe_error(exc),
        )

    comparison_after = compare_daily_ledgers(snapshot.normalized_ledger, after_rows)
    record["warehouse_after_snapshot_path"] = str(after_path)
    record["warehouse_after_snapshot_sha256"] = after_hash
    record["warehouse_provenance_after"] = warehouse_provenance(after_rows)
    record["comparison_after"] = comparison_after
    record["source_only_gap_distribution_after"] = classify_source_only_dates(
        comparison_after, after_rows
    )
    record["verification"] = "fresh_autocommit_sql_exact_keys_and_ohlc"
    return _finish(
        progress_path,
        record,
        status=(
            "verified_source_sequence"
            if comparison_after["date_key_and_ohlc_match"]
            else "post_write_mismatch"
        ),
    )


def _finish(path: Path, record: dict[str, Any], **updates: Any) -> dict[str, Any]:
    """Apply the terminal fields, append the checkpoint, and return the outcome."""

    status = updates.pop("status", None)
    if status is not None:
        record["status"] = str(status)
    record.update(updates)
    append_progress(path, record)
    return record


async def run_apply(
    symbols: Sequence[str],
    universe: Sequence[Mapping[str, Any]],
    *,
    max_codes: int,
    progress_path: Path,
    snapshot_dir: Path,
    time_budget_seconds: int,
    source_timeout_seconds: int,
    reader_factory: Any = MySQLConvertibleReader,
    source_fetcher: Any = fetch_raw_convertible_source,
    scheduler_run: Any = _managed_repair,
    source_resolver: Any = _load_active_script_source,
    retry_failed: bool = False,
    budget_started_at: float | None = None,
    unattributable_rows: Mapping[str, Any] | None = None,
    utc_now: Any = None,
    monotonic: Any = time.monotonic,
) -> tuple[dict[str, Any], int]:
    """Probe, repair, then independently compare full exact-symbol sequences.

    ``unattributable_rows`` is the aggregate legacy evidence already gathered by
    the read-only overview pass; it is carried into the report so a per-code
    completeness claim can never absorb those rows.
    """

    if not 1 <= time_budget_seconds <= MAX_APPLY_SECONDS:
        raise ValueError(f"time budget must be 1..{MAX_APPLY_SECONDS} seconds")
    if not 1 <= source_timeout_seconds <= MAX_SOURCE_TIMEOUT_SECONDS:
        raise ValueError(f"source timeout must be 1..{MAX_SOURCE_TIMEOUT_SECONDS} seconds")
    if not 1 <= max_codes <= MAX_APPLY_CODES:
        raise ValueError(f"max_codes must be between 1 and {MAX_APPLY_CODES}")
    requested = _validate_ordered_symbols(symbols) if symbols else None
    if requested is not None and len(requested) > max_codes:
        raise ValueError(f"an apply invocation cannot exceed max_codes={max_codes}")

    clock = utc_now or (lambda: datetime.now(UTC))
    progress = read_progress(progress_path)
    previous = latest_progress_by_symbol(progress)
    candidate_symbols = [str(row["symbol"]) for row in universe if row.get("symbol")]
    scope_hash = make_scope_hash(
        candidate_symbols if requested is None else requested,
        universe,
    )
    budget = BatchBudget(
        time_budget_seconds=time_budget_seconds,
        source_timeout_seconds=source_timeout_seconds,
        started_at=budget_started_at if budget_started_at is not None else monotonic(),
        monotonic=monotonic,
    )
    selected, inventory_outcomes, deferred = select_apply_symbols(
        candidate_symbols,
        requested,
        max_codes,
        previous,
        clock(),
        retry_failed,
        progress,
    )
    generated_at = clock().astimezone(UTC).isoformat(timespec="seconds")

    outcomes: list[dict[str, Any]] = []
    state: dict[str, Any] = {
        "source_requests_made": False,
        "managed_invoked": False,
        "database_write_possible": False,
        "resolved_source": None,
    }
    with reader_factory() as reader:
        for index, symbol in enumerate(selected):
            outcome = await _reconcile_symbol(
                symbol,
                scope_hash=scope_hash,
                budget=budget,
                progress_path=progress_path,
                snapshot_dir=snapshot_dir,
                reader=reader,
                source_fetcher=source_fetcher,
                scheduler_run=scheduler_run,
                source_resolver=source_resolver,
                utc_now=clock,
                monotonic=monotonic,
                state=state,
            )
            outcomes.append(outcome)
            if outcome["status"] == "deferred_budget":
                for skipped in selected[index + 1 :]:
                    outcomes.append(
                        _finish(
                            progress_path,
                            _base_record(
                                symbol=skipped,
                                scope_hash=scope_hash,
                                status="deferred_budget",
                                now=clock(),
                            ),
                            reason="batch_wall_clock_budget_exhausted",
                            remaining_seconds=round(budget.remaining_seconds(), 3),
                        )
                    )
                break

    report: dict[str, Any] = {
        "schema_version": REPORT_VERSION,
        "report_type": REPORT_VERSION,
        "generated_at_utc": generated_at,
        "finished_at_utc": clock().astimezone(UTC).isoformat(timespec="seconds"),
        "mode": "managed_bounded_convertible_history_reconciliation",
        "source_requests_made": bool(state["source_requests_made"]),
        "managed_scheduler_invoked": bool(state["managed_invoked"]),
        "writes_database": bool(state["database_write_possible"]),
        "budget_enforcement": BUDGET_ENFORCEMENT,
        "lifecycle_policy": LIFECYCLE_POLICY,
        "turnover_or_volume_unit_policy": VOLUME_UNIT_POLICY,
        "history_completeness": "not_certified",
        "outcomes": outcomes,
        "deferred_inventory": inventory_outcomes,
        "deferred_inventory_count": len(
            [row for row in inventory_outcomes if str(row.get("status", "")).startswith("deferred")]
        ),
        "not_selected_count": len(deferred),
        "unattributable_rows": dict(unattributable_rows or {}),
        "unattributable_rows_excluded_from_per_code_claims": True,
    }
    _report_limits(
        report,
        max_codes=max_codes,
        time_budget_seconds=time_budget_seconds,
        source_timeout_seconds=source_timeout_seconds,
        progress_path=progress_path,
        snapshot_dir=snapshot_dir,
        scope_hash=scope_hash,
    )
    exit_code = _apply_exit_code(outcomes)
    if not outcomes:
        report["status"] = (
            "no_runnable_candidates" if candidate_symbols else "no_inventory_candidates"
        )
        report["apply_max_codes"] = max_codes
        report["source_requests_made"] = False
        report["writes_database"] = False
        exit_code = EXIT_DEFERRED
    return report, exit_code


def _report_limits(
    report: dict[str, Any],
    *,
    max_codes: int,
    time_budget_seconds: int,
    source_timeout_seconds: int,
    progress_path: Path,
    snapshot_dir: Path,
    scope_hash: str,
) -> dict[str, Any]:
    report.update(
        {
            "max_codes": max_codes,
            "time_budget_seconds": time_budget_seconds,
            "source_timeout_seconds_max": source_timeout_seconds,
            "scope_hash": scope_hash,
            "progress_file": str(progress_path),
            "snapshot_dir": str(snapshot_dir),
        }
    )
    return report


def build_overview_report(
    *,
    snapshot_symbols: Iterable[Any],
    snapshot_evidence: Mapping[str, Any],
    history_rows: Iterable[Mapping[str, Any]],
    history_evidence: Mapping[str, Any],
    progress: Sequence[Mapping[str, Any]],
    max_codes: int,
    now: datetime,
    extra_universe: Sequence[Mapping[str, Any]] | None = None,
    universe: Sequence[Mapping[str, Any]] | None = None,
    invalid_codes: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Build the read-only inventory and bounded apply plan; probes nothing."""

    rows = list(history_rows)
    if universe is None:
        universe, computed_invalid = build_convertible_universe(snapshot_symbols, rows)
    else:
        computed_invalid = {}
    if extra_universe:
        universe, _, _ = merge_universe(universe, extra_universe)
    history = {str(row["symbol"]): row for row in rows if row.get("symbol")}
    latest = latest_progress_by_symbol(progress)
    candidates: list[dict[str, Any]] = []
    for entry in universe:
        symbol = str(entry["symbol"])
        item = dict(entry)
        warehouse_row = history.get(symbol)
        if warehouse_row is None:
            item["warehouse"] = {"status": "no_warehouse_rows"}
        else:
            item["warehouse"] = {
                key: _json_default(warehouse_row.get(key))
                for key in _OVERVIEW_METRIC_FIELDS
                if key in warehouse_row
            }
            for key in (
                "row_count_by_source",
                "canonical_row_count",
                "legacy_unknown_row_count",
                "source_field_available",
                "provenance_status",
            ):
                if key in warehouse_row:
                    item["warehouse"][key] = warehouse_row[key]
        previous_row = latest.get(symbol)
        item["latest_controller_status"] = (
            str(previous_row.get("status", "unknown")) if previous_row else "unknown"
        )
        item["listing_boundary"] = "unknown"
        item["source_retention"] = "unknown"
        item["status"] = "unverified"
        item["head_gap_status"] = "unverified"
        item["internal_gap_status"] = "unverified"
        item["tail_gap_status"] = "unverified"
        candidates.append(item)
    provenance = dict(history_evidence.get("source_provenance") or {})
    return {
        "schema_version": REPORT_VERSION,
        "report_type": REPORT_VERSION,
        "generated_at_utc": now.astimezone(UTC).isoformat(timespec="seconds"),
        "mode": "warehouse_overview_and_bounded_apply_plan",
        "writes_database": False,
        "source_requests_made": False,
        "apply_requires_explicit_flag": True,
        "source_identity": SOURCE_IDENTITY,
        "source_snapshot": dict(snapshot_evidence),
        "historical_inventory": {**dict(history_evidence), "source_provenance": provenance},
        "unattributable_rows": dict(history_evidence.get("unattributable_rows") or {}),
        "invalid_or_unrecognized_codes": dict(invalid_codes or computed_invalid),
        "candidate_count": len(candidates),
        "apply_max_codes": max_codes,
        "candidate_symbols": candidates,
        "history_completeness": "not_certified",
        "lifecycle_policy": LIFECYCLE_POLICY,
        "turnover_or_volume_unit_policy": VOLUME_UNIT_POLICY,
        "limitations": [
            "warehouse minimum/maximum dates are inventory only",
            "source first observation does not establish listing or source inception",
            "legacy_unknown provenance remains visible and is not converted into a lifecycle claim",
            "empty source response never verifies a code or closes a date interval",
        ],
    }


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    _atomic_json_write(path, report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only plan and explicitly bounded managed recovery for convertible-bond history."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="probe and repair via the existing managed script service",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="exact sh/sz/bj convertible symbols; defaults to inventory-prioritized symbols",
    )
    parser.add_argument("--max-codes", type=int, default=DEFAULT_APPLY_CODES)
    parser.add_argument(
        "--time-budget-seconds",
        type=int,
        default=DEFAULT_APPLY_SECONDS,
        help=(
            f"soft total apply wall-clock budget, maximum {MAX_APPLY_SECONDS} seconds; the "
            "supervising process must hard-stop at budget plus 20 seconds"
        ),
    )
    parser.add_argument(
        "--source-timeout-seconds",
        type=int,
        default=DEFAULT_SOURCE_TIMEOUT_SECONDS,
        help=f"killable source timeout per exact code, maximum {MAX_SOURCE_TIMEOUT_SECONDS} seconds",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="bypass the 24-hour cooldown for actual source failures/empty responses",
    )
    parser.add_argument("--progress-file", type=Path, default=DEFAULT_PROGRESS_FILE)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument(
        "--universe-file",
        type=Path,
        default=None,
        help="issuance-master JSON merged with warehouse inventory; never replaces progress",
    )
    parser.add_argument("--report", type=Path, default=None, help="write the JSON report here")
    return parser


def main(
    argv: Sequence[str] | None = None,
    reader_factory: Any = MySQLConvertibleReader,
    source_fetcher: Any = fetch_raw_convertible_source,
    scheduler_run: Any = _managed_repair,
    source_resolver: Any = _load_active_script_source,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if not 1 <= args.max_codes <= MAX_APPLY_CODES:
            raise ValueError(f"--max-codes must be between 1 and {MAX_APPLY_CODES}")
        if not 1 <= args.time_budget_seconds <= MAX_APPLY_SECONDS:
            raise ValueError(f"--time-budget-seconds must be between 1 and {MAX_APPLY_SECONDS}")
        if not 1 <= args.source_timeout_seconds <= MAX_SOURCE_TIMEOUT_SECONDS:
            raise ValueError(
                f"--source-timeout-seconds must be between 1 and {MAX_SOURCE_TIMEOUT_SECONDS}"
            )
        if args.report is not None and args.report.resolve() == args.progress_file.resolve():
            raise ValueError("--report and --progress-file must be different paths")
        requested = _validate_ordered_symbols(args.symbols) if args.symbols else None
        if requested is not None and len(requested) > args.max_codes:
            raise ValueError("--symbols count cannot exceed --max-codes")
        progress = read_progress(args.progress_file)
        budget_started_at = time.monotonic()
        with reader_factory() as reader:
            snapshot_symbols, snapshot_evidence = reader.read_convertible_snapshot_symbols()
            history_rows, history_evidence = reader.read_convertible_history_overview()
        universe, invalid = build_convertible_universe(snapshot_symbols, history_rows)
        extras: list[dict[str, Any]] = []
        added = enriched = 0
        if args.universe_file is not None:
            extras = load_extra_universe(args.universe_file)
            universe, added, enriched = merge_universe(universe, extras)
        now = datetime.now(UTC)
        if not args.apply:
            report = build_overview_report(
                snapshot_symbols=snapshot_symbols,
                snapshot_evidence=snapshot_evidence,
                history_rows=history_rows,
                history_evidence=history_evidence,
                progress=progress,
                max_codes=args.max_codes,
                now=now,
                extra_universe=extras,
                universe=universe,
                invalid_codes=invalid,
            )
            exit_code = 0
        else:
            report, exit_code = asyncio.run(
                run_apply(
                    requested or [],
                    universe,
                    max_codes=args.max_codes,
                    progress_path=args.progress_file,
                    snapshot_dir=args.snapshot_dir,
                    time_budget_seconds=args.time_budget_seconds,
                    source_timeout_seconds=args.source_timeout_seconds,
                    reader_factory=reader_factory,
                    source_fetcher=source_fetcher,
                    scheduler_run=scheduler_run,
                    source_resolver=source_resolver,
                    retry_failed=args.retry_failed,
                    budget_started_at=budget_started_at,
                    unattributable_rows=history_evidence.get("unattributable_rows"),
                )
            )
        report["universe_merge"] = {
            "universe_file": str(args.universe_file) if args.universe_file else None,
            "issuance_master_symbol_count": len(extras),
            "added_symbol_count": added,
            "enriched_existing_symbol_count": enriched,
            "merged_universe_count": len(universe),
        }
        if args.apply:
            report["invalid_or_unrecognized_codes"] = invalid
        if args.report is not None:
            _write_report(args.report, report)
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
        return exit_code
    except Exception as exc:
        failure = {
            "schema_version": REPORT_VERSION,
            "report_type": REPORT_VERSION,
            "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": (
                "managed_bounded_convertible_history_reconciliation"
                if args.apply
                else "warehouse_overview_and_bounded_apply_plan"
            ),
            "status": "controller_failed",
            "error": _safe_error(exc),
            "writes_database": False,
            "source_requests_made": False,
        }
        if args.report is not None:
            _write_report(args.report, failure)
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        return EXIT_ATTENTION_REQUIRED


if __name__ == "__main__":
    raise SystemExit(main())
