"""Recover Binance crypto bar gaps from each pair's evidenced source start.

Read-only by default: without ``--apply`` the script loads the inception
manifest, audits the warehouse keyset, prints a month-bounded plan and makes
**no** exchange call and **no** checkpoint write.  ``--apply`` runs one bounded
batch through the registered collector script and closes a shard only after the
warehouse keyset confirms every expected open time in its range.

Invariants (do not relax them):

* A bar is never fabricated.  An expected hour the source does not have is
  classified ``source_absent``; an hour whose source row exists but is invalid
  (empty price cell, ``close_time`` not after ``open_time``) is
  ``archive_invalid_bar``.  Neither becomes a zero-filled or forward-filled bar.
  An empty price cell normalizes to ``None`` -- the established warehouse NULL
  that ``mysql_base`` writes as SQL NULL -- and ``0`` stays ``0.0``.
* Business time is preserved.  Shard bounds and verification windows are the
  source's own UTC bar-open instants; a snapshot observation is never relabelled
  as a historical bar.
* ``--max-shards``, ``--max-minutes``, ``--pause-seconds``, ``--timeout-seconds``
  and ``--retry-cooldown-hours`` are real limits on vendor traffic.
* Checkpoints are append-only.  A closed or evidenced shard is skipped on
  re-run; an open attempt defers until its cooldown expires.  Nothing here
  resets a cursor or clears a cooldown to "unblock" a run.

Report shape and exit codes are what
``scripts/ops/run_full_history_recovery_worker.py`` parses in
``_classify_crypto``: ``apply`` (one row per processed shard) plus
``apply_summary`` obeying ``open`` = this run's non-terminal rows,
``plan_open_remaining_shards`` = ``planned_shards`` - this run's terminal rows,
and exit ``0`` only when the plan has no shard left outside the closed set,
``1`` when it does, ``2`` on a usage or audit failure.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import math
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from datetime import time as datetime_time
from pathlib import Path
from typing import Any, Final, Protocol
from uuid import uuid4

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_ROOT.parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

UTC_TIME = timezone.utc

LOGGER = logging.getLogger("crypto_full_history_recovery")

DEFAULT_MANIFEST = _REPO_ROOT / "var/reports/iteration203/crypto-inception-manifest.json"
DEFAULT_PROGRESS = _REPO_ROOT / "var/reports/iteration203/crypto-hourly-full-history-progress.jsonl"
DEFAULT_EVIDENCE = _BACKEND_ROOT / "logs/crypto_full_history_recovery/source_absence_evidence.jsonl"

INTERVAL_MS: Final[Mapping[str, int]] = {"1d": 86_400_000, "1h": 3_600_000}
#: interval -> (registered data script id, warehouse table)
INTERVAL_TARGETS: Final[Mapping[str, tuple[str, str]]] = {
    "1d": ("crypto_daily_market", "CRYPTO_DAILY_MARKET"),
    "1h": ("crypto_hourly_market", "CRYPTO_HOURLY_MARKET"),
}
SOURCE_MARKET: Final = "BINANCE"
#: Positional kline columns whose price cells must survive as NULL when empty.
PRICE_FIELDS: Final = ("open_price", "high_price", "low_price", "close_price")

# Statuses the recovery worker accepts from this controller.  Anything outside
# this set makes the worker flag the run for review, so a dispatch failure is
# recorded as an open gap carrying an ``error_class`` instead of a new status.
STATUS_CLOSED: Final = "closed"
STATUS_SOURCE_ABSENT: Final = "source_absent"
STATUS_SOURCE_INVALID: Final = "source_invalid"
STATUS_UNRESOLVED: Final = "unresolved_coverage"
STATUS_DEFERRED_UNRESOLVED: Final = "deferred_unresolved_cooldown"
STATUS_DEFERRED_FAILED: Final = "deferred_failed_cooldown"
STATUS_NOT_RUN_BUDGET: Final = "not_run_batch_budget"
TERMINAL_STATUSES: Final = frozenset({STATUS_CLOSED, STATUS_SOURCE_ABSENT, STATUS_SOURCE_INVALID})
OPEN_STATUSES: Final = frozenset(
    {
        STATUS_UNRESOLVED,
        STATUS_DEFERRED_UNRESOLVED,
        STATUS_DEFERRED_FAILED,
        STATUS_NOT_RUN_BUDGET,
    }
)
ALLOWED_STATUSES: Final = TERMINAL_STATUSES | OPEN_STATUSES
#: A budget or cooldown deferral records what one run did; it is not the period's
#: state, so it never replaces the attempt whose cooldown is running.
MATERIAL_STATUSES: Final = TERMINAL_STATUSES | {STATUS_UNRESOLVED}

#: Per-hour gap classifications, reused from the iteration 203 evidence ledger.
GAP_REPAIRABLE: Final = "archive_contains_bar"
GAP_SOURCE_ABSENT: Final = "source_absent"
GAP_ARCHIVE_INVALID: Final = "archive_invalid_bar"
GAP_ARCHIVE_UNAVAILABLE: Final = "archive_unavailable"

ERROR_CLASS_COVERAGE: Final = "coverage_remaining"
ERROR_CLASS_DISPATCH_FAILED: Final = "dispatch_failed"
ERROR_CLASS_INFRASTRUCTURE_FATAL: Final = "infrastructure_fatal"
ERROR_CLASS_OUTCOME_UNKNOWN: Final = "outcome_unknown"
ERROR_CLASS_VERIFICATION: Final = "verification_failed"
#: Open attempts whose retry is deferred as a failure rather than as coverage.
FAILURE_ERROR_CLASSES: Final = frozenset(
    {ERROR_CLASS_DISPATCH_FAILED, ERROR_CLASS_INFRASTRUCTURE_FATAL, ERROR_CLASS_VERIFICATION}
)

DEFAULT_REPORT_EXIT_RESERVE_SECONDS: Final = 15.0
#: Keep enough budget to verify a shard after its managed call returns.
POST_MANAGED_VERIFY_RESERVE_SECONDS: Final = 2.0
#: Magnitude cutover for source epoch scale, mirroring ``binance_vision``: the
#: archive switched from milliseconds to microseconds, so scale is not scope.
_MICROSECOND_CUTOVER: Final = 100_000_000_000_000
_SECOND_CUTOVER: Final = 100_000_000_000

DaySleep = Callable[[float], Any]


class KeyReader(Protocol):
    """Read the warehouse ``OPEN_TIME_MS`` keyset for one pair and time range."""

    def read_open_times(
        self, *, table: str, symbol: str, start_ms: int, end_ms: int
    ) -> set[int]: ...


class SourceProbe(Protocol):
    """Ask the source what it actually holds for one calendar month."""

    def fetch_month(self, *, symbol: str, interval: str, month: str) -> MonthEvidence: ...


class Dispatcher(Protocol):
    """Run the registered collector script for one shard window."""

    async def dispatch(
        self, *, shard: RecoveryShard, timeout_seconds: float
    ) -> DispatchReceipt: ...


@dataclass(frozen=True)
class PairSpec:
    """One manifest pair: a source-evidenced first bar, never a guessed listing date."""

    symbol: str
    interval: str
    first_open_ms: int
    listing_boundary: str

    @property
    def step_ms(self) -> int:
        return INTERVAL_MS[self.interval]

    @property
    def table(self) -> str:
        return INTERVAL_TARGETS[self.interval][1]

    @property
    def script_id(self) -> str:
        return INTERVAL_TARGETS[self.interval][0]


@dataclass(frozen=True)
class MissingRange:
    start_ms: int
    end_ms: int
    missing_bars: int
    edge: str


@dataclass(frozen=True)
class RecoveryShard:
    """One pair/month of evidenced missing bars: the checkpoint and dispatch unit."""

    shard_id: str
    symbol: str
    interval: str
    table: str
    script_id: str
    since: str
    until: str
    expected_missing_bars: int
    first_missing_ms: int
    last_missing_ms: int
    verify_start_ms: int
    verify_end_ms: int
    gap_edges: tuple[str, ...]
    source_first_open_ms: int
    listing_boundary: str
    period_key: str
    missing_open_ms: tuple[int, ...] = ()


@dataclass(frozen=True)
class PairAudit:
    symbol: str
    interval: str
    table: str
    source_first_open_ms: int
    source_first_open_utc: str
    listing_boundary: str
    latest_closed_open_ms: int | None
    expected_bars: int = 0
    present_bars: int = 0
    missing_bars: int = 0
    gap_ranges: list[MissingRange] = field(default_factory=list)
    status: str = "audited"
    error: str | None = None


@dataclass(frozen=True)
class PlanReport:
    as_of_utc: str
    pairs: list[PairAudit]
    shards: list[RecoveryShard]
    plan_sha256: str


@dataclass(frozen=True)
class ShardOutcome:
    """One report row.  ``status`` is always inside :data:`ALLOWED_STATUSES`."""

    shard_id: str
    symbol: str
    interval: str
    since: str
    until: str
    status: str
    expected_missing_bars: int
    remaining_missing_bars: int | None = None
    execution_id: str | None = None
    error: str | None = None
    error_class: str | None = None
    source_checked_months: tuple[str, ...] = ()
    source_absent_bars: int | None = None
    source_invalid_bars: int | None = None
    database_write_possible: bool = False

    def to_ledger_record(self, *, recorded_at_utc: str) -> dict[str, Any]:
        payload: dict[str, Any] = asdict(self)
        payload["source_checked_months"] = list(self.source_checked_months)
        payload["period_key"] = period_key_of(self.symbol, self.interval, self.since)
        payload["recorded_at_utc"] = recorded_at_utc
        return payload


@dataclass(frozen=True)
class SourceBar:
    """One source row with its prices kept as ``None`` when the cell is empty."""

    open_time_ms: int
    close_time_ms: int | None
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    volume: float | None
    trade_count: int | None

    @property
    def invalid_reason(self) -> str | None:
        missing = [name for name in PRICE_FIELDS if getattr(self, name) is None]
        if missing:
            return f"empty_or_unparseable_price_cell:{','.join(missing)}"
        if self.close_time_ms is None:
            return "missing_close_time"
        if self.close_time_ms <= self.open_time_ms:
            return f"close_time_not_after_open_time:{self.close_time_ms}"
        return None

    @property
    def is_valid(self) -> bool:
        return self.invalid_reason is None


@dataclass(frozen=True)
class MonthEvidence:
    """What the archive says about one calendar month."""

    month: str
    archive_url: str
    available: bool
    bar_count: int
    bars: Mapping[int, SourceBar]


@dataclass(frozen=True)
class GapClassification:
    classes: Mapping[int, str]
    months_checked: tuple[str, ...]

    @property
    def counts(self) -> dict[str, int]:
        out = {GAP_REPAIRABLE: 0, GAP_SOURCE_ABSENT: 0, GAP_ARCHIVE_INVALID: 0}
        for name in self.classes.values():
            out[name] = out.get(name, 0) + 1
        return out

    def terminal_status(self) -> str | None:
        """A terminal source-side closure only when *every* hour is evidenced."""
        if not self.classes:
            return None
        names = set(self.classes.values())
        if names & {GAP_REPAIRABLE, GAP_ARCHIVE_UNAVAILABLE}:
            return None
        if names == {GAP_SOURCE_ABSENT}:
            return STATUS_SOURCE_ABSENT
        return STATUS_SOURCE_INVALID


@dataclass(frozen=True)
class AttemptRecord:
    """The latest checkpointed attempt for one pair/month period."""

    period_key: str
    shard_id: str
    status: str
    error_class: str | None
    recorded_at_utc: str

    @property
    def requires_retry_deferral(self) -> bool:
        """Only a real coverage/failure attempt cools down; a budget deferral does not."""
        return self.status == STATUS_UNRESOLVED


@dataclass(frozen=True)
class DispatchReceipt:
    """What the managed collector reported; never proof of coverage by itself."""

    execution_id: str | None = None
    completed: bool = False
    outcome_certain: bool = True
    error: str | None = None
    error_class: str | None = None
    database_write_possible: bool = False


@dataclass(frozen=True)
class BatchSelection:
    """The plan split into local-only work and capped vendor-bound work."""

    decided: list[ShardOutcome]
    evidenced: list[tuple[RecoveryShard, GapClassification]]
    vendor_shards: list[RecoveryShard]


# --------------------------------------------------------------------------- #
# Pure plan core
# --------------------------------------------------------------------------- #


def period_key_of(symbol: str, interval: str, since: str) -> str:
    """Stable pair/month key so a shrinking gap span stays recognised."""
    try:
        month = datetime.fromisoformat(since[:10]).strftime("%Y-%m")
    except ValueError:
        return f"shard:{symbol.strip().upper()}|{interval.strip().lower()}|{since[:10]}"
    return f"{symbol.strip().upper()}|{interval.strip().lower()}|{month}"


def load_manifest(
    path: Path,
    *,
    symbols: set[str] | None = None,
    intervals: set[str] | None = None,
) -> list[PairSpec]:
    """Load the observed source-boundary manifest without inventing dates."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("complete") is not True:
        raise ValueError("crypto inception manifest must declare complete=true")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("crypto inception manifest has no records list")

    result: list[PairSpec] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("crypto inception manifest contains a malformed record")
        symbol = str(record.get("symbol") or "").strip().upper()
        interval = str(record.get("interval") or "").strip().lower()
        if interval not in INTERVAL_MS:
            continue
        if symbols is not None and symbol not in symbols:
            continue
        if intervals is not None and interval not in intervals:
            continue
        if record.get("status") != "discovered":
            raise ValueError(f"{symbol} {interval} has no confirmed source-first bar")
        first_open_ms = record.get("first_open_ms")
        if isinstance(first_open_ms, bool) or not isinstance(first_open_ms, int):
            raise ValueError(f"{symbol} {interval} has an invalid first_open_ms")
        if first_open_ms < 0 or first_open_ms % INTERVAL_MS[interval]:
            raise ValueError(f"{symbol} {interval} first_open_ms is not interval-aligned")
        key = (symbol, interval)
        if not symbol or key in seen:
            raise ValueError(f"duplicate or empty manifest pair {key!r}")
        seen.add(key)
        result.append(
            PairSpec(
                symbol=symbol,
                interval=interval,
                first_open_ms=first_open_ms,
                listing_boundary=str(record.get("listing_boundary") or "unknown"),
            )
        )

    if symbols:
        missing = symbols - {spec.symbol for spec in result}
        if missing:
            raise ValueError(f"symbols are absent from the manifest: {', '.join(sorted(missing))}")
    if not result:
        raise ValueError("no manifest pairs match the requested filters")
    return sorted(result, key=lambda item: (item.interval, item.symbol))


