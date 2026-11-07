"""Contract tests for the bounded Binance crypto full-history recovery controller.

Everything runs against fixtures and owned temporary storage: no live warehouse,
no live exchange, no ``--apply`` against production data.  Each guard is covered
by a counterfactual -- a fixture that would pass if the guard were removed.
"""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from scripts import crypto_full_history_recovery as ctrl

AS_OF = datetime(2020, 2, 5, 0, 0, 0, tzinfo=UTC)
FIRST_OPEN = int(datetime(2019, 11, 1, 0, tzinfo=UTC).timestamp() * 1000)
STEP = 3_600_000
TABLE = "CRYPTO_HOURLY_MARKET"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
LAST_CLOSED = ctrl.latest_closed_open_ms("1h", AS_OF)


def hour(stamp: str) -> int:
    """The source's own UTC business instant for one bar open."""
    moment = datetime.strptime(stamp, "%Y-%m-%dT%H").replace(tzinfo=UTC)
    return int(moment.timestamp() * 1000)


#: The gaps the fixtures leave in the warehouse: two contiguous November hours plus
#: one January hour for BTCUSDT, one December hour for ETHUSDT -> three shards.
MISSING: dict[str, tuple[int, ...]] = {
    "BTCUSDT": (hour("2019-11-05T03"), hour("2019-11-05T04"), hour("2020-01-10T05")),
    "ETHUSDT": (hour("2019-12-20T08"),),
}


def full_grid(start: int = FIRST_OPEN, end: int = LAST_CLOSED) -> set[int]:
    return set(range(start, end + STEP, STEP))


@dataclass
class FakeKeyReader:
    """Warehouse stand-in holding only ``OPEN_TIME_MS`` keys; it has no write path."""

    present: dict[str, set[int]]
    reads: list[tuple[str, str, int, int]] = field(default_factory=list)

    def read_open_times(self, *, table: str, symbol: str, start_ms: int, end_ms: int) -> set[int]:
        self.reads.append((table, symbol, start_ms, end_ms))
        stored = self.present.get(symbol, set())
        return {open_ms for open_ms in stored if start_ms <= open_ms <= end_ms}


@dataclass
class FakeSource:
    """Exchange stand-in: canned archive rows per month, with every call recorded."""

    rows: dict[tuple[str, str], list[list[str]]]
    available: bool = True
    calls: list[tuple[str, str]] = field(default_factory=list)

    def fetch_month(self, *, symbol: str, interval: str, month: str) -> ctrl.MonthEvidence:
        self.calls.append((symbol, month))
        return ctrl.build_month_evidence(
            month=month,
            archive_url=f"archive://{symbol}/{interval}/{month}.zip",
            available=self.available,
            rows=self.rows.get((symbol, month), []),
        )


@dataclass
class FakeClock:
    value: float = 0.0
    step: float = 0.0

    def __call__(self) -> float:
        current = self.value
        self.value += self.step
        return current

    def advance(self, seconds: float) -> None:
        self.value += seconds


@dataclass
class FakeSleep:
    pauses: list[float] = field(default_factory=list)
    clock: FakeClock | None = None

    async def __call__(self, seconds: float) -> None:
        self.pauses.append(seconds)
        if self.clock is not None:
            self.clock.advance(seconds)


def valid_row(open_ms: int, *, close: str = "100.5", volume: str = "3.25") -> list[str]:
    """One archive row on the source's own open/close boundaries."""
    return [
        str(open_ms),
        "100.0",
        "101.0",
        "99.0",
        close,
        volume,
        str(open_ms + STEP - 1),
        "400.0",
        "12",
        "1.0",
        "2.0",
        "0",
    ]


@dataclass
class FakeDispatcher:
    """Managed collector stand-in.  It owns the only bar write path in the fixture."""

    key_reader: FakeKeyReader
    outcome: str = "success"
    missing_hours: frozenset[int] = frozenset()
    calls: list[str] = field(default_factory=list)
    timeouts: list[float] = field(default_factory=list)
    clock: FakeClock | None = None
    budget_cost: float = 0.0

    async def dispatch(
        self, *, shard: ctrl.RecoveryShard, timeout_seconds: float
    ) -> ctrl.DispatchReceipt:
        self.calls.append(shard.shard_id)
        self.timeouts.append(timeout_seconds)
        if self.clock is not None:
            self.clock.advance(self.budget_cost)
        if self.outcome == "success":
            # The collector -- never the controller -- writes the bars it fetches.
            self.key_reader.present.setdefault(shard.symbol, set()).update(
                open_ms for open_ms in shard.missing_open_ms if open_ms not in self.missing_hours
            )
            return ctrl.DispatchReceipt(
                execution_id=f"ak_exec_{shard.shard_id[:8]}", completed=True
            )
        if self.outcome == "incomplete":
            return ctrl.DispatchReceipt(
                error="collection script status is failed",
                error_class=ctrl.ERROR_CLASS_DISPATCH_FAILED,
                database_write_possible=True,
            )
        if self.outcome == "timeout":
            return ctrl.DispatchReceipt(
                error="managed dispatch exceeded 120s",
                outcome_certain=False,
                error_class=ctrl.ERROR_CLASS_OUTCOME_UNKNOWN,
                database_write_possible=True,
            )
        if self.outcome == "infrastructure":
            return ctrl.DispatchReceipt(
                error="OperationalError: connection reset",
                error_class=ctrl.ERROR_CLASS_INFRASTRUCTURE_FATAL,
                database_write_possible=True,
            )
        raise AssertionError(f"unknown outcome {self.outcome!r}")


