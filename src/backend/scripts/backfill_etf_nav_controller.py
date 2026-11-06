"""Bounded, resumable ETF NAV full-history recovery controller (iteration 204, 204-B05-03 / AC05).

This is the executable that the full-history recovery worker shells out to for the
``etf`` rotation:

    .venv/bin/python scripts/backfill_etf_nav_controller.py \
        --probe --apply --max-codes 5 --time-budget-seconds 240 \
        --output-dir var/reports/iteration203/etf_nav_controller --report <run>/etf-report.json

Semantics that are load-bearing here
------------------------------------
* **NAV is a lagged observation, not a bar.**  Every row keeps the *source business date*
  (``VALUE_DATE``) it was published with; the controller's own fetch instant is recorded
  separately as ``captured_at``.  ``source_last_nav_date`` is never derived from
  ``captured_at``, and a lagging tail is reported as ``source_tail.calendar_day_lag`` with
  ``freshness_proven: false`` rather than as a missing bar.  Publication lag classes (QDII
  T+1, money-fund accrual, suspension/source-end) stay source facts, not gaps to fill.
* **Never fabricate.**  A NAV value is never interpolated, forward-filled or synthesised;
  a source whose first available date cannot be proven keeps
  ``listing_boundary_status: "unknown"`` / ``SOURCE_LIMITED`` and is reported as such.
* **No flags = read-only plan.**  ``--probe`` only inspects source reachability and the
  first/last available NAV dates; ``--apply`` is the only mode that writes to the warehouse
  or to the checkpoint state.  ``--max-codes`` and ``--time-budget-seconds`` are real
  bounds on vendor traffic, not advisories.
* **Idempotent per-code checkpoints.**  ``<output-dir>/checkpoints.jsonl`` is append-only;
  a code already ``verified_for_source_snapshot`` (or ``archived_history_complete``) is
  skipped, and a code quarantined as ``invalidated_source_metric_not_nav`` (money-fund
  income and other non-NAV metrics) stays quarantined -- a later verify event for the same
  code does not un-quarantine it, it is counted as a conflict and reported.
* **No fighting the four continuous shards.**  ``ai-for-investor-etf-nav-backfill@0..3``
  keep their own state under ``<output-dir>/shard-N/`` and walk the sorted universe
  forward from their own cursor.  This controller reads those cursors and their newest run
  receipts **read-only** and excludes each shard's in-flight plus near-future window from
  its own selection; it never writes inside a ``shard-N/`` directory.
* **Protected legacy scope.**  Reviewed legacy NAV/cache rows are fingerprinted before and
  after every managed write; a changed baseline downgrades the outcome to attention
  instead of letting the batch report a success.

Layering
--------
The pure core (selection, checkpoint merge, budget accounting, snapshot/diff emission,
report assembly) has no I/O and takes injected adapters; the adapters (fixture JSON, live
Sina/East Money/warehouse) are separate classes at the bottom.  Everything that needs the
live source is ``NOT_RUN`` in development and is labelled in the report.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

BACKEND_ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "etf-nav-controller-run-report-v1"
REPORT_TYPE = "etf_nav_controller_run"

DEFAULT_MAX_CODES = 5
DEFAULT_TIME_BUDGET_SECONDS = 240.0
DEFAULT_OUTPUT_DIR = "var/reports/iteration203/etf_nav_controller"
DEFAULT_PROTECTED_SCOPE_MANIFEST = "data/reviewed_etf_protected_legacy_scope.json"

#: Conservative per-code cost estimates used for budget accounting.  The measured cost of
#: the completed codes in the same run replaces the seed as soon as one code finishes.
PROBE_SECONDS_SEED = 20.0
APPLY_SECONDS_SEED = 45.0

CHECKPOINT_FILENAME = "checkpoints.jsonl"
LEDGER_FILENAME = "allcode-pending-ledger.jsonl"
EVENTS_FILENAME = "events.jsonl"
CURSOR_FILENAME = "cursor.json"
LOCK_FILENAME = "controller.lock"
SNAPSHOT_DIRNAME = "source-snapshots"
DIFF_DIRNAME = "diffs"
LISTING_DIRNAME = "sina-listing-snapshots"
SHARD_DIR_PATTERN = re.compile(r"^shard-\d+$")

#: Statuses the recovery worker's ``_classify_etf`` accepts.  Anything outside these sets
#: would be reported as "unhandled ETF outcome status", so the controller never emits one.
SUCCESS_STATUSES = frozenset({"verified_read_only", "applied_and_verified"})
SOURCE_DEFERRED_STATUSES = frozenset({"source_probe_timeout"})
BUDGET_DEFERRED_STATUSES = frozenset(
    {"not_started_time_budget_exhausted", "not_applied_time_budget_insufficient"}
)
ATTENTION_STATUSES = frozenset(
    {
        "pending_target_reconciliation",
        "lifecycle_boundary_mismatch",
        "protected_legacy_guard_blocked",
        "managed_execution_failed",
        "managed_execution_pending",
        "deferred_managed_time_budget_exhausted",
        "applied_but_reconciliation_pending",
        "source_semantic_rejected",
        "source_or_apply_error",
        "protected_legacy_baseline_read_failed",
        "protected_legacy_baseline_mismatch",
        "protected_legacy_scope_changed_after_managed",
    }
)
KNOWN_STATUSES = (
    SUCCESS_STATUSES | SOURCE_DEFERRED_STATUSES | BUDGET_DEFERRED_STATUSES | ATTENTION_STATUSES
)

PROVEN_IDENTITY_STATUSES = frozenset(
    {
        "verified_by_sina_etf_node",
        "verified_by_etf_daily_master",
        "verified_by_reviewed_lifecycle_manifest",
    }
)
QUARANTINE_IDENTITY_STATUS = "verified_source_metric_excluded_from_nav"

#: The bounded batch never certifies full history; AC05 stays open until every code has an
#: independently evidenced start *and* target end.
HISTORY_COMPLETENESS = "not_certified_by_a_bounded_batch_or_source_snapshot"
NAV_LAG_INTERPRETATION = (
    "publication_lag_is_not_a_missing_bar_and_is_never_backfilled_by_this_controller"
)
SOURCE_LIMITED_FIRST_DATE = "SOURCE_LIMITED"

#: Warehouse column names the protected legacy fingerprint is reported under.
PROTECTED_FINGERPRINT_KEYS = (
    "protected_scope_codes_count",
    "protected_scope_codes_sha256",
    "protected_legacy_nav_rows",
    "protected_legacy_nav_sha256",
    "protected_cache_rows",
    "protected_cache_sha256",
)


class NotRunError(RuntimeError):
    """Raised by an adapter whose live dependency was never exercised in development."""


# ---------------------------------------------------------------------------
# canonical hashing primitives (pure)
# ---------------------------------------------------------------------------


def canonical_json(value: object) -> str:
    """Deterministic JSON encoding used for every content hash and artifact body."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_decimal(value: float | int | str | None) -> str | None:
    """Canonicalise a source numeric to the target's 4dp decimal string for hashing.

    ``None`` stays ``None``: a source-native missing NAV field is never treated as zero.
    """
    if value is None:
        return None
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.0001")))
    except (InvalidOperation, ValueError):
        return f"raw:{value}"


def gzip_stable(text: str) -> bytes:
    """Gzip with a zero mtime so identical content yields identical bytes on every run."""
    return gzip.compress(text.encode("utf-8"), mtime=0)


# ---------------------------------------------------------------------------
# NAV observations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NavRow:
    """One source NAV observation keyed by its own business date.

    ``business_date`` is the source's ``VALUE_DATE`` (the NAV reference date).  The
    controller's fetch instant is *not* stored here on purpose; it lives on the snapshot as
    ``captured_at`` so a lagged publication can never be relabelled as a same-day bar.
    """

    business_date: str
    unit_nav: float | str | None = None
    accumulated_nav: float | str | None = None
    daily_growth: float | str | None = None
    purchase_status: str | None = None
    redemption_status: str | None = None

    def as_json_row(self) -> list[Any]:
        return [
            self.business_date,
            self.unit_nav,
            self.accumulated_nav,
            self.daily_growth,
            self.purchase_status,
            self.redemption_status,
        ]

    @staticmethod
    def from_json_row(row: Sequence[Any]) -> NavRow:
        values = list(row) + [None] * (6 - len(row))
        return NavRow(
            business_date=str(values[0]),
            unit_nav=values[1],
            accumulated_nav=values[2],
            daily_growth=values[3],
            purchase_status=values[4],
            redemption_status=values[5],
        )


@dataclass(frozen=True)
class TargetNavRow:
    """A row read back from the canonical warehouse table with fresh SQL."""

    business_date: str
    unit_nav: float | str | None = None
    accumulated_nav: float | str | None = None
    daily_growth: float | str | None = None


@dataclass(frozen=True)
class NavProbe:
    """Source reachability plus the first/last available NAV dates for one code."""

    fund_code: str
    provider: str
    source_complete: bool
    rows: tuple[NavRow, ...]
    first_nav_date: str | None
    last_nav_date: str | None
    observed_at: str
    semantic_evidence: dict[str, Any] = field(default_factory=dict)
    provider_evidence: dict[str, Any] = field(default_factory=dict)
    retention_limited: bool = False
    is_nav_metric: bool = True
    timed_out: bool = False
    error: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)


# ---------------------------------------------------------------------------
# snapshot + diff artifacts (pure)
# ---------------------------------------------------------------------------


def business_keys_sha256(rows: Sequence[NavRow]) -> str:
    return sha256_hex(canonical_json(sorted(row.business_date for row in rows)))


def values_sha256(rows: Sequence[NavRow]) -> str:
    table = sorted(
        [
            row.business_date,
            normalize_decimal(row.unit_nav),
            normalize_decimal(row.accumulated_nav),
            normalize_decimal(row.daily_growth),
        ]
        for row in rows
    )
    return sha256_hex(canonical_json(table))


def build_snapshot_content(probe: NavProbe, listing_boundary_status: str) -> dict[str, Any]:
    """Content-only snapshot payload: excludes ``captured_at`` so hashes stay comparable."""
    rows = sorted(probe.rows, key=lambda row: row.business_date)
    return {
        "fund_code": probe.fund_code,
        "provider": probe.provider,
        "provider_evidence": probe.provider_evidence,
        "source_complete": probe.source_complete,
        "source_first_nav_date": probe.first_nav_date,
        "source_last_nav_date": probe.last_nav_date,
        "row_count": len(rows),
        "business_keys_sha256": business_keys_sha256(rows),
        "values_sha256": values_sha256(rows),
        "listing_boundary_status": listing_boundary_status,
        "rows": [row.as_json_row() for row in rows],
    }


def snapshot_sha256_of(content: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json(content))


def write_snapshot(
    snapshot_dir: Path,
    content: Mapping[str, Any],
    captured_at: str,
    sha256: str | None = None,
) -> tuple[Path, str]:
    digest = sha256 or snapshot_sha256_of(content)
    path = snapshot_dir / f"{content['fund_code']}-{digest}.json.gz"
    if path.is_file():
        # Content-addressed: an identical source snapshot keeps its original capture stamp
        # instead of being rewritten on every pass, so repeated runs are byte-stable.
        return path, digest
    payload = dict(content)
    payload["snapshot_sha256"] = digest
    payload["captured_at"] = captured_at
    _write_bytes_atomically(path, gzip_stable(canonical_json(payload)))
    return path, digest


