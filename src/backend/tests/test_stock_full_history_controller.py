"""Contract and safety tests for ``scripts/stock_full_history_controller.py``.

Everything here runs against in-memory fakes and a temporary owned directory.
No live warehouse (``akshare_data``) connection is opened and no vendor request
is made.

Each non-negotiable guard has a counterfactual test that fails if the guard were
removed:

* read-only by default        -> ``test_overview_makes_no_source_or_write_calls``
* ``--max-codes`` bound       -> ``test_apply_is_bounded_by_max_codes``
* ``--max-minutes`` bound     -> ``test_apply_is_bounded_by_wall_clock_budget``
* idempotent verified skip    -> ``test_apply_skips_already_verified_instruments``
* resumable after failure     -> ``test_run_is_resumable_after_mid_batch_crash``
* never fabricate a bar       -> ``test_missing_days_are_classified_not_fabricated``
* cooldown enforcement        -> ``test_source_failed_symbol_is_held_in_cooldown``
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts import stock_full_history_controller as controller  # noqa: E402


def _load_worker_module() -> Any:
    """Load the recovery worker read-only when it exists on this branch.

    ``run_full_history_recovery_worker.py`` currently lives on the sibling
    ``fix/afi-recovery-runtime-assets`` branch, so it can be absent here. The
    golden classifier below pins the contract either way; when the worker lands
    on ``dev`` the cross-checks run against the real function.
    """

    path = BACKEND_ROOT / "scripts" / "ops" / "run_full_history_recovery_worker.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_recovery_worker_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec_module, not after.  The worker uses
    # ``from __future__ import annotations``, so its dataclasses resolve ``X | None``
    # string annotations through ``sys.modules`` by module name; without the entry the
    # lookup returns None and collection dies with
    # ``AttributeError: 'NoneType' object has no attribute '__dict__'`` -- which is exactly
    # what CI hit on the merge ref, where this file *does* exist and the branch-only path
    # above was never taken.
    sys.modules["_recovery_worker_under_test"] = module
    spec.loader.exec_module(module)
    return module


worker = _load_worker_module()
WORKER_AVAILABLE = worker is not None

STOCK_SUCCESS_STATUSES = {"verified_match", "scheduled_verified"}
STOCK_RETRYABLE_SOURCE_STATUSES = STOCK_SUCCESS_STATUSES | {"source_failed"}
STOCK_BUDGET_DEFERRED_STATUSES = STOCK_SUCCESS_STATUSES | {"deferred_budget"}
STOCK_KNOWN_STATUSES = STOCK_RETRYABLE_SOURCE_STATUSES | {
    "deferred_budget",
    "deferred_scheduler_budget",
    "verification_failed",
    "backfill_failed",
    "unresolved_difference",
    "source_worker_crashed",
}


def classify_stock_like_worker(returncode: int, report: dict[str, Any]) -> tuple[str, bool]:
    """Golden transcription of the worker's ``_classify_stock`` branch.

    Mirrors ``scripts/ops/run_full_history_recovery_worker.py`` lines 783-841 so
    the exit-code/report contract is proven even when that file is not yet on
    this branch.
    """

    if report.get("mode") != "apply" or not isinstance(report.get("outcomes"), list):
        return "attention_required", True
    statuses = [
        str(row.get("status", "unknown")) for row in report["outcomes"] if isinstance(row, dict)
    ]
    if len(statuses) != len(report["outcomes"]):
        return "attention_required", True
    if set(statuses) - STOCK_KNOWN_STATUSES:
        return "attention_required", True
    status_set = set(statuses)
    if "source_failed" in status_set:
        if returncode == 2 and status_set <= STOCK_RETRYABLE_SOURCE_STATUSES:
            return "source_failed_retryable", False
        return "attention_required", True
    if returncode == 3 and "deferred_budget" in status_set:
        if status_set <= STOCK_BUDGET_DEFERRED_STATUSES:
            return "deferred_budget_retryable", False
        return "attention_required", True
    if status_set & (STOCK_KNOWN_STATUSES - STOCK_RETRYABLE_SOURCE_STATUSES):
        return "attention_required", True
    if returncode != 0:
        return "attention_required", True
    return "completed", False


def assert_worker_contract(returncode: int, report: dict[str, Any]) -> tuple[str, bool]:
    """Check the report against the golden rules, and the real worker if present."""

    expected_status, expected_attention = classify_stock_like_worker(returncode, report)
    if WORKER_AVAILABLE:
        real_status, real_attention, reasons = worker._classify_stock(returncode, report)
        assert (real_status, real_attention) == (expected_status, expected_attention), reasons
        return real_status, real_attention
    return expected_status, expected_attention


UTC = timezone.utc
NOW = datetime(2026, 11, 5, 3, 0, 0, tzinfo=UTC)

# Every outcome key ever observed in the historic iteration203 report shards.
# An outcome must stay inside this vocabulary; new keys are the worker's problem.
HISTORIC_OUTCOME_KEYS = {
    "adapter_precision",
    "adjustment",
    "captured_at_utc",
    "checkpoint_key",
    "claim_key",
    "comparison",
    "comparison_after",
    "comparison_before",
    "cooldown_hours",
    "error",
    "execution_error",
    "execution_id",
    "execution_status",
    "full_history_status",
    "listing_boundary_status",
    "managed_parameters",
    "normalizer_version",
    "period_key",
    "reason",
    "recorded_at_utc",
    "schema_version",
    "scope_end_date",
    "scope_hash",
    "scope_start_date",
    "source",
    "source_first_date",
    "source_row_count",
    "source_snapshot_artifact_id",
    "source_snapshot_normalized_sha256",
    "source_snapshot_ohlc_sha256",
    "source_snapshot_parser_version",
    "source_snapshot_raw_sha256",
    "status",
    "symbol",
    "verification_error",
    "warehouse_verification_scope",
    "write_possible",
}

HISTORIC_REPORT_KEYS = {
    "attempted_count",
    "batch_limit",
    "end_date",
    "listing_boundary_status",
    "mode",
    "outcomes",
    "remaining_unverified_count",
    "report_path",
    "scope_hash",
    "scope_verified",
    "selected_symbol_count",
    "source_refresh_pending",
    "source_refresh_reasons",
    "start_date",
    "time_budget_minutes",
    "universe_source_status",
    "universe_sources",
}


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeWarehouse:
    def __init__(
        self, symbols: list[str], bars: dict[str, list[controller.DailyBar]] | None = None
    ) -> None:
        self.symbols = symbols
        self.bars_by_symbol: dict[str, list[controller.DailyBar]] = {
            symbol: list(rows) for symbol, rows in (bars or {}).items()
        }
        self.universe_calls = 0
        self.bars_calls = 0

    def universe(self) -> tuple[list[str], dict[str, Any], str, list[str]]:
        self.universe_calls += 1
        inventory = {
            "STOCK_INFO_A_CODE_NAME": {
                "table": "STOCK_INFO_A_CODE_NAME",
                "canonical_symbol_count": len(self.symbols),
                "status": "read",
            }
        }
        return sorted(self.symbols), inventory, "current", []

    def bars(self, symbol: str) -> list[controller.DailyBar]:
        self.bars_calls += 1
        return list(self.bars_by_symbol.get(symbol, []))


class FakeSource:
    """Returns prepared rows and advances the injected clock like a real probe."""

    def __init__(
        self,
        rows_by_symbol: dict[str, list[dict[str, Any]]],
        *,
        clock: FakeClock,
        seconds_per_call: float = 15.0,
        failing: tuple[str, ...] = (),
        crash_on: str | None = None,
    ) -> None:
        self.rows_by_symbol = rows_by_symbol
        self.clock = clock
        self.seconds_per_call = seconds_per_call
        self.failing = failing
        self.crash_on = crash_on
        self.calls: list[str] = []

    def fetch(self, symbol: str, *, start_date: str, end_date: str) -> list:
        self.calls.append(symbol)
        self.clock.advance(self.seconds_per_call)
        if self.crash_on == symbol:
            raise KeyboardInterrupt("simulated hard interruption mid-batch")
        if symbol in self.failing:
            raise RuntimeError(f"no kline array in response for {symbol}")
        return list(self.rows_by_symbol.get(symbol, []))


class FakeWriter:
    """A managed execution that upserts exactly the fetched bars.

    Upsert semantics never delete, so a warehouse-only row survives the write --
    which is what the orphan test asserts.
    """

    def __init__(
        self,
        warehouse: FakeWarehouse,
        *,
        failing: tuple[str, ...] = (),
        inert: tuple[str, ...] = (),
    ) -> None:
        self.warehouse = warehouse
        self.failing = failing
        self.inert = inert
        self.calls: list[tuple[str, list[controller.DailyBar]]] = []

    def write(self, symbol: str, *, bars: Any, scope: Any) -> controller.WriteReceipt:
        self.calls.append((symbol, list(bars)))
        if symbol in self.failing:
            return controller.WriteReceipt(
                execution_id="ak_exec_failed",
                status="failed",
                error="managed execution failed",
                write_possible=True,
            )
        if symbol not in self.inert:
            merged = {bar.date_key: bar for bar in self.warehouse.bars_by_symbol.get(symbol, [])}
            for bar in bars:
                merged[bar.date_key] = bar
            self.warehouse.bars_by_symbol[symbol] = [merged[key] for key in sorted(merged)]
        return controller.WriteReceipt(execution_id="ak_exec_fake", status="completed")


def rows(dates: list[str], *, close: Any = 10.0) -> list[dict[str, Any]]:
    return [{"date": date, "open": 9.0, "high": 11.0, "low": 8.0, "close": close} for date in dates]


def bars(dates: list[str], *, close: float | None = 10.0) -> list[controller.DailyBar]:
    return [
        controller.DailyBar(date_key=date, open=9.0, high=11.0, low=8.0, close=close)
        for date in dates
    ]


def make_config(tmp_path: Path, **overrides: Any) -> controller.ControllerConfig:
    values: dict[str, Any] = {
        "apply": True,
        "max_codes": 10,
        "max_minutes": 6.0,
        "source_timeout_seconds": 45.0,
        "retry_cooldown_hours": 24.0,
        "progress_path": tmp_path / "progress.jsonl",
        "report_path": tmp_path / "report.json",
        "start_date": controller.DEFAULT_START_DATE,
        "end_date": "2026-11-05",
    }
    values.update(overrides)
    return controller.ControllerConfig(**values)


def run(tmp_path: Path, warehouse: FakeWarehouse, source: Any, writer: Any, **overrides: Any):
    clock = FakeClock()
    if isinstance(source, FakeSource):
        source.clock = clock
    result = controller.run_controller(
        make_config(tmp_path, **overrides),
        source=source,
        warehouse=warehouse,
        writer=writer,
        clock=clock,
        now=NOW,
    )
    return result, clock


def statuses_of(report: dict[str, Any]) -> list[str]:
    return [str(item["status"]) for item in report["outcomes"]]


def ledger_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def scope_hash(end_date: str) -> str:
    return controller.compute_scope_hash(
        start_date=controller.DEFAULT_START_DATE,
        end_date=end_date,
        source=controller.SOURCE_NAME,
        adjustment=controller.ADJUSTMENT,
        normalizer=controller.NORMALIZER_VERSION,
    )


def seed_ledger(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
        ),
        encoding="utf-8",
    )


def failure_record(
    symbol: str, end_date: str, recorded_at: datetime, **extra: Any
) -> dict[str, Any]:
    record = {
        "schema_version": 1,
        "checkpoint_key": controller.compute_checkpoint_key(
            scope_hash=scope_hash(end_date),
            symbol=symbol,
            source=controller.SOURCE_NAME,
            adjustment=controller.ADJUSTMENT,
        ),
        "symbol": symbol,
        "status": "source_failed",
        "recorded_at_utc": recorded_at.isoformat(),
    }
    record.update(extra)
    return record


# --------------------------------------------------------------------------- #
# Guard 1: read-only by default
# --------------------------------------------------------------------------- #


def test_overview_makes_no_source_or_write_calls(tmp_path: Path) -> None:
    """Counterfactual: without the no-apply guard this probes and writes."""

    warehouse = FakeWarehouse(["000001", "000002"])
    source = FakeSource({s: rows(["2026-11-04"]) for s in ["000001", "000002"]}, clock=FakeClock())
    writer = FakeWriter(warehouse)

    result = controller.run_controller(
        make_config(tmp_path, apply=False),
        source=source,
        warehouse=warehouse,
        writer=writer,
        clock=FakeClock(),
        now=NOW,
    )

    assert result.exit_code == 0
    assert result.report["mode"] == "overview"
    assert result.report["read_only"] is True
    assert source.calls == [], "an overview must never reach the vendor"
    assert writer.calls == []
    assert result.report["outcomes"] == []
    # An overview is not a verification result (recorded ledger behaviour).
    assert result.report["remaining_unverified_count"] is None
    assert result.report["scope_verified"] is False
    # Nothing is checkpointed, so an overview cannot fake a verified state for later runs.
    assert not (tmp_path / "progress.jsonl").exists()


def test_apply_writes_only_under_explicit_apply(tmp_path: Path) -> None:
    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock())
    writer = FakeWriter(warehouse)

    controller.run_controller(
        make_config(tmp_path, apply=False),
        source=source,
        warehouse=warehouse,
        writer=writer,
        clock=FakeClock(),
        now=NOW,
    )
    assert not (tmp_path / "progress.jsonl").exists()
    assert source.calls == []

    run(tmp_path, warehouse, source, writer)
    assert (tmp_path / "progress.jsonl").exists()


# --------------------------------------------------------------------------- #
# Guard 2: --max-codes bound
# --------------------------------------------------------------------------- #


def test_apply_is_bounded_by_max_codes(tmp_path: Path) -> None:
    """Counterfactual: without the cap all 25 universe symbols are probed."""

    symbols = [f"{index:06d}" for index in range(25)]
    warehouse = FakeWarehouse(symbols)
    source = FakeSource({s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock())
    writer = FakeWriter(warehouse)

    result, _ = run(tmp_path, warehouse, source, writer, max_codes=3, max_minutes=60.0)

    assert len(source.calls) == 3, "source traffic must never exceed --max-codes"
    assert len(writer.calls) == 3
    assert result.report["attempted_count"] == 3
    assert result.report["batch_limit"] == 3
    deferred = [item for item in result.report["outcomes"] if item["status"] == "deferred_budget"]
    assert len(deferred) == 22
    assert all(item["reason"] == "insufficient_budget_for_full_source_probe" for item in deferred)
    assert result.exit_code == 3


# --------------------------------------------------------------------------- #
# Guard 3: --max-minutes wall-clock bound
# --------------------------------------------------------------------------- #


def test_apply_is_bounded_by_wall_clock_budget(tmp_path: Path) -> None:
    """Counterfactual: without the clock bound all six selected symbols are probed."""

    symbols = [f"{index:06d}" for index in range(6)]
    # Bars already match the source, so each symbol needs a probe but no write.
    warehouse = FakeWarehouse(symbols, {s: bars(["2026-11-04"]) for s in symbols})
    source = FakeSource({s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock())
    writer = FakeWriter(warehouse)

    # 60s budget; each probe costs 15s; a probe+write pair needs 30s.
    result, clock = run(
        tmp_path,
        warehouse,
        source,
        writer,
        max_codes=10,
        max_minutes=1.0,
        source_timeout_seconds=15.0,
    )

    assert len(source.calls) == 3, "the batch must stop when the clock budget runs out"
    assert clock.value == 45.0
    assert statuses_of(result.report).count("verified_match") == 3
    assert statuses_of(result.report).count("deferred_budget") == 3
    assert result.report["time_budget_minutes"] == 1.0
    assert result.exit_code == 3


def test_budget_reserve_always_holds_room_for_the_write_phase(tmp_path: Path) -> None:
    """A probe is never started when its managed write cannot also fit."""

    symbols = ["000001", "000002"]
    warehouse = FakeWarehouse(symbols)
    source = FakeSource({s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock())
    writer = FakeWriter(warehouse)

    # 15s total, 10s probe + 10s write reserve -> nothing fits, so nothing is probed.
    result, _ = run(
        tmp_path,
        warehouse,
        source,
        writer,
        max_codes=10,
        max_minutes=0.25,
        source_timeout_seconds=10.0,
    )

    assert source.calls == []
    assert statuses_of(result.report) == ["deferred_budget", "deferred_budget"]
    assert writer.calls == []
    assert result.exit_code == 3


def test_write_is_skipped_when_the_remaining_budget_cannot_cover_it(tmp_path: Path) -> None:
    """The probe happened; the write is deferred, and no unfenced write sneaks in."""

    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock(), seconds_per_call=20.0)
    writer = FakeWriter(warehouse)

    # 75s budget: a 30s probe + 30s write reserve fits at the start, but after a
    # 20s probe only 55s remain, so the write must be deferred rather than forced.
    result, _ = run(
        tmp_path, warehouse, source, writer, max_minutes=1.25, source_timeout_seconds=30.0
    )

    outcome = result.report["outcomes"][0]
    assert outcome["status"] == "deferred_scheduler_budget"
    assert outcome["write_possible"] is False
    assert writer.calls == []
    assert warehouse.bars_by_symbol.get("000001", []) == []
    # The probe is real work, so it is counted and checkpointed.
    assert result.report["attempted_count"] == 1
    assert len(ledger_lines(tmp_path / "progress.jsonl")) == 1


def test_missing_writer_refuses_an_unfenced_write(tmp_path: Path) -> None:
    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock())

    result, _ = run(tmp_path, warehouse, source, None)

    outcome = result.report["outcomes"][0]
    assert outcome["status"] == "deferred_scheduler_budget"
    assert outcome["write_possible"] is False
    assert warehouse.bars_by_symbol.get("000001", []) == []


# --------------------------------------------------------------------------- #
# Guard 4: idempotent skip of verified instruments
# --------------------------------------------------------------------------- #


def test_apply_skips_already_verified_instruments(tmp_path: Path) -> None:
    symbols = ["000001", "000002"]
    warehouse = FakeWarehouse(symbols)
    source = FakeSource({s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock())
    writer = FakeWriter(warehouse)

    first, _ = run(tmp_path, warehouse, source, writer)
    assert sorted(statuses_of(first.report)) == ["scheduled_verified", "scheduled_verified"]
    assert first.exit_code == 0
    calls_after_first = list(source.calls)
    assert len(calls_after_first) == 2

    # Counterfactual: without the checkpoint skip this probes both symbols again.
    second, _ = run(tmp_path, warehouse, source, writer)
    assert source.calls == calls_after_first, "verified checkpoints must be skipped on re-run"
    assert second.report["outcomes"] == []
    assert second.report["attempted_count"] == 0
    assert second.report["remaining_unverified_count"] == 0
    assert second.exit_code == 0
    assert len(ledger_lines(tmp_path / "progress.jsonl")) == 2


def test_verified_state_does_not_leak_across_scopes(tmp_path: Path) -> None:
    """Verification is scoped; a past pass cannot certify today's head."""

    symbols = ["000001"]
    warehouse = FakeWarehouse(symbols)
    source = FakeSource({s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock())
    writer = FakeWriter(warehouse)

    run(tmp_path, warehouse, source, writer, end_date="2026-11-05")
    assert len(source.calls) == 1
    run(tmp_path, warehouse, source, writer, end_date="2026-11-05")
    assert len(source.calls) == 1, "the same scope stays idempotent"
    run(tmp_path, warehouse, source, writer, end_date="2026-11-06")
    assert len(source.calls) == 2, "a new scope resumes work instead of inheriting a skip"


# --------------------------------------------------------------------------- #
# Guard 5: resumability after a mid-batch failure
# --------------------------------------------------------------------------- #


def test_run_is_resumable_after_mid_batch_crash(tmp_path: Path) -> None:
    """Counterfactual: without per-symbol durability the crash loses all progress."""

    symbols = [f"{index:06d}" for index in range(5)]
    warehouse = FakeWarehouse(symbols)
    crashing = FakeSource(
        {s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock(), crash_on="000002"
    )
    writer = FakeWriter(warehouse)

    with pytest.raises(KeyboardInterrupt):
        controller.run_controller(
            make_config(tmp_path),
            source=crashing,
            warehouse=warehouse,
            writer=writer,
            clock=crashing.clock,
            now=NOW,
        )

    # Durable up to the crash and no further.
    lines = ledger_lines(tmp_path / "progress.jsonl")
    assert [line["symbol"] for line in lines] == ["000000", "000001"]
    assert all(line["status"] == "scheduled_verified" for line in lines)

    resumed = FakeSource({s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock())
    result, _ = run(tmp_path, warehouse, resumed, writer)

    assert resumed.calls == ["000002", "000003", "000004"], "no cursor reset and no re-probe"
    assert sorted(statuses_of(result.report)) == ["scheduled_verified"] * 3
    assert len(ledger_lines(tmp_path / "progress.jsonl")) == 5


def test_source_failure_is_recorded_and_the_batch_continues(tmp_path: Path) -> None:
    symbols = ["000001", "000002"]
    warehouse = FakeWarehouse(symbols)
    source = FakeSource(
        {s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock(), failing=("000001",)
    )
    writer = FakeWriter(warehouse)

    result, _ = run(tmp_path, warehouse, source, writer)

    assert statuses_of(result.report) == ["source_failed", "scheduled_verified"]
    assert result.exit_code == 2
    failed = next(
        line for line in ledger_lines(tmp_path / "progress.jsonl") if line["symbol"] == "000001"
    )
    assert failed["status"] == "source_failed"
    assert failed["cooldown_hours"] == 24.0
    assert "no kline array" in failed["error"]
    assert writer.calls == [("000002", bars(["2026-11-04"]))]


# --------------------------------------------------------------------------- #
# Guard 6: never fabricate a bar
# --------------------------------------------------------------------------- #


def test_missing_days_are_classified_not_fabricated(tmp_path: Path) -> None:
    """Counterfactual: fabrication would show extra written dates or a filled value."""

    source_dates = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-07"]
    warehouse = FakeWarehouse(["000001"], {"000001": bars(["2026-11-03", "2026-11-04"])})
    source = FakeSource({"000001": rows(source_dates)}, clock=FakeClock())
    writer = FakeWriter(warehouse)

    result, _ = run(tmp_path, warehouse, source, writer)

    outcome = result.report["outcomes"][0]
    before = outcome["comparison_before"]
    assert before["source_only_count"] == 2
    assert before["source_only_by_edge"] == {"head": 1, "internal": 0, "tail": 1, "all": 2}
    assert before["exact_match"] is False

    # Only the rows the source returned were ever handed to the writer.
    written = writer.calls[0][1]
    assert [bar.date_key for bar in written] == source_dates
    assert sorted(bar.date_key for bar in warehouse.bars_by_symbol["000001"]) == sorted(
        source_dates
    )
    assert controller.classify_gaps(before)["fabricated_rows"] == 0
    assert outcome["status"] == "scheduled_verified"


def test_head_internal_and_tail_edges_are_distinguished() -> None:
    source = bars(["2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"])
    warehouse = bars(["2026-01-03", "2026-01-05"])

    comparison = controller.compute_comparison(source, warehouse)

    assert comparison["source_only_by_edge"] == {"head": 1, "internal": 1, "tail": 0, "all": 2}
    assert comparison["source_only_sample"] == ["2026-01-02", "2026-01-04"]
    assert comparison["warehouse_only_count"] == 0


def test_source_native_null_is_preserved_not_zero_filled() -> None:
    """Counterfactual: coercing a blank to 0.0 is caught by this test."""

    for blank in ("", None, float("nan"), "-", "--"):
        normalized = controller.normalize_source_rows(
            [{"date": "2026-01-05", "open": 1.0, "high": 2.0, "low": 0.5, "close": blank}]
        )
        assert normalized.bars[0].close is None, f"{blank!r} must stay a source-native blank"
        assert normalized.bars[0].open == 1.0

    real = controller.normalize_source_rows(
        [{"date": "2026-01-05", "open": 1.0, "high": 2.0, "low": 0.5, "close": 3.0}]
    )
    blank = controller.normalize_source_rows(
        [{"date": "2026-01-05", "open": 1.0, "high": 2.0, "low": 0.5, "close": None}]
    )
    comparison = controller.compute_comparison(blank.bars, real.bars)
    assert comparison["exact_match"] is False
    assert comparison["ohlc_value_change_count"] == 1, "None vs 3.0 is a real difference"
    assert comparison["source_only_by_edge"]["all"] == 0, "no date was invented"


def test_zero_is_a_real_price_and_is_not_treated_as_missing() -> None:
    normalized = controller.normalize_source_rows(
        [{"date": "2026-01-05", "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0}]
    )

    assert normalized.bars[0].close == 0.0
    assert normalized.bars[0].close is not None


def test_warehouse_only_row_survives_and_stays_an_open_difference(tmp_path: Path) -> None:
    """A row the source cannot explain is reported, never deleted or hidden."""

    warehouse = FakeWarehouse(["000001"], {"000001": bars(["2026-01-05", "2026-01-06"])})
    source = FakeSource({"000001": rows(["2026-01-05"])}, clock=FakeClock())
    writer = FakeWriter(warehouse)

    result, _ = run(tmp_path, warehouse, source, writer)

    outcome = result.report["outcomes"][0]
    assert outcome["comparison_before"]["warehouse_only_count"] == 1
    assert outcome["comparison_before"]["warehouse_only_sample"] == ["2026-01-06"]
    assert outcome["status"] == "unresolved_difference"
    assert outcome["full_history_status"] == "unverified"
    assert [bar.date_key for bar in warehouse.bars_by_symbol["000001"]] == [
        "2026-01-05",
        "2026-01-06",
    ]
    assert result.exit_code == 1


def test_unknown_listing_boundary_is_recorded_as_unknown(tmp_path: Path) -> None:
    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": rows(["1991-01-29"])}, clock=FakeClock())

    result, _ = run(tmp_path, warehouse, source, FakeWriter(warehouse))

    assert result.report["listing_boundary_status"] == "unknown"
    assert all(item["listing_boundary_status"] == "unknown" for item in result.report["outcomes"])


def test_bounded_batch_never_claims_global_full_history_complete(tmp_path: Path) -> None:
    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock())

    result, _ = run(tmp_path, warehouse, source, FakeWriter(warehouse))

    # Coverage is only ever asserted for the frozen scope, never globally.
    assert "full_history_complete" not in result.report
    assert result.report["start_date"] == controller.DEFAULT_START_DATE
    assert result.report["end_date"] == "2026-11-05"
    assert result.report["outcomes"][0]["full_history_status"] == (
        "verified_tencent_qfq_date_and_ohlc_sequence_match"
    )


# --------------------------------------------------------------------------- #
# Guard 7: retry cooldown
# --------------------------------------------------------------------------- #


def test_source_failed_symbol_is_held_in_cooldown(tmp_path: Path) -> None:
    """Counterfactual: without the cooldown the failing symbol is probed every run."""

    progress = tmp_path / "progress.jsonl"
    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock())
    writer = FakeWriter(warehouse)

    seed_ledger(progress, [failure_record("000001", "2026-11-05", NOW - timedelta(hours=1))])
    result, _ = run(tmp_path, warehouse, source, writer, retry_cooldown_hours=24.0)
    assert source.calls == [], "a cooled-down failure must not be re-probed"
    assert result.report["outcomes"] == []
    assert result.exit_code == 0

    # Expiry releases it; nothing was reset or cleared.
    seed_ledger(progress, [failure_record("000001", "2026-11-05", NOW - timedelta(hours=25))])
    result, _ = run(tmp_path, warehouse, source, writer, retry_cooldown_hours=24.0)
    assert source.calls == ["000001"]
    assert statuses_of(result.report) == ["scheduled_verified"]


def test_retry_cooldown_hours_flag_is_a_real_bound(tmp_path: Path) -> None:
    progress = tmp_path / "progress.jsonl"
    warehouse = FakeWarehouse(["000001"])
    # No recorded cooldown_hours, so the CLI flag governs.
    seed_ledger(progress, [failure_record("000001", "2026-11-05", NOW - timedelta(hours=3))])

    held = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock())
    run(tmp_path, warehouse, held, FakeWriter(warehouse), retry_cooldown_hours=24.0)
    assert held.calls == []

    released = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock())
    run(tmp_path, warehouse, released, FakeWriter(warehouse), retry_cooldown_hours=2.0)
    assert released.calls == ["000001"]


def test_cooldown_holds_one_symbol_without_stalling_the_others(tmp_path: Path) -> None:
    symbols = ["000001", "000002"]
    warehouse = FakeWarehouse(symbols)
    seed_ledger(tmp_path / "progress.jsonl", [failure_record("000001", "2026-11-05", NOW)])

    source = FakeSource({s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock())
    result, _ = run(tmp_path, warehouse, source, FakeWriter(warehouse), max_codes=5)

    assert source.calls == ["000002"], "the cooled-down symbol must not starve the batch"
    assert statuses_of(result.report) == ["scheduled_verified"]


def test_undated_failure_keeps_cooling_down() -> None:
    record = controller.LedgerRecord(
        checkpoint_key="k", symbol="000001", status="source_failed", recorded_at_utc=""
    )

    assert controller.is_cooling_down(record, now=NOW, default_hours=24.0) is True


# --------------------------------------------------------------------------- #
# Guard 8: report shape and exit codes the worker expects
# --------------------------------------------------------------------------- #


def test_cli_accepts_the_exact_worker_command(tmp_path: Path) -> None:
    argv = [
        "--apply",
        "--max-codes",
        "10",
        "--max-minutes",
        "6.0",
        "--source-timeout-seconds",
        "45",
        "--retry-cooldown-hours",
        "24.0",
        "--progress",
        str(tmp_path / "progress.jsonl"),
        "--report",
        str(tmp_path / "report.json"),
    ]

    _, config = controller.parse_args(argv)

    assert config.apply is True
    assert (config.max_codes, config.max_minutes) == (10, 6.0)
    assert (config.source_timeout_seconds, config.retry_cooldown_hours) == (45.0, 24.0)
    assert config.progress_path == tmp_path / "progress.jsonl"
    assert config.report_path == tmp_path / "report.json"


def test_apply_report_top_level_matches_the_historic_shard_shape(tmp_path: Path) -> None:
    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock())

    result, _ = run(tmp_path, warehouse, source, FakeWriter(warehouse))

    assert set(result.report) == HISTORIC_REPORT_KEYS, "no invented top-level keys"
    assert result.report["mode"] == "apply", "the worker requires mode == 'apply'"
    assert isinstance(result.report["outcomes"], list)
    assert result.report["listing_boundary_status"] == "unknown"
    assert result.report["universe_source_status"] == "current"
    assert result.report["source_refresh_reasons"] == []


def test_outcomes_stay_inside_the_historic_key_vocabulary(tmp_path: Path) -> None:
    symbols = ["000001", "000002", "000003"]
    warehouse = FakeWarehouse(symbols)
    source = FakeSource(
        {s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock(), failing=("000002",)
    )

    result, _ = run(tmp_path, warehouse, source, FakeWriter(warehouse), max_codes=2)

    for outcome in result.report["outcomes"]:
        assert set(outcome) <= HISTORIC_OUTCOME_KEYS, sorted(set(outcome) - HISTORIC_OUTCOME_KEYS)
        assert outcome["schema_version"] == 3
        assert outcome["source"] == "tencent"
        assert outcome["adjustment"] == "qfq"
        assert outcome["normalizer_version"] == "stock-history-normalizer-v2"
    verified = result.report["outcomes"][0]
    assert verified["source_snapshot_normalized_sha256"] != verified["source_snapshot_ohlc_sha256"]
    assert verified["period_key"].startswith(f"stock-full-history:v1:{verified['scope_hash']}:")


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["verified_match", "scheduled_verified"], 0),
        ([], 0),
        (["source_failed", "verified_match"], 2),
        (["deferred_budget", "verified_match"], 3),
        (["verification_failed"], 1),
        (["backfill_failed"], 1),
        (["unresolved_difference"], 1),
        (["deferred_scheduler_budget"], 1),
        (["source_worker_crashed"], 1),
        # A real failure outranks a deferral, matching the worker's precedence.
        (["source_failed", "deferred_budget"], 2),
    ],
)
def test_exit_code_matches_the_worker_contract(statuses: list[str], expected: int) -> None:
    assert controller.resolve_exit_code(statuses) == expected