def write_manifest(path: Path) -> Path:
    records = [
        {
            "symbol": symbol,
            "interval": "1h",
            "status": "discovered",
            "first_open_ms": FIRST_OPEN,
            "listing_boundary": "earliest source bar; independent instrument listing date unknown",
        }
        for symbol in SYMBOLS
    ]
    path.write_text(json.dumps({"complete": True, "records": records}), encoding="utf-8")
    return path


def make_reader() -> FakeKeyReader:
    return FakeKeyReader(present={symbol: full_grid() - set(MISSING[symbol]) for symbol in SYMBOLS})


def archive_rows(
    *,
    repairable: bool = True,
    invalid_hours: frozenset[int] = frozenset(),
    repair_hours: frozenset[int] | None = None,
) -> dict[tuple[str, str], list[list[str]]]:
    """Archive contents for every month of the plan.

    ``repairable=True`` means the source really holds the missing hours (so a
    dispatch can close them).  ``repairable=False`` means the closed-month
    archive has no row there at all -- evidenced absence, not a write target.
    """
    rows: dict[tuple[str, str], list[list[str]]] = {}
    for symbol in SYMBOLS:
        missing = set(MISSING[symbol])
        for open_ms in full_grid():
            key = (symbol, ctrl.month_of(open_ms))
            rows.setdefault(key, [])
            if open_ms in missing:
                if open_ms in invalid_hours:
                    rows[key].append(valid_row(open_ms, close=""))  # empty price cell
                elif repair_hours is not None:
                    if open_ms in repair_hours:
                        rows[key].append(valid_row(open_ms))
                elif repairable:
                    rows[key].append(valid_row(open_ms))
                continue  # otherwise: the source has no row for this hour
            rows[key].append(valid_row(open_ms))
    return rows


def fixture_paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "manifest": write_manifest(tmp_path / "manifest.json"),
        "progress": tmp_path / "ledger" / "progress.jsonl",
        "evidence": tmp_path / "ledger" / "evidence.jsonl",
        "output": tmp_path / "report" / "crypto-report.json",
    }


def argv(args: dict[str, Path], *extra: str) -> list[str]:
    base = [
        "--manifest",
        str(args["manifest"]),
        "--intervals",
        "1h",
        "--progress-file",
        str(args["progress"]),
        "--evidence-file",
        str(args["evidence"]),
        "--output",
        str(args["output"]),
        f"--as-of={AS_OF.isoformat()}",
        "--report-exit-reserve-seconds",
        "0",
    ]
    return base + list(extra)


@dataclass
class Harness:
    fixture: dict[str, Path]
    reader: FakeKeyReader
    source: FakeSource
    dispatcher: FakeDispatcher
    sleep: FakeSleep
    clock: FakeClock
    report: dict[str, Any]
    exit_code: int

    @property
    def summary(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self.report["apply_summary"])

    def rows(self) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", self.report.get("apply", []))


async def run_case(
    tmp_path: Path,
    *extra: str,
    dispatch_outcome: str = "success",
    repairable: bool = True,
    archive_available: bool = True,
    invalid_hours: frozenset[int] = frozenset(),
    budget_cost: float = 0.0,
    clock_step: float = 0.0,
    reader: FakeKeyReader | None = None,
    fixture: dict[str, Path] | None = None,
    repair_hours: frozenset[int] | None = None,
    still_absent: frozenset[int] = frozenset(),
) -> Harness:
    resolved = fixture or fixture_paths(tmp_path)
    key_reader = reader or make_reader()
    source = FakeSource(
        rows=archive_rows(
            repairable=repairable, invalid_hours=invalid_hours, repair_hours=repair_hours
        ),
        available=archive_available,
    )
    clock = FakeClock(step=clock_step)
    sleep = FakeSleep(clock=clock)
    dispatcher = FakeDispatcher(
        key_reader,
        outcome=dispatch_outcome,
        missing_hours=still_absent,
        clock=clock,
        budget_cost=budget_cost,
    )
    args = ctrl.parse_args(argv(resolved, *extra))
    report, exit_code = await ctrl.run(
        args,
        key_reader=key_reader,
        source=source,
        dispatcher=dispatcher,
        monotonic=clock,
        sleep=sleep,
    )
    ctrl.serialize_report(report, args.output)
    return Harness(
        fixture=resolved,
        reader=key_reader,
        source=source,
        dispatcher=dispatcher,
        sleep=sleep,
        clock=clock,
        report=report,
        exit_code=exit_code,
    )