def diff_summary(
    source_rows: Sequence[NavRow],
    target_rows: Sequence[TargetNavRow],
    *,
    max_sample: int = 20,
) -> dict[str, Any]:
    """Source-vs-target reconciliation on business keys and per-field values."""
    source_by_date = {row.business_date: row for row in source_rows}
    target_by_date: dict[str, TargetNavRow] = {}
    duplicate_dates: dict[str, int] = {}
    for row in target_rows:
        if row.business_date in target_by_date:
            duplicate_dates[row.business_date] = duplicate_dates.get(row.business_date, 1) + 1
        else:
            target_by_date[row.business_date] = row

    missing = sorted(set(source_by_date) - set(target_by_date))
    extra = sorted(set(target_by_date) - set(source_by_date))
    duplicates = sorted(duplicate_dates)

    mismatch_counts = {"unit_nav": 0, "accumulated_nav": 0, "growth": 0}
    mismatch_examples: list[dict[str, Any]] = []
    for business_date in sorted(set(source_by_date) & set(target_by_date)):
        source = source_by_date[business_date]
        target = target_by_date[business_date]
        for field_name, source_value, target_value in (
            ("unit_nav", source.unit_nav, target.unit_nav),
            ("accumulated_nav", source.accumulated_nav, target.accumulated_nav),
            ("growth", source.daily_growth, target.daily_growth),
        ):
            if normalize_decimal(source_value) != normalize_decimal(target_value):
                mismatch_counts[field_name] += 1
                if len(mismatch_examples) < max_sample:
                    mismatch_examples.append(
                        {
                            "business_date": business_date,
                            "field": field_name,
                            "source": normalize_decimal(source_value),
                            "target": normalize_decimal(target_value),
                        }
                    )

    exact_match = not (missing or extra or duplicates or any(mismatch_counts.values()))
    return {
        "source_rows": len(source_rows),
        "target_rows": len(target_rows),
        "missing_source_key_count": len(missing),
        "missing_source_key_sample": missing[:max_sample],
        "extra_target_key_count": len(extra),
        "extra_target_key_sample": extra[:max_sample],
        "duplicate_target_key_count": len(duplicates),
        "duplicate_target_key_sample": duplicates[:max_sample],
        "value_mismatch_counts": mismatch_counts,
        "value_mismatch_examples": mismatch_examples,
        "exact_match": exact_match,
        "details": {
            "missing_source_key_dates": missing,
            "extra_target_key_dates": extra,
            "duplicate_target_key_dates": duplicates,
            "value_mismatches": mismatch_examples,
        },
    }


def write_diff(
    diff_dir: Path,
    fund_code: str,
    snapshot_digest: str,
    phase: str,
    summary: Mapping[str, Any],
    content: Mapping[str, Any],
) -> Path:
    payload = {
        "fund_code": fund_code,
        "phase": phase,
        "snapshot_sha256": snapshot_digest,
        "business_keys_sha256": content["business_keys_sha256"],
        "values_sha256": content["values_sha256"],
        "summary": {key: value for key, value in summary.items() if key != "details"},
        "details": summary.get("details", {}),
    }
    path = diff_dir / f"{fund_code}-{snapshot_digest}-{phase}.diff.json.gz"
    _write_bytes_atomically(path, gzip_stable(canonical_json(payload)))
    return path


def source_tail(
    requested_end_date: str,
    source_last_nav_date: str | None,
    *,
    terminal: bool = False,
) -> dict[str, Any]:
    """Lag diagnostic: a date gap is a publication fact, never an inferred missing bar."""
    lag: int | None = None
    if source_last_nav_date:
        try:
            last = date.fromisoformat(source_last_nav_date)
            end = date.fromisoformat(requested_end_date)
        except ValueError:
            lag = None
        else:
            lag = (end - last).days
    if terminal:
        status = "archived_terminal_matches_reviewed_lifecycle"
    elif source_last_nav_date is None:
        status = "source_unreachable_no_tail_evidence"
    elif lag and lag > 0:
        status = "lagged_publication_tail_not_evidence_of_missing_bars"
    else:
        status = "tail_matches_requested_end_date"
    return {
        "status": status,
        "requested_end_date": requested_end_date,
        "source_last_nav_date": source_last_nav_date,
        "calendar_day_lag": lag,
        "freshness_proven": False,
        "interpretation": NAV_LAG_INTERPRETATION,
    }


# ---------------------------------------------------------------------------
# checkpoint merge (pure)
# ---------------------------------------------------------------------------

VERIFIED_CHECKPOINT_STATUSES = frozenset(
    {"verified_for_source_snapshot", "archived_history_complete"}
)
QUARANTINE_CHECKPOINT_STATUS = "invalidated_source_metric_not_nav"


@dataclass
class CheckpointRecord:
    fund_code: str
    status: str
    snapshot_sha256: str | None = None
    business_keys_sha256: str | None = None
    values_sha256: str | None = None
    provider: str | None = None
    source_first_nav_date: str | None = None
    source_last_nav_date: str | None = None
    source_row_count: int | None = None
    source_snapshot_path: str | None = None
    target_diff_path: str | None = None
    listing_boundary_status: str = "unknown"
    historical_scope_status: str = "listing_boundary_unknown"
    verified_at: str | None = None
    semantic_evidence: dict[str, Any] | None = None
    source_tail: dict[str, Any] | None = None
    quarantine: dict[str, Any] | None = None

    def is_verified(self) -> bool:
        return self.status in VERIFIED_CHECKPOINT_STATUSES

    def is_quarantined(self) -> bool:
        return self.status == QUARANTINE_CHECKPOINT_STATUS


@dataclass
class CheckpointMerge:
    """Merged per-code checkpoint state plus the audit trail of how it was decided."""

    records: dict[str, CheckpointRecord] = field(default_factory=dict)
    quarantined: dict[str, CheckpointRecord] = field(default_factory=dict)
    sticky_conflicts: list[str] = field(default_factory=list)
    malformed_lines: int = 0

    @property
    def verified_codes(self) -> set[str]:
        return {code for code, record in self.records.items() if record.is_verified()}


def merge_checkpoint_events(lines: Iterable[str]) -> CheckpointMerge:
    """Fold the append-only checkpoint log into current per-code state.

    Quarantine is sticky: once a code is invalidated as ``not NAV``, a later ``checkpoint``
    verify event cannot restore it, because retrying a money-fund income metric into a NAV
    success would corrupt the canonical series.  Such events are counted instead.
    """
    merge = CheckpointMerge()
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            merge.malformed_lines += 1
            continue
        if not isinstance(event, dict):
            merge.malformed_lines += 1
            continue
        code = event.get("fund_code")
        status = event.get("status")
        if not isinstance(code, str) or not isinstance(status, str):
            merge.malformed_lines += 1
            continue
        record = CheckpointRecord(
            fund_code=code,
            status=status,
            snapshot_sha256=_opt_str(event.get("snapshot_sha256")),
            business_keys_sha256=_opt_str(event.get("business_keys_sha256")),
            values_sha256=_opt_str(event.get("values_sha256")),
            provider=_opt_str(event.get("provider")),
            source_first_nav_date=_opt_str(event.get("source_first_nav_date")),
            source_last_nav_date=_opt_str(event.get("source_last_nav_date")),
            source_row_count=_opt_int(event.get("source_row_count")),
            source_snapshot_path=_opt_str(event.get("source_snapshot_path")),
            target_diff_path=_opt_str(event.get("target_diff_path")),
            listing_boundary_status=str(event.get("listing_boundary_status") or "unknown"),
            historical_scope_status=str(
                event.get("historical_scope_status") or "listing_boundary_unknown"
            ),
            verified_at=_opt_str(event.get("verified_at") or event.get("invalidated_at")),
            semantic_evidence=_opt_dict(event.get("semantic_evidence")),
            source_tail=_opt_dict(event.get("source_tail")),
            quarantine=_opt_dict(event.get("evidence")),
        )
        if status == QUARANTINE_CHECKPOINT_STATUS:
            merge.quarantined[code] = record
            merge.records[code] = record
            continue
        if code in merge.quarantined:
            merge.sticky_conflicts.append(code)
            continue
        merge.records[code] = record
    return merge


# ---------------------------------------------------------------------------
# listing identity plane (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CodeIdentity:
    """Reviewed listing/product identity for one fund code."""

    fund_code: str
    product_identity_status: str
    eligible_for_nav_probe: bool
    current_sina_node_member: bool
    reviewed_lifecycle: dict[str, Any] | None
    lifecycle_identity_conflict: bool
    listing_boundary_status: str
    nav_quarantined: bool = False
    semantic_quarantine: dict[str, Any] | None = None
    sina_name: str | None = None

    def as_listing_evidence(self) -> dict[str, Any]:
        return {
            "fund_code": self.fund_code,
            "eligible_for_nav_probe": self.eligible_for_nav_probe,
            "product_identity_status": self.product_identity_status,
            "current_sina_node_member": self.current_sina_node_member,
            "reviewed_lifecycle": self.reviewed_lifecycle,
            "lifecycle_identity_conflict": self.lifecycle_identity_conflict,
            "listing_boundary_status": self.listing_boundary_status,
        }


@dataclass(frozen=True)
class ListingSnapshot:
    observed_at: str
    source: str
    rows: tuple[dict[str, Any], ...]
    complete: bool
    error: str | None = None

    @property
    def codes(self) -> list[str]:
        return sorted({str(row.get("fund_code")) for row in self.rows if row.get("fund_code")})

    @property
    def name_by_code(self) -> dict[str, str]:
        names: dict[str, str] = {}
        for row in self.rows:
            code = row.get("fund_code")
            name = row.get("fund_name")
            if isinstance(code, str) and isinstance(name, str):
                names.setdefault(code, name)
        return names

    @property
    def source_row_count(self) -> int:
        return len(self.rows)

    @property
    def unique_code_count(self) -> int:
        return len({str(row.get("fund_code")) for row in self.rows if row.get("fund_code")})