def latest_closed_open_ms(interval: str, now: datetime) -> int:
    """Last bar-open instant whose interval has fully elapsed in UTC."""
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval {interval!r}")
    if now.tzinfo is None:
        raise ValueError("as-of datetime must include a timezone")
    now_ms = int(now.astimezone(UTC_TIME).timestamp() * 1000)
    step_ms = INTERVAL_MS[interval]
    return (now_ms // step_ms) * step_ms - step_ms


def utc_datetime(open_time_ms: int) -> datetime:
    return datetime.fromtimestamp(open_time_ms / 1000, tz=UTC_TIME)


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC_TIME).isoformat()


def parse_utc(value: str) -> datetime:
    """Accept ``...Z`` or an explicit offset; a naive stamp is rejected."""
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must carry a UTC offset, got {value!r}")
    return parsed.astimezone(UTC_TIME)


def epoch_ms(value: object) -> int:
    """Normalize a source epoch to milliseconds across s/ms/us scales.

    Mirrors ``app.data_fetch.providers.binance_vision.to_epoch_ms``: the archive
    changed scales between epochs, so magnitude decides, never file scope.
    """
    text = str(value).strip()
    if not text.lstrip("-").isdigit():
        raise ValueError(f"invalid source epoch {value!r}")
    raw = int(text) if "." not in text else int(float(text))
    if raw >= _MICROSECOND_CUTOVER:
        return raw // 1000
    if raw >= _SECOND_CUTOVER:
        return raw
    return raw * 1000