def statuses_by_shard(case: Harness) -> dict[str, str]:
    return {row["shard_id"]: row["status"] for row in case.rows()}


# --------------------------------------------------------------------------- #
# The worker's own parse contract, mirrored from ``_classify_crypto``
# --------------------------------------------------------------------------- #

WORKER_TERMINAL = frozenset({"closed", "source_absent", "source_invalid"})
WORKER_NORMAL = WORKER_TERMINAL | {
    "unresolved_coverage",
    "deferred_unresolved_cooldown",
    "deferred_failed_cooldown",
    "not_run_batch_budget",
}


def classify_crypto(returncode: int, report: dict[str, Any]) -> tuple[str, bool, list[str]]:
    summary = report.get("apply_summary")
    outcomes = report.get("apply")
    if not isinstance(summary, dict) or not isinstance(outcomes, list):
        return "attention_required", True, ["crypto CLI report does not match the apply contract"]
    statuses = [str(row.get("status", "unknown")) for row in outcomes if isinstance(row, dict)]
    if len(statuses) != len(outcomes):
        return "attention_required", True, ["crypto CLI report contains a malformed outcome"]
    terminal_counts = [summary.get(status, 0) for status in sorted(WORKER_TERMINAL)]
    if any(type(count) is not int or count < 0 for count in terminal_counts):
        return "attention_required", True, ["crypto terminal shard counts are malformed"]
    terminal_count = sum(terminal_counts)
    open_count = sum(status not in WORKER_TERMINAL for status in statuses)
    if summary.get("open") != open_count:
        return "attention_required", True, ["crypto open count disagrees with individual outcomes"]
    plan_open = summary.get("plan_open_remaining_shards", open_count)
    if type(plan_open) is not int or plan_open < 0:
        return "attention_required", True, ["crypto plan-open shard count is malformed"]
    planned_shards = summary.get("planned_shards")
    if planned_shards is not None and (
        type(planned_shards) is not int
        or planned_shards < terminal_count
        or plan_open != planned_shards - terminal_count
    ):
        return "attention_required", True, ["crypto plan-open count disagrees with the plan"]
    if open_count > plan_open:
        return "attention_required", True, ["crypto selected open count exceeds the plan"]
    unexpected = sorted(set(statuses) - WORKER_NORMAL)
    if unexpected:
        return "attention_required", True, [f"crypto outcomes need review: {unexpected}"]
    if returncode != (1 if plan_open else 0):
        return "attention_required", True, ["crypto CLI exit disagrees with its remaining contract"]
    if plan_open:
        return "incomplete_open_shards", False, [f"{open_count} selected shards remain open"]
    return "completed", False, []


# --------------------------------------------------------------------------- #
# Guard: no flags means read-only
# --------------------------------------------------------------------------- #


async def test_no_flags_is_a_read_only_plan(tmp_path: Path) -> None:
    case = await run_case(tmp_path)

    assert case.exit_code == 0
    assert case.report["mode"] == "plan"
    assert case.report["read_only"] is True
    assert "apply" not in case.report and "apply_summary" not in case.report
    # Counterfactual: dropping the apply gate would make vendor calls and checkpoints here.
    assert case.dispatcher.calls == []
    assert case.source.calls == []
    assert case.sleep.pauses == []
    assert not case.fixture["progress"].exists()
    assert not case.fixture["evidence"].exists()
    assert case.report["summary"]["shards"] == 3
    assert all(read[0] == TABLE for read in case.reader.reads)
    # The plan preserves each pair's evidenced start instead of a common default.
    assert {pair["source_first_open_ms"] for pair in case.report["pairs"]} == {FIRST_OPEN}


def test_controller_keeps_no_bar_write_path() -> None:
    """The controller reads the keyset and asks the registered collector to write.

    Counterfactual: adding an ``INSERT``/``UPDATE`` here would give a future change a
    place to store a zero-filled or forward-filled candle, so the guard is textual as
    well as behavioural.
    """
    statements = re.findall(
        r'"(SELECT|INSERT|UPDATE|DELETE)[^"]*"', inspect.getsource(ctrl), re.IGNORECASE
    )
    assert "SELECT" in [item.upper() for item in statements]
    assert not [item for item in statements if item.upper() != "SELECT"]
    assert not hasattr(ctrl.MySQLKeyReader, "store")
    assert not hasattr(ctrl.MySQLKeyReader, "execute")


async def test_controller_reports_zero_warehouse_writes_when_applied(tmp_path: Path) -> None:
    case = await run_case(tmp_path, "--apply", "--max-shards", "5")
    assert case.summary["warehouse_write_calls"] == 0
    assert case.summary["fabricated_bars"] == 0
    assert case.summary["scheduler_started"] is False


# --------------------------------------------------------------------------- #
# Guards: both budgets are real limits on vendor traffic
# --------------------------------------------------------------------------- #