def test_worker_classifies_a_clean_source_failure_as_retryable(tmp_path: Path) -> None:
    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": []}, clock=FakeClock())

    result, _ = run(tmp_path, warehouse, source, FakeWriter(warehouse))

    assert result.exit_code == 2
    status, attention = assert_worker_contract(result.exit_code, result.report)
    assert status == "source_failed_retryable"
    assert attention is False


def test_worker_classifies_a_clean_budget_deferral_as_retryable(tmp_path: Path) -> None:
    symbols = ["000001", "000002", "000003"]
    warehouse = FakeWarehouse(symbols, {s: bars(["2026-11-04"]) for s in symbols})
    source = FakeSource({s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock())

    result, _ = run(tmp_path, warehouse, source, FakeWriter(warehouse), max_codes=1)

    assert result.exit_code == 3
    status, attention = assert_worker_contract(result.exit_code, result.report)
    assert status == "deferred_budget_retryable"
    assert attention is False


def test_worker_classifies_a_clean_verified_batch_as_completed(tmp_path: Path) -> None:
    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock())

    result, _ = run(tmp_path, warehouse, source, FakeWriter(warehouse))

    assert result.exit_code == 0
    status, attention = assert_worker_contract(result.exit_code, result.report)
    assert status == "completed"
    assert attention is False