def build_identity(
    code: str,
    listing: ListingSnapshot,
    *,
    master_codes: set[str],
    reviewed_lifecycle: Mapping[str, Mapping[str, Any]],
    semantic_quarantine: Mapping[str, Mapping[str, Any]],
    nav_only_codes: set[str],
) -> CodeIdentity:
    """Resolve one code's identity from the reviewed planes, fail-closed.

    Identity planes: the live Sina ETF node, the canonical ETF daily/NAV master (codes that
    already hold NAV rows), and the reviewed lifecycle manifest.  A code proven to be a
    non-NAV metric goes to quarantine instead of the probe queue.
    """
    lifecycle = reviewed_lifecycle.get(code)
    quarantine = semantic_quarantine.get(code)
    in_sina = code in set(listing.codes)
    in_master = code in master_codes

    if quarantine is not None:
        return CodeIdentity(
            fund_code=code,
            product_identity_status=QUARANTINE_IDENTITY_STATUS,
            eligible_for_nav_probe=False,
            current_sina_node_member=in_sina,
            reviewed_lifecycle=dict(lifecycle) if lifecycle else None,
            lifecycle_identity_conflict=bool(lifecycle and lifecycle.get("conflicts")),
            listing_boundary_status=str(
                (lifecycle or {}).get("listing_boundary_status", "unknown")
            ),
            nav_quarantined=True,
            semantic_quarantine=dict(quarantine),
            sina_name=listing.name_by_code.get(code),
        )

    if lifecycle is not None:
        return CodeIdentity(
            fund_code=code,
            product_identity_status="verified_by_reviewed_lifecycle_manifest",
            eligible_for_nav_probe=True,
            current_sina_node_member=in_sina,
            reviewed_lifecycle=dict(lifecycle),
            lifecycle_identity_conflict=bool(lifecycle.get("conflicts")),
            listing_boundary_status=str(
                lifecycle.get("listing_boundary_status", "known_from_reviewed_official_sources")
            ),
            sina_name=listing.name_by_code.get(code),
        )

    if in_sina:
        return CodeIdentity(
            fund_code=code,
            product_identity_status="verified_by_sina_etf_node",
            eligible_for_nav_probe=True,
            current_sina_node_member=True,
            reviewed_lifecycle=None,
            lifecycle_identity_conflict=False,
            listing_boundary_status="unknown",
            sina_name=listing.name_by_code.get(code),
        )

    if in_master:
        return CodeIdentity(
            fund_code=code,
            product_identity_status="verified_by_etf_daily_master",
            eligible_for_nav_probe=True,
            current_sina_node_member=False,
            reviewed_lifecycle=None,
            lifecycle_identity_conflict=False,
            listing_boundary_status="unknown",
            sina_name=listing.name_by_code.get(code),
        )

    return CodeIdentity(
        fund_code=code,
        product_identity_status="needs_product_review",
        eligible_for_nav_probe=False,
        current_sina_node_member=False,
        reviewed_lifecycle=None,
        lifecycle_identity_conflict=False,
        listing_boundary_status="unknown",
        nav_quarantined=code in nav_only_codes,
        sina_name=listing.name_by_code.get(code),
    )


# ---------------------------------------------------------------------------
# shard non-collision + selection (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShardWindow:
    """Codes a continuous sibling shard is working through right now."""

    shard: str
    cursor_code: str | None
    in_flight_codes: tuple[str, ...]
    forward_codes: tuple[str, ...]

    @property
    def owned(self) -> set[str]:
        return set(self.in_flight_codes) | set(self.forward_codes)


def shard_windows(
    universe: Sequence[str],
    windows_by_shard: Mapping[str, tuple[str | None, Sequence[str]]],
    *,
    lookahead: int,
) -> list[ShardWindow]:
    """Project each shard's cursor forward over the sorted universe.

    The shards walk the sorted code list from their own cursor, so their near-future window
    is predictable from the cursor alone; this keeps the bounded recovery batch on codes the
    continuous path is not about to touch.
    """
    ordered = sorted(universe)
    position = {code: index for index, code in enumerate(ordered)}
    result: list[ShardWindow] = []
    for shard in sorted(windows_by_shard):
        cursor_code, in_flight = windows_by_shard[shard]
        forward: tuple[str, ...] = ()
        if lookahead > 0 and cursor_code in position:
            start = position[cursor_code] + 1
            forward = tuple(ordered[start : start + lookahead])
        elif lookahead > 0 and cursor_code is None and ordered:
            forward = tuple(ordered[:lookahead])
        result.append(
            ShardWindow(
                shard=shard,
                cursor_code=cursor_code,
                in_flight_codes=tuple(in_flight),
                forward_codes=forward,
            )
        )
    return result


def select_candidates(
    *,
    universe: Sequence[str],
    identities: Mapping[str, CodeIdentity],
    merge: CheckpointMerge,
    cursor_code: str | None,
    max_codes: int,
    shard_owned: set[str],
) -> tuple[list[str], dict[str, int]]:
    """Deterministic bounded selection: cursor-first, then wrap, skipping closed work.

    Skipped: verified checkpoints, the sticky quarantine set, codes a sibling continuous
    shard owns, and codes without a proven listing identity.
    """
    ordered = sorted(set(universe))
    skipped = {
        "skip_verified": 0,
        "skip_quarantined": 0,
        "skip_shard_owned": 0,
        "skip_identity_unproven": 0,
    }
    eligible: list[str] = []
    for code in ordered:
        record = merge.records.get(code)
        if code in merge.quarantined or (record is not None and record.is_quarantined()):
            skipped["skip_quarantined"] += 1
            continue
        if record is not None and record.is_verified():
            skipped["skip_verified"] += 1
            continue
        identity = identities.get(code)
        if identity is None or not identity.eligible_for_nav_probe:
            skipped["skip_identity_unproven"] += 1
            continue
        if code in shard_owned:
            skipped["skip_shard_owned"] += 1
            continue
        eligible.append(code)

    if not eligible or max_codes <= 0:
        return [], skipped

    start = 0
    if cursor_code is not None:
        for index, code in enumerate(eligible):
            if code > cursor_code:
                start = index
                break
        else:
            start = 0
    rotated = eligible[start:] + eligible[:start]
    return rotated[:max_codes], skipped


# ---------------------------------------------------------------------------
# budget accounting (pure)
# ---------------------------------------------------------------------------


@dataclass
class BudgetLedger:
    """Wall-clock budget for vendor traffic; the code bound lives in the selection step."""

    limit_seconds: float
    clock: Any = time.monotonic
    started: float = 0.0
    probe_cost_total: float = 0.0
    apply_cost_total: float = 0.0
    probe_samples: list[float] = field(default_factory=list)
    apply_samples: list[float] = field(default_factory=list)
    deferred_not_started: int = 0
    deferred_not_applied: int = 0

    def __post_init__(self) -> None:
        # The deadline is measured on the injected clock so a test or a caller-supplied
        # monotonic source cannot silently disable the budget.
        self.started = float(self.clock())

    def remaining_seconds(self) -> float:
        return max(0.0, self.limit_seconds - (self.clock() - self.started))

    def mean_or_seed(self, samples: Sequence[float], seed: float) -> float:
        if not samples:
            return seed
        return sum(samples) / len(samples)

    def can_probe(self) -> bool:
        return self.remaining_seconds() >= self.mean_or_seed(self.probe_samples, PROBE_SECONDS_SEED)

    def can_apply(self) -> bool:
        estimate = self.mean_or_seed(self.apply_samples, APPLY_SECONDS_SEED)
        return self.remaining_seconds() >= estimate

    def record_probe(self, cost_seconds: float) -> None:
        self.probe_cost_total += cost_seconds
        self.probe_samples.append(cost_seconds)

    def record_apply(self, cost_seconds: float) -> None:
        self.apply_cost_total += cost_seconds
        self.apply_samples.append(cost_seconds)

    def as_event(self) -> dict[str, Any]:
        return {
            "time_budget_seconds": self.limit_seconds,
            "remaining_seconds": round(self.remaining_seconds(), 3),
            "probe_seconds_used": round(self.probe_cost_total, 3),
            "apply_seconds_used": round(self.apply_cost_total, 3),
            "codes_deferred_not_started": self.deferred_not_started,
            "codes_deferred_not_applied": self.deferred_not_applied,
        }


# ---------------------------------------------------------------------------
# protected legacy scope (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProtectedScopeBaseline:
    """Reviewed frozen baseline for legacy NAV/cache rows the controller must not disturb."""

    codes: tuple[str, ...]
    codes_count: int
    codes_sha256: str
    nav_rows: int
    nav_sha256: str
    cache_rows: int
    cache_sha256: str
    manifest_path: str
    manifest_sha256: str

    def as_expected_scope(self) -> dict[str, Any]:
        return {
            "codes_count": self.codes_count,
            "codes_sha256": self.codes_sha256,
            "expected_nav_rows": self.nav_rows,
            "expected_nav_sha256": self.nav_sha256,
            "expected_cache_rows": self.cache_rows,
            "expected_cache_sha256": self.cache_sha256,
        }

    def fingerprint_expectations(self) -> dict[str, Any]:
        return {
            "protected_scope_codes_count": self.codes_count,
            "protected_scope_codes_sha256": self.codes_sha256,
            "protected_legacy_nav_rows": self.nav_rows,
            "protected_legacy_nav_sha256": self.nav_sha256,
            "protected_cache_rows": self.cache_rows,
            "protected_cache_sha256": self.cache_sha256,
        }


def load_protected_scope(path: Path) -> ProtectedScopeBaseline:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    codes = [str(code) for code in payload.get("protected_codes", [])]
    baseline = ProtectedScopeBaseline(
        codes=tuple(sorted(codes)),
        codes_count=int(payload["codes_count"]),
        codes_sha256=str(payload["codes_sha256"]),
        nav_rows=int(payload["nav_rows"]),
        nav_sha256=str(payload["nav_sha256"]),
        cache_rows=int(payload["cache_rows"]),
        cache_sha256=str(payload["cache_sha256"]),
        manifest_path=str(path),
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
    )
    if baseline.codes_count != len(codes):
        raise ValueError(
            f"protected legacy scope manifest declares {baseline.codes_count} codes "
            f"but lists {len(codes)}"
        )
    return baseline


def protected_check(
    baseline: ProtectedScopeBaseline,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, Any]:
    expected = baseline.fingerprint_expectations()
    before_ok = _fingerprint_matches(expected, before)
    after_ok = _fingerprint_matches(expected, after)
    if not before_ok:
        status = "protected_legacy_baseline_mismatch"
    elif not after_ok:
        status = "protected_legacy_scope_changed_after_managed"
    elif before != after:
        status = "protected_legacy_scope_changed_after_managed"
    else:
        status = "before_and_after_match"
    return {
        "status": status,
        "before": dict(before),
        "after": dict(after),
        "expected": expected,
    }


def _fingerprint_matches(expected: Mapping[str, Any], value: Mapping[str, Any]) -> bool:
    if not all(key in value for key in PROTECTED_FINGERPRINT_KEYS):
        return False
    return all(value.get(key) == expected_value for key, expected_value in expected.items())


# ---------------------------------------------------------------------------
# report assembly + contract self-check
# ---------------------------------------------------------------------------

REQUIRED_REPORT_KEYS = (
    "schema_version",
    "report_type",
    "run_id",
    "run_event",
    "outcomes",
    "selected_codes",
    "selected_listing_evidence",
    "fresh_sina_probe_ready",
    "full_history_complete",
    "report_path",
)
REQUIRED_RUN_EVENT_KEYS = (
    "event",
    "run_id",
    "started_at",
    "mode",
    "network_used",
    "probe_ready",
    "apply_enabled",
    "full_history_complete",
    "history_completeness",
    "max_codes",
    "time_budget_seconds",
    "managed_await_policy",
    "protected_legacy_scope",
    "current_sina_snapshot",
    "current_sina_snapshot_path",
    "sina_refresh_error",
    "selected_codes",
    "selected_listing_evidence",
    "processed_codes",
    "last_attempted_code",
    "completed_at",
    "remaining_seconds",
)


def new_run_id() -> str:
    return hashlib.sha256(f"{os.getpid()}-{time.time_ns()}".encode()).hexdigest()[:32]