async def test_max_shards_caps_vendor_bound_shards(tmp_path: Path) -> None:
    case = await run_case(tmp_path, "--apply", "--max-shards", "2")

    assert len(case.dispatcher.calls) == 2
    assert len(case.source.calls) == 2
    assert case.summary["planned_shards"] == 3
    assert case.summary["selected"] == 2
    assert case.summary["closed"] == 2
    assert case.exit_code == 1
    # Counterfactual: without the cap, all three shards would be dispatched in one run.
    assert case.summary["plan_open_remaining_shards"] == 1


async def test_max_shards_allows_the_whole_plan_when_it_fits(tmp_path: Path) -> None:
    case = await run_case(tmp_path, "--apply", "--max-shards", "5")
    assert len(case.dispatcher.calls) == 3
    assert len(case.source.calls) == 3
    assert case.exit_code == 0


async def test_time_budget_exhaustion_stops_further_source_calls(tmp_path: Path) -> None:
    case = await run_case(
        tmp_path,
        "--apply",
        "--max-shards",
        "5",
        "--max-minutes",
        "2",
        budget_cost=150.0,
    )

    # Counterfactual: without the minute budget all three vendor shards get probed.
    assert len(case.dispatcher.calls) == 1
    assert len(case.source.calls) == 1
    assert case.summary["closed"] == 1
    assert case.summary["not_run"] == 2
    assert case.summary["open"] == 2
    assert case.exit_code == 1
    deferred = [row for row in case.rows() if row["status"] == "not_run_batch_budget"]
    assert len(deferred) == 2
    for row in deferred:
        assert "no source call was made" in row["error"] or "no further shard" in row["error"]
    assert case.reader.reads  # verification stayed read-only


async def test_pause_seconds_spaces_consecutive_dispatches(tmp_path: Path) -> None:
    case = await run_case(tmp_path, "--apply", "--max-shards", "5", "--pause-seconds", "7")
    # Counterfactual: removing the pause leaves three dispatches back to back.
    assert case.sleep.pauses == [7.0, 7.0]
    assert len(case.dispatcher.calls) == 3


async def test_per_shard_timeout_is_bounded_by_the_run_budget(tmp_path: Path) -> None:
    case = await run_case(
        tmp_path, "--apply", "--max-shards", "5", "--timeout-seconds", "30", "--max-minutes", "2"
    )
    assert all(value <= 30.0 for value in case.dispatcher.timeouts)


# --------------------------------------------------------------------------- #
# Guards: checkpoints make re-runs idempotent
# --------------------------------------------------------------------------- #


async def test_closed_shards_are_not_reopened_or_redispatched(tmp_path: Path) -> None:
    first = await run_case(tmp_path, "--apply", "--max-shards", "5")
    assert first.exit_code == 0
    assert first.summary["closed"] == 3
    assert first.fixture["progress"].exists()

    # Re-run against the same warehouse: the repaired hours are no longer in the plan.
    second = await run_case(
        tmp_path,
        "--apply",
        "--max-shards",
        "5",
        reader=first.reader,
        fixture=first.fixture,
    )
    # Counterfactual: losing the keyset checkpoint would re-dispatch all three shards.
    assert second.dispatcher.calls == []
    assert second.source.calls == []
    assert second.rows() == []
    assert second.summary["planned_shards"] == 0
    assert second.exit_code == 0


async def test_source_absent_shards_close_without_dispatch(tmp_path: Path) -> None:
    case = await run_case(tmp_path, "--apply", "--max-shards", "5", repairable=False)

    assert set(statuses_by_shard(case).values()) == {"source_absent"}
    assert case.summary["source_absent"] == 3
    assert case.summary["closed"] == 0
    # Counterfactual: a zero-fill path would dispatch these hours as if repairable.
    assert case.dispatcher.calls == []
    assert len(case.source.calls) == 3
    assert case.exit_code == 0
    rows = [json.loads(line) for line in case.fixture["evidence"].read_text().splitlines()]
    assert {row["classification"] for row in rows} == {"source_absent"}
    assert {row["archive_url"] for row in rows} == {
        f"archive://{row['symbol']}/1h/{row['month']}.zip" for row in rows
    }


async def test_evidenced_absence_is_never_reprobed_on_the_next_run(tmp_path: Path) -> None:
    first = await run_case(tmp_path, "--apply", "--max-shards", "5", repairable=False)
    second = await run_case(
        tmp_path,
        "--apply",
        "--max-shards",
        "5",
        repairable=False,
        reader=first.reader,
        fixture=first.fixture,
    )
    # Counterfactual: ignoring the ledger would re-download the same archives every run.
    assert second.source.calls == []
    assert second.dispatcher.calls == []
    assert set(statuses_by_shard(second).values()) == {"source_absent"}
    assert second.summary["plan_open_remaining_shards"] == 0
    assert second.exit_code == 0


# --------------------------------------------------------------------------- #
# Guards: NULL preservation and no fabricated candles
# --------------------------------------------------------------------------- #


