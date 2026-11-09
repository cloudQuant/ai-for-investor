"""Reconcile A-share full daily history against its source, one bounded batch per run.

This is the asset controller that
``scripts/ops/run_full_history_recovery_worker.py`` shells out to for the
``stock`` registry slot.  The worker's CLI contract is fixed:

    stock_full_history_controller.py --apply --max-codes N --max-minutes F
        --source-timeout-seconds S --retry-cooldown-hours H
        --progress PATH --report PATH

Safety invariants this module must never break:

* Running with **no flags is read-only**.  It reports inventory only and makes
  zero source requests and zero writes; ``remaining_unverified_count`` stays
  ``None`` because an overview is not a verification result.
* A missing trading day is **never fabricated**.  Gaps are classified
  (head/internal/tail) and left missing; source-native ``None`` OHLC values are
  preserved as ``None`` and are never zero-filled or forward-filled.
* The per-symbol progress ledger makes a re-run idempotent inside one scope:
  already-verified checkpoints are skipped, and a mid-batch failure is
  resumable without resetting any cursor or clearing a cooldown.
* Unknown listing boundaries and adjusted-price bases are recorded as
  ``unknown``, never defaulted.
* ``--retry-cooldown-hours`` and ``--source-timeout-seconds`` are real bounds on
  vendor traffic.

The pure core (normalization, gap computation, batch selection, checkpointing,
exit-code resolution) has no I/O and is exercised by
``tests/test_stock_full_history_controller.py``.  Source and warehouse access
live only behind the adapter protocols at the bottom of this file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

# ``datetime.UTC`` is 3.11+; the project targets 3.10, so bind the alias here.
UTC = timezone.utc

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "src" / "backend"
DEFAULT_PROGRESS = (
    REPO_ROOT / "var" / "reports" / "iteration203" / "stock-controller" / "progress.jsonl"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "var"
    / "reports"
    / "iteration203"
    / "stock-controller"
    / "reports"
    / "stock-report.json"
)

DEFAULT_START_DATE = "1900-01-01"
DEFAULT_MAX_CODES = 10
DEFAULT_MAX_MINUTES = 6.0
DEFAULT_SOURCE_TIMEOUT_SECONDS = 45.0
DEFAULT_RETRY_COOLDOWN_HOURS = 24.0

SOURCE_NAME = "tencent"
ADJUSTMENT = "qfq"
NORMALIZER_VERSION = "stock-history-normalizer-v2"
WAREHOUSE_VERIFICATION_SCOPE = "business_date_keys_and_ohlc_only"
ADAPTER_PRECISION = "akshare_dataframe_exposed"
STOCK_SCRIPT_ID = "stock_zh_a_hist"
STOCK_UNIVERSE_TABLES = (
    ("STOCK_INFO_A_CODE_NAME", ("symbol", "code")),
    ("STOCK_INFO_BJ_NAME_CODE", ("symbol", "证券代码")),
)
SOURCE_COLUMNS = ("date", "日期", "open", "开盘", "high", "最高", "low", "最低")
SAMPLE_LIMIT = 12
OUTCOME_SCHEMA_VERSION = 3
LEDGER_SCHEMA_VERSION = 1

SUCCESS_STATUSES = frozenset({"verified_match", "scheduled_verified"})
STATUS_SOURCE_FAILED = "source_failed"
STATUS_DEFERRED_BUDGET = "deferred_budget"
STATUS_DEFERRED_SCHEDULER_BUDGET = "deferred_scheduler_budget"
STATUS_VERIFICATION_FAILED = "verification_failed"
STATUS_BACKFILL_FAILED = "backfill_failed"
STATUS_UNRESOLVED_DIFFERENCE = "unresolved_difference"
STATUS_WORKER_CRASHED = "source_worker_crashed"
ATTENTION_STATUSES = frozenset(
    {
        STATUS_DEFERRED_SCHEDULER_BUDGET,
        STATUS_VERIFICATION_FAILED,
        STATUS_BACKFILL_FAILED,
        STATUS_UNRESOLVED_DIFFERENCE,
        STATUS_WORKER_CRASHED,
    }
)
# A verified checkpoint is skipped only for the exact scope it was earned in.
SKIPPABLE_STATUSES = SUCCESS_STATUSES


@dataclass(frozen=True)
class DailyBar:
    """One source-native daily bar; every OHLC member may legitimately be ``None``."""

    date_key: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None

    def ohlc(self) -> tuple[float | None, float | None, float | None, float | None]:
        return (self.open, self.high, self.low, self.close)


@dataclass(frozen=True)
class NormalizedSource:
    bars: tuple[DailyBar, ...]
    duplicate_date_count: int
    rejected_row_count: int

    @property
    def first_date(self) -> str | None:
        return self.bars[0].date_key if self.bars else None

    @property
    def row_count(self) -> int:
        return len(self.bars)


@dataclass(frozen=True)
class WriteReceipt:
    execution_id: str | None
    status: str
    error: str | None = None
    write_possible: bool = False


@dataclass(frozen=True)
class Budget:
    """Wall-clock bound for one invocation.

    ``monotonic`` is injected so the batch bound is testable without sleeping.
    """

    started_at: float
    total_seconds: float
    reserve_seconds: float
    monotonic: Any = time.monotonic

    def elapsed(self) -> float:
        return max(0.0, float(self.monotonic()) - self.started_at)

    def remaining(self) -> float:
        return max(0.0, self.total_seconds - self.elapsed())

    def has_room(self, needed: float) -> bool:
        return self.remaining() >= (needed + self.reserve_seconds)


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _as_date_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return str(value.isoformat())[:10]
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    text = text[:10].replace("/", "-")
    for candidate in (text, f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) == 8 else text):
        try:
            return datetime.strptime(candidate, "%Y-%m-%d").date().isoformat()
        except ValueError:
            continue
    return None


def _as_optional_float(value: Any) -> float | None:
    """Preserve source-native blanks as ``None``; never coerce a blank to zero."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if text in {"", "-", "--", "nan", "NaN", "None", "null"}:
        return None
    try:
        return float(text.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _pick(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def normalize_source_rows(rows: Iterable[Mapping[str, Any]]) -> NormalizedSource:
    """Sort and de-duplicate raw source rows without inventing any value."""

    by_date: dict[str, DailyBar] = {}
    duplicates = 0
    rejected = 0
    for row in rows:
        if not isinstance(row, Mapping):
            rejected += 1
            continue
        date_key = _as_date_key(_pick(row, *SOURCE_COLUMNS[:2]))
        if date_key is None:
            rejected += 1
            continue
        bar = DailyBar(
            date_key=date_key,
            open=_as_optional_float(_pick(row, "open", "开盘")),
            high=_as_optional_float(_pick(row, "high", "最高")),
            low=_as_optional_float(_pick(row, "low", "最低")),
            close=_as_optional_float(_pick(row, "close", "收盘")),
        )
        if date_key in by_date:
            duplicates += 1
            # Keep the first observation; a duplicate is evidence, not a rewrite.
            continue
        by_date[date_key] = bar
    return NormalizedSource(
        bars=tuple(by_date[key] for key in sorted(by_date)),
        duplicate_date_count=duplicates,
        rejected_row_count=rejected,
    )


def snapshot_digests(rows: Sequence[Mapping[str, Any]], bars: Sequence[DailyBar]) -> dict[str, str]:
    raw = [{str(k): str(v) for k, v in dict(row).items()} for row in rows]
    normalized = [bar.__dict__ for bar in bars]
    ohlc = [[bar.date_key, *bar.ohlc()] for bar in bars]
    return {
        "source_snapshot_raw_sha256": _canonical_sha256(raw),
        "source_snapshot_normalized_sha256": _canonical_sha256(normalized),
        "source_snapshot_ohlc_sha256": _canonical_sha256(ohlc),
    }


def _sample(values: Iterable[str]) -> list[str]:
    ordered = sorted(values)
    return ordered[:SAMPLE_LIMIT]


def _ohlc_changed(left: DailyBar, right: DailyBar) -> bool:
    # ``None`` is a real observation, so None vs 0.0 is a difference, not a match.
    return left.ohlc() != right.ohlc()


def compute_comparison(
    source_bars: Sequence[DailyBar], warehouse_bars: Sequence[DailyBar]
) -> dict[str, Any]:
    """Reconcile business-date keys and OHLC only; classify gaps, fabricate nothing."""

    source_by_date = {bar.date_key: bar for bar in source_bars}
    warehouse_by_date = {bar.date_key: bar for bar in warehouse_bars}
    source_dates = set(source_by_date)
    warehouse_dates = set(warehouse_by_date)

    source_only = sorted(source_dates - warehouse_dates)
    warehouse_only = sorted(warehouse_dates - source_dates)
    warehouse_first = min(warehouse_dates) if warehouse_dates else None
    warehouse_last = max(warehouse_dates) if warehouse_dates else None

    head = internal = tail = 0
    for date_key in source_only:
        if warehouse_first is None or warehouse_last is None:
            # With no warehouse anchor the edge is genuinely unknown; count it as head.
            head += 1
        elif date_key < warehouse_first:
            head += 1
        elif date_key > warehouse_last:
            tail += 1
        else:
            internal += 1

    changed = [
        date_key
        for date_key in sorted(source_dates & warehouse_dates)
        if _ohlc_changed(source_by_date[date_key], warehouse_by_date[date_key])
    ]
    source_duplicates = len(source_bars) - len(source_dates)
    warehouse_duplicates = len(warehouse_bars) - len(warehouse_dates)

    return {
        "exact_match": not source_only
        and not warehouse_only
        and not changed
        and source_duplicates == 0
        and warehouse_duplicates == 0,
        "source_row_count": len(source_bars),
        "warehouse_row_count": len(warehouse_bars),
        "source_date_key_count": len(source_dates),
        "warehouse_date_key_count": len(warehouse_dates),
        "source_duplicate_date_count": source_duplicates,
        "warehouse_duplicate_date_count": warehouse_duplicates,
        "source_only_count": len(source_only),
        "source_only_by_edge": {
            "head": head,
            "internal": internal,
            "tail": tail,
            "all": len(source_only),
        },
        "warehouse_only_count": len(warehouse_only),
        "ohlc_value_change_count": len(changed),
        "source_only_sample": _sample(source_only),
        "warehouse_only_sample": _sample(warehouse_only),
        "ohlc_value_change_sample": _sample(changed),
    }


def classify_gaps(comparison: Mapping[str, Any]) -> dict[str, Any]:
    """Human/ledger-facing gap classification. Missing stays missing."""

    edges = comparison.get("source_only_by_edge") or {}
    return {
        "head_missing": int(edges.get("head", 0) or 0),
        "internal_missing": int(edges.get("internal", 0) or 0),
        "tail_missing": int(edges.get("tail", 0) or 0),
        "warehouse_only": int(comparison.get("warehouse_only_count", 0) or 0),
        "ohlc_value_changes": int(comparison.get("ohlc_value_change_count", 0) or 0),
        "classification": "unverified_gap"
        if int(comparison.get("source_only_count", 0) or 0)
        else "boundary_and_value_reconciled",
        "fabricated_rows": 0,
    }


def compute_scope_hash(
    *, start_date: str, end_date: str, source: str, adjustment: str, normalizer: str
) -> str:
    return _canonical_sha256(
        {
            "scope_start_date": start_date,
            "scope_end_date": end_date,
            "source": source,
            "adjustment": adjustment,
            "normalizer_version": normalizer,
        }
    )


def compute_checkpoint_key(*, scope_hash: str, symbol: str, source: str, adjustment: str) -> str:
    return _canonical_sha256(
        {
            "scope_hash": scope_hash,
            "symbol": symbol,
            "source": source,
            "adjustment": adjustment,
            "normalizer_version": NORMALIZER_VERSION,
        }
    )


def compute_period_key(*, scope_hash: str, symbol: str, snapshot_sha256: str) -> str:
    return f"stock-full-history:v1:{scope_hash}:{symbol}:{snapshot_sha256}"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True)
class LedgerRecord:
    checkpoint_key: str
    symbol: str
    status: str
    recorded_at_utc: str
    cooldown_hours: float | None = None

    @property
    def recorded_at(self) -> datetime | None:
        return _parse_timestamp(self.recorded_at_utc)


def _coerce_cooldown(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        cooldown = float(value)
    except (TypeError, ValueError):
        return None
    return cooldown if cooldown >= 0 else None


def load_ledger(path: Path) -> tuple[dict[str, LedgerRecord], int]:
    """Read the append-only JSONL ledger; the last line per checkpoint wins."""

    records: dict[str, LedgerRecord] = {}
    malformed = 0
    if not path.is_file():
        return records, malformed
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return records, malformed
    for line in raw:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(payload, dict):
            malformed += 1
            continue
        checkpoint_key = payload.get("checkpoint_key")
        symbol = payload.get("symbol")
        status = payload.get("status")
        if not isinstance(checkpoint_key, str) or not isinstance(symbol, str):
            malformed += 1
            continue
        if not isinstance(status, str):
            malformed += 1
            continue
        recorded_at = payload.get("recorded_at_utc")
        records[checkpoint_key] = LedgerRecord(
            checkpoint_key=checkpoint_key,
            symbol=symbol,
            status=status,
            recorded_at_utc=recorded_at if isinstance(recorded_at, str) else "",
            cooldown_hours=_coerce_cooldown(payload.get("cooldown_hours")),
        )
    return records, malformed


def is_verified(record: LedgerRecord | None) -> bool:
    """A checkpoint is only ever earned inside its own scope.

    ``select_batch`` looks records up by ``checkpoint_key``, which already embeds
    ``scope_hash``, so a verification from yesterday's scope can never suppress
    today's work. Dropping that identity (or keying by symbol alone) would let
    the first full pass mark the whole universe permanently done.
    """

    return record is not None and record.status in SKIPPABLE_STATUSES


def is_cooling_down(record: LedgerRecord | None, *, now: datetime, default_hours: float) -> bool:
    """Honour a recorded failure cooldown; never clear it implicitly."""

    if record is None or record.status != STATUS_SOURCE_FAILED:
        return False
    hours = record.cooldown_hours if record.cooldown_hours is not None else default_hours
    recorded_at = record.recorded_at
    if recorded_at is None:
        # An undated failure cannot be proven expired, so it keeps cooling down.
        return True
    return recorded_at + timedelta(hours=hours) > now


@dataclass(frozen=True)
class Candidate:
    symbol: str
    checkpoint_key: str


@dataclass(frozen=True)
class BatchPlan:
    attempt: tuple[Candidate, ...]
    deferred: tuple[Candidate, ...]
    skipped_verified: int
    skipped_cooldown: int


def select_batch(
    candidates: Sequence[Candidate],
    ledger: Mapping[str, LedgerRecord],
    *,
    now: datetime,
    max_codes: int,
    budget: Budget,
    per_code_seconds: float,
    cooldown_hours: float,
    cooldown_only: frozenset[str] = frozenset({STATUS_SOURCE_FAILED}),
) -> BatchPlan:
    """Fair-cursor selection bounded by code count, wall clock, and cooldowns."""

    attempt: list[Candidate] = []
    deferred: list[Candidate] = []
    skipped_verified = 0
    skipped_cooldown = 0
    queue: list[Candidate] = []

    for candidate in candidates:
        record = ledger.get(candidate.checkpoint_key)
        if is_verified(record):
            skipped_verified += 1
            continue
        if record is not None and record.status in cooldown_only:
            if is_cooling_down(record, now=now, default_hours=cooldown_hours):
                skipped_cooldown += 1
                continue
        queue.append(candidate)

    # Fair cursor: least-recently-touched first, then code order for determinism.
    queue.sort(
        key=lambda item: (
            (ledger[item.checkpoint_key].recorded_at or datetime.fromtimestamp(0, UTC))
            if item.checkpoint_key in ledger
            else datetime.fromtimestamp(0, UTC),
            item.symbol,
        )
    )

    for candidate in queue:
        if len(attempt) >= max_codes:
            deferred.append(candidate)
            continue
        if not budget.has_room(per_code_seconds):
            deferred.append(candidate)
            continue
        attempt.append(candidate)

    return BatchPlan(
        attempt=tuple(attempt),
        deferred=tuple(deferred),
        skipped_verified=skipped_verified,
        skipped_cooldown=skipped_cooldown,
    )


def resolve_exit_code(statuses: Sequence[str]) -> int:
    """Map outcome statuses to the exit code the recovery worker expects."""

    present = set(statuses)
    if STATUS_SOURCE_FAILED in present:
        # Worker: exit 2 with statuses inside {success, source_failed} is retryable.
        return 2
    if STATUS_DEFERRED_BUDGET in present:
        # Worker: exit 3 is the only budget-deferral signal it accepts.
        return 3
    if present & ATTENTION_STATUSES:
        return 1
    return 0


def _utc_iso(now: datetime) -> str:
    return now.astimezone(UTC).isoformat()


def base_outcome(
    *, symbol: str, scope_hash: str, start_date: str, end_date: str, now: datetime
) -> dict[str, Any]:
    return {
        "schema_version": OUTCOME_SCHEMA_VERSION,
        "recorded_at_utc": _utc_iso(now),
        "scope_hash": scope_hash,
        "scope_start_date": start_date,
        "scope_end_date": end_date,
        "checkpoint_key": compute_checkpoint_key(
            scope_hash=scope_hash, symbol=symbol, source=SOURCE_NAME, adjustment=ADJUSTMENT
        ),
        "normalizer_version": NORMALIZER_VERSION,
        "symbol": symbol,
        "source": SOURCE_NAME,
        "adjustment": ADJUSTMENT,
        # Unknown is recorded as unknown; never defaulted to a guessed listing date.
        "listing_boundary_status": "unknown",
    }


def ledger_line(outcome: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "recorded_at_utc": outcome.get("recorded_at_utc"),
        "scope_hash": outcome.get("scope_hash"),
        "scope_start_date": outcome.get("scope_start_date"),
        "scope_end_date": outcome.get("scope_end_date"),
        "checkpoint_key": outcome.get("checkpoint_key"),
        "normalizer_version": outcome.get("normalizer_version"),
        "symbol": outcome.get("symbol"),
        "source": outcome.get("source"),
        "adjustment": outcome.get("adjustment"),
        "listing_boundary_status": outcome.get("listing_boundary_status"),
        "status": outcome.get("status"),
    }
    for key in (
        "reason",
        "error",
        "cooldown_hours",
        "comparison",
        "comparison_before",
        "comparison_after",
        "execution_id",
        "execution_status",
        "execution_error",
        "verification_error",
        "claim_key",
        "period_key",
        "write_possible",
        "managed_parameters",
        "full_history_status",
        "source_first_date",
        "source_row_count",
        "source_snapshot_artifact_id",
        "source_snapshot_raw_sha256",
        "source_snapshot_normalized_sha256",
        "source_snapshot_ohlc_sha256",
        "source_snapshot_parser_version",
        "adapter_precision",
        "captured_at_utc",
        "warehouse_verification_scope",
    ):
        if key in outcome:
            payload[key] = outcome[key]
    return payload


def append_ledger(path: Path, outcome: Mapping[str, Any]) -> None:
    """Append one durable line before the next symbol is attempted.

    Durability per line is what makes a mid-batch failure resumable.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(ledger_line(outcome), ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(dict(report), stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class SourceAdapter(Protocol):
    def fetch(self, symbol: str, *, start_date: str, end_date: str) -> list[Mapping[str, Any]]:
        """Return raw source rows or raise; never a synthesized row."""


class WarehouseAdapter(Protocol):
    def universe(self) -> tuple[list[str], dict[str, Any], str, list[str]]:
        """Return (symbols, per-source inventory evidence, status, refresh reasons)."""

    def bars(self, symbol: str) -> list[DailyBar]:
        """Return persisted bars for one symbol."""


class WriterAdapter(Protocol):
    def write(
        self, symbol: str, *, bars: Sequence[DailyBar], scope: Mapping[str, Any]
    ) -> WriteReceipt:
        """Persist the exact fetched bars through the managed path only."""


@dataclass
class ControllerConfig:
    apply: bool
    max_codes: int
    max_minutes: float
    source_timeout_seconds: float
    retry_cooldown_hours: float
    progress_path: Path
    report_path: Path
    start_date: str = DEFAULT_START_DATE
    end_date: str | None = None


@dataclass
class RunResult:
    report: dict[str, Any]
    exit_code: int


def _snapshot_fields(now: datetime, digests: Mapping[str, str], source: NormalizedSource) -> dict:
    return {
        "source_first_date": source.first_date,
        "source_row_count": source.row_count,
        "source_snapshot_artifact_id": digests["source_snapshot_raw_sha256"],
        "source_snapshot_raw_sha256": digests["source_snapshot_raw_sha256"],
        "source_snapshot_normalized_sha256": digests["source_snapshot_normalized_sha256"],
        "source_snapshot_ohlc_sha256": digests["source_snapshot_ohlc_sha256"],
        "source_snapshot_parser_version": NORMALIZER_VERSION,
        "adapter_precision": ADAPTER_PRECISION,
        "captured_at_utc": _utc_iso(now),
        "warehouse_verification_scope": WAREHOUSE_VERIFICATION_SCOPE,
    }


def _full_history_status(source: NormalizedSource) -> str:
    if source.first_date is None:
        return "unverified"
    return f"verified_{SOURCE_NAME}_{ADJUSTMENT}_date_and_ohlc_sequence_match"


def run_controller(
    config: ControllerConfig,
    *,
    source: SourceAdapter | None,
    warehouse: WarehouseAdapter,
    writer: WriterAdapter | None,
    clock: Any = time.monotonic,
    now: datetime | None = None,
) -> RunResult:
    """Execute the pure batch loop against injected adapters."""

    stamp = now or datetime.now(UTC)
    end_date = config.end_date or stamp.date().isoformat()
    scope_hash = compute_scope_hash(
        start_date=config.start_date,
        end_date=end_date,
        source=SOURCE_NAME,
        adjustment=ADJUSTMENT,
        normalizer=NORMALIZER_VERSION,
    )
    symbols, inventory, inventory_status, refresh_reasons = warehouse.universe()
    ledger, malformed_lines = load_ledger(config.progress_path)
    candidates = [
        Candidate(
            symbol=symbol,
            checkpoint_key=compute_checkpoint_key(
                scope_hash=scope_hash, symbol=symbol, source=SOURCE_NAME, adjustment=ADJUSTMENT
            ),
        )
        for symbol in symbols
    ]
    budget = Budget(
        started_at=float(clock()),
        total_seconds=config.max_minutes * 60.0,
        # The budget must always cover a probe AND its managed write.
        reserve_seconds=config.source_timeout_seconds,
        monotonic=clock,
    )
    verified_in_scope = sum(
        1
        for candidate in candidates
        if candidate.checkpoint_key in ledger
        and ledger[candidate.checkpoint_key].status in SUCCESS_STATUSES
    )

    report: dict[str, Any] = {
        "mode": "apply" if config.apply else "overview",
        "scope_hash": scope_hash,
        "start_date": config.start_date,
        "end_date": end_date,
        "selected_symbol_count": len(candidates),
        "attempted_count": 0,
        "remaining_unverified_count": None,
        "scope_verified": False,
        "batch_limit": config.max_codes,
        "time_budget_minutes": config.max_minutes,
        "listing_boundary_status": "unknown",
        "outcomes": [],
        "universe_source_status": inventory_status,
        "source_refresh_pending": bool(refresh_reasons),
        "source_refresh_reasons": list(refresh_reasons),
        "universe_sources": inventory,
        "report_path": str(config.report_path),
    }

    if not config.apply:
        # Read-only overview: inventory only, no source traffic, no verification claim.
        report["read_only"] = True
        report["ledger_checkpoint_count"] = len(ledger)
        report["ledger_malformed_lines"] = malformed_lines
        report["verified_in_scope_count"] = verified_in_scope
        write_report(config.report_path, report)
        return RunResult(report=report, exit_code=0)

    assert source is not None
    # A probe costs ``source_timeout_seconds``; the Budget reserve holds back the
    # equal cost of the managed write that can follow it.
    per_code_seconds = config.source_timeout_seconds
    plan = select_batch(
        candidates,
        ledger,
        now=stamp,
        max_codes=config.max_codes,
        budget=budget,
        per_code_seconds=per_code_seconds,
        cooldown_hours=config.retry_cooldown_hours,
    )
    outcomes: list[dict[str, Any]] = []
    deferred_outcomes: list[dict[str, Any]] = []

    for candidate in plan.deferred:
        deferred_outcomes.append(
            {
                **base_outcome(
                    symbol=candidate.symbol,
                    scope_hash=scope_hash,
                    start_date=config.start_date,
                    end_date=end_date,
                    now=stamp,
                ),
                "status": STATUS_DEFERRED_BUDGET,
                "reason": "insufficient_budget_for_full_source_probe",
            }
        )

    for candidate in plan.attempt:
        outcome = base_outcome(
            symbol=candidate.symbol,
            scope_hash=scope_hash,
            start_date=config.start_date,
            end_date=end_date,
            now=stamp,
        )
        if not budget.has_room(per_code_seconds):
            # A pure budget deferral is report evidence only, and it is not an
            # attempt: writing one ledger line per unselected symbol on every
            # invocation would grow the checkpoint file without recording any
            # new observation about the symbol.
            outcome["status"] = STATUS_DEFERRED_BUDGET
            outcome["reason"] = "insufficient_budget_for_full_source_probe"
            outcomes.append(outcome)
            continue

        # Each symbol is checkpointed individually so an interrupted run resumes.
        try:
            raw_rows = source.fetch(
                candidate.symbol, start_date=config.start_date, end_date=end_date
            )
        except Exception as exc:  # source failure is an outcome, never a fabricated bar
            outcome["status"] = STATUS_SOURCE_FAILED
            outcome["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            outcome["cooldown_hours"] = float(config.retry_cooldown_hours)
            outcomes.append(outcome)
            append_ledger(config.progress_path, outcome)
            report["attempted_count"] = int(report["attempted_count"]) + 1
            continue

        captured = stamp
        normalized = normalize_source_rows(raw_rows)
        digests = snapshot_digests(raw_rows, normalized.bars)
        outcome.update(_snapshot_fields(captured, digests, normalized))
        outcome["period_key"] = compute_period_key(
            scope_hash=scope_hash,
            symbol=candidate.symbol,
            snapshot_sha256=digests["source_snapshot_normalized_sha256"],
        )
        report["attempted_count"] = int(report["attempted_count"]) + 1

        if normalized.row_count == 0:
            outcome["status"] = STATUS_SOURCE_FAILED
            outcome["error"] = "source returned no rows; nothing was written"
            outcome["cooldown_hours"] = float(config.retry_cooldown_hours)
            outcome["full_history_status"] = "unverified"
            outcomes.append(outcome)
            append_ledger(config.progress_path, outcome)
            continue

        before = compute_comparison(normalized.bars, warehouse.bars(candidate.symbol))
        outcome["comparison_before"] = before
        if before["exact_match"]:
            outcome["status"] = "verified_match"
            outcome["comparison"] = before
            outcome["full_history_status"] = _full_history_status(normalized)
            outcomes.append(outcome)
            append_ledger(config.progress_path, outcome)
            continue

        if not budget.has_room(per_code_seconds):
            outcome["status"] = STATUS_DEFERRED_SCHEDULER_BUDGET
            outcome["reason"] = "insufficient_budget_for_managed_write"
            outcome["write_possible"] = False
            outcome["full_history_status"] = "unverified"
            outcomes.append(outcome)
            append_ledger(config.progress_path, outcome)
            continue

        if writer is None:
            # No managed writer resolved: refuse an unfenced write, record the deferral.
            outcome["status"] = STATUS_DEFERRED_SCHEDULER_BUDGET
            outcome["reason"] = "managed_writer_unavailable"
            outcome["write_possible"] = False
            outcome["full_history_status"] = "unverified"
            outcomes.append(outcome)
            append_ledger(config.progress_path, outcome)
            continue

        receipt = writer.write(
            candidate.symbol,
            bars=normalized.bars,
            scope={"scope_hash": scope_hash, "period_key": outcome["period_key"]},
        )
        outcome["execution_id"] = receipt.execution_id
        outcome["execution_status"] = receipt.status
        outcome["execution_error"] = receipt.error
        outcome["write_possible"] = receipt.write_possible
        after = compute_comparison(normalized.bars, warehouse.bars(candidate.symbol))
        outcome["comparison_after"] = after

        if receipt.status != "completed":
            outcome["status"] = STATUS_BACKFILL_FAILED
            outcome["full_history_status"] = "unverified"
        elif after["exact_match"]:
            outcome["status"] = "scheduled_verified"
            outcome["full_history_status"] = _full_history_status(normalized)
        elif after["warehouse_only_count"] or after["warehouse_duplicate_date_count"]:
            # Warehouse rows the source cannot explain are left as an open difference.
            outcome["status"] = STATUS_UNRESOLVED_DIFFERENCE
            outcome["full_history_status"] = "unverified"
        else:
            outcome["status"] = STATUS_VERIFICATION_FAILED
            outcome["full_history_status"] = "unverified"
        outcome["verification_error"] = (
            None if after["exact_match"] else "post_write_sequence_mismatch"
        )
        outcomes.append(outcome)
        append_ledger(config.progress_path, outcome)

    # Attempted symbols first, then the report-only budget deferrals.
    outcomes.extend(deferred_outcomes)
    statuses = [str(item["status"]) for item in outcomes]
    report["outcomes"] = outcomes
    report["remaining_unverified_count"] = max(
        0,
        len(candidates)
        - verified_in_scope
        - sum(1 for status in statuses if status in SUCCESS_STATUSES),
    )
    report["scope_verified"] = bool(
        report["remaining_unverified_count"] == 0 and not malformed_lines
    )
    write_report(config.report_path, report)
    return RunResult(report=report, exit_code=resolve_exit_code(statuses))


def build_overview_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_full_history_controller.py",
        description=(
            "Bounded A-share full-history reconciliation controller. "
            "Without --apply this is a read-only inventory overview."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the bounded batch; without this flag nothing is written",
    )
    parser.add_argument("--max-codes", type=int, default=DEFAULT_MAX_CODES)
    parser.add_argument("--max-minutes", type=float, default=DEFAULT_MAX_MINUTES)
    parser.add_argument(
        "--source-timeout-seconds", type=float, default=DEFAULT_SOURCE_TIMEOUT_SECONDS
    )
    parser.add_argument("--retry-cooldown-hours", type=float, default=DEFAULT_RETRY_COOLDOWN_HOURS)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=None)
    return parser


def parse_args(argv: Sequence[str] | None) -> tuple[argparse.ArgumentParser, ControllerConfig]:
    parser = build_overview_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.max_codes < 1:
        parser.error("--max-codes must be at least 1")
    if not math.isfinite(args.max_minutes) or args.max_minutes <= 0:
        parser.error("--max-minutes must be a positive finite number")
    if not math.isfinite(args.source_timeout_seconds) or args.source_timeout_seconds <= 0:
        parser.error("--source-timeout-seconds must be a positive finite number")
    if not math.isfinite(args.retry_cooldown_hours) or args.retry_cooldown_hours < 0:
        parser.error("--retry-cooldown-hours must be a non-negative finite number")
    config = ControllerConfig(
        apply=bool(args.apply),
        max_codes=int(args.max_codes),
        max_minutes=float(args.max_minutes),
        source_timeout_seconds=float(args.source_timeout_seconds),
        retry_cooldown_hours=float(args.retry_cooldown_hours),
        progress_path=Path(args.progress),
        report_path=Path(args.report),
        start_date=str(args.start_date),
        end_date=str(args.end_date) if args.end_date else None,
    )
    return parser, config


def build_live_adapters(
    config: ControllerConfig,
) -> tuple[SourceAdapter, WarehouseAdapter, WriterAdapter]:
    """Import the real data-access layer lazily so tests never touch it."""

    return (
        AkshareSourceAdapter(timeout_seconds=config.source_timeout_seconds),
        WarehouseDailyAdapter(),
        ManagedScriptWriterAdapter(),
    )


class AkshareSourceAdapter:
    """Thin wrapper over ``AkshareToMySql.fetch_ak_data`` with the per-call timeout."""

    def __init__(self, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch(self, symbol: str, *, start_date: str, end_date: str) -> list[Mapping[str, Any]]:
        from app.data_fetch.configs.db_config import DB_CONFIG
        from app.data_fetch.providers.akshare_to_mysql import AkshareToMySql

        engine = AkshareToMySql(DB_CONFIG)
        frame = engine.fetch_ak_data(
            "stock_zh_a_hist_tx",
            symbol=_prefixed_symbol(symbol),
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust=ADJUSTMENT,
            _call_timeout=self._timeout_seconds,
        )
        if frame is None or len(frame) == 0:
            return []
        return [dict(row) for row in frame.to_dict("records")]


class WarehouseDailyAdapter:
    """Read the stock universe and persisted daily bars from the warehouse."""

    def __init__(self) -> None:
        from app.data_fetch.configs.db_config import DB_CONFIG
        from app.data_fetch.core.mysql_base import MysqlBase

        self._db = MysqlBase(DB_CONFIG)

    def universe(self) -> tuple[list[str], dict[str, Any], str, list[str]]:
        symbols: list[str] = []
        inventory: dict[str, Any] = {}
        reasons: list[str] = []
        status = "current"
        for table, columns in STOCK_UNIVERSE_TABLES:
            entry: dict[str, Any] = {
                "table": table,
                "code_columns": list(columns),
                "status": "read",
            }
            if not self._db.table_exists(table):
                entry["status"] = "missing"
                reasons.append(f"{table} is absent")
                status = "stale"
                inventory[table] = entry
                continue
            frame = self._db.get_data_by_columns(table, list(columns))
            # pandas returns a Index here; `Index or []` raises "truth value ... is ambiguous".
            frame_columns = getattr(frame, "columns", None)
            available = list(frame_columns) if frame_columns is not None else []
            counts: dict[str, int] = {}
            values: list[str] = []
            for column in columns:
                if column not in available:
                    counts[column] = 0
                    continue
                series = frame[column].dropna().astype(str).str.strip()
                counts[column] = int(len(series))
                values.extend(series.tolist())
            canonical = sorted({value for value in values if _looks_like_symbol(value)})
            entry.update(
                {
                    "source_row_count": int(len(frame)),
                    "canonical_symbol_count": len(canonical),
                    "selected_code_column_counts": counts,
                    "source_snapshot_date": self._db.get_latest_date(table, "data_date")
                    or self._db.get_latest_date(table, "updated_at"),
                }
            )
            inventory[table] = entry
            symbols.extend(canonical)
        ordered = sorted(set(symbols))
        if not ordered:
            status = "unreadable"
            reasons.append("no stock universe symbols could be read")
        return ordered, inventory, status, reasons

    def bars(self, symbol: str) -> list[DailyBar]:
        rows = self._db.query_data(
            "SELECT data_date, `开盘`, `收盘`, `最高`, `最低` FROM STOCK_ZH_A_HIST"
            " WHERE symbol = %s AND source = %s AND adjustment = %s",
            (symbol, SOURCE_NAME, ADJUSTMENT),
        )
        if not rows:
            return []
        bars: list[DailyBar] = []
        for row in rows:
            date_key = _as_date_key(row[0])
            if date_key is None:
                continue
            bars.append(
                DailyBar(
                    date_key=date_key,
                    open=_as_optional_float(row[1]),
                    close=_as_optional_float(row[2]),
                    high=_as_optional_float(row[3]),
                    low=_as_optional_float(row[4]),
                )
            )
        return bars


class ManagedScriptWriterAdapter:
    """Persist fetched rows only through the managed script service.

    The controller never issues a raw ``INSERT``: an unfenced direct write would
    bypass the single-writer claim discipline the recovery pipeline depends on.
    """

    def write(
        self, symbol: str, *, bars: Sequence[DailyBar], scope: Mapping[str, Any]
    ) -> WriteReceipt:
        import asyncio

        from app.models.akshare_mgmt import TriggeredBy
        from app.services.akshare.script import AkshareScriptService

        if not bars:
            return WriteReceipt(execution_id=None, status="skipped", write_possible=False)

        parameters = {
            "symbol": symbol,
            "start_date": bars[0].date_key.replace("-", ""),
            "end_date": bars[-1].date_key.replace("-", ""),
            "adjust": ADJUSTMENT,
            "source": SOURCE_NAME,
            "_recovery_scope_hash": scope.get("scope_hash"),
            "_recovery_period_key": scope.get("period_key"),
        }

        async def _dispatch() -> Any:
            from app.db.database import async_session_maker

            async with async_session_maker() as session:
                service = AkshareScriptService(session)
                return await service.run_script(
                    STOCK_SCRIPT_ID,
                    parameters=parameters,
                    triggered_by=TriggeredBy.MANUAL,
                )

        try:
            execution = asyncio.run(_dispatch())
        except Exception as exc:
            return WriteReceipt(
                execution_id=None,
                status="failed",
                error=f"{type(exc).__name__}: {str(exc)[:300]}",
                write_possible=True,
            )
        status = str(getattr(execution, "status", "") or "").lower()
        return WriteReceipt(
            execution_id=getattr(execution, "id", None),
            status="completed" if status == "completed" else status or "unknown",
            error=getattr(execution, "error_message", None),
            write_possible=True,
        )


def _looks_like_symbol(value: str) -> bool:
    text = str(value).strip()
    return len(text) == 6 and text.isdigit()


def _prefixed_symbol(symbol: str) -> str:
    text = str(symbol).strip()
    if text.startswith(("sh", "sz", "bj")):
        return text
    if text.startswith("6"):
        return f"sh{text}"
    if text.startswith(("4", "8")):
        return f"bj{text}"
    return f"sz{text}"


def main(argv: Sequence[str] | None = None) -> int:
    parser, config = parse_args(argv)
    del parser
    if config.apply:
        source, warehouse, writer = build_live_adapters(config)
    else:
        _, warehouse, _ = build_live_adapters(config)
        source, writer = None, None
    try:
        result = run_controller(config, source=source, warehouse=warehouse, writer=writer)
    except Exception as exc:
        failure: dict[str, Any] = {
            "mode": "apply" if config.apply else "overview",
            "status": "controller_internal_error",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "outcomes": [],
            "write_possible": bool(config.apply),
        }
        print(json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result.report, ensure_ascii=False, indent=2, sort_keys=True))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