def number_or_none(raw: object) -> float | None:
    """Normalized NULL for an empty or unparseable numeric source cell.

    An empty price cell becomes ``None`` -- the warehouse NULL ``mysql_base``
    writes for ``NaN``/``None``.  It never becomes ``0`` and is never filled from
    a neighbour; a real source ``0`` is preserved as ``0.0``.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        numeric = float(raw)
        return numeric if math.isfinite(numeric) else None
    text = str(raw).strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        return None
    return numeric if math.isfinite(numeric) else None


def integer_or_none(raw: object) -> int | None:
    value = number_or_none(raw)
    return None if value is None else int(value)


def parse_source_bar(cells: Sequence[object]) -> SourceBar | None:
    """Map one positional kline row onto named fields, preserving its NULLs."""
    if len(cells) < 7:
        return None
    if not str(cells[0]).strip().lstrip("-").isdigit():
        return None  # header row
    try:
        open_time_ms = epoch_ms(cells[0])
    except ValueError:
        return None
    close_time_raw = cells[6]
    close_time_ms: int | None = None
    if str(close_time_raw).strip().lstrip("-").isdigit():
        close_time_ms = epoch_ms(close_time_raw)
    return SourceBar(
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        open_price=number_or_none(cells[1]),
        high_price=number_or_none(cells[2]),
        low_price=number_or_none(cells[3]),
        close_price=number_or_none(cells[4]),
        volume=number_or_none(cells[5]),
        trade_count=integer_or_none(cells[8]) if len(cells) > 8 else None,
    )


def _edge_for_range(start_ms: int, end_ms: int, first_ms: int, last_ms: int) -> str:
    is_head = start_ms == first_ms
    is_tail = end_ms == last_ms
    if is_head and is_tail:
        return "head_and_tail"
    if is_head:
        return "head"
    if is_tail:
        return "tail"
    return "internal"


def expected_open_times(start_ms: int, end_ms: int, step_ms: int) -> tuple[int, ...]:
    """Grid opens between two evidenced instants, inclusive; nothing is invented."""
    if end_ms < start_ms:
        return ()
    if step_ms <= 0 or (end_ms - start_ms) % step_ms:
        raise ValueError("expected open-time range is not aligned to the interval")
    return tuple(range(start_ms, end_ms + step_ms, step_ms))


def find_missing_ranges(
    *, first_open_ms: int, last_closed_open_ms: int, present_open_times: set[int], step_ms: int
) -> list[MissingRange]:
    """Compress absent expected opens into contiguous head/internal/tail ranges."""
    if last_closed_open_ms < first_open_ms:
        return []
    if step_ms <= 0 or (last_closed_open_ms - first_open_ms) % step_ms:
        raise ValueError("expected open-time range is not aligned to the interval")

    ranges: list[MissingRange] = []
    missing_start: int | None = None
    missing_count = 0
    cursor = first_open_ms
    while cursor <= last_closed_open_ms:
        if cursor not in present_open_times:
            if missing_start is None:
                missing_start = cursor
                missing_count = 0
            missing_count += 1
        elif missing_start is not None:
            end_ms = cursor - step_ms
            ranges.append(
                MissingRange(
                    start_ms=missing_start,
                    end_ms=end_ms,
                    missing_bars=missing_count,
                    edge=_edge_for_range(missing_start, end_ms, first_open_ms, last_closed_open_ms),
                )
            )
            missing_start = None
            missing_count = 0
        cursor += step_ms

    if missing_start is not None:
        ranges.append(
            MissingRange(
                start_ms=missing_start,
                end_ms=last_closed_open_ms,
                missing_bars=missing_count,
                edge=_edge_for_range(
                    missing_start, last_closed_open_ms, first_open_ms, last_closed_open_ms
                ),
            )
        )
    return ranges


def _month_bounds(year: int, month: int) -> tuple[int, int]:
    first = datetime(year, month, 1, tzinfo=UTC_TIME)
    next_month = (
        datetime(year + 1, 1, 1, tzinfo=UTC_TIME)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=UTC_TIME)
    )
    return int(first.timestamp() * 1000), int(next_month.timestamp() * 1000)


def month_of(open_time_ms: int) -> str:
    return utc_datetime(open_time_ms).strftime("%Y-%m")


def is_month_closed(month: str, as_of: datetime) -> bool:
    """A month is closed only when its own grid has finished elapsing."""
    parsed = datetime.strptime(month, "%Y-%m")
    _first_ms, next_month_ms = _month_bounds(parsed.year, parsed.month)
    return next_month_ms <= int(as_of.astimezone(UTC_TIME).timestamp() * 1000)


def _segment_edges(opens: Sequence[int], first_ms: int, last_ms: int, span: int) -> tuple[str, ...]:
    """Head/internal/tail labels for the contiguous runs inside one month shard."""
    edges: set[str] = set()
    run_start: int = opens[0]
    previous: int = run_start
    for open_ms in opens[1:]:
        if open_ms != previous + span:
            edges.add(_edge_for_range(run_start, previous, first_ms, last_ms))
            run_start = open_ms
        previous = open_ms
    edges.add(_edge_for_range(run_start, previous, first_ms, last_ms))
    return tuple(sorted(edges))


def build_monthly_shards(
    spec: PairSpec, gaps: Sequence[MissingRange], *, latest_closed_ms: int
) -> list[RecoveryShard]:
    """One shard per pair/month, carrying that month's evidenced missing opens."""
    step_ms = spec.step_ms
    by_month: dict[str, list[int]] = {}
    for gap in gaps:
        for open_ms in expected_open_times(gap.start_ms, gap.end_ms, step_ms):
            by_month.setdefault(month_of(open_ms), []).append(open_ms)

    shards: list[RecoveryShard] = []
    for _month, opens in sorted(by_month.items()):
        missing = tuple(sorted(opens))
        first_missing = missing[0]
        last_missing = missing[-1]
        since = utc_datetime(first_missing).date()
        until = utc_datetime(last_missing).date()
        since_ms = int(
            datetime.combine(since, datetime_time.min, tzinfo=UTC_TIME).timestamp() * 1000
        )
        until_ms = int(
            datetime.combine(until, datetime_time.min, tzinfo=UTC_TIME).timestamp() * 1000
        )
        until_ms += 86_400_000 - step_ms
        verify_start = max(spec.first_open_ms, since_ms)
        verify_end = min(latest_closed_ms, until_ms)
        identity = (
            f"{spec.symbol}|{spec.interval}|{since.isoformat()}|{until.isoformat()}|{len(missing)}"
        )
        shards.append(
            RecoveryShard(
                shard_id=hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20],
                symbol=spec.symbol,
                interval=spec.interval,
                table=spec.table,
                script_id=spec.script_id,
                since=since.isoformat(),
                until=until.isoformat(),
                expected_missing_bars=len(missing),
                first_missing_ms=first_missing,
                last_missing_ms=last_missing,
                verify_start_ms=verify_start,
                verify_end_ms=verify_end,
                gap_edges=_segment_edges(missing, spec.first_open_ms, latest_closed_ms, step_ms),
                source_first_open_ms=spec.first_open_ms,
                listing_boundary=spec.listing_boundary,
                period_key=period_key_of(spec.symbol, spec.interval, since.isoformat()),
                missing_open_ms=missing,
            )
        )
    return shards