def test_empty_price_cell_is_the_normalized_null_never_zero() -> None:
    assert ctrl.number_or_none("") is None
    assert ctrl.number_or_none("   ") is None
    assert ctrl.number_or_none(None) is None
    assert ctrl.number_or_none("nan") is None
    assert ctrl.number_or_none("0") == 0.0  # a real source zero stays a zero

    bar = ctrl.parse_source_bar(valid_row(hour("2019-11-05T03"), close=""))
    assert bar is not None
    # Counterfactual: ``float(cell)`` coercion makes this 0.0 and looks like a valid bar.
    assert bar.close_price is None
    assert bar.open_price == 100.0
    assert bar.invalid_reason == "empty_or_unparseable_price_cell:close_price"
    assert bar.is_valid is False


def test_source_observation_time_is_preserved_not_relabelled() -> None:
    open_ms = hour("2019-12-20T08")
    row = valid_row(open_ms)
    row[6] = str(open_ms - 759_479)  # close before open, as the 2020-12 placeholder behaves
    bar = ctrl.parse_source_bar(row)
    assert bar is not None
    assert bar.close_time_ms == open_ms - 759_479
    assert bar.invalid_reason is not None
    assert bar.invalid_reason.startswith("close_time_not_after_open_time")


def test_microsecond_and_second_archive_epochs_stay_on_the_millisecond_grid() -> None:
    assert ctrl.epoch_ms("1573000000000000") == 1_573_000_000_000
    assert ctrl.epoch_ms("1573000000000") == 1_573_000_000_000
    assert ctrl.epoch_ms("1573000000") == 1_573_000_000_000


async def test_invalid_source_row_closes_as_source_invalid_without_dispatch(tmp_path: Path) -> None:
    bad_hour = hour("2019-11-05T03")
    case = await run_case(
        tmp_path,
        "--apply",
        "--max-shards",
        "5",
        repairable=False,
        invalid_hours=frozenset({bad_hour}),
    )
    # Counterfactual: coercing the empty close to zero makes the row look repairable,
    # so the shard would be dispatched and reported closed instead of source_invalid.
    rows = [
        row for row in case.rows() if row["symbol"] == "BTCUSDT" and row["since"] == "2019-11-05"
    ]
    assert len(rows) == 1
    assert rows[0]["status"] == "source_invalid"
    assert rows[0]["source_invalid_bars"] == 1
    assert rows[0]["source_absent_bars"] == 1
    assert rows[0]["shard_id"] not in case.dispatcher.calls
    assert bad_hour not in case.reader.present["BTCUSDT"]  # nothing written for it

    evidence = [json.loads(line) for line in case.fixture["evidence"].read_text().splitlines()]
    invalid = [row for row in evidence if row["classification"] == "archive_invalid_bar"]
    assert len(invalid) == 1
    # The NULL is recorded as a null, not as a price.
    assert invalid[0]["source_close_price"] is None
    assert invalid[0]["invalid_reason"] == "empty_or_unparseable_price_cell:close_price"


async def test_unavailable_archive_stays_open_instead_of_claiming_absence(
    tmp_path: Path,
) -> None:
    before = make_reader()
    case = await run_case(
        tmp_path,
        "--apply",
        "--max-shards",
        "5",
        archive_available=False,
        dispatch_outcome="incomplete",
    )
    # A month the archive cannot answer for is not evidence of absence, and is not filled.
    assert case.exit_code == 1
    assert {row["status"] for row in case.rows()} == {"unresolved_coverage"}
    assert {row["error_class"] for row in case.rows()} == {"dispatch_failed"}
    assert not case.fixture["evidence"].exists()
    for symbol in SYMBOLS:
        assert case.reader.present[symbol] == before.present[symbol]


async def test_mixed_shard_closes_the_repairable_hour_and_keeps_the_absent_one(
    tmp_path: Path,
) -> None:
    """One archive hour is collected; the hour the source never published stays missing."""
    present_hour = hour("2019-11-05T03")
    absent_hour = hour("2019-11-05T04")
    case = await run_case(
        tmp_path,
        "--apply",
        "--max-shards",
        "5",
        repair_hours=frozenset({present_hour}),
        still_absent=frozenset({absent_hour}),
    )
    # Counterfactual: a forward/zero fill would report this shard closed and put a bar
    # for the absent hour into the warehouse; the run would then exit 0 with no evidence.
    mixed = [row for row in case.rows() if row["since"] == "2019-11-05"]
    assert len(mixed) == 1
    assert mixed[0]["status"] == "source_absent"
    assert mixed[0]["remaining_missing_bars"] == 1
    assert mixed[0]["source_absent_bars"] == 1
    assert present_hour in case.reader.present["BTCUSDT"]  # the source hour really landed
    assert absent_hour not in case.reader.present["BTCUSDT"]  # the absent one was not invented
    # The other two shards have no source row either, so nothing else is dispatched.
    assert len(case.dispatcher.calls) == 1
    assert case.exit_code == 0
    assert case.summary["source_absent"] == 3
    assert case.summary["closed"] == 0
    assert case.summary["plan_open_remaining_shards"] == 0


# --------------------------------------------------------------------------- #
# Guards: resume after a mid-batch failure, and the retry cooldown
# --------------------------------------------------------------------------- #