def validate_apply_report(report: Mapping[str, Any]) -> list[str]:
    """Re-check the worker's ``_classify_etf`` invariants before the report is trusted.

    The controller runs this on its own output: a violation is reported instead of a
    silent, wrongly-successful batch.
    """
    problems: list[str] = []
    if report.get("schema_version") != SCHEMA_VERSION or report.get("report_type") != REPORT_TYPE:
        problems.append("report identity fields do not match the run-report contract")
    run_id = report.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        problems.append("run_id is not 32 lowercase hex characters")
        return problems
    run_event = report.get("run_event")
    outcomes = report.get("outcomes")
    if not isinstance(run_event, dict) or not isinstance(outcomes, list):
        problems.append("run_event/outcomes are missing")
        return problems
    if run_event.get("run_id") != run_id:
        problems.append("run_event.run_id differs from the report run_id")
    if any(row.get("run_id") != run_id for row in outcomes if isinstance(row, dict)):
        problems.append("an outcome is not bound to this run_id")
    selected = run_event.get("selected_codes")
    if not isinstance(selected, list) or report.get("selected_codes") != selected:
        problems.append("selected_codes differ between the report and its run event")
    if report.get("selected_listing_evidence") != run_event.get("selected_listing_evidence"):
        problems.append("selected_listing_evidence differs between report and run event")
    if (
        run_event.get("full_history_complete") is not False
        or report.get("full_history_complete") is not False
    ):
        problems.append("a bounded batch must not claim full_history_complete")
    outcome_codes = [row.get("fund_code") for row in outcomes if isinstance(row, dict)]
    if len(set(outcome_codes)) != len(outcome_codes):
        problems.append("duplicate per-code outcomes in one run")
    if set(outcome_codes) != set(selected if isinstance(selected, list) else []):
        problems.append("outcomes do not cover exactly the selected codes")
    if any(row.get("event") != "nav_probe" for row in outcomes if isinstance(row, dict)):
        problems.append("an outcome row is not a nav_probe event")
    not_started = sum(
        1
        for row in outcomes
        if isinstance(row, dict) and row.get("status") == "not_started_time_budget_exhausted"
    )
    processed = run_event.get("processed_codes")
    if processed != len(outcomes) - not_started:
        problems.append("processed_codes disagrees with the outcome events")
    unknown = sorted(
        {
            str(row.get("status"))
            for row in outcomes
            if isinstance(row, dict) and row.get("status") not in KNOWN_STATUSES
        }
    )
    if unknown:
        problems.append(f"unhandled outcome statuses: {unknown}")
    for row in outcomes:
        if not isinstance(row, dict) or row.get("status") not in SUCCESS_STATUSES:
            continue
        if (
            row.get("source_complete") is not True
            or row.get("diff_after", {}).get("exact_match") is not True
        ):
            problems.append(
                f"{row.get('fund_code')} claims success without source-complete exact-match proof"
            )
        for key in ("business_keys_sha256", "values_sha256", "snapshot_sha256"):
            value = row.get(key)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                problems.append(f"{row.get('fund_code')} success lacks a {key} digest")
        if not isinstance(row.get("source_snapshot_path"), str) or not row.get(
            "source_snapshot_path"
        ):
            problems.append(f"{row.get('fund_code')} success lacks a snapshot path")
        if row.get("status") == "applied_and_verified":
            execution = row.get("scheduler_execution")
            if (
                not isinstance(execution, dict)
                or str(execution.get("status", "")).casefold() != "completed"
            ):
                problems.append(
                    f"{row.get('fund_code')} applied without a completed managed execution"
                )
    protection = run_event.get("protected_legacy_scope")
    if isinstance(protection, dict):
        checks = protection.get("checks")
        if not isinstance(checks, list):
            problems.append("protected_legacy_scope.checks is missing")
        else:
            managed = {
                row.get("fund_code")
                for row in outcomes
                if isinstance(row, dict) and isinstance(row.get("scheduler_execution"), dict)
            }
            if not managed <= {
                check.get("fund_code") for check in checks if isinstance(check, dict)
            }:
                problems.append(
                    "a managed write lacks a matching protected-scope before/after check"
                )
    return problems


# ---------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------


class ListingSource(Protocol):
    def refresh(self) -> ListingSnapshot: ...


class NavProbeSource(Protocol):
    def probe(self, fund_code: str, start_date: str, end_date: str) -> NavProbe: ...


class TargetRepo(Protocol):
    def read_rows(self, fund_code: str) -> list[TargetNavRow]: ...

    def codes_with_rows(self) -> set[str]: ...

    def row_count(self) -> int: ...

    def apply_rows(self, fund_code: str, rows: Sequence[NavRow]) -> dict[str, int]: ...


class ProtectedScopeProbe(Protocol):
    def fingerprint(self, codes: Sequence[str]) -> dict[str, Any]: ...


class ManagedDispatcher(Protocol):
    def dispatch(self, fund_code: str, rows: Sequence[NavRow], run_id: str) -> dict[str, Any]: ...


class ReviewedManifests(Protocol):
    def reviewed_lifecycle(self) -> Mapping[str, Mapping[str, Any]]: ...

    def semantic_quarantine(self) -> Mapping[str, Mapping[str, Any]]: ...


@dataclass
class FixtureAdapters:
    """Offline adapters backed by a JSON fixture directory; performs no network I/O.

    Fixture layout (all optional except ``listing.json``)::

        listing.json          {"observed_at","source","rows":[{"fund_code","fund_name"}],"complete"}
        target.json           {"<code>": [["YYYY-MM-DD", unit, acc, growth], ...]}
        nav/<code>.json       {"provider","source_complete","first_nav_date","last_nav_date",
                               "observed_at","rows":[...],"semantic_evidence":{...}}
        protected.json        fingerprint values for the protected legacy scope
        executions/<code>.json managed-execution receipt
    """

    root: Path
    clock: Any = time.monotonic
    fail_on_code: str | None = None
    timeout_codes: tuple[str, ...] = ()
    delay_seconds: float = 0.0
    written: dict[str, int] = field(default_factory=dict)
    protected_mutated_on_write: bool = False
    _protected_state: dict[str, Any] | None = None
    _target_cache: dict[str, list[Any]] | None = None

    def _read(self, name: str) -> dict[str, Any]:
        path = self.root / name
        if not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    def refresh(self) -> ListingSnapshot:
        payload = self._read("listing.json")
        rows = payload.get("rows", [])
        return ListingSnapshot(
            observed_at=str(payload.get("observed_at") or "fixture"),
            source=str(payload.get("source") or "fixture_etf_node"),
            rows=tuple(row for row in rows if isinstance(row, dict)),
            complete=bool(payload.get("complete", True)),
            error=payload.get("error"),
        )

    def lifecycle_manifest(self) -> dict[str, Any]:
        return self._read("reviewed_lifecycle.json").get("entries", {})

    def quarantine_manifest(self) -> dict[str, Any]:
        return self._read("semantic_quarantine.json").get("entries", {})

    def probe(self, fund_code: str, start_date: str, end_date: str) -> NavProbe:
        if fund_code == self.fail_on_code:
            raise RuntimeError(f"fixture source failure for {fund_code}")
        if fund_code in self.timeout_codes:
            return NavProbe(
                fund_code=fund_code,
                provider="fixture",
                source_complete=False,
                rows=(),
                first_nav_date=None,
                last_nav_date=None,
                observed_at="fixture",
                timed_out=True,
            )
        time.sleep(self.delay_seconds)
        payload = self._read(f"nav/{fund_code}.json")
        rows = tuple(NavRow.from_json_row(row) for row in payload.get("rows", []))
        return NavProbe(
            fund_code=fund_code,
            provider=str(payload.get("provider") or "fixture"),
            source_complete=bool(payload.get("source_complete", True)),
            rows=rows,
            first_nav_date=payload.get("first_nav_date"),
            last_nav_date=payload.get("last_nav_date"),
            observed_at=str(payload.get("observed_at") or "fixture"),
            semantic_evidence=dict(payload.get("semantic_evidence") or {}),
            provider_evidence=dict(payload.get("provider_evidence") or {}),
            retention_limited=bool(payload.get("retention_limited", False)),
            is_nav_metric=bool(payload.get("is_nav_metric", True)),
        )

    def _target_state(self) -> dict[str, list[Any]]:
        if self._target_cache is None:
            raw = self._read("target.json")
            self._target_cache = {
                str(code): [list(row) for row in rows] for code, rows in raw.items()
            }
        return self._target_cache

    def read_rows(self, fund_code: str) -> list[TargetNavRow]:
        table = self._target_state().get(fund_code, [])
        return [
            TargetNavRow(
                business_date=str(row[0]),
                unit_nav=row[1] if len(row) > 1 else None,
                accumulated_nav=row[2] if len(row) > 2 else None,
                daily_growth=row[3] if len(row) > 3 else None,
            )
            for row in table
        ]

    def codes_with_rows(self) -> set[str]:
        return {code for code, rows in self._target_state().items() if rows}

    def row_count(self) -> int:
        return sum(len(rows) for rows in self._target_state().values())

    def apply_rows(self, fund_code: str, rows: Sequence[NavRow]) -> dict[str, int]:
        self.written[fund_code] = len(rows)
        state = self._target_state()
        # Emulate the idempotent business-key upsert so a post-apply fresh read matches.
        state[fund_code] = [row.as_json_row() for row in rows]
        return {"inserted": len(rows), "unchanged": 0}

    def fingerprint(self, codes: Sequence[str]) -> dict[str, Any]:
        state = self._protected_state or dict(self._read("protected.json"))
        self._protected_state = state
        if self.protected_mutated_on_write:
            state = {
                **state,
                "protected_legacy_nav_rows": state.get("protected_legacy_nav_rows", 0) + 1,
            }
        return {
            "protected_scope_codes_count": state.get("protected_scope_codes_count"),
            "protected_scope_codes_sha256": state.get("protected_scope_codes_sha256"),
            "protected_legacy_nav_rows": state.get("protected_legacy_nav_rows"),
            "protected_legacy_nav_sha256": state.get("protected_legacy_nav_sha256"),
            "protected_cache_rows": state.get("protected_cache_rows"),
            "protected_cache_sha256": state.get("protected_cache_sha256"),
        }

    def dispatch(self, fund_code: str, rows: Sequence[NavRow], run_id: str) -> dict[str, Any]:
        receipt = self._read(f"executions/{fund_code}.json")
        return {
            "execution_id": receipt.get("execution_id", f"ak_exec_fixture_{fund_code}"),
            "status": receipt.get("status", "completed"),
            "error_message": receipt.get("error_message"),
            "run_id": run_id,
            "rows_written": len(rows),
            "dispatch": "fixture_managed_execution",
        }


@dataclass
class SinaEtfNodeListing:
    """Live Sina ETF node listing (NOT_RUN in development: real vendor request)."""

    symbol: str = "ETF"

    def refresh(self) -> ListingSnapshot:  # pragma: no cover - live vendor path
        raise NotRunError(
            "Sina ETF node listing is NOT_RUN: no live vendor request was exercised. "
            "Wire it to app.data_fetch fund_etf_category_sina before production use."
        )


@dataclass
class PingzhongDataNavProbe:
    """Live East Money pingzhongdata/F10 NAV probe (NOT_RUN in development)."""

    timeout_seconds: float = 45.0

    def probe(self, fund_code: str, start_date: str, end_date: str) -> NavProbe:  # pragma: no cover
        raise NotRunError(
            "East Money NAV probe is NOT_RUN: no live vendor request was exercised. "
            "The business dates it returns must be kept as published; see parse_pingzhongdata_rows."
        )