def test_controller_never_emits_an_unclassifiable_status(tmp_path: Path) -> None:
    """The worker has no branch for an unknown status; producing one is a contract break."""

    symbols = ["000001", "000002", "000003", "000004"]
    warehouse = FakeWarehouse(symbols)
    source = FakeSource(
        {s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock(), failing=("000003",)
    )
    writer = FakeWriter(warehouse, failing=("000004",))

    result, _ = run(tmp_path, warehouse, source, writer, max_codes=4)

    observed = set(statuses_of(result.report))
    assert observed <= STOCK_KNOWN_STATUSES, sorted(observed - STOCK_KNOWN_STATUSES)
    assert result.exit_code == 2


def test_failed_write_never_reports_a_verified_symbol(tmp_path: Path) -> None:
    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock())
    writer = FakeWriter(warehouse, failing=("000001",))

    result, _ = run(tmp_path, warehouse, source, writer)

    outcome = result.report["outcomes"][0]
    assert outcome["status"] == "backfill_failed"
    assert outcome["full_history_status"] == "unverified"
    assert result.exit_code == 1
    status, attention = assert_worker_contract(result.exit_code, result.report)
    assert status == "attention_required"
    assert attention is True


def test_unverified_post_write_state_is_not_called_success(tmp_path: Path) -> None:
    """Counterfactual: trusting the write receipt alone would report a verification."""

    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock())
    writer = FakeWriter(warehouse, inert=("000001",))

    result, _ = run(tmp_path, warehouse, source, writer)

    outcome = result.report["outcomes"][0]
    assert outcome["status"] == "verification_failed"
    assert outcome["comparison_after"]["exact_match"] is False