async def test_mid_batch_failure_resumes_after_the_cooldown_expires(tmp_path: Path) -> None:
    first = await run_case(tmp_path, "--apply", "--max-shards", "1", dispatch_outcome="incomplete")
    assert first.exit_code == 1
    assert first.summary["unresolved"] == 1
    cooled = first.rows()[0]
    assert cooled["status"] == "unresolved_coverage"
    assert cooled["error_class"] == "dispatch_failed"
    assert cooled["remaining_missing_bars"] == 2

    # Next run inside the window: that shard defers and the vendor is not called for it.
    second = await run_case(tmp_path, "--apply", "--max-shards", "1", reader=first.reader)
    # Counterfactual: dropping the cooldown would re-dispatch the failed shard every tick.
    assert cooled["shard_id"] not in second.dispatcher.calls
    assert len(second.dispatcher.calls) == 1  # only the *next* shard is vendor-bound
    assert second.exit_code == 1
    assert second.summary["deferred_failed"] == 1
    deferred = [row for row in second.rows() if row["status"] == "deferred_failed_cooldown"]
    assert len(deferred) == 1
    assert "24 hour retry cooldown" in deferred[0]["error"]

    # A deferred row never overwrites the attempt that earned the cooldown.
    third = await run_case(tmp_path, "--apply", "--max-shards", "1", reader=first.reader)
    assert cooled["shard_id"] not in third.dispatcher.calls
    assert third.summary["deferred_failed"] == 1

    # Once the window elapses the shard is dispatched again and the plan closes.
    lines = [json.loads(line) for line in first.fixture["progress"].read_text().splitlines()]
    lines[0]["recorded_at_utc"] = (AS_OF - timedelta(hours=25)).isoformat()
    first.fixture["progress"].write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    fourth = await run_case(
        tmp_path, "--apply", "--max-shards", "5", reader=first.reader, fixture=first.fixture
    )
    assert fourth.dispatcher.calls == [cooled["shard_id"]]
    assert fourth.exit_code == 0
    assert fourth.summary["closed"] == 1


async def test_ledger_is_append_only_and_the_open_attempt_survives(tmp_path: Path) -> None:
    first = await run_case(tmp_path, "--apply", "--max-shards", "1", dispatch_outcome="incomplete")
    first_bytes = first.fixture["progress"].read_bytes()
    assert len(first_bytes.decode().strip().splitlines()) == 1

    second = await run_case(
        tmp_path, "--apply", "--max-shards", "5", reader=first.reader, fixture=first.fixture
    )
    after_bytes = first.fixture["progress"].read_bytes()
    # Counterfactual: truncating or rewriting the checkpoint would drop the open attempt
    # that carries the cooldown, and the failed shard would be retried immediately.
    assert after_bytes.startswith(first_bytes)
    lines = [json.loads(line) for line in after_bytes.decode().strip().splitlines()]
    assert lines[0]["status"] == "unresolved_coverage"
    assert (lines[0]["symbol"], lines[0]["since"]) == ("BTCUSDT", "2019-11-05")
    # A deferral is this run's decision, not the period's state, so it is reported
    # in the run but never written over the attempt being cooled.
    assert all(row["status"] != "deferred_failed_cooldown" for row in lines)
    assert first.reader.present["BTCUSDT"] is second.reader.present["BTCUSDT"]


async def test_legacy_failure_status_keeps_its_cooldown_guard(tmp_path: Path) -> None:
    resolved = fixture_paths(tmp_path)
    resolved["progress"].parent.mkdir(parents=True, exist_ok=True)
    legacy = {
        "symbol": "BTCUSDT",
        "interval": "1h",
        "since": "2019-11-05",
        "status": "managed_outcome_unknown",
        "recorded_at_utc": (AS_OF - timedelta(hours=1)).isoformat(),
    }
    resolved["progress"].write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    case = await run_case(tmp_path, "--apply", "--max-shards", "5", fixture=resolved)
    # A status outside today's vocabulary still counts as an open attempt.
    deferred = [row for row in case.rows() if row["status"].startswith("deferred")]
    assert [(row["symbol"], row["since"]) for row in deferred] == [("BTCUSDT", "2019-11-05")]
    assert deferred[0]["status"] == "deferred_unresolved_cooldown"
    assert len(case.dispatcher.calls) == 2  # the cooled shard was not dispatched


async def test_uncertain_write_stops_the_batch_without_a_source_failure(tmp_path: Path) -> None:
    case = await run_case(tmp_path, "--apply", "--max-shards", "5", dispatch_outcome="timeout")
    rows = case.rows()
    assert case.exit_code == 1
    assert len(case.dispatcher.calls) == 1
    assert rows[0]["status"] == "unresolved_coverage"
    assert rows[0]["error_class"] == "outcome_unknown"
    assert rows[0]["database_write_possible"] is True
    assert "no source failure was recorded" in rows[0]["error"]
    assert {row["status"] for row in rows[1:]} == {"not_run_batch_budget"}
    assert all(row["status"] in ctrl.ALLOWED_STATUSES for row in rows)