def parse_pingzhongdata_rows(script_text: str) -> list[NavRow]:
    """Parse ``Data_netWorthTrend``/``Data_ACWorthTrend`` from a pingzhongdata JS blob.

    Pure and fixture-testable.  Timestamps are converted to the source's own business date
    only; nothing is invented for a date the source does not publish.
    """
    unit_series = _extract_js_series(script_text, "Data_netWorthTrend")
    acc_series = _extract_js_series(script_text, "Data_ACWorthTrend")
    acc_by_date: dict[str, float | str | None] = {}
    for timestamp, value in acc_series:
        acc_by_date[_epoch_to_business_date(timestamp)] = value
    rows: list[NavRow] = []
    for timestamp, value in unit_series:
        business_date = _epoch_to_business_date(timestamp)
        rows.append(
            NavRow(
                business_date=business_date,
                unit_nav=value,
                accumulated_nav=acc_by_date.get(business_date),
            )
        )
    return rows


def _extract_js_series(script_text: str, name: str) -> list[tuple[int, float | str | None]]:
    match = re.search(rf"{name}\s*=\s*(\[.*?\]);", script_text, re.S)
    if match is None:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    series: list[tuple[int, float | str | None]] = []
    for item in payload:
        # Data_netWorthTrend is a list of {"x","y"} objects; Data_ACWorthTrend is a list of
        # [epochMillis, value] pairs. Both carry the source's own date, nothing else.
        if isinstance(item, dict):
            if "x" not in item:
                continue
            epoch, raw = item["x"], item.get("y")
        elif isinstance(item, list) and len(item) >= 2:
            epoch, raw = item[0], item[1]
        else:
            continue
        if raw is None or raw == "":
            value: float | str | None = None
        else:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = str(raw)
        series.append((int(epoch), value))
    return series


SHANGHAI = timezone(timedelta(hours=8))


def _epoch_to_business_date(epoch_millis: int) -> str:
    """The source's own business date: CN fund NAV series are stamped on Shanghai trading days."""
    return datetime.fromtimestamp(epoch_millis / 1000, tz=SHANGHAI).date().isoformat()


@dataclass
class WarehouseNavRepo:
    """Live warehouse reader/writer for ``ETF_FUND_HIST_EM`` (NOT_RUN in development)."""

    table_name: str = "ETF_FUND_HIST_EM"

    def read_rows(self, fund_code: str) -> list[TargetNavRow]:  # pragma: no cover - live SQL
        raise NotRunError("warehouse read is NOT_RUN: no live warehouse query was exercised")

    def codes_with_rows(self) -> set[str]:  # pragma: no cover - live SQL
        raise NotRunError("warehouse read is NOT_RUN: no live warehouse query was exercised")

    def row_count(self) -> int:  # pragma: no cover - live SQL
        raise NotRunError("warehouse read is NOT_RUN: no live warehouse query was exercised")

    def apply_rows(
        self, fund_code: str, rows: Sequence[NavRow]
    ) -> dict[str, int]:  # pragma: no cover
        raise NotRunError(
            "warehouse write is NOT_RUN: this development build never applies to the live warehouse"
        )


@dataclass
class ManagedExecutionDispatcher:
    """Managed execution receipts through the akshare execution service (NOT_RUN)."""

    script_id: str = "etf_fund_hist_em"

    def dispatch(
        self, fund_code: str, rows: Sequence[NavRow], run_id: str
    ) -> dict[str, Any]:  # pragma: no cover
        raise NotRunError(
            "managed dispatch is NOT_RUN: it must create a manual-triggered execution "
            "(task_id=None) so a manual batch never consumes a cron claim"
        )


# ---------------------------------------------------------------------------
# state I/O
# ---------------------------------------------------------------------------