def test_report_and_ledger_are_persisted_on_disk(tmp_path: Path) -> None:
    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock())

    result, _ = run(tmp_path, warehouse, source, FakeWriter(warehouse))

    on_disk = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert on_disk["mode"] == "apply"
    assert on_disk["outcomes"] == result.report["outcomes"]
    lines = ledger_lines(tmp_path / "progress.jsonl")
    assert len(lines) == 1
    assert lines[0]["status"] == "scheduled_verified"
    assert lines[0]["checkpoint_key"] == result.report["outcomes"][0]["checkpoint_key"]
    assert lines[0]["scope_hash"] == result.report["scope_hash"]


def test_progress_and_report_parent_directories_are_created(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    warehouse = FakeWarehouse(["000001"])
    source = FakeSource({"000001": rows(["2026-11-04"])}, clock=FakeClock())

    result, _ = run(
        tmp_path,
        warehouse,
        source,
        FakeWriter(warehouse),
        progress_path=nested / "progress.jsonl",
        report_path=nested / "report.json",
    )

    assert (nested / "report.json").is_file()
    assert (nested / "progress.jsonl").is_file()
    assert result.exit_code == 0


def test_ledger_loads_last_line_wins_and_counts_malformed(tmp_path: Path) -> None:
    progress = tmp_path / "progress.jsonl"
    key = "c" * 64
    progress.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "checkpoint_key": key,
                        "symbol": "000001",
                        "status": "source_failed",
                        "recorded_at_utc": "2026-11-05T00:00:00+00:00",
                    }
                ),
                "not json at all",
                json.dumps(
                    {
                        "checkpoint_key": key,
                        "symbol": "000001",
                        "status": "verified_match",
                        "recorded_at_utc": "2026-11-05T01:00:00+00:00",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records, malformed = controller.load_ledger(progress)

    assert malformed == 1
    assert records[key].status == "verified_match"
    assert controller.is_verified(records[key]) is True


def test_deferred_budget_is_not_written_to_the_ledger(tmp_path: Path) -> None:
    """Per-run deferral evidence must not inflate the durable checkpoint file."""

    symbols = [f"{index:06d}" for index in range(20)]
    warehouse = FakeWarehouse(symbols)
    source = FakeSource({s: rows(["2026-11-04"]) for s in symbols}, clock=FakeClock())

    run(tmp_path, warehouse, source, FakeWriter(warehouse), max_codes=2, max_minutes=60.0)

    lines = ledger_lines(tmp_path / "progress.jsonl")
    assert [line["symbol"] for line in lines] == ["000000", "000001"]
    assert all(line["status"] == "scheduled_verified" for line in lines)


def test_argparse_rejects_a_non_positive_batch_bound(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        controller.parse_args(["--max-codes", "0", "--report", str(tmp_path / "r.json")])
    with pytest.raises(SystemExit):
        controller.parse_args(["--max-minutes", "0", "--report", str(tmp_path / "r.json")])
    with pytest.raises(SystemExit):
        controller.parse_args(
            ["--source-timeout-seconds", "-1", "--report", str(tmp_path / "r.json")]
        )


def test_real_warehouse_adapter_reads_a_pandas_frame_without_truthiness_error() -> None:
    """Exercise the real adapter, not the protocol fake.

    ``universe()`` used ``list(getattr(frame, "columns", []) or [])``; pandas
    returns an ``Index`` there and ``Index or []`` raises
    ``ValueError: The truth value of a Index is ambiguous``. The protocol fake
    never runs this code, which is why it shipped.
    """

    import pandas as pd

    class FakeDb:
        def table_exists(self, table: str) -> bool:
            return True

        def get_data_by_columns(self, table: str, columns: list[str]) -> Any:
            return pd.DataFrame({columns[0]: ["000001", "600000"], "extra": ["a", "b"]})

        def get_latest_date(self, table: str, column: str) -> str:
            return "2026-11-08"

    adapter = object.__new__(controller.WarehouseDailyAdapter)
    adapter._db = FakeDb()

    symbols, inventory, status, reasons = adapter.universe()

    assert symbols == ["000001", "600000"]
    assert status == "current"
    assert reasons == []
    assert inventory["STOCK_INFO_A_CODE_NAME"]["source_row_count"] == 2


def test_warehouse_bars_are_scoped_to_the_written_source_and_adjustment() -> None:
    """Read one observation series, not every source sharing a date.

    ``STOCK_ZH_A_HIST`` holds the legacy pipeline's rows (``legacy_unknown`` /
    ``unknown``) beside this controller's ``tencent`` / ``qfq`` rows. Selecting
    by symbol alone therefore returned two rows per business date, which the
    post-write comparison reported as duplicate date keys and turned every
    successful write into ``post_write_sequence_mismatch``.
    """

    captured: dict[str, Any] = {}

    class FakeDb:
        def query_data(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
            captured["sql"] = sql
            captured["params"] = params
            return [("2026-11-09", 11.78, 11.89, 11.91, 11.76)]

    adapter = object.__new__(controller.WarehouseDailyAdapter)
    adapter._db = FakeDb()

    bars = adapter.bars("000001")

    assert captured["params"] == ("000001", controller.SOURCE_NAME, controller.ADJUSTMENT)
    assert "source = %s" in captured["sql"]
    assert "adjustment = %s" in captured["sql"]
    assert [(bar.date_key, bar.close) for bar in bars] == [("2026-11-09", 11.89)]