async def test_infrastructure_failure_defers_the_rest_of_the_batch(tmp_path: Path) -> None:
    case = await run_case(
        tmp_path, "--apply", "--max-shards", "5", dispatch_outcome="infrastructure"
    )
    assert len(case.dispatcher.calls) == 1
    assert case.rows()[0]["error_class"] == "infrastructure_fatal"
    assert {row["status"] for row in case.rows()[1:]} == {"not_run_batch_budget"}


# --------------------------------------------------------------------------- #
# Guard: the report the recovery worker parses
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("dispatch_outcome", "extra"),
    [
        ("success", ["--max-shards", "5"]),
        ("success", ["--max-shards", "1"]),
        ("success", ["--max-shards", "5", "--retry-cooldown-hours", "0"]),
        ("incomplete", ["--max-shards", "5"]),
        ("timeout", ["--max-shards", "5"]),
        ("infrastructure", ["--max-shards", "5"]),
    ],
)
async def test_apply_report_satisfies_the_worker_classifier(
    tmp_path: Path, dispatch_outcome: str, extra: list[str]
) -> None:
    case = await run_case(tmp_path, "--apply", *extra, dispatch_outcome=dispatch_outcome)
    status, needs_attention, reasons = classify_crypto(case.exit_code, case.report)
    assert not needs_attention, (status, reasons, case.summary)
    assert status in {"completed", "incomplete_open_shards"}
    assert set(case.report) >= {
        "apply",
        "apply_summary",
        "plan_sha256",
        "mode",
        "as_of_utc",
        "shards",
        "pairs",
        "limits",
        "budget",
    }
    assert case.report["mode"] == "apply"
    assert case.report["read_only"] is False
    assert all(row["status"] in ctrl.ALLOWED_STATUSES for row in case.rows())
    assert {row["shard_id"] for row in case.rows()} <= {
        shard["shard_id"] for shard in case.report["shards"]
    }


async def test_summary_rejects_a_status_the_worker_does_not_know() -> None:
    plan = ctrl.PlanReport(
        as_of_utc=AS_OF.isoformat(),
        pairs=[],
        shards=[
            ctrl.RecoveryShard(
                shard_id="a" * 20,
                symbol="BTCUSDT",
                interval="1h",
                table=TABLE,
                script_id="crypto_hourly_market",
                since="2019-11-05",
                until="2019-11-05",
                expected_missing_bars=2,
                first_missing_ms=hour("2019-11-05T03"),
                last_missing_ms=hour("2019-11-05T04"),
                verify_start_ms=hour("2019-11-05T03"),
                verify_end_ms=hour("2019-11-05T04"),
                gap_edges=("internal",),
                source_first_open_ms=FIRST_OPEN,
                listing_boundary="unknown",
                period_key="BTCUSDT|1h|2019-11",
                missing_open_ms=(hour("2019-11-05T03"), hour("2019-11-05T04")),
            )
        ],
        plan_sha256="0" * 64,
    )
    # Counterfactual: emitting a legacy ``failed`` status would silently pass this run
    # and light up the worker's review path instead.
    with pytest.raises(ValueError, match="outside the worker contract"):
        ctrl.apply_summary(
            plan,
            [
                ctrl.ShardOutcome(
                    shard_id="a" * 20,
                    symbol="BTCUSDT",
                    interval="1h",
                    since="2019-11-05",
                    until="2019-11-05",
                    status="failed",
                    expected_missing_bars=2,
                )
            ],
            progress_path=Path("progress.jsonl"),
            evidence_path=Path("evidence.jsonl"),
            source_requests=1,
        )


# --------------------------------------------------------------------------- #
# Plan maths: business dates, bounds and gap edges
# --------------------------------------------------------------------------- #


def test_shards_keep_the_source_business_hours_and_verified_bounds(tmp_path: Path) -> None:
    resolved = fixture_paths(tmp_path)
    specs = ctrl.load_manifest(resolved["manifest"], intervals={"1h"})
    plan = ctrl.audit_plan(specs, key_reader=make_reader(), as_of=AS_OF)

    assert len(plan.shards) == 3
    by_symbol_month = {(shard.symbol, shard.since[:7]): shard for shard in plan.shards}
    assert by_symbol_month[("BTCUSDT", "2019-11")].missing_open_ms == (
        hour("2019-11-05T03"),
        hour("2019-11-05T04"),
    )
    assert by_symbol_month[("BTCUSDT", "2019-11")].gap_edges == ("internal",)
    assert by_symbol_month[("BTCUSDT", "2019-11")].expected_missing_bars == 2
    assert by_symbol_month[("BTCUSDT", "2020-01")].since == "2020-01-10"
    assert by_symbol_month[("ETHUSDT", "2019-12")].until == "2019-12-20"
    for shard in plan.shards:
        assert shard.verify_end_ms <= LAST_CLOSED  # never verifies an open bar
        assert shard.verify_start_ms >= shard.source_first_open_ms
        assert shard.verify_start_ms % STEP == 0 and shard.verify_end_ms % STEP == 0
    assert (
        plan.plan_sha256
        == ctrl.audit_plan(specs, key_reader=make_reader(), as_of=AS_OF).plan_sha256
    )