def _write_bytes_atomically(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _append_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_text_if_present(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def read_cursor(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    code = payload.get("last_fund_code") if isinstance(payload, dict) else None
    return code if isinstance(code, str) else None


def write_cursor(path: Path, code: str | None, observed_at: str) -> None:
    if code is None:
        return
    _write_bytes_atomically(
        path,
        json.dumps({"last_fund_code": code, "updated_at": observed_at}, indent=2).encode("utf-8"),
    )


def discover_shard_state_dirs(output_dir: Path) -> list[Path]:
    if not output_dir.is_dir():
        return []
    return sorted(
        entry
        for entry in output_dir.iterdir()
        if entry.is_dir() and SHARD_DIR_PATTERN.match(entry.name)
    )


def read_sibling_shard_windows(
    output_dir: Path,
    *,
    inflight_runs: int,
) -> dict[str, tuple[str | None, tuple[str, ...]]]:
    """Read sibling shard state read-only; never create or modify anything under shard-N/."""
    windows: dict[str, tuple[str | None, tuple[str, ...]]] = {}
    for shard_dir in discover_shard_state_dirs(output_dir):
        cursor_code = read_cursor(shard_dir / CURSOR_FILENAME)
        in_flight: list[str] = []
        runs_dir = shard_dir / "runs"
        if runs_dir.is_dir() and inflight_runs > 0:
            newest = sorted(runs_dir.glob("*.json"), key=lambda item: item.name, reverse=True)[
                :inflight_runs
            ]
            for run_file in newest:
                try:
                    payload = json.loads(run_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                codes = payload.get("selected_codes") if isinstance(payload, dict) else None
                if isinstance(codes, list):
                    in_flight.extend(str(code) for code in codes if isinstance(code, str))
        windows[shard_dir.name] = (cursor_code, tuple(in_flight))
    return windows


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _opt_dict(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


@dataclass
class ControllerOptions:
    probe: bool
    apply: bool
    max_codes: int
    time_budget_seconds: float
    output_dir: Path
    report_path: Path
    source_start_date: str
    source_end_date: str
    protected_scope_manifest: Path | None
    shard_lookahead: int
    shard_inflight_runs: int
    skip_shard_guard: bool


@dataclass
class CodeResult:
    fund_code: str
    status: str
    outcome: dict[str, Any]
    checkpoint_event: dict[str, Any] | None = None
    invalidation_event: dict[str, Any] | None = None
    attempted: bool = True


def run_controller(
    options: ControllerOptions,
    *,
    listing: ListingSource,
    probe_source: NavProbeSource,
    target: TargetRepo,
    protected_probe: ProtectedScopeProbe,
    dispatcher: ManagedDispatcher,
    manifests: ReviewedManifests,
    run_id: str | None = None,
    clock: Any = time.monotonic,
) -> dict[str, Any]:
    """Execute one bounded pass and return the run report (shape per ``_classify_etf``)."""
    started_at = _now_iso()
    identifier = run_id or new_run_id()
    output_dir = options.output_dir
    apply_enabled = options.apply
    mode = "apply" if apply_enabled else ("probe" if options.probe else "plan")
    network_used = bool(options.probe or apply_enabled)
    budget = BudgetLedger(limit_seconds=options.time_budget_seconds, clock=clock)

    if network_used:
        try:
            listing_snapshot = listing.refresh()
        except Exception as exc:  # a refresh failure must become evidence, never a crash
            listing_snapshot = ListingSnapshot(
                _now_iso(),
                "unavailable",
                (),
                False,
                error=f"{type(exc).__name__}: {exc}",
            )
    else:
        listing_snapshot = ListingSnapshot("", "not_requested_while_read_only", (), False)
    sina_refresh_error = listing_snapshot.error
    snapshot_digest: str | None = None
    listing_snapshot_path: str | None = None
    if network_used and listing_snapshot.rows:
        listing_payload = {
            "observed_at": listing_snapshot.observed_at,
            "source": listing_snapshot.source,
            "complete": listing_snapshot.complete,
            "rows": sorted(listing_snapshot.rows, key=lambda row: str(row.get("fund_code"))),
        }
        snapshot_digest = snapshot_sha256_of(listing_payload)
        listing_snapshot_path = str(
            _listing_snapshot_path(output_dir, listing_payload, snapshot_digest, apply_enabled)
        )

    reviewed_lifecycle = manifests.reviewed_lifecycle()
    semantic_quarantine = manifests.semantic_quarantine()
    # Reading the canonical NAV table is a read, so the plan may use it; a failure there is
    # recorded instead of silently shrinking the universe.
    master_plane_error: str | None = None
    try:
        master_codes: set[str] = target.codes_with_rows()
        existing_nav_row_count = target.row_count()
    except Exception as exc:
        master_codes = set()
        existing_nav_row_count = None
        master_plane_error = f"{type(exc).__name__}: {exc}"
    universe = sorted(
        set(listing_snapshot.codes)
        | set(master_codes)
        | set(reviewed_lifecycle)
        | set(semantic_quarantine)
    )
    identities = {
        code: build_identity(
            code,
            listing_snapshot,
            master_codes=master_codes,
            reviewed_lifecycle=reviewed_lifecycle,
            semantic_quarantine=semantic_quarantine,
            nav_only_codes=set(),
        )
        for code in universe
    }

    merge = merge_checkpoint_events(_read_text_if_present(output_dir / CHECKPOINT_FILENAME))
    cursor_code = read_cursor(output_dir / CURSOR_FILENAME)
    if options.skip_shard_guard:
        windows_by_shard: Mapping[str, tuple[str | None, Sequence[str]]] = {}
    else:
        windows_by_shard = read_sibling_shard_windows(
            output_dir,
            inflight_runs=options.shard_inflight_runs,
        )
    projected = shard_windows(universe, windows_by_shard, lookahead=options.shard_lookahead)
    shard_owned: set[str] = set()
    for window in projected:
        shard_owned |= window.owned

    selected, skipped = select_candidates(
        universe=universe,
        identities=identities,
        merge=merge,
        cursor_code=cursor_code,
        max_codes=options.max_codes,
        shard_owned=shard_owned,
    )
    plan_preview = list(selected)
    if not network_used:
        # A read-only plan emits no per-code outcome rows: its candidates are reported under
        # ``plan.candidate_preview`` so the run event stays internally consistent (no source
        # request was made, so nothing may look probed or verified).
        selected = []

    baseline: ProtectedScopeBaseline | None = None
    baseline_error: str | None = None
    if options.protected_scope_manifest is not None:
        try:
            baseline = load_protected_scope(options.protected_scope_manifest)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            baseline_error = (
                f"protected legacy scope manifest unusable: {type(exc).__name__}: {exc}"
            )
    else:
        baseline_error = "protected legacy scope manifest not supplied"

    results: list[CodeResult] = []
    last_attempted: str | None = None
    for index, code in enumerate(selected):
        identity = identities[code]
        if not budget.can_probe():
            deferred = [
                CodeResult(
                    fund_code=remaining_code,
                    status="not_started_time_budget_exhausted",
                    outcome={
                        "event": "nav_probe",
                        "run_id": identifier,
                        "fund_code": remaining_code,
                        "status": "not_started_time_budget_exhausted",
                        "reason": "time_budget_exhausted_before_probe",
                        "source_complete": False,
                    },
                    attempted=False,
                )
                for remaining_code in selected[index:]
            ]
            budget.deferred_not_started += len(deferred)
            results.extend(deferred)
            break
        if not apply_enabled:
            results.append(
                _probe_only_result(
                    code,
                    identity,
                    options,
                    probe_source,
                    target,
                    identifier,
                    budget,
                )
            )
            last_attempted = code
            continue
        results.append(
            _apply_one(
                code,
                identity,
                options,
                probe_source,
                target,
                protected_probe,
                dispatcher,
                baseline,
                identifier,
                budget,
                merge,
            )
        )
        last_attempted = code

    processed_codes = sum(1 for result in results if result.attempted)
    outcomes = [result.outcome for result in results]

    result_index = result_by_code(results)
    ledger_rows = [_ledger_row(code, identities[code], merge, result_index) for code in universe]
    checkpoint_events = [
        event for event in (result.checkpoint_event for result in results) if event is not None
    ]
    invalidation_events = [
        event for event in (result.invalidation_event for result in results) if event is not None
    ]
    run_event = _build_run_event(
        identifier,
        mode,
        options,
        started_at,
        listing_snapshot,
        snapshot_digest,
        listing_snapshot_path,
        sina_refresh_error,
        universe,
        identities,
        selected,
        results,
        processed_codes,
        last_attempted,
        skipped,
        projected,
        budget,
        baseline,
        baseline_error,
        merge,
        reviewed_lifecycle,
        semantic_quarantine,
        master_codes,
        existing_nav_row_count,
        master_plane_error,
    )
    probe_ready = bool(
        network_used
        and listing_snapshot.complete
        and listing_snapshot.source_row_count > 0
        and 0 < listing_snapshot.unique_code_count <= listing_snapshot.source_row_count
        and listing_snapshot_path
        and sina_refresh_error is None
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "run_id": identifier,
        "run_event": run_event,
        "outcomes": outcomes,
        "selected_codes": selected,
        "selected_listing_evidence": [identities[code].as_listing_evidence() for code in selected],
        "fresh_sina_probe_ready": probe_ready,
        "full_history_complete": False,
        "report_path": str(options.report_path),
        "mode": mode,
        "plan": {
            "universe_count": len(universe),
            "eligible_for_nav_probe_count": sum(
                1 for identity in identities.values() if identity.eligible_for_nav_probe
            ),
            "quarantined_count": len(merge.quarantined),
            "verified_checkpoint_count": len(merge.verified_codes),
            "quarantine_sticky_conflicts": len(merge.sticky_conflicts),
            "candidate_preview": plan_preview,
            "skipped": skipped,
            "budget_deferred": budget.as_event(),
            "sibling_shard_guard": run_event["sibling_shard_guard"],
            "full_history_complete": False,
        },
    }

    contract_problems = validate_apply_report(report) if mode == "apply" else []
    if contract_problems:
        # A report that violates the worker's contract may not persist success either:
        # unproven checkpoints would make the next run skip real work.
        checkpoint_events = []
    report["contract_problems"] = contract_problems

    if apply_enabled:
        _persist_state(
            output_dir,
            checkpoint_events,
            invalidation_events,
            ledger_rows,
            run_event,
            outcomes,
            last_attempted,
            started_at,
        )
    _write_report(options.report_path, report)
    return report


def _listing_snapshot_path(
    output_dir: Path,
    payload: Mapping[str, Any],
    digest: str,
    apply_enabled: bool,
) -> Path:
    """Under ``--apply`` the listing evidence is persisted; otherwise nothing is created."""
    path = output_dir / LISTING_DIRNAME / f"sina-node-{digest}.json.gz"
    if apply_enabled:
        _write_bytes_atomically(path, gzip_stable(canonical_json(payload)))
    return path


def result_by_code(results: Sequence[CodeResult]) -> dict[str, CodeResult]:
    return {result.fund_code: result for result in results}


def _probe_only_result(
    code: str,
    identity: CodeIdentity,
    options: ControllerOptions,
    probe_source: NavProbeSource,
    target: TargetRepo,
    identifier: str,
    budget: BudgetLedger,
) -> CodeResult:
    started = budget.clock()
    try:
        probe = probe_source.probe(code, options.source_start_date, options.source_end_date)
    except Exception as exc:
        return _error_result(identifier, code, f"{type(exc).__name__}: {exc}")
    budget.record_probe(budget.clock() - started)
    diff = diff_summary(probe.rows, target.read_rows(code))
    status = (
        "verified_read_only"
        if diff["exact_match"] and probe.source_complete
        else "pending_target_reconciliation"
    )
    outcome = {
        "event": "nav_probe",
        "run_id": identifier,
        "fund_code": code,
        "status": status,
        "provider": probe.provider,
        "source_complete": probe.source_complete,
        "source_first_nav_date": probe.first_nav_date,
        "source_last_nav_date": probe.last_nav_date,
        "source_row_count": probe.row_count,
        "listing_boundary_status": "unknown"
        if probe.first_nav_date is None
        else identity.listing_boundary_status,
        "historical_scope_status": _historical_scope_status(probe, diff),
        "source_tail": source_tail(
            _iso(options.source_end_date), probe.last_nav_date, terminal=_is_terminal(identity)
        ),
        "diff_after": {k: v for k, v in diff.items() if k != "details"},
        "probe_only": True,
        "writes_performed": False,
    }
    return CodeResult(fund_code=code, status=status, outcome=outcome)


def _apply_one(
    code: str,
    identity: CodeIdentity,
    options: ControllerOptions,
    probe_source: NavProbeSource,
    target: TargetRepo,
    protected_probe: ProtectedScopeProbe,
    dispatcher: ManagedDispatcher,
    baseline: ProtectedScopeBaseline | None,
    identifier: str,
    budget: BudgetLedger,
    merge: CheckpointMerge,
) -> CodeResult:
    probe_started = budget.clock()
    try:
        probe = probe_source.probe(code, options.source_start_date, options.source_end_date)
    except Exception as exc:
        return _error_result(identifier, code, f"{type(exc).__name__}: {exc}")
    budget.record_probe(budget.clock() - probe_started)

    if probe.timed_out:
        return CodeResult(
            fund_code=code,
            status="source_probe_timeout",
            outcome={
                "event": "nav_probe",
                "run_id": identifier,
                "fund_code": code,
                "status": "source_probe_timeout",
                "reason": "source_probe_timeout_no_cooldown_fabricated",
                "source_complete": False,
            },
        )

    if not probe.is_nav_metric:
        return _quarantine_result(identifier, code, probe)

    if not probe.rows:
        # An empty NAV series is not evidence: certifying it would let the checkpoint skip
        # the code forever, so the row stays pending with its reason recorded.
        return CodeResult(
            fund_code=code,
            status="pending_target_reconciliation",
            outcome={
                "event": "nav_probe",
                "run_id": identifier,
                "fund_code": code,
                "status": "pending_target_reconciliation",
                "reason": "source_probe_returned_no_rows_no_certification",
                "provider": probe.provider,
                "source_complete": probe.source_complete,
                "source_row_count": 0,
            },
        )

    listing_boundary_status = (
        SOURCE_LIMITED_FIRST_DATE
        if probe.first_nav_date is None
        else identity.listing_boundary_status
    )
    target_rows = target.read_rows(code)
    diff_before = diff_summary(probe.rows, target_rows)
    if not diff_before["exact_match"] and not budget.can_apply():
        budget.deferred_not_applied += 1
        return CodeResult(
            fund_code=code,
            status="not_applied_time_budget_insufficient",
            outcome={
                "event": "nav_probe",
                "run_id": identifier,
                "fund_code": code,
                "status": "not_applied_time_budget_insufficient",
                "reason": "remaining_time_budget_below_apply_estimate",
                "source_complete": probe.source_complete,
                "source_row_count": probe.row_count,
                "diff_before": _trim(diff_before),
            },
        )

    snapshot_dir = options.output_dir / SNAPSHOT_DIRNAME
    content = build_snapshot_content(probe, listing_boundary_status)
    digest = snapshot_sha256_of(content)
    previous = merge.records.get(code)
    snapshot_path, _ = write_snapshot(
        snapshot_dir,
        content,
        captured_at=probe.observed_at,
        sha256=digest,
    )
    diff_dir = snapshot_dir / DIFF_DIRNAME
    write_diff(diff_dir, code, digest, "before-apply", diff_before, content)

    scheduler_execution: dict[str, Any] | None = None
    protected_checks: list[dict[str, Any]] = []
    status = "verified_read_only"
    reason: str | None = None
    after_diff = diff_before
    applied = False

    if diff_before["exact_match"]:
        if not probe.source_complete:
            status = "pending_target_reconciliation"
            reason = "source_probe_incomplete_no_certification"
    elif not probe.source_complete:
        # Rows are missing but the probe itself is not provably complete: refuse to write
        # rather than manufacture the rest of the series.
        status = "pending_target_reconciliation"
        reason = "source_incomplete_probe_retention_limited_no_write_fabricated"
    elif baseline is None:
        status = "protected_legacy_baseline_read_failed"
        reason = (
            f"protected legacy scope unusable; apply refused ({options.protected_scope_manifest})"
        )
    else:
        apply_started = budget.clock()
        before = protected_probe.fingerprint(baseline.codes)
        try:
            receipt = dispatcher.dispatch(code, probe.rows, identifier)
            target.apply_rows(code, probe.rows)
        except Exception as exc:
            return _error_result(
                identifier, code, f"managed apply failed: {type(exc).__name__}: {exc}"
            )
        budget.record_apply(budget.clock() - apply_started)
        after = protected_probe.fingerprint(baseline.codes)
        check = protected_check(baseline, before, after)
        check["fund_code"] = code
        check.pop("expected", None)
        protected_checks.append(check)
        after_diff = diff_summary(probe.rows, target.read_rows(code))
        write_diff(diff_dir, code, digest, "after-apply", after_diff, content)
        applied = True
        if check["status"] != "before_and_after_match":
            status = check["status"]
            reason = "protected legacy scope changed around the managed write"
        elif receipt.get("status") != "completed":
            status = "managed_execution_failed"
            reason = "managed execution did not complete"
        elif after_diff["exact_match"]:
            status = "applied_and_verified"
            scheduler_execution = receipt
        else:
            status = "applied_but_reconciliation_pending"
            reason = "post-apply fresh SQL does not match the source snapshot yet"

    diff_phase = "after-apply" if applied else "before-apply"
    after_diff_path = str(diff_dir / f"{code}-{digest}-{diff_phase}.diff.json.gz")
    verified_at = _now_iso()
    historical_scope_status = _historical_scope_status(probe, after_diff)
    outcome: dict[str, Any] = {
        "event": "nav_probe",
        "run_id": identifier,
        "fund_code": code,
        "status": status,
        "provider": probe.provider,
        "source_complete": probe.source_complete,
        "source_first_nav_date": probe.first_nav_date,
        "source_last_nav_date": probe.last_nav_date,
        "source_row_count": probe.row_count,
        "business_keys_sha256": content["business_keys_sha256"],
        "values_sha256": content["values_sha256"],
        "snapshot_sha256": digest,
        "source_snapshot_path": str(snapshot_path),
        "listing_boundary_status": listing_boundary_status,
        "historical_scope_status": historical_scope_status,
        "source_tail": source_tail(
            _iso(options.source_end_date), probe.last_nav_date, terminal=_is_terminal(identity)
        ),
        "semantic_evidence": probe.semantic_evidence,
        "diff_before": _trim(diff_before),
        "diff_after": _trim(after_diff),
        "protected_legacy_checks": protected_checks,
    }
    if scheduler_execution is not None:
        outcome["scheduler_execution"] = scheduler_execution
    if reason is not None:
        outcome["reason"] = reason

    checkpoint_event: dict[str, Any] | None = None
    if status in SUCCESS_STATUSES:
        checkpoint_event = {
            "event": "checkpoint",
            "fund_code": code,
            "status": "verified_for_source_snapshot"
            if not _is_terminal(identity)
            else "archived_history_complete",
            "provider": probe.provider,
            "source_first_nav_date": probe.first_nav_date,
            "source_last_nav_date": probe.last_nav_date,
            "source_row_count": probe.row_count,
            "business_keys_sha256": content["business_keys_sha256"],
            "values_sha256": content["values_sha256"],
            "snapshot_sha256": digest,
            "target_diff": _trim(after_diff),
            "listing_boundary_status": listing_boundary_status,
            "historical_scope_status": historical_scope_status,
            "verified_at": verified_at,
            "source_snapshot_changed_from_previous": bool(
                previous is None or previous.snapshot_sha256 != digest
            ),
            "source_snapshot_path": str(snapshot_path),
            "target_diff_path": after_diff_path,
            "semantic_evidence": probe.semantic_evidence,
            "source_tail": outcome["source_tail"],
            "scheduler_execution_id": (scheduler_execution or {}).get("execution_id"),
        }
    return CodeResult(
        fund_code=code,
        status=status,
        outcome=outcome,
        checkpoint_event=checkpoint_event,
    )


def _quarantine_result(identifier: str, code: str, probe: NavProbe) -> CodeResult:
    """A non-NAV metric stays quarantined: it is never retried into a NAV success."""
    now = _now_iso()
    return CodeResult(
        fund_code=code,
        status="source_semantic_rejected",
        outcome={
            "event": "nav_probe",
            "run_id": identifier,
            "fund_code": code,
            "status": "source_semantic_rejected",
            "reason": "source_product_metric_metadata_does_not_describe_unit_cumulative_nav",
            "source_complete": False,
            "semantic_evidence": probe.semantic_evidence,
        },
        invalidation_event={
            "event": "checkpoint_invalidated",
            "fund_code": code,
            "status": QUARANTINE_CHECKPOINT_STATUS,
            "invalidated_at": now,
            "reason": "source_product_metric_metadata_does_not_describe_unit_cumulative_nav",
            "semantic_status": "excluded_from_nav_pending_separate_dataset",
            "evidence": probe.semantic_evidence,
        },
    )


def _error_result(identifier: str, code: str, detail: str) -> CodeResult:
    return CodeResult(
        fund_code=code,
        status="source_or_apply_error",
        outcome={
            "event": "nav_probe",
            "run_id": identifier,
            "fund_code": code,
            "status": "source_or_apply_error",
            "reason": detail,
            "source_complete": False,
        },
    )


def _is_terminal(identity: CodeIdentity) -> bool:
    lifecycle = identity.reviewed_lifecycle or {}
    return bool(lifecycle.get("terminal"))


def _historical_scope_status(probe: NavProbe, diff: Mapping[str, Any]) -> str:
    if not probe.source_complete:
        return "source_retention_limited_first_date_unknown"
    if diff.get("exact_match"):
        if probe.first_nav_date is None:
            return "source_snapshot_target_match_listing_boundary_source_limited"
        return "source_snapshot_target_match_listing_boundary_unknown"
    return "target_missing_source_rows"


def _trim(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in summary.items() if key != "details"}


def _iso(compact_date: str) -> str:
    if len(compact_date) == 8 and compact_date.isdigit():
        return f"{compact_date[0:4]}-{compact_date[4:6]}-{compact_date[6:8]}"
    return compact_date


def _ledger_row(
    code: str,
    identity: CodeIdentity,
    merge: CheckpointMerge,
    results: Mapping[str, CodeResult],
) -> dict[str, Any]:
    record = merge.records.get(code)
    result = results.get(code)
    verified = record if record is not None and record.is_verified() else None
    return {
        "fund_code": code,
        "current_sina_node_member": identity.current_sina_node_member,
        "current_sina_name": identity.sina_name,
        "product_identity_status": identity.product_identity_status,
        "product_review_required": identity.product_identity_status == "needs_product_review",
        "eligible_for_nav_probe": identity.eligible_for_nav_probe,
        "nav_quarantined": identity.nav_quarantined or code in merge.quarantined,
        "semantic_quarantine": identity.semantic_quarantine,
        "reviewed_lifecycle": identity.reviewed_lifecycle,
        "lifecycle_identity_conflict": identity.lifecycle_identity_conflict,
        "source_probe_status": "not_probed" if result is None else "probed",
        "source_first_nav_date": verified.source_first_nav_date if verified else None,
        "source_last_nav_date": verified.source_last_nav_date if verified else None,
        "source_row_count": verified.source_row_count if verified else None,
        "business_keys_sha256": verified.business_keys_sha256 if verified else None,
        "values_sha256": verified.values_sha256 if verified else None,
        "listing_boundary_status": identity.listing_boundary_status,
        "historical_scope_status": (
            "source_metric_is_not_nav_pending_separate_dataset"
            if code in merge.quarantined
            else (verified.historical_scope_status if verified else "listing_boundary_unknown")
        ),
        "checkpoint_status": record.status if record else None,
        "selected_this_run": result is not None,
        "outcome_status": result.status if result else None,
        "pending_reason": _pending_reason(code, identity, merge, verified, result),
    }


def _pending_reason(
    code: str,
    identity: CodeIdentity,
    merge: CheckpointMerge,
    verified: CheckpointRecord | None,
    result: CodeResult | None,
) -> str:
    if code in merge.quarantined:
        return "source_metric_is_not_nav"
    if result is not None and result.status in BUDGET_DEFERRED_STATUSES:
        return "time_budget_deferred"
    if result is not None and result.status in ATTENTION_STATUSES:
        return f"outcome_{result.status}"
    if verified is not None:
        return "verified_for_current_source_snapshot"
    if not identity.eligible_for_nav_probe:
        return "identity_needs_product_review"
    if identity.product_identity_status in PROVEN_IDENTITY_STATUSES:
        return "current_source_snapshot_not_probed"
    return "universe_membership_only"


def _build_run_event(
    identifier: str,
    mode: str,
    options: ControllerOptions,
    started_at: str,
    listing_snapshot: ListingSnapshot,
    snapshot_digest: str | None,
    listing_snapshot_path: str | None,
    sina_refresh_error: str | None,
    universe: Sequence[str],
    identities: Mapping[str, CodeIdentity],
    selected: Sequence[str],
    results: Sequence[CodeResult],
    processed_codes: int,
    last_attempted: str | None,
    skipped: Mapping[str, int],
    projected: Sequence[ShardWindow],
    budget: BudgetLedger,
    baseline: ProtectedScopeBaseline | None,
    baseline_error: str | None,
    merge: CheckpointMerge,
    reviewed_lifecycle: Mapping[str, Mapping[str, Any]],
    semantic_quarantine: Mapping[str, Mapping[str, Any]],
    master_codes: set[str],
    existing_nav_row_count: int | None,
    master_plane_error: str | None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for result in results:
        for check in result.outcome.get("protected_legacy_checks", []) or []:
            checks.append({key: value for key, value in check.items() if key != "expected"})
    if baseline is not None:
        protected_scope: dict[str, Any] = {
            **baseline.as_expected_scope(),
            "checks": checks,
            "manifest_path": baseline.manifest_path,
            "manifest_sha256": baseline.manifest_sha256,
        }
    else:
        protected_scope = {
            "codes_count": None,
            "codes_sha256": None,
            "expected_nav_rows": None,
            "expected_nav_sha256": None,
            "expected_cache_rows": None,
            "expected_cache_sha256": None,
            "checks": checks,
            "status": "protected_legacy_baseline_read_failed",
            "error": baseline_error,
        }
    excluded_by_shard = sorted({code for window in projected for code in window.owned})
    return {
        "event": "controller_run",
        "run_id": identifier,
        "started_at": started_at,
        "mode": mode,
        "network_used": bool(options.probe or options.apply),
        "probe_ready": bool(
            listing_snapshot.complete
            and listing_snapshot_path
            and (options.probe or options.apply)
            and sina_refresh_error is None
        ),
        "apply_enabled": bool(options.apply),
        "full_history_complete": False,
        "history_completeness": HISTORY_COMPLETENESS,
        "max_codes": options.max_codes,
        "time_budget_seconds": options.time_budget_seconds,
        "managed_await_policy": {
            "soft_timeout": "remaining_controller_budget",
            "cancellation_cleanup_may_overrun_soft_timeout": True,
            "thread_termination_guaranteed": False,
            "outer_process_hard_stop_owner": "invoking process supervisor",
        },
        "protected_legacy_scope": protected_scope,
        "source_start_date": options.source_start_date,
        "source_end_date": options.source_end_date,
        "sina_node_code_count": listing_snapshot.unique_code_count,
        "etf_daily_master_code_count": len(master_codes),
        "reviewed_lifecycle_code_count": len(reviewed_lifecycle),
        "existing_nav_code_count": len(master_codes),
        "existing_nav_row_count": existing_nav_row_count,
        "etf_daily_master_plane_error": master_plane_error,
        "current_sina_code_count": listing_snapshot.unique_code_count,
        "current_sina_snapshot": {
            "status": "live_snapshot_loaded" if listing_snapshot.rows else "snapshot_unavailable",
            "observed_at": listing_snapshot.observed_at,
            "source": listing_snapshot.source,
            "source_row_count": listing_snapshot.source_row_count,
            "unique_code_count": listing_snapshot.unique_code_count,
            "complete": listing_snapshot.complete,
            "network_used": bool(options.probe or options.apply),
            "snapshot_sha256": snapshot_digest,
            "snapshot_path": listing_snapshot_path,
        },
        "current_sina_snapshot_path": listing_snapshot_path,
        "sina_refresh_error": sina_refresh_error,
        "universe_union_count": len(universe),
        "eligible_for_nav_probe_count": sum(
            1 for identity in identities.values() if identity.eligible_for_nav_probe
        ),
        "quarantined_nav_code_count": len(merge.quarantined) + len(semantic_quarantine),
        "needs_product_review_count": sum(
            1
            for code in universe
            if identities[code].product_identity_status == "needs_product_review"
        ),
        "reviewed_lifecycle_count": len(reviewed_lifecycle),
        "lifecycle_identity_conflict_count": sum(
            1 for code in universe if identities[code].lifecycle_identity_conflict
        ),
        "unknown_listing_boundary_count": sum(
            1
            for code in universe
            if identities[code].listing_boundary_status
            in {"unknown", SOURCE_LIMITED_FIRST_DATE, ""}
        ),
        "identity_manifest": {
            "reviewed_lifecycle_codes": sorted(reviewed_lifecycle),
            "semantic_quarantine_codes": sorted(semantic_quarantine),
        },
        "semantic_quarantine_codes": sorted(merge.quarantined) or sorted(semantic_quarantine),
        "invalidated_checkpoints_this_run": sum(
            1 for result in results if result.invalidation_event is not None
        ),
        "quarantine_sticky_conflicts": len(merge.sticky_conflicts),
        "verified_checkpoint_count_excluding_quarantine": len(merge.verified_codes),
        "listing_boundary_status": (
            "known_for_reviewed_manifest_entries; unknown_for_remaining_codes"
        ),
        "selected_codes": list(selected),
        "selected_listing_evidence": [identities[code].as_listing_evidence() for code in selected],
        "processed_codes": processed_codes,
        "last_attempted_code": last_attempted,
        "selection_skipped": dict(skipped),
        "sibling_shard_guard": {
            "enabled": not options.skip_shard_guard,
            "shard_state_dirs": [window.shard for window in projected],
            "inflight_runs_read": options.shard_inflight_runs,
            "lookahead_per_shard": options.shard_lookahead,
            "excluded_code_count": len(excluded_by_shard),
            "sample_excluded_codes": excluded_by_shard[:10],
            "wrote_into_shard_dirs": False,
        },
        "budget_accounting": budget.as_event(),
        "completed_at": _now_iso(),
        "remaining_seconds": round(budget.remaining_seconds(), 3),
    }


def _persist_state(
    output_dir: Path,
    checkpoint_events: Sequence[Mapping[str, Any]],
    invalidation_events: Sequence[Mapping[str, Any]],
    ledger_rows: Sequence[Mapping[str, Any]],
    run_event: Mapping[str, Any],
    outcomes: Sequence[Mapping[str, Any]],
    last_attempted: str | None,
    started_at: str,
) -> None:
    _append_jsonl(output_dir / CHECKPOINT_FILENAME, [*invalidation_events, *checkpoint_events])
    _append_jsonl(output_dir / EVENTS_FILENAME, [run_event, *outcomes])
    if ledger_rows:
        payload = "\n".join(canonical_json(row) for row in ledger_rows) + "\n"
        _write_bytes_atomically(output_dir / LEDGER_FILENAME, payload.encode("utf-8"))
    write_cursor(output_dir / CURSOR_FILENAME, last_attempted, started_at)


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_bytes_atomically(path, json.dumps(report, indent=1, ensure_ascii=False).encode("utf-8"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backfill_etf_nav_controller.py",
        description=(
            "Bounded, resumable ETF NAV full-history recovery controller. "
            "No flags is a read-only plan; --probe inspects source reachability and the "
            "first/last available NAV dates; --apply is the only mode that writes."
        ),
    )
    parser.add_argument(
        "--probe", action="store_true", help="probe source reachability/first NAV date"
    )
    parser.add_argument(
        "--apply", action="store_true", help="allow managed writes and checkpoint state"
    )
    parser.add_argument(
        "--max-codes", type=int, default=DEFAULT_MAX_CODES, help="codes per bounded batch"
    )
    parser.add_argument(
        "--time-budget-seconds",
        type=float,
        default=DEFAULT_TIME_BUDGET_SECONDS,
        help="wall-clock budget for vendor traffic in this batch",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path(DEFAULT_OUTPUT_DIR), help="state namespace"
    )
    parser.add_argument(
        "--report", type=Path, required=False, default=None, help="per-run report path"
    )
    parser.add_argument(
        "--source-start-date",
        default="19000101",
        help="requested source window start (the source's own first available date still wins)",
    )
    parser.add_argument(
        "--source-end-date",
        default=None,
        help="requested source window end as YYYYMMDD; defaults to today's UTC date",
    )
    parser.add_argument(
        "--protected-scope-manifest",
        type=Path,
        default=None,
        help="reviewed protected legacy scope manifest (refuses apply when absent)",
    )
    parser.add_argument(
        "--shard-lookahead",
        type=int,
        default=400,
        help="codes each sibling continuous shard is about to reach; excluded from selection",
    )
    parser.add_argument(
        "--shard-inflight-runs",
        type=int,
        default=2,
        help="how many recent shard run receipts to read for in-flight codes",
    )
    parser.add_argument(
        "--skip-shard-guard",
        action="store_true",
        help="debug only: select codes the continuous shards currently own",
    )
    parser.add_argument(
        "--fixture-dir", type=Path, default=None, help="offline JSON fixture adapters"
    )
    parser.add_argument(
        "--allow-live-sources",
        action="store_true",
        help="use the live adapters; every live adapter is NOT_RUN-verified and raises",
    )
    return parser


def _default_source_end_date() -> str:
    """Today is only the *requested* window end; a lagged NAV tail is never read as a gap."""
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.max_codes < 1:
        parser.error("--max-codes must be at least 1")
    if args.time_budget_seconds <= 0:
        parser.error("--time-budget-seconds must be greater than zero")

    output_dir: Path = args.output_dir
    report_path: Path = args.report if args.report is not None else output_dir / "last-report.json"
    options = ControllerOptions(
        probe=bool(args.probe),
        apply=bool(args.apply),
        max_codes=int(args.max_codes),
        time_budget_seconds=float(args.time_budget_seconds),
        output_dir=output_dir,
        report_path=report_path,
        source_start_date=str(args.source_start_date),
        source_end_date=str(args.source_end_date or _default_source_end_date()),
        protected_scope_manifest=args.protected_scope_manifest,
        shard_lookahead=int(args.shard_lookahead),
        shard_inflight_runs=int(args.shard_inflight_runs),
        skip_shard_guard=bool(args.skip_shard_guard),
    )

    if args.fixture_dir is not None:
        fixture = FixtureAdapters(root=args.fixture_dir)
        adapters: dict[str, Any] = {
            "listing": fixture,
            "probe_source": fixture,
            "target": fixture,
            "protected_probe": fixture,
            "dispatcher": fixture,
            "manifests": _FixtureManifests(fixture),
        }
    elif args.allow_live_sources:
        listing = SinaEtfNodeListing()
        adapters = {
            "listing": listing,
            "probe_source": PingzhongDataNavProbe(),
            "target": WarehouseNavRepo(),
            "protected_probe": _LiveProtectedScopeProbe(),
            "dispatcher": ManagedExecutionDispatcher(),
            "manifests": _LiveManifests(),
        }
    else:
        adapters = {}
        report = _no_adapter_report(options)
        _write_report(report_path, report)
        print(
            "no source adapters selected: pass --fixture-dir for an offline run or "
            "--allow-live-sources for the NOT_RUN live path",
            file=sys.stderr,
        )
        return 0

    if options.apply:
        with _namespace_lock(output_dir) as lock:
            if not lock.acquired:
                report = _no_adapter_report(options, lock_held=True)
                _write_report(report_path, report)
                print(
                    "another controller pass holds this state namespace; nothing was probed",
                    file=sys.stderr,
                )
                return 0
            report = _run_with_adapters(options, adapters)
    else:
        # Read-only modes take no lock and create no state file; only --report is written.
        report = _run_with_adapters(options, adapters)
    if report.get("contract_problems"):
        for problem in report["contract_problems"]:
            print(f"ETF controller report contract problem: {problem}", file=sys.stderr)
    return 0


def _run_with_adapters(options: ControllerOptions, adapters: Mapping[str, Any]) -> dict[str, Any]:
    return run_controller(
        options,
        listing=adapters["listing"],
        probe_source=adapters["probe_source"],
        target=adapters["target"],
        protected_probe=adapters["protected_probe"],
        dispatcher=adapters["dispatcher"],
        manifests=adapters["manifests"],
    )


class _FixtureManifests:
    """Reviewed manifests supplied from the fixture directory (offline)."""

    def __init__(self, fixture: FixtureAdapters) -> None:
        self._fixture = fixture

    def reviewed_lifecycle(self) -> Mapping[str, Mapping[str, Any]]:
        return self._fixture.lifecycle_manifest()

    def semantic_quarantine(self) -> Mapping[str, Mapping[str, Any]]:
        return self._fixture.quarantine_manifest()


class _LiveProtectedScopeProbe:
    """Protected legacy scope fingerprint over the live warehouse (NOT_RUN)."""

    def fingerprint(self, codes: Sequence[str]) -> dict[str, Any]:
        raise NotRunError(
            "protected legacy scope fingerprint is NOT_RUN: no live warehouse query was exercised"
        )


class _LiveManifests:
    """Reviewed manifests from ``src/backend/data``; absent files mean no reviewed plane."""

    def reviewed_lifecycle(self) -> Mapping[str, Mapping[str, Any]]:
        path = BACKEND_ROOT / "data" / "reviewed_etf_lifecycle_manifest.json"
        return _manifest_entries(path)

    def semantic_quarantine(self) -> Mapping[str, Mapping[str, Any]]:
        path = BACKEND_ROOT / "data" / "fund_metric_semantics_quarantine.json"
        return _manifest_entries(path)


def _manifest_entries(path: Path) -> Mapping[str, Mapping[str, Any]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    raw_entries = payload.get("entries", payload)
    if not isinstance(raw_entries, dict):
        return {}
    return {
        str(code): dict(value) for code, value in raw_entries.items() if isinstance(value, dict)
    }


def _no_adapter_report(options: ControllerOptions, *, lock_held: bool = False) -> dict[str, Any]:
    identifier = new_run_id()
    now = _now_iso()
    reason = (
        "controller state namespace lock held by another pass; no source probe was treated as complete"
        if lock_held
        else "no source adapters selected; nothing was probed and nothing was written"
    )
    run_event: dict[str, Any] = {
        "event": "controller_run",
        "run_id": identifier,
        "started_at": now,
        "mode": "apply" if options.apply else ("probe" if options.probe else "plan"),
        "network_used": False,
        "probe_ready": False,
        "apply_enabled": bool(options.apply),
        "full_history_complete": False,
        "history_completeness": HISTORY_COMPLETENESS,
        "max_codes": options.max_codes,
        "time_budget_seconds": options.time_budget_seconds,
        "managed_await_policy": {"soft_timeout": "remaining_controller_budget"},
        "protected_legacy_scope": {
            "codes_count": None,
            "codes_sha256": None,
            "expected_nav_rows": None,
            "expected_nav_sha256": None,
            "expected_cache_rows": None,
            "expected_cache_sha256": None,
            "checks": [],
            "status": "protected_legacy_baseline_read_failed",
        },
        "current_sina_snapshot": {
            "status": "snapshot_unavailable",
            "observed_at": None,
            "source": None,
            "source_row_count": 0,
            "unique_code_count": 0,
            "complete": False,
            "network_used": False,
        },
        "current_sina_snapshot_path": None,
        "sina_refresh_error": reason,
        "selected_codes": [],
        "selected_listing_evidence": [],
        "processed_codes": 0,
        "last_attempted_code": None,
        "completed_at": now,
        "remaining_seconds": options.time_budget_seconds,
        "sibling_shard_guard": {"enabled": not options.skip_shard_guard},
        "budget_accounting": {"time_budget_seconds": options.time_budget_seconds},
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "run_id": identifier,
        "run_event": run_event,
        "outcomes": [],
        "selected_codes": [],
        "selected_listing_evidence": [],
        "fresh_sina_probe_ready": False,
        "full_history_complete": False,
        "report_path": str(options.report_path),
        "plan": {"reason": reason, "full_history_complete": False},
    }


class _namespace_lock:
    """One writer per state namespace; the shard directories keep their own locks.

    Read-only modes never take it, because taking it would itself create a file.
    """

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self._lock_path = output_dir / LOCK_FILENAME
        self._handle: Any = None
        self.acquired = False

    def __enter__(self) -> _namespace_lock:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._lock_path.open("a+")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.acquired = False
            return self
        self.acquired = True
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self.acquired and self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        if self._handle is not None:
            self._handle.close()


__all__ = [
    "BUDGET_DEFERRED_STATUSES",
    "BudgetLedger",
    "CheckpointMerge",
    "CodeIdentity",
    "ControllerOptions",
    "NavProbe",
    "NavRow",
    "NotRunError",
    "PROVEN_IDENTITY_STATUSES",
    "ProtectedScopeBaseline",
    "SCHEMA_VERSION",
    "SUCCESS_STATUSES",
    "TargetNavRow",
    "build_identity",
    "business_keys_sha256",
    "diff_summary",
    "gzip_stable",
    "main",
    "merge_checkpoint_events",
    "new_run_id",
    "normalize_decimal",
    "parse_pingzhongdata_rows",
    "protected_check",
    "run_controller",
    "select_candidates",
    "shard_windows",
    "snapshot_sha256_of",
    "source_tail",
    "values_sha256",
]

if __name__ == "__main__":
    sys.exit(main())