def audit_plan(specs: Sequence[PairSpec], *, key_reader: KeyReader, as_of: datetime) -> PlanReport:
    """Compare each manifest pair with the warehouse ``OPEN_TIME_MS`` keyset."""
    if as_of.tzinfo is None:
        raise ValueError("as-of datetime must include a timezone")
    normalized = as_of.astimezone(UTC_TIME)
    pair_audits: list[PairAudit] = []
    shards: list[RecoveryShard] = []
    for spec in specs:
        last_closed = latest_closed_open_ms(spec.interval, normalized)
        base: dict[str, Any] = {
            "symbol": spec.symbol,
            "interval": spec.interval,
            "table": spec.table,
            "source_first_open_ms": spec.first_open_ms,
            "source_first_open_utc": iso_utc(utc_datetime(spec.first_open_ms)),
            "listing_boundary": spec.listing_boundary,
            "latest_closed_open_ms": last_closed,
        }
        if last_closed < spec.first_open_ms:
            pair_audits.append(PairAudit(**{**base, "status": "no_closed_source_bar_yet"}))
            continue
        if (last_closed - spec.first_open_ms) % spec.step_ms:
            pair_audits.append(
                PairAudit(
                    **{
                        **base,
                        "status": "error",
                        "error": "source first open is not aligned with the interval grid",
                    }
                )
            )
            continue
        try:
            present = key_reader.read_open_times(
                table=spec.table,
                symbol=spec.symbol,
                start_ms=spec.first_open_ms,
                end_ms=last_closed,
            )
        except Exception as exc:  # adapter boundary: record the failure, never guess
            pair_audits.append(
                PairAudit(**{**base, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
            )
            continue

        gaps = find_missing_ranges(
            first_open_ms=spec.first_open_ms,
            last_closed_open_ms=last_closed,
            present_open_times=present,
            step_ms=spec.step_ms,
        )
        pair_audits.append(
            PairAudit(
                **{
                    **base,
                    "expected_bars": (last_closed - spec.first_open_ms) // spec.step_ms + 1,
                    "present_bars": sum(
                        1 for open_ms in present if spec.first_open_ms <= open_ms <= last_closed
                    ),
                    "missing_bars": sum(gap.missing_bars for gap in gaps),
                    "gap_ranges": gaps,
                }
            )
        )
        shards.extend(build_monthly_shards(spec, gaps, latest_closed_ms=last_closed))

    shards.sort(key=lambda item: (item.since, item.symbol, item.interval, item.until))
    identity_payload = json.dumps(
        {
            "as_of_utc": iso_utc(normalized),
            "pairs": [asdict(pair) for pair in pair_audits],
            "shards": [shard_payload(shard) for shard in shards],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return PlanReport(
        as_of_utc=iso_utc(normalized),
        pairs=pair_audits,
        shards=shards,
        plan_sha256=hashlib.sha256(identity_payload.encode("utf-8")).hexdigest(),
    )


def shard_payload(shard: RecoveryShard) -> dict[str, Any]:
    """Report-visible shard view; the full missing-open list stays internal."""
    payload = asdict(shard)
    payload.pop("missing_open_ms", None)
    return payload


# --------------------------------------------------------------------------- #
# Pure gap classification
# --------------------------------------------------------------------------- #


def build_month_evidence(
    *, month: str, archive_url: str, available: bool, rows: Sequence[Sequence[object]]
) -> MonthEvidence:
    bars: dict[int, SourceBar] = {}
    for cells in rows:
        bar = parse_source_bar(cells)
        if bar is not None:
            bars[bar.open_time_ms] = bar
    return MonthEvidence(
        month=month, archive_url=archive_url, available=available, bar_count=len(bars), bars=bars
    )


def make_month_evidence(
    source: SourceProbe, *, symbol: str, interval: str, month: str, as_of: datetime
) -> MonthEvidence:
    """A month the archive has not rolled up yet answers nothing about its hours."""
    evidence = source.fetch_month(symbol=symbol, interval=interval, month=month)
    if evidence.available and not is_month_closed(month, as_of):
        return MonthEvidence(
            month=evidence.month,
            archive_url=evidence.archive_url,
            available=False,
            bar_count=evidence.bar_count,
            bars=evidence.bars,
        )
    return evidence


def classify_missing_opens(
    shard: RecoveryShard, months: Sequence[MonthEvidence]
) -> GapClassification:
    """Classify each expected missing hour from archive evidence only.

    An hour is repairable (``archive_contains_bar``) only when the source really
    returned a valid row at that exact UTC open time.  Absence in a closed,
    fetchable month is ``source_absent``; a row that exists but is empty or
    self-inconsistent is ``archive_invalid_bar``.  A month the archive cannot
    answer for stays unevidenced instead of being guessed either way.
    """
    by_month = {item.month: item for item in months}
    classes: dict[int, str] = {}
    checked: list[str] = []
    for open_ms in shard.missing_open_ms:
        month = month_of(open_ms)
        evidence = by_month.get(month)
        if evidence is None:
            classes[open_ms] = GAP_ARCHIVE_UNAVAILABLE
            continue
        if month not in checked:
            checked.append(month)
        if not evidence.available:
            classes[open_ms] = GAP_ARCHIVE_UNAVAILABLE
            continue
        bar = evidence.bars.get(open_ms)
        if bar is None:
            classes[open_ms] = GAP_SOURCE_ABSENT
        elif bar.is_valid:
            classes[open_ms] = GAP_REPAIRABLE
        else:
            classes[open_ms] = GAP_ARCHIVE_INVALID
    return GapClassification(classes=classes, months_checked=tuple(sorted(checked)))


def _evidence_classification(
    symbol: str, interval: str, opens: Sequence[int], index: Mapping[tuple[str, str, int], str]
) -> GapClassification | None:
    """Rebuild a classification from checkpointed evidence for the given opens."""
    if not opens:
        return None
    classes: dict[int, str] = {}
    for open_ms in opens:
        name = index.get((symbol, interval, open_ms))
        if name is None or name == GAP_ARCHIVE_UNAVAILABLE:
            return None
        classes[open_ms] = name
    return GapClassification(
        classes=classes, months_checked=tuple(sorted({month_of(o) for o in opens}))
    )


def classification_from_evidence_index(
    shard: RecoveryShard, index: Mapping[tuple[str, str, int], str]
) -> GapClassification | None:
    """Whole-shard classification from the evidence ledger: no probe, no dispatch."""
    return _evidence_classification(shard.symbol, shard.interval, shard.missing_open_ms, index)


def residual_classification(
    shard: RecoveryShard,
    still_missing: Sequence[int],
    index: Mapping[tuple[str, str, int], str],
) -> GapClassification | None:
    """Classify only the hours a collection round could not place in the warehouse.

    A mixed shard (some hours repairable, some evidenced absent) closes as
    ``source_absent`` once the repairable hours arrive, instead of staying open on
    hours the source has never published.
    """
    return _evidence_classification(shard.symbol, shard.interval, still_missing, index)


# --------------------------------------------------------------------------- #
# Append-only checkpoint ledger
# --------------------------------------------------------------------------- #


def append_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    """Append checkpoints in place; an atomic rename would strand this inode."""
    rows = list(records)
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in rows:
            handle.write(json.dumps(dict(record), ensure_ascii=False, sort_keys=True) + "\n")


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def load_attempts(progress_path: Path) -> dict[str, AttemptRecord]:
    """Latest checkpointed attempt per pair/month; the newest line always wins."""
    latest: dict[str, tuple[AttemptRecord, datetime]] = {}
    for record in _iter_jsonl(progress_path):
        try:
            symbol = str(record["symbol"])
            interval = str(record["interval"])
            since = str(record["since"])
            status = str(record["status"])
            recorded = parse_utc(str(record["recorded_at_utc"]))
        except (KeyError, TypeError, ValueError):
            continue
        if status not in ALLOWED_STATUSES:
            # A status from an older controller build is still history: treat it
            # as an open attempt so its cooldown guard is never widened.
            status = STATUS_UNRESOLVED
        if status not in MATERIAL_STATUSES:
            # A budget or cooldown deferral receipts this run; it is not the
            # period's state, so it must never replace (and so clear) the open
            # attempt whose cooldown is running.
            continue
        attempt = AttemptRecord(
            period_key=period_key_of(symbol, interval, since),
            shard_id=str(record.get("shard_id") or ""),
            status=status,
            error_class=(
                str(record["error_class"]) if record.get("error_class") is not None else None
            ),
            recorded_at_utc=iso_utc(recorded),
        )
        previous = latest.get(attempt.period_key)
        if previous is None or recorded >= previous[1]:
            latest[attempt.period_key] = (attempt, recorded)
    return {key: value[0] for key, value in latest.items()}


def load_evidence_index(evidence_path: Path) -> dict[tuple[str, str, int], str]:
    """Per-hour archive classifications already evidenced on disk."""
    index: dict[tuple[str, str, int], str] = {}
    for record in _iter_jsonl(evidence_path):
        try:
            symbol = str(record["symbol"]).strip().upper()
            interval = str(record["interval"]).strip().lower()
            open_ms = int(record["open_time_ms"])
            name = str(record["classification"])
        except (KeyError, TypeError, ValueError):
            continue
        if name in {GAP_REPAIRABLE, GAP_SOURCE_ABSENT, GAP_ARCHIVE_INVALID}:
            index[(symbol, interval, open_ms)] = name
    return index


def evidence_rows(
    shard: RecoveryShard,
    classification: GapClassification,
    months: Mapping[str, MonthEvidence],
    *,
    verified_at_utc: str,
) -> list[dict[str, Any]]:
    """One evidence row per classified hour, carrying the source's own bounds."""
    rows: list[dict[str, Any]] = []
    for open_ms, name in sorted(classification.classes.items()):
        if name == GAP_ARCHIVE_UNAVAILABLE:
            continue  # nothing was established; recording it would be a fake
        evidence = months.get(month_of(open_ms))
        bar = evidence.bars.get(open_ms) if evidence is not None else None
        rows.append(
            {
                "symbol": shard.symbol,
                "interval": shard.interval,
                "month": month_of(open_ms),
                "open_time_ms": open_ms,
                "open_time_utc": iso_utc(utc_datetime(open_ms)),
                "classification": name,
                "shard_id": shard.shard_id,
                "archive_url": evidence.archive_url if evidence is not None else None,
                "archive_bar_count": evidence.bar_count if evidence is not None else None,
                "verified_at_utc": verified_at_utc,
                "source_close_time_ms": None if bar is None else bar.close_time_ms,
                "source_close_price": None if bar is None else bar.close_price,
                "source_volume": None if bar is None else bar.volume,
                "invalid_reason": None if bar is None else bar.invalid_reason,
            }
        )
    return rows


def cooling_attempts(
    attempts: Mapping[str, AttemptRecord], *, now: datetime, cooldown: timedelta
) -> dict[str, AttemptRecord]:
    """Open attempts whose retry window has not elapsed yet."""
    cutoff = now.astimezone(UTC_TIME) - cooldown
    cooling: dict[str, AttemptRecord] = {}
    for period_key, attempt in attempts.items():
        if not attempt.requires_retry_deferral:
            continue
        try:
            recorded = parse_utc(attempt.recorded_at_utc)
        except ValueError:
            # An unreadable checkpoint keeps its guard: defer, never retry.
            cooling[period_key] = attempt
            continue
        if recorded >= cutoff:
            cooling[period_key] = attempt
    return cooling


# --------------------------------------------------------------------------- #
# Pure batch selection
# --------------------------------------------------------------------------- #


def select_batch(
    shards: Sequence[RecoveryShard],
    *,
    attempts: Mapping[str, AttemptRecord],
    evidence_index: Mapping[tuple[str, str, int], str],
    now: datetime,
    cooldown: timedelta,
    max_shards: int,
) -> BatchSelection:
    """Split the plan into local-only work and capped vendor-bound work.

    Idempotent skips and cooldown deferrals come from checkpoints alone, so they
    never consume ``max_shards``; only shards still needing an archive probe or a
    managed collection count against that vendor limit.
    """
    cooling = cooling_attempts(attempts, now=now, cooldown=cooldown)
    decided: list[ShardOutcome] = []
    evidenced: list[tuple[RecoveryShard, GapClassification]] = []
    vendor: list[RecoveryShard] = []
    for shard in shards:
        attempt = attempts.get(shard.period_key)
        classification = classification_from_evidence_index(shard, evidence_index)
        status = classification.terminal_status() if classification is not None else None
        if status in {STATUS_SOURCE_ABSENT, STATUS_SOURCE_INVALID} and classification is not None:
            if attempt is not None and attempt.status in TERMINAL_STATUSES:
                # Idempotent skip: already evidenced, so no probe and no dispatch.
                decided.append(_evidenced_outcome(shard, status, classification))
            else:
                evidenced.append((shard, classification))
            continue
        deferred = cooling.get(shard.period_key)
        if deferred is not None:
            defer_status = (
                STATUS_DEFERRED_FAILED
                if deferred.error_class in FAILURE_ERROR_CLASSES
                else STATUS_DEFERRED_UNRESOLVED
            )
            decided.append(
                _deferred(shard, defer_status, _cooldown_reason(shard, deferred, cooldown))
            )
            continue
        vendor.append(shard)
    return BatchSelection(decided=decided, evidenced=evidenced, vendor_shards=vendor[:max_shards])


UNKNOWN_WRITE_STOP_REASON: Final = (
    "stopped after a managed dispatch whose write outcome became unknown; "
    "no further shard was dispatched"
)
INFRASTRUCTURE_STOP_REASON: Final = (
    "stopped after an infrastructure failure; the gap stays open and no further "
    "shard was dispatched"
)
BUDGET_STOP_REASON: Final = (
    "batch time budget exhausted before the source probe; no source call was made; "
    "no further shard was dispatched"
)


def _cooldown_reason(shard: RecoveryShard, attempt: AttemptRecord, cooldown: timedelta) -> str:
    hours = cooldown.total_seconds() / 3600
    return (
        f"previous {attempt.status} attempt for {shard.symbol}/{shard.interval}/{shard.since[:7]} "
        f"at {attempt.recorded_at_utc} is within the {hours:g} hour retry cooldown; gap remains open"
    )


def _deferred(shard: RecoveryShard, status: str, error: str) -> ShardOutcome:
    return ShardOutcome(
        shard_id=shard.shard_id,
        symbol=shard.symbol,
        interval=shard.interval,
        since=shard.since,
        until=shard.until,
        status=status,
        expected_missing_bars=shard.expected_missing_bars,
        error=error,
    )


def _evidenced_outcome(
    shard: RecoveryShard,
    status: str,
    classification: GapClassification,
    *,
    remaining_missing_bars: int | None = None,
) -> ShardOutcome:
    counts = classification.counts
    return ShardOutcome(
        shard_id=shard.shard_id,
        symbol=shard.symbol,
        interval=shard.interval,
        since=shard.since,
        until=shard.until,
        status=status,
        expected_missing_bars=shard.expected_missing_bars,
        remaining_missing_bars=(
            shard.expected_missing_bars
            if remaining_missing_bars is None
            else remaining_missing_bars
        ),
        error=(
            "evidenced against the closed-month Binance archive; no valid source bar exists for "
            "these opens, so the shard was not dispatched and no bar was fabricated"
        ),
        source_checked_months=classification.months_checked,
        source_absent_bars=counts.get(GAP_SOURCE_ABSENT, 0),
        source_invalid_bars=counts.get(GAP_ARCHIVE_INVALID, 0),
    )


# --------------------------------------------------------------------------- #
# Reporting (the worker's parse contract)
# --------------------------------------------------------------------------- #


def apply_summary(
    plan: PlanReport,
    outcomes: Sequence[ShardOutcome],
    *,
    progress_path: Path,
    evidence_path: Path,
    source_requests: int,
) -> dict[str, Any]:
    """Summarize this run and the whole plan in the shape the worker parses."""
    planned = {shard.shard_id: shard for shard in plan.shards}
    seen: set[str] = set()
    for outcome in outcomes:
        if outcome.shard_id in seen:
            raise ValueError(f"duplicate apply outcome shard id: {outcome.shard_id}")
        if outcome.status not in ALLOWED_STATUSES:
            raise ValueError(f"outcome status is outside the worker contract: {outcome.status}")
        if outcome.shard_id not in planned:
            raise ValueError(f"apply outcome is not in the audited plan: {outcome.shard_id}")
        if outcome.expected_missing_bars != planned[outcome.shard_id].expected_missing_bars:
            raise ValueError(f"apply outcome changed planned key count: {outcome.shard_id}")
        seen.add(outcome.shard_id)

    counts = dict.fromkeys(sorted(ALLOWED_STATUSES), 0)
    for outcome in outcomes:
        counts[outcome.status] += 1
    terminal_this_run = sum(counts[status] for status in TERMINAL_STATUSES)
    open_rows = sum(1 for outcome in outcomes if outcome.status not in TERMINAL_STATUSES)
    plan_open = len(planned) - terminal_this_run
    if plan_open < 0:
        raise ValueError("terminal shard count exceeds the planned shard count")
    if open_rows > plan_open:
        raise ValueError("selected open count exceeds the remaining planned shard count")
    return {
        "planned_shards": len(planned),
        "selected": len(outcomes),
        "closed": counts[STATUS_CLOSED],
        "source_absent": counts[STATUS_SOURCE_ABSENT],
        "source_invalid": counts[STATUS_SOURCE_INVALID],
        "unresolved": counts[STATUS_UNRESOLVED],
        "deferred_unresolved": counts[STATUS_DEFERRED_UNRESOLVED],
        "deferred_failed": counts[STATUS_DEFERRED_FAILED],
        "not_run": counts[STATUS_NOT_RUN_BUDGET],
        # The worker requires ``open`` to be this run's non-terminal row count.
        "open": open_rows,
        "plan_open_remaining_shards": plan_open,
        "progress_file": str(progress_path),
        "evidence_file": str(evidence_path),
        "source_requests_made": source_requests,
        "warehouse_write_calls": 0,
        "fabricated_bars": 0,
        "scheduler_started": False,
    }


def report_payload(
    plan: PlanReport,
    *,
    mode: str,
    run_id: str,
    limits: Mapping[str, Any],
    budget: Mapping[str, Any],
    stats: Mapping[str, Any] | None = None,
    outcomes: Sequence[ShardOutcome] | None = None,
    summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "read_only": mode != "apply",
        "as_of_utc": plan.as_of_utc,
        "plan_sha256": plan.plan_sha256,
        "summary": {
            "pairs": len(plan.pairs),
            "pair_errors": sum(1 for pair in plan.pairs if pair.status == "error"),
            "missing_bars": sum(pair.missing_bars for pair in plan.pairs),
            "shards": len(plan.shards),
        },
        "pairs": [asdict(pair) for pair in plan.pairs],
        "shards": [shard_payload(shard) for shard in plan.shards],
        "limits": dict(limits),
        "budget": dict(budget),
    }
    if stats is not None:
        payload["stats"] = dict(stats)
    if outcomes is not None:
        payload["apply"] = [asdict(outcome) for outcome in outcomes]
    if summary is not None:
        payload["apply_summary"] = dict(summary)
    return payload


def serialize_report(payload: Mapping[str, Any], output: Path | None) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    return text


# --------------------------------------------------------------------------- #
# Bounded apply orchestration (adapters injected; the pure core stays I/O free)
# --------------------------------------------------------------------------- #


async def apply_batch(
    plan: PlanReport,
    *,
    key_reader: KeyReader,
    source: SourceProbe,
    dispatcher: Dispatcher,
    progress_path: Path,
    evidence_path: Path,
    max_shards: int,
    pause_seconds: float,
    timeout_seconds: float,
    retry_cooldown_hours: float,
    deadline: float,
    now: datetime,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: DaySleep = asyncio.sleep,
) -> tuple[list[ShardOutcome], dict[str, int]]:
    """Run one capped batch and checkpoint only what the source and keyset confirm."""
    if max_shards < 1:
        raise ValueError("max_shards must be at least one")
    if pause_seconds < 1:
        raise ValueError("pause_seconds must be at least one second")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if retry_cooldown_hours < 0:
        raise ValueError("retry_cooldown_hours must be non-negative")

    attempts = load_attempts(progress_path)
    evidence_index = load_evidence_index(evidence_path)
    cooldown = timedelta(hours=retry_cooldown_hours)
    stats = {
        "source_requests": 0,
        "dispatches": 0,
        "archive_months_fetched": 0,
        "checkpoint_skips": 0,
    }
    selection = select_batch(
        plan.shards,
        attempts=attempts,
        evidence_index=evidence_index,
        now=now,
        cooldown=cooldown,
        max_shards=max_shards,
    )
    outcomes: list[ShardOutcome] = list(selection.decided)
    stats["checkpoint_skips"] = len(selection.decided)
    # A cooldown deferral or an idempotent skip records no new evidence and performed
    # no work, so it is reported for this run but never written over the material
    # attempt that carries the period's state.

    # Already-evidenced shards close from local evidence: no exchange call, no dispatch.
    for shard, classification in selection.evidenced:
        status = classification.terminal_status()
        if status is None:  # pragma: no cover - select_batch only offers terminals
            continue
        outcome = _evidenced_outcome(shard, status, classification)
        outcomes.append(outcome)
        _checkpoint(progress_path, outcome, now=now)

    stop_reason: str | None = None
    for index, shard in enumerate(selection.vendor_shards):
        if stop_reason is not None:
            outcome = _deferred(shard, STATUS_NOT_RUN_BUDGET, stop_reason)
            outcomes.append(outcome)
            _checkpoint(progress_path, outcome, now=now)
            continue
        if deadline - monotonic() <= POST_MANAGED_VERIFY_RESERVE_SECONDS:
            stop_reason = BUDGET_STOP_REASON
            outcome = _deferred(shard, STATUS_NOT_RUN_BUDGET, stop_reason)
            outcomes.append(outcome)
            _checkpoint(progress_path, outcome, now=now)
            continue

        months, classification = await _probe_missing_months(
            shard,
            source=source,
            evidence_index=evidence_index,
            deadline=deadline,
            monotonic=monotonic,
            stats=stats,
            as_of=now,
        )
        append_jsonl(
            evidence_path,
            evidence_rows(shard, classification, months, verified_at_utc=iso_utc(now)),
        )
        # Keep this run's fresh evidence in the index too: a mixed shard must be able
        # to close from it after collection without re-reading the archive.
        for open_ms, name in classification.classes.items():
            if name != GAP_ARCHIVE_UNAVAILABLE:
                evidence_index[(shard.symbol, shard.interval, open_ms)] = name
        terminal = classification.terminal_status()
        if terminal in {STATUS_SOURCE_ABSENT, STATUS_SOURCE_INVALID}:
            outcome = _evidenced_outcome(shard, terminal, classification)
            outcomes.append(outcome)
            _checkpoint(progress_path, outcome, now=now)
            continue

        receipt = await dispatcher.dispatch(
            shard=shard, timeout_seconds=min(timeout_seconds, max(1.0, deadline - monotonic()))
        )
        stats["dispatches"] += 1
        stats["source_requests"] += 1

        present, verification_error = _read_keyset(shard, key_reader=key_reader)
        remaining_count: int | None = None
        still_missing: tuple[int, ...] = ()
        if present is not None:
            expected = expected_open_times(
                shard.verify_start_ms, shard.verify_end_ms, INTERVAL_MS[shard.interval]
            )
            remaining_count = sum(1 for open_ms in expected if open_ms not in present)
            still_missing = tuple(
                open_ms for open_ms in shard.missing_open_ms if open_ms not in present
            )

        if not receipt.outcome_certain:
            outcome = ShardOutcome(
                shard_id=shard.shard_id,
                symbol=shard.symbol,
                interval=shard.interval,
                since=shard.since,
                until=shard.until,
                status=STATUS_UNRESOLVED,
                expected_missing_bars=shard.expected_missing_bars,
                remaining_missing_bars=remaining_count,
                execution_id=receipt.execution_id,
                error=(
                    f"{receipt.error or 'managed dispatch outcome is unknown'}; the managed write "
                    "may have committed, so no source failure was recorded and no bar was fabricated"
                    + (f"; keyset verification: {verification_error}" if verification_error else "")
                ),
                error_class=ERROR_CLASS_OUTCOME_UNKNOWN,
                source_checked_months=classification.months_checked,
                database_write_possible=True,
            )
            outcomes.append(outcome)
            _checkpoint(progress_path, outcome, now=now)
            stop_reason = UNKNOWN_WRITE_STOP_REASON
            continue

        if receipt.error_class == ERROR_CLASS_INFRASTRUCTURE_FATAL:
            # A broken database path would repeat on the next shard, so the batch
            # stops with the gap open instead of spending more vendor traffic.
            outcomes.append(
                ShardOutcome(
                    shard_id=shard.shard_id,
                    symbol=shard.symbol,
                    interval=shard.interval,
                    since=shard.since,
                    until=shard.until,
                    status=STATUS_UNRESOLVED,
                    expected_missing_bars=shard.expected_missing_bars,
                    remaining_missing_bars=remaining_count,
                    execution_id=receipt.execution_id,
                    error=receipt.error,
                    error_class=ERROR_CLASS_INFRASTRUCTURE_FATAL,
                    source_checked_months=classification.months_checked,
                    database_write_possible=receipt.database_write_possible,
                )
            )
            _checkpoint(progress_path, outcomes[-1], now=now)
            stop_reason = INFRASTRUCTURE_STOP_REASON
            continue

        if verification_error is not None:
            outcomes.append(
                ShardOutcome(
                    shard_id=shard.shard_id,
                    symbol=shard.symbol,
                    interval=shard.interval,
                    since=shard.since,
                    until=shard.until,
                    status=STATUS_UNRESOLVED,
                    expected_missing_bars=shard.expected_missing_bars,
                    remaining_missing_bars=None,
                    execution_id=receipt.execution_id,
                    error=f"{receipt.error}; {verification_error}"
                    if receipt.error
                    else verification_error,
                    error_class=ERROR_CLASS_VERIFICATION,
                    source_checked_months=classification.months_checked,
                    database_write_possible=receipt.database_write_possible,
                )
            )
            _checkpoint(progress_path, outcomes[-1], now=now)
            continue

        if remaining_count == 0:
            outcomes.append(
                ShardOutcome(
                    shard_id=shard.shard_id,
                    symbol=shard.symbol,
                    interval=shard.interval,
                    since=shard.since,
                    until=shard.until,
                    status=STATUS_CLOSED,
                    expected_missing_bars=shard.expected_missing_bars,
                    remaining_missing_bars=0,
                    execution_id=receipt.execution_id,
                    source_checked_months=classification.months_checked,
                )
            )
            _checkpoint(progress_path, outcomes[-1], now=now)
            if index + 1 < len(selection.vendor_shards):
                pause_budget = deadline - monotonic()
                if pause_budget > 0:
                    await sleep(min(pause_seconds, pause_budget))
            continue

        after = residual_classification(shard, still_missing, evidence_index)
        after_status = after.terminal_status() if after is not None else None
        if after_status in {STATUS_SOURCE_ABSENT, STATUS_SOURCE_INVALID} and after is not None:
            outcomes.append(
                _evidenced_outcome(
                    shard, after_status, after, remaining_missing_bars=len(still_missing)
                )
            )
        else:
            outcomes.append(
                ShardOutcome(
                    shard_id=shard.shard_id,
                    symbol=shard.symbol,
                    interval=shard.interval,
                    since=shard.since,
                    until=shard.until,
                    status=STATUS_UNRESOLVED,
                    expected_missing_bars=shard.expected_missing_bars,
                    remaining_missing_bars=remaining_count,
                    execution_id=receipt.execution_id,
                    error=(
                        receipt.error
                        or f"warehouse still has {len(still_missing)} expected missing bars"
                    ),
                    error_class=receipt.error_class or ERROR_CLASS_COVERAGE,
                    source_checked_months=classification.months_checked,
                    database_write_possible=receipt.database_write_possible,
                )
            )
        _checkpoint(progress_path, outcomes[-1], now=now)
        if index + 1 < len(selection.vendor_shards):
            pause_budget = deadline - monotonic()
            if pause_budget > 0:
                await sleep(min(pause_seconds, pause_budget))

    return outcomes, stats


def _checkpoint(progress_path: Path, outcome: ShardOutcome, *, now: datetime) -> None:
    append_jsonl(progress_path, [outcome.to_ledger_record(recorded_at_utc=iso_utc(now))])


async def _probe_missing_months(
    shard: RecoveryShard,
    *,
    source: SourceProbe,
    evidence_index: dict[tuple[str, str, int], str],
    deadline: float,
    monotonic: Callable[[], float],
    stats: dict[str, int],
    as_of: datetime,
) -> tuple[dict[str, MonthEvidence], GapClassification]:
    """Fetch only the months still lacking evidence, inside the time budget."""
    wanted = sorted(
        {
            month_of(open_ms)
            for open_ms in shard.missing_open_ms
            if (shard.symbol, shard.interval, open_ms) not in evidence_index
        }
    )
    months: dict[str, MonthEvidence] = {}
    for month in wanted:
        if deadline - monotonic() <= POST_MANAGED_VERIFY_RESERVE_SECONDS:
            break  # leave the hours unevidenced rather than overrun the vendor budget
        evidence = make_month_evidence(
            source, symbol=shard.symbol, interval=shard.interval, month=month, as_of=as_of
        )
        months[month] = evidence
        stats["archive_months_fetched"] += 1
        stats["source_requests"] += 1
    classification = classify_missing_opens(shard, list(months.values()))
    classes = dict(classification.classes)
    checked = set(classification.months_checked)
    for open_ms, name in list(classes.items()):
        if name != GAP_ARCHIVE_UNAVAILABLE:
            continue
        previous = evidence_index.get((shard.symbol, shard.interval, open_ms))
        if previous is not None:
            classes[open_ms] = previous
            checked.add(month_of(open_ms))
    return months, GapClassification(classes=classes, months_checked=tuple(sorted(checked)))


def _read_keyset(
    shard: RecoveryShard, *, key_reader: KeyReader
) -> tuple[set[int] | None, str | None]:
    try:
        return (
            key_reader.read_open_times(
                table=shard.table,
                symbol=shard.symbol,
                start_ms=shard.verify_start_ms,
                end_ms=shard.verify_end_ms,
            ),
            None,
        )
    except Exception as exc:  # adapter boundary
        return None, f"keyset verification: {type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------- #
# Warehouse / exchange / scheduler adapters (lazy app imports, thin by design)
# --------------------------------------------------------------------------- #


class MySQLKeyReader:
    """Read-only ``OPEN_TIME_MS`` keyset reader; the controller keeps no bar write."""

    def __init__(self, *, fetch_size: int = 10_000) -> None:
        self.fetch_size = fetch_size
        self.connection: Any | None = None

    def __enter__(self) -> MySQLKeyReader:
        import mysql.connector

        from app.data_fetch.configs.db_config import DB_CONFIG

        self.connection = mysql.connector.connect(**DB_CONFIG, autocommit=True)
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def read_open_times(self, *, table: str, symbol: str, start_ms: int, end_ms: int) -> set[int]:
        allowed_tables = {value[1] for value in INTERVAL_TARGETS.values()}
        if table not in allowed_tables:
            raise ValueError(f"unsupported crypto table {table!r}")
        if self.connection is None:
            raise RuntimeError("MySQLKeyReader must be used as a context manager")
        cursor = self.connection.cursor(buffered=False)
        try:
            cursor.execute(
                f"SELECT `OPEN_TIME_MS` FROM `{table}` "
                "WHERE `MARKET` = %s AND `SYMBOL` = %s "
                "AND `OPEN_TIME_MS` >= %s AND `OPEN_TIME_MS` <= %s "
                "ORDER BY `OPEN_TIME_MS`",
                (SOURCE_MARKET, symbol, start_ms, end_ms),
            )
            values: set[int] = set()
            while rows := cursor.fetchmany(self.fetch_size):
                values.update(int(row[0]) for row in rows if row[0] is not None)
            return values
        finally:
            cursor.close()


class BinanceArchiveSource:
    """Monthly archive probe: one HTTP GET per month, no request weight spent."""

    HOST: Final = "https://data.binance.vision"

    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def archive_url(self, symbol: str, interval: str, month: str) -> str:
        return (
            f"{self.HOST}/data/spot/monthly/klines/{symbol}/{interval}/"
            f"{symbol}-{interval}-{month}.zip"
        )

    def fetch_month(self, *, symbol: str, interval: str, month: str) -> MonthEvidence:
        url = self.archive_url(symbol, interval, month)
        unavailable = MonthEvidence(
            month=month, archive_url=url, available=False, bar_count=0, bars={}
        )
        if not _month_is_valid(month):
            return unavailable
        try:
            blob = self._get(url)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                LOGGER.warning("archive HTTP failure %s: %s", url, exc)
            # A 404 is only "the month does not exist"; the caller still refuses
            # to treat a not-yet-rolled-up month as evidence of absence.
            return unavailable
        except (OSError, TimeoutError, zipfile.BadZipFile, ValueError) as exc:
            LOGGER.warning("archive unavailable %s: %s", url, exc)
            return unavailable
        return build_month_evidence(
            month=month, archive_url=url, available=True, rows=_csv_rows(blob)
        )

    def _get(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
            return response.read()


def _month_is_valid(month: str) -> bool:
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        return False
    return True


def _csv_rows(blob: bytes) -> list[list[str]]:
    """Rows from the archive zip, cells kept raw so empty price cells survive."""
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = archive.namelist()
        if not names:
            return []
        text = archive.read(names[0]).decode("utf-8", errors="replace")
    rows: list[list[str]] = []
    for line in text.strip().splitlines():
        cells = line.split(",")
        if not cells[0].strip().lstrip("-").isdigit():
            continue  # header row (some windows carry one) or blank tail
        rows.append(cells)
    return rows


class ManagedScriptDispatcher:
    """Dispatch one shard through the registered collector script.

    The collector owns the warehouse write, so this controller has no bar write
    path at all: a source NULL cannot be turned into a fabricated bar here.  The
    current hourly script honours ``symbols``/``since`` and treats the tail
    window itself; closure is therefore decided only by the keyset re-read.
    """

    def __init__(self, *, session_factory: Callable[[], Any] | None = None) -> None:
        self._session_factory = session_factory

    async def dispatch(self, *, shard: RecoveryShard, timeout_seconds: float) -> DispatchReceipt:
        from app.db import database
        from app.models.akshare_mgmt import TriggeredBy
        from app.services.akshare.script import AkshareScriptService

        factory = self._session_factory or database.async_session_maker
        parameters: dict[str, Any] = {
            "symbols": [shard.symbol],
            "since": date.fromisoformat(shard.since),
            "until": date.fromisoformat(shard.until),
            "_ingest_mode": "backfill",
        }
        try:
            async with factory() as session:
                service = AkshareScriptService(session)
                execution = await asyncio.wait_for(
                    service.run_script(
                        shard.script_id,
                        parameters=parameters,
                        operator_id=None,
                        task_id=None,
                        triggered_by=TriggeredBy.MANUAL,
                        timeout_seconds=int(timeout_seconds),
                    ),
                    timeout=timeout_seconds + 5,
                )
        except TimeoutError:
            return DispatchReceipt(
                error=f"managed dispatch exceeded {timeout_seconds:.0f}s",
                error_class=ERROR_CLASS_OUTCOME_UNKNOWN,
                database_write_possible=True,
            )
        except Exception as exc:  # adapter boundary
            return DispatchReceipt(
                error=f"{type(exc).__name__}: {exc}",
                error_class=_error_class_for_exception(exc),
                database_write_possible=_is_infrastructure_fatal(exc),
            )
        status = str(getattr(getattr(execution, "status", None), "value", "") or "")
        execution_id: str | None = getattr(execution, "execution_id", None)
        if status != "completed":
            return DispatchReceipt(
                execution_id=execution_id,
                error=f"collection script status is {status or 'unknown'}",
                error_class=ERROR_CLASS_DISPATCH_FAILED,
                database_write_possible=True,
            )
        return DispatchReceipt(execution_id=execution_id, completed=True)


def _error_class_for_exception(exc: BaseException) -> str:
    if _is_infrastructure_fatal(exc):
        return ERROR_CLASS_INFRASTRUCTURE_FATAL
    return ERROR_CLASS_DISPATCH_FAILED


def _is_infrastructure_fatal(exc: BaseException) -> bool:
    """Failures where dispatching more shards would repeat a broken DB path."""
    try:
        from sqlalchemy.exc import SQLAlchemyError

        sqlalchemy_types: tuple[type[BaseException], ...] = (SQLAlchemyError,)
    except ImportError:  # pragma: no cover - SQLAlchemy is a runtime dependency
        sqlalchemy_types = ()

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ConnectionError, TimeoutError, OSError, *sqlalchemy_types)):
            return True
        if type(current).__module__.startswith("mysql.connector.errors"):
            return True
        current = current.__cause__ or current.__context__
    return False


@contextmanager
def _open_key_reader(reader: KeyReader | None) -> Iterator[KeyReader]:
    """Yield a usable key reader, owning the MySQL connection when none injected."""
    candidate: Any = reader if reader is not None else MySQLKeyReader()
    enter = getattr(candidate, "__enter__", None)
    if not callable(enter):
        yield candidate
        return
    entered = enter()
    try:
        yield entered
    finally:
        exit_ = getattr(candidate, "__exit__", None)
        if callable(exit_):
            exit_(None, None, None)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bound Binance crypto full-history recovery")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--symbols", help="comma-separated manifest symbols")
    parser.add_argument("--intervals", default="1h", help="comma-separated subset of 1d,1h")
    parser.add_argument(
        "--as-of", help="fixed timezone-aware audit time, e.g. 2026-11-05T00:00:00Z"
    )
    parser.add_argument("--output", type=Path, help="write the JSON report to this path")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="run one bounded batch; without this flag the CLI is read-only",
    )
    parser.add_argument("--max-shards", type=int, default=25, help="vendor-bound shards per run")
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=4.0,
        help="total CLI budget, including manifest load and the warehouse audit",
    )
    parser.add_argument(
        "--report-exit-reserve-seconds",
        type=float,
        default=DEFAULT_REPORT_EXIT_RESERVE_SECONDS,
        help="time reserved inside --max-minutes to serialize and write the report",
    )
    parser.add_argument("--pause-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--progress-file", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--evidence-file", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument(
        "--retry-cooldown-hours",
        type=float,
        default=24.0,
        help="defer an open gap for this many hours before retrying it",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.max_shards < 1:
        parser.error("--max-shards must be at least 1")
    if not math.isfinite(args.max_minutes) or args.max_minutes <= 0:
        parser.error("--max-minutes must be positive")
    if not math.isfinite(args.report_exit_reserve_seconds) or args.report_exit_reserve_seconds < 0:
        parser.error("--report-exit-reserve-seconds must be non-negative")
    if not math.isfinite(args.pause_seconds) or args.pause_seconds < 1:
        parser.error("--pause-seconds must be at least one second")
    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if not math.isfinite(args.retry_cooldown_hours) or args.retry_cooldown_hours < 0:
        parser.error("--retry-cooldown-hours must be non-negative")
    return args


def _parse_symbols(value: str | None) -> set[str] | None:
    if value is None:
        return None
    return {item.strip().upper() for item in value.split(",") if item.strip()}


def _interval_set(value: str) -> set[str]:
    intervals = {item.strip().lower() for item in value.split(",") if item.strip()}
    unknown = intervals - set(INTERVAL_MS)
    if unknown:
        raise ValueError(f"unsupported interval(s): {', '.join(sorted(unknown))}")
    return intervals


def limits_of(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "apply": bool(args.apply),
        "manifest": str(args.manifest),
        "intervals": sorted(_interval_set(args.intervals)),
        "max_shards": args.max_shards,
        "max_minutes": args.max_minutes,
        "pause_seconds": args.pause_seconds,
        "timeout_seconds": args.timeout_seconds,
        "retry_cooldown_hours": args.retry_cooldown_hours,
        "progress_file": str(args.progress_file),
        "evidence_file": str(args.evidence_file),
        "vendor_traffic_limit_covers_archive_probes_and_dispatches": True,
    }


async def run(
    args: argparse.Namespace,
    *,
    key_reader: KeyReader,
    source: SourceProbe,
    dispatcher: Dispatcher,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: DaySleep = asyncio.sleep,
    now: datetime | None = None,
) -> tuple[dict[str, Any], int]:
    """Plan or apply one bounded batch and return ``(report, exit_code)``."""
    started = monotonic()
    budget_seconds = args.max_minutes * 60
    deadline = started + budget_seconds
    apply_deadline = deadline - args.report_exit_reserve_seconds
    as_of = parse_utc(args.as_of) if args.as_of else (now or datetime.now(UTC_TIME))
    specs = load_manifest(
        args.manifest,
        symbols=_parse_symbols(args.symbols),
        intervals=_interval_set(args.intervals),
    )
    plan = audit_plan(specs, key_reader=key_reader, as_of=as_of)
    errors = [pair for pair in plan.pairs if pair.status == "error"]
    budget: dict[str, Any] = {
        "total_budget_seconds": budget_seconds,
        "report_exit_reserve_seconds": args.report_exit_reserve_seconds,
        "total_deadline_includes_manifest_and_warehouse_audit": True,
        "elapsed_before_apply_seconds": max(0.0, monotonic() - started),
        "apply_budget_seconds": max(0.0, apply_deadline - monotonic()),
        "dispatch_permitted": (apply_deadline - monotonic()) > POST_MANAGED_VERIFY_RESERVE_SECONDS,
        "budget_is_soft_around_blocking_sql_and_cleanup": True,
    }
    stats: dict[str, int] = {
        "source_requests": 0,
        "dispatches": 0,
        "archive_months_fetched": 0,
        "checkpoint_skips": 0,
    }
    run_id = f"crypto-{as_of.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:12]}"

    if not args.apply:
        payload = report_payload(
            plan,
            mode="plan",
            run_id=run_id,
            limits=limits_of(args),
            budget=budget,
            stats=stats,
        )
        if errors:
            payload["audit_errors"] = [
                f"{pair.symbol}/{pair.interval}: {pair.error}" for pair in errors
            ]
        return payload, 2 if errors else 0

    if errors:
        raise RuntimeError(
            "refusing apply because one or more selected pair audits failed: "
            + "; ".join(f"{pair.symbol}/{pair.interval}: {pair.error}" for pair in errors[:10])
        )

    outcomes, applied_stats = await apply_batch(
        plan,
        key_reader=key_reader,
        source=source,
        dispatcher=dispatcher,
        progress_path=args.progress_file,
        evidence_path=args.evidence_file,
        max_shards=args.max_shards,
        pause_seconds=args.pause_seconds,
        timeout_seconds=args.timeout_seconds,
        retry_cooldown_hours=args.retry_cooldown_hours,
        deadline=apply_deadline,
        now=as_of,
        monotonic=monotonic,
        sleep=sleep,
    )
    summary = apply_summary(
        plan,
        outcomes,
        progress_path=args.progress_file,
        evidence_path=args.evidence_file,
        source_requests=int(applied_stats["source_requests"]),
    )
    payload = report_payload(
        plan,
        mode="apply",
        run_id=run_id,
        limits=limits_of(args),
        budget=budget,
        stats=applied_stats,
        outcomes=outcomes,
        summary=summary,
    )
    return payload, 1 if int(summary["plan_open_remaining_shards"]) else 0


def main(
    argv: Sequence[str] | None = None,
    *,
    key_reader: KeyReader | None = None,
    source: SourceProbe | None = None,
    dispatcher: Dispatcher | None = None,
) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    try:
        if not args.manifest.is_file():
            raise FileNotFoundError(f"crypto inception manifest is missing: {args.manifest}")
        probe = source if source is not None else BinanceArchiveSource()
        runner = dispatcher if dispatcher is not None else ManagedScriptDispatcher()
        with _open_key_reader(key_reader) as reader:
            report, exit_code = asyncio.run(
                run(args, key_reader=reader, source=probe, dispatcher=runner)
            )
    except (ValueError, FileNotFoundError, RuntimeError, json.JSONDecodeError) as exc:
        LOGGER.error("crypto recovery stopped: %s", exc)
        return 2
    text = serialize_report(report, args.output)
    if args.output is None:
        print(text)
    summary = report.get("apply_summary") or {}
    if summary:
        LOGGER.info(
            "crypto recovery planned=%s closed=%s source_absent=%s source_invalid=%s "
            "remaining=%s vendor_calls=%s",
            summary.get("planned_shards"),
            summary.get("closed"),
            summary.get("source_absent"),
            summary.get("source_invalid"),
            summary.get("plan_open_remaining_shards"),
            summary.get("source_requests_made"),
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