def test_missing_ranges_and_expected_grids_refuse_misaligned_bounds(tmp_path: Path) -> None:
    resolved = fixture_paths(tmp_path)
    specs = ctrl.load_manifest(resolved["manifest"], intervals={"1h"})
    assert specs[0].first_open_ms == FIRST_OPEN
    with pytest.raises(ValueError, match="not aligned"):
        ctrl.expected_open_times(FIRST_OPEN, FIRST_OPEN + STEP + 1, STEP)
    with pytest.raises(ValueError, match="not aligned"):
        ctrl.find_missing_ranges(
            first_open_ms=FIRST_OPEN,
            last_closed_open_ms=FIRST_OPEN + 1,
            present_open_times=set(),
            step_ms=STEP,
        )


class BrokenReader:
    """Warehouse stand-in whose keyset read fails, as a dropped connection would."""

    def read_open_times(self, *, table: str, symbol: str, start_ms: int, end_ms: int) -> set[int]:
        raise ConnectionError("warehouse unavailable")


async def test_apply_refuses_when_a_pair_audit_failed(tmp_path: Path) -> None:
    resolved = fixture_paths(tmp_path)
    dispatcher = FakeDispatcher(make_reader())
    args = ctrl.parse_args(argv(resolved, "--apply"))
    # An audit that could not read the keyset refuses to dispatch at all. Reporting a
    # clean apply result would let the worker close a shard it never verified.
    with pytest.raises(RuntimeError, match="refusing apply"):
        await ctrl.run(
            args,
            key_reader=BrokenReader(),
            source=FakeSource(rows={}),
            dispatcher=dispatcher,
            monotonic=FakeClock(),
            sleep=FakeSleep(),
        )
    assert dispatcher.calls == []
    assert not resolved["progress"].exists()
    assert not resolved["evidence"].exists()

    plan_report, plan_code = await ctrl.run(
        ctrl.parse_args(argv(resolved)),
        key_reader=BrokenReader(),
        source=FakeSource(rows={}),
        dispatcher=dispatcher,
        monotonic=FakeClock(),
        sleep=FakeSleep(),
    )
    assert plan_code == 2
    assert "warehouse unavailable" in plan_report["pairs"][0]["error"]
    assert "apply" not in plan_report
    # The refusal must not leave a checkpoint behind for the next run to trust.
    assert not resolved["progress"].exists()


def test_cli_exit_codes(tmp_path: Path) -> None:
    resolved = fixture_paths(tmp_path)
    reader = make_reader()
    dispatcher = FakeDispatcher(reader)
    argv_line = argv(resolved, "--apply", "--max-shards", "5")

    assert (
        ctrl.main(
            argv_line,
            key_reader=reader,
            source=FakeSource(rows=archive_rows()),
            dispatcher=dispatcher,
        )
        == 0
    )
    assert resolved["output"].is_file()
    written = json.loads(resolved["output"].read_text(encoding="utf-8"))
    assert written["apply_summary"]["closed"] == 3
    assert len(dispatcher.calls) == 3

    # A shard left open keeps the documented exit code 1 for the worker.
    open_reader = make_reader()
    assert (
        ctrl.main(
            argv(resolved, "--apply", "--max-shards", "5"),
            key_reader=open_reader,
            source=FakeSource(rows=archive_rows(repairable=False), available=False),
            dispatcher=FakeDispatcher(open_reader, outcome="incomplete"),
        )
        == 1
    )

    # A pair audit that cannot read the keyset exits 2 through the CLI boundary.
    audit_failed_reader = make_reader()
    assert (
        ctrl.main(
            argv(resolved, "--apply"),
            key_reader=BrokenReader(),
            source=FakeSource(rows={}),
            dispatcher=FakeDispatcher(audit_failed_reader),
        )
        == 2
    )
    assert audit_failed_reader.reads == []

    # Usage errors stay exit code 2 and never write a checkpoint.
    with pytest.raises(SystemExit):
        ctrl.parse_args(["--apply", "--max-shards", "0"])
    with pytest.raises(SystemExit):
        ctrl.parse_args(["--apply", "--pause-seconds", "0.2"])


async def test_apply_on_an_empty_plan_exits_zero(tmp_path: Path) -> None:
    resolved = fixture_paths(tmp_path)
    complete = FakeKeyReader(present={symbol: full_grid() for symbol in SYMBOLS})
    args = ctrl.parse_args(argv(resolved, "--apply", "--max-shards", "5"))
    report, exit_code = await ctrl.run(
        args,
        key_reader=complete,
        source=FakeSource(rows={}),
        dispatcher=FakeDispatcher(complete),
        monotonic=FakeClock(),
        sleep=FakeSleep(),
    )
    assert exit_code == 0
    assert report["apply"] == []
    assert report["apply_summary"]["plan_open_remaining_shards"] == 0
