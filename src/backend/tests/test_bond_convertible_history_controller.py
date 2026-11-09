"""Tests for ``scripts/bond_convertible_history_controller.py`` - the AC05 convertible-bond leg.

The controller is a runtime asset: the recovery worker shells out to it, so these
tests pin the CLI contract, both vendor-traffic budgets, the content-addressed
snapshot shape the operator already has under ``var/reports/iteration203``,
resumable per-code checkpoints, and the non-negotiable rule that legacy rows
without a usable instrument key are never attributed to a code.

No vendor call and no warehouse write happens here: the source probe, the SQL
reader and the managed script service are injected fakes over owned temp storage.
The one exception is the killable-child timeout, which runs a real local child
process with no network.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import multiprocessing
import sys
import time
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "src" / "backend" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

_spec = importlib.util.spec_from_file_location(
    "bond_convertible_history_controller",
    SCRIPTS_DIR / "bond_convertible_history_controller.py",
)
assert _spec is not None and _spec.loader is not None
controller = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = controller
_spec.loader.exec_module(controller)

BOND = "sh113062"
SOURCE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
ALL_DATES = ["2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09"]
MISSING_DATE = "2020-01-08"
PRESENT_DATES = [day for day in ALL_DATES if day != MISSING_DATE]

# A legacy row that carries no instrument symbol: its real business date sits in
# ``date`` while ``data_date`` is only the legacy load/collection date.  Attributing
# it to a code by date or price is what the invariant forbids.
LEGACY_UNATTRIBUTABLE_ROW = {
    "symbol": None,
    "data_date": "2026-01-01",
    "date": MISSING_DATE,
    "open": "101.5",
    "high": "102.5",
    "low": "100.5",
    "close": "101.5",
    "volume": "1001",
    "source": None,
}


def falsely_attributed_legacy_row() -> dict[str, Any]:
    """What a price/sequence matcher would hand back for the row above."""

    attributed = dict(LEGACY_UNATTRIBUTABLE_ROW)
    attributed["symbol"] = BOND
    attributed["data_date"] = attributed.pop("date")
    return attributed


def source_payload(dates: list[str], *, close: float = 101.5) -> dict[str, Any]:
    return {
        "columns": SOURCE_COLUMNS,
        "rows": [
            {
                "date": day,
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000 + index,
            }
            for index, day in enumerate(dates)
        ],
    }


def warehouse_rows(dates: list[str], *, symbol: str = BOND) -> list[dict[str, Any]]:
    return [
        {
            "symbol": symbol,
            "data_date": row["date"],
            "open": str(row["open"]),
            "high": str(row["high"]),
            "low": str(row["low"]),
            "close": str(row["close"]),
            "volume": str(row["volume"]),
            "source": "sina",
        }
        for row in source_payload(dates)["rows"]
    ]


def universe_for(symbols: list[str]) -> list[dict[str, Any]]:
    rows = [{"symbol": symbol} for symbol in symbols]
    return controller.build_convertible_universe(symbols, rows)[0]


class FakeClock:
    """Monotonic clock that advances a fixed step per call, so budgets are deterministic."""

    def __init__(self, step: float = 0.0, start: float = 1_000.0) -> None:
        self.value = start
        self.step = step

    def monotonic(self) -> float:
        current = self.value
        self.value += self.step
        return current


class SimpleExecution:
    def __init__(self, *, execution_id: str, status: str, error_message: str | None = None) -> None:
        self.execution_id = execution_id
        self.status = status
        self.error_message = error_message


class FakeReader:
    """Read-only warehouse double; records every per-code read it serves."""

    def __init__(self, codes: dict[str, list[dict[str, Any]]]) -> None:
        self.codes = codes
        self.per_code_reads: list[str] = []

    def __enter__(self) -> FakeReader:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read_convertible_snapshot_symbols(self) -> tuple[list[Any], dict[str, Any]]:
        return list(self.codes), {"table": "BOND_ZH_HS_COV_SPOT", "status": "read"}

    def read_convertible_history_overview(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows = [
            {
                "symbol": symbol,
                "row_count": len(bars),
                "date_key_count": len(bars),
                "duplicate_date_rows": 0,
                "first_date": bars[0]["data_date"] if bars else None,
                "last_date": bars[-1]["data_date"] if bars else None,
                "incomplete_ohlc_rows": sum(
                    1
                    for bar in bars
                    if any(bar.get(field) is None for field in ("open", "high", "low", "close"))
                ),
                "row_count_by_source": {"sina": len(bars)},
                "canonical_row_count": len(bars),
                "legacy_unknown_row_count": 0,
                "source_field_available": True,
                "provenance_status": "canonical_only",
            }
            for symbol, bars in sorted(self.codes.items())
        ]
        evidence = {
            "table": controller.CONVERTIBLE_HISTORY_TABLE,
            "status": "read",
            "source_provenance": {
                "source_field_available": True,
                "row_count_by_source": {
                    "sina": sum(len(bars) for bars in self.codes.values()),
                    "legacy_unknown": 1,
                },
                "valid_history_symbols_by_provenance_status": {"canonical_only": len(self.codes)},
                "unrecognized_symbol_row_count_by_source": {"legacy_unknown": 1},
                "canonical_source_semantics": "canonical provenance does not certify completeness",
            },
            "unattributable_rows": {
                "row_count": 1,
                "unique_symbol_value_count": 1,
                "duplicate_row_count": 0,
                "no_symbol_row_count": 1,
                "row_count_by_source": {"legacy_unknown": 1},
                "attribution_policy": (
                    "rows without a recognized instrument symbol are preserved as aggregate evidence only"
                ),
            },
            "coverage_semantics": "inventory only",
        }
        return rows, evidence

    def read_convertible_bars_with_provenance(self, symbol: str) -> list[dict[str, Any]]:
        self.per_code_reads.append(symbol)
        return list(self.codes.get(symbol, []))


class Harness:
    """Wires the controller's adapters to fakes and counts vendor/managed traffic."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        codes: dict[str, list[dict[str, Any]]] | None = None,
        payloads: dict[str, Any] | None = None,
        failing: set[str] | None = None,
    ) -> None:
        self.tmp_path = tmp_path
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.progress_path = tmp_path / "progress.jsonl"
        self.snapshot_dir = tmp_path / "snapshots"
        initial = codes if codes is not None else {BOND: warehouse_rows(PRESENT_DATES)}
        self.reader = FakeReader(initial)
        self.payloads = (
            payloads
            if payloads is not None
            else {symbol: source_payload(ALL_DATES) for symbol in initial}
        )
        self.failing = failing or set()
        self.source_calls: list[tuple[str, int]] = []
        self.managed_calls: list[dict[str, Any]] = []

    def source_fetcher(self, symbol: str, timeout_seconds: int) -> dict[str, Any]:
        self.source_calls.append((symbol, timeout_seconds))
        if symbol in self.failing:
            raise RuntimeError("HTTPError: 404 Client Error: Not Found for Sina hisdata")
        return self.payloads[symbol]

    async def scheduler_run(
        self,
        symbol: str,
        source: str,
        snapshot: Any,
        *,
        timeout_seconds: float,
        source_timeout_seconds: int,
        dispatch_receipt: dict[str, Any],
    ) -> SimpleExecution:
        self.managed_calls.append(
            {
                "symbol": symbol,
                "source": source,
                "timeout_seconds": timeout_seconds,
                "source_timeout_seconds": source_timeout_seconds,
                "dispatch_receipt": dispatch_receipt,
            }
        )
        rows = list(self.reader.codes.get(symbol, []))
        present = {row["data_date"] for row in rows}
        for ledger in snapshot.normalized_ledger:
            if ledger["data_date"] in present:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "data_date": ledger["data_date"],
                    "open": _as_text(ledger["open"]),
                    "high": _as_text(ledger["high"]),
                    "low": _as_text(ledger["low"]),
                    "close": _as_text(ledger["close"]),
                    "volume": _as_text(ledger["volume"]),
                    "source": "sina",
                }
            )
            present.add(ledger["data_date"])
        self.reader.codes[symbol] = sorted(rows, key=lambda row: row["data_date"])
        return SimpleExecution(execution_id=f"exec-{len(self.managed_calls)}", status="completed")

    @staticmethod
    async def source_resolver() -> str:
        return "sina"

    async def run_apply(
        self,
        symbols: list[str] | None = None,
        *,
        max_codes: int = 5,
        budget: int = 240,
        source_timeout: int = 45,
        monotonic: Any = time.monotonic,
        retry_failed: bool = False,
        scheduler_run: Any = None,
    ) -> tuple[dict[str, Any], int]:
        return await controller.run_apply(
            symbols or [],
            universe_for(sorted(self.reader.codes)),
            max_codes=max_codes,
            progress_path=self.progress_path,
            snapshot_dir=self.snapshot_dir,
            time_budget_seconds=budget,
            source_timeout_seconds=source_timeout,
            reader_factory=lambda: self.reader,
            source_fetcher=self.source_fetcher,
            scheduler_run=scheduler_run or self.scheduler_run,
            source_resolver=self.source_resolver,
            retry_failed=retry_failed,
            unattributable_rows=self.reader.read_convertible_history_overview()[1][
                "unattributable_rows"
            ],
            monotonic=monotonic,
        )

    def main(self, argv: list[str]) -> int:
        return controller.main(
            argv,
            reader_factory=lambda: self.reader,
            source_fetcher=self.source_fetcher,
            scheduler_run=self.scheduler_run,
            source_resolver=self.source_resolver,
        )

    def report_file(self, argv: list[str]) -> dict[str, Any]:
        path = self.tmp_path / "report.json"
        argv = [*argv, "--report", str(path), "--progress-file", str(self.progress_path)]
        exit_code = self.main(argv)
        report = json.loads(path.read_text(encoding="utf-8"))
        report["_exit_code"] = exit_code
        return report

    def snapshot_files(self) -> list[str]:
        return sorted(item.name for item in self.snapshot_dir.glob("*.json"))


def _as_text(value: Any) -> str | None:
    return None if value is None else str(value)


# ---------------------------------------------------------------------------
# No flags means read-only.
# ---------------------------------------------------------------------------


def test_default_invocation_is_a_read_only_plan(tmp_path: Path) -> None:
    harness = Harness(tmp_path)

    report = harness.report_file([])

    assert report["_exit_code"] == 0
    assert report["mode"] == "warehouse_overview_and_bounded_apply_plan"
    assert report["writes_database"] is False
    assert report["source_requests_made"] is False
    assert report["apply_requires_explicit_flag"] is True
    assert report["history_completeness"] == "not_certified"
    assert report["candidate_count"] == 1
    assert report["limitations"]
    assert harness.source_calls == []
    assert harness.reader.per_code_reads == []
    assert harness.snapshot_files() == []
    assert not harness.progress_path.exists()


def test_apply_writes_only_to_owned_storage_and_dispatches_on_a_real_difference(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path)

    plan = harness.report_file([])
    assert plan["mode"] == "warehouse_overview_and_bounded_apply_plan"

    report, exit_code = asyncio.run(harness.run_apply())
    outcome = report["outcomes"][0]
    assert report["mode"] == "managed_bounded_convertible_history_reconciliation"
    assert exit_code == controller.EXIT_ALL_VERIFIED
    assert report["writes_database"] is True, "a real missing session existed"
    assert len(harness.managed_calls) == 1
    for key in (
        "source_snapshot_path",
        "warehouse_before_snapshot_path",
        "warehouse_after_snapshot_path",
    ):
        assert str(outcome[key]).startswith(str(tmp_path))
    assert {item.parent for item in tmp_path.rglob("*") if item.is_file()} <= {
        tmp_path,
        harness.snapshot_dir,
    }


def test_plan_carries_the_unattributable_legacy_evidence(tmp_path: Path) -> None:
    report = Harness(tmp_path).report_file([])

    evidence = report["unattributable_rows"]
    assert evidence["row_count"] == 1
    assert evidence["no_symbol_row_count"] == 1
    assert evidence["unique_symbol_value_count"] == 1
    assert "attribution_policy" in evidence
    assert report["historical_inventory"]["source_provenance"][
        "unrecognized_symbol_row_count_by_source"
    ] == {"legacy_unknown": 1}


def test_universe_merges_inventory_with_issuance_evidence(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    universe_file = tmp_path / "issuance.json"
    universe_file.write_text(
        json.dumps(
            {
                "schema_version": "bond-convertible-issuance-universe-v1",
                "symbols": [
                    {
                        "symbol": "sz128061",
                        "listing_date": "2019-01-08",
                        "name": "Example Convertible",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = harness.report_file(["--universe-file", str(universe_file)])

    assert report["universe_merge"]["added_symbol_count"] == 1
    assert report["universe_merge"]["merged_universe_count"] == 2
    assert report["source_requests_made"] is False


# ---------------------------------------------------------------------------
# Both budgets are real bounds on vendor traffic.
# ---------------------------------------------------------------------------


def test_max_codes_bounds_source_probes(tmp_path: Path) -> None:
    codes = {
        f"sh1100{index:02d}": warehouse_rows(PRESENT_DATES, symbol=f"sh1100{index:02d}")
        for index in range(1, 9)
    }
    harness = Harness(tmp_path, codes=codes)

    report, exit_code = asyncio.run(harness.run_apply(max_codes=3))

    assert len(harness.source_calls) == 3
    assert len(report["outcomes"]) == 3
    assert len(harness.managed_calls) == 3
    assert exit_code == controller.EXIT_ALL_VERIFIED
    assert report["max_codes"] == 3
    assert report["not_selected_count"] == 5


def test_time_budget_defers_the_rest_of_the_batch(tmp_path: Path) -> None:
    codes = {
        f"sh1100{index:02d}": warehouse_rows([], symbol=f"sh1100{index:02d}")
        for index in range(1, 6)
    }
    payloads = {symbol: source_payload(ALL_DATES) for symbol in codes}
    harness = Harness(tmp_path, codes=codes, payloads=payloads)
    clock = FakeClock(step=20.0)

    report, exit_code = asyncio.run(
        harness.run_apply(max_codes=5, budget=90, monotonic=clock.monotonic)
    )

    statuses = [row["status"] for row in report["outcomes"]]
    assert len(harness.source_calls) == 1
    assert statuses.count("deferred_budget") == 4
    assert exit_code == controller.EXIT_DEFERRED
    assert report["source_requests_made"] is True
    assert report["writes_database"] is True, (
        "the one probed code was repaired before the budget died"
    )
    reasons = {
        row.get("reason") for row in report["outcomes"] if row["status"] == "deferred_budget"
    }
    assert reasons <= {
        "insufficient_wall_clock_budget_before_source_probe",
        "batch_wall_clock_budget_exhausted",
    }


def test_source_timeout_is_clamped_to_the_remaining_budget(tmp_path: Path) -> None:
    harness = Harness(tmp_path, codes={BOND: warehouse_rows([])})
    clock = FakeClock(step=10.0)

    report, exit_code = asyncio.run(
        harness.run_apply(budget=30, source_timeout=45, monotonic=clock.monotonic)
    )

    assert harness.source_calls == [(BOND, 5)]
    outcome = report["outcomes"][0]
    assert outcome["source_timeout_seconds"] == 5
    assert outcome["status"] == "deferred_budget"
    assert outcome["reason"] == "insufficient_budget_for_managed_dispatch_and_post_write_sql"
    assert harness.managed_calls == []
    assert exit_code == controller.EXIT_DEFERRED


def test_batch_budget_arithmetic() -> None:
    budget = controller.BatchBudget(240, 45, 0.0, monotonic=lambda: 213.0)
    assert budget.remaining_seconds() == 27.0
    assert budget.clamped_source_timeout(budget.remaining_seconds()) == 22
    assert budget.managed_timeout(27.0) == 22.0
    assert budget.clamped_source_timeout(3.5) is None
    assert budget.clamped_source_timeout(4.0) is None
    assert budget.managed_timeout(4.0) is None
    assert budget.managed_timeout(3.0) is None
    assert controller.BatchBudget(240, 45, 0.0, monotonic=lambda: 400.0).remaining_seconds() == 0.0


def test_explicit_symbols_over_max_codes_reject_before_any_probe(tmp_path: Path) -> None:
    harness = Harness(
        tmp_path,
        codes={symbol: warehouse_rows([]) for symbol in ("sh110001", "sh110002", "sh110003")},
    )

    with pytest.raises(ValueError, match="max_codes"):
        asyncio.run(harness.run_apply(["sh110001", "sh110002", "sh110003"], max_codes=2))
    assert harness.source_calls == []
    assert harness.managed_calls == []

    report = harness.report_file(
        ["--apply", "--symbols", "sh110001", "sh110002", "--max-codes", "1"]
    )
    assert report["status"] == "controller_failed"
    assert report["_exit_code"] == controller.EXIT_ATTENTION_REQUIRED
    assert report["writes_database"] is False


def test_out_of_range_cli_bounds_reject_without_reading_the_warehouse(tmp_path: Path) -> None:
    harness = Harness(tmp_path)

    for flag, value in (
        ("--max-codes", "0"),
        ("--time-budget-seconds", "601"),
        ("--source-timeout-seconds", "91"),
    ):
        report = harness.report_file(["--apply", flag, value])
        assert report["status"] == "controller_failed", flag
        assert harness.source_calls == []


def test_killable_child_is_terminated_at_the_source_timeout() -> None:
    def slow_worker(connection: Any, symbol: str) -> None:
        time.sleep(30)
        connection.send(json.dumps({"columns": [], "rows": []}))

    started = time.monotonic()
    with pytest.raises(TimeoutError, match="exceeded 1 seconds"):
        controller._run_killable_probe(slow_worker, ("sh110001",), 1, start_method="fork")
    elapsed = time.monotonic() - started

    assert elapsed < 5.0
    assert [child for child in multiprocessing.active_children() if child.exitcode is None] == []


# ---------------------------------------------------------------------------
# Checkpoints: idempotent re-runs, mid-batch resume, cooldown.
# ---------------------------------------------------------------------------


def test_repair_then_idempotent_second_run_dispatches_no_write(tmp_path: Path) -> None:
    harness = Harness(tmp_path)

    first, first_exit = asyncio.run(harness.run_apply())
    assert [row["status"] for row in first["outcomes"]] == ["verified_source_sequence"]
    assert first["writes_database"] is True
    assert first_exit == controller.EXIT_ALL_VERIFIED
    assert len(harness.managed_calls) == 1
    assert harness.managed_calls[0]["dispatch_receipt"]["claim_key"].startswith(
        "bond-convertible-history:v1:"
    )

    second, second_exit = asyncio.run(harness.run_apply())
    outcome = second["outcomes"][0]
    assert [row["status"] for row in second["outcomes"]] == ["verified_unchanged"]
    assert outcome["write_attempted"] is False
    assert second["writes_database"] is False
    assert second["managed_scheduler_invoked"] is False
    assert len(harness.managed_calls) == 1, "the second run dispatched nothing"
    assert second_exit == controller.EXIT_ALL_VERIFIED


def test_identical_rerun_reuses_content_hashed_snapshots(tmp_path: Path) -> None:
    harness = Harness(tmp_path)

    asyncio.run(harness.run_apply())
    repair_files = harness.snapshot_files()
    assert any("-warehouse-before-" in name for name in repair_files)
    assert any("-warehouse-after-" in name for name in repair_files)

    asyncio.run(harness.run_apply())
    verified_files = harness.snapshot_files()
    bytes_after_second = {
        name: (harness.snapshot_dir / name).read_bytes() for name in verified_files
    }

    asyncio.run(harness.run_apply())
    assert harness.snapshot_files() == verified_files, (
        "an identical warehouse state hashes identically"
    )
    for name in verified_files:
        assert (harness.snapshot_dir / name).read_bytes() == bytes_after_second[name]

    for name in verified_files:
        if "-warehouse-" not in name:
            continue
        stated = name.split("-")[-1].removesuffix(".json")
        payload = json.loads((harness.snapshot_dir / name).read_text(encoding="utf-8"))
        assert payload["snapshot_sha256"] == stated
        recomputed = controller.sha256_hex(
            {key: value for key, value in payload.items() if key != "snapshot_sha256"}
        )
        assert recomputed == stated, "the filename is the content hash, as in iteration203"
        assert payload["read_only_select"] is True
        assert payload["key_fields"] == ["symbol", "data_date"]
        assert payload["compared_fields"] == ["open", "high", "low", "close"]


def test_source_snapshot_is_content_addressed_and_collision_fails_closed(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    snapshot = controller.normalize_source_payload(BOND, source_payload(ALL_DATES))
    harness.snapshot_dir.mkdir(parents=True, exist_ok=True)
    (harness.snapshot_dir / f"{snapshot.symbol}-{snapshot.raw_content_sha256}.json").write_text(
        '{"tampered": true}\n', encoding="utf-8"
    )

    report, exit_code = asyncio.run(harness.run_apply())

    assert [row["status"] for row in report["outcomes"]] == ["verification_failed"]
    assert exit_code == controller.EXIT_ATTENTION_REQUIRED
    assert harness.managed_calls == []
    assert report["writes_database"] is False


def test_mid_batch_failure_resumes_without_resetting_cooldowns(tmp_path: Path) -> None:
    symbols = ["sh110001", "sh110002", "sh110003"]
    codes = {symbol: warehouse_rows(PRESENT_DATES, symbol=symbol) for symbol in symbols}
    harness = Harness(tmp_path, codes=codes, failing={"sh110001"})

    report_one, exit_one = asyncio.run(harness.run_apply(max_codes=2))
    statuses_one = {row["symbol"]: row["status"] for row in report_one["outcomes"]}
    assert statuses_one == {"sh110001": "source_failed", "sh110002": "verified_source_sequence"}
    assert exit_one == controller.EXIT_SOURCE_FAILURE
    ledger_after_one = harness.progress_path.read_text(encoding="utf-8")
    probes_after_one = len(harness.source_calls)

    report_two, _ = asyncio.run(harness.run_apply(max_codes=3))
    assert harness.progress_path.read_text(encoding="utf-8").startswith(ledger_after_one)
    cooled = [
        row
        for row in report_two["deferred_inventory"]
        if row["status"] == "deferred_failure_cooldown"
    ]
    assert [row["previous_failure_status"] for row in cooled] == ["source_failed"]
    assert cooled[0]["symbol"] == "sh110001"
    assert time.strptime(cooled[0]["retry_after_utc"][:19], "%Y-%m-%dT%H:%M:%S")
    attempted = [row["symbol"] for row in report_two["outcomes"]]
    assert "sh110001" not in attempted
    assert "sh110003" in attempted, "the unattempted code is picked up by the next bounded run"
    assert len(harness.source_calls) == probes_after_one + 2
    assert list(tmp_path.glob("*cursor*")) == []

    retry_harness = Harness(tmp_path / "retry", codes=codes, failing={"sh110001"})
    retry_harness.progress_path.write_text(ledger_after_one, encoding="utf-8")
    report_three, _ = asyncio.run(retry_harness.run_apply(max_codes=3, retry_failed=True))
    assert "sh110001" in [row["symbol"] for row in report_three["outcomes"]]


def test_checkpoint_key_and_scope_hash_are_stable(tmp_path: Path) -> None:
    harness = Harness(tmp_path)

    first, _ = asyncio.run(harness.run_apply())
    checkpoint = first["outcomes"][0]["checkpoint_key"]
    assert checkpoint == controller.make_checkpoint_key(BOND)
    assert first["scope_hash"] == controller.make_scope_hash([BOND], universe_for([BOND]))

    second, _ = asyncio.run(harness.run_apply())
    assert second["outcomes"][0]["checkpoint_key"] == checkpoint
    assert second["scope_hash"] == first["scope_hash"]


def test_source_failure_is_recorded_without_a_write_or_a_fabricated_boundary(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, failing={BOND})

    report, exit_code = asyncio.run(harness.run_apply())
    outcome = report["outcomes"][0]

    assert outcome["status"] == "source_failed"
    assert outcome["failure_phase"] == "source_fetch_or_normalization"
    assert "404" in outcome["error"]
    assert exit_code == controller.EXIT_SOURCE_FAILURE
    assert report["source_requests_made"] is True
    assert report["writes_database"] is False
    assert harness.managed_calls == []
    assert len(controller.read_progress(harness.progress_path)) >= 1


def test_empty_source_response_stays_unverified(tmp_path: Path) -> None:
    harness = Harness(
        tmp_path,
        codes={BOND: warehouse_rows(ALL_DATES)},
        payloads={BOND: {"columns": SOURCE_COLUMNS, "rows": []}},
    )

    report, exit_code = asyncio.run(harness.run_apply())
    outcome = report["outcomes"][0]

    assert outcome["status"] == "source_empty_unverified"
    assert "no date or lifecycle boundary is inferred" in outcome["error"]
    assert exit_code == controller.EXIT_DEFERRED
    assert harness.managed_calls == []
    assert report["writes_database"] is False


def test_no_eligible_code_reports_the_no_work_status(tmp_path: Path) -> None:
    harness = Harness(tmp_path, codes={})

    report, exit_code = asyncio.run(harness.run_apply())

    assert report["outcomes"] == []
    assert report["status"] == "no_inventory_candidates"
    assert report["apply_max_codes"] == 5
    assert report["source_requests_made"] is False
    assert report["writes_database"] is False
    assert exit_code == controller.EXIT_DEFERRED


def test_progress_ledger_fails_closed_on_a_forged_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "progress.jsonl"
    path.write_text(
        json.dumps({"symbol": BOND, "status": "verified_unchanged", "checkpoint_key": "deadbeef"})
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="mismatched checkpoint key"):
        controller.read_progress(path)


def test_progress_ledger_is_append_only(tmp_path: Path) -> None:
    path = tmp_path / "progress.jsonl"
    record = controller._base_record(
        symbol=BOND,
        scope_hash="scope",
        status="verified_unchanged",
        now=controller.datetime.now(controller.UTC),
    )

    controller.append_progress(path, record)
    first = path.read_text(encoding="utf-8")
    controller.append_progress(path, {**record, "attempt_id": "second"})

    assert path.read_text(encoding="utf-8").startswith(first)
    assert len(controller.read_progress(path)) == 2


# ---------------------------------------------------------------------------
# Unattributable legacy rows.
# ---------------------------------------------------------------------------


def test_legacy_null_symbol_rows_are_never_attributed_to_a_code(tmp_path: Path) -> None:
    harness = Harness(tmp_path, codes={BOND: warehouse_rows(PRESENT_DATES)})

    report, _ = asyncio.run(harness.run_apply())
    outcome = report["outcomes"][0]

    assert outcome["comparison_before"]["source_only_count"] == 1
    assert outcome["comparison_before"]["source_only_dates"] == [MISSING_DATE]
    assert outcome["comparison_before"]["date_key_and_ohlc_match"] is False
    assert outcome["status"] == "verified_source_sequence"
    assert report["unattributable_rows_excluded_from_per_code_claims"] is True
    assert report["unattributable_rows"]["row_count"] == 1
    assert harness.reader.per_code_reads[0] == BOND


def test_counterfactual_attributing_legacy_rows_would_falsely_verify(tmp_path: Path) -> None:
    """The guard is load-bearing: bypassing it turns a real gap into a false closure."""

    guarded = controller.compare_daily_ledgers(
        source_payload(ALL_DATES)["rows"], warehouse_rows(PRESENT_DATES)
    )
    unguarded = controller.compare_daily_ledgers(
        source_payload(ALL_DATES)["rows"],
        warehouse_rows(PRESENT_DATES) + [falsely_attributed_legacy_row()],
    )

    assert guarded["date_key_and_ohlc_match"] is False
    assert guarded["source_only_count"] == 1
    assert unguarded["date_key_and_ohlc_match"] is True
    assert unguarded["warehouse_observation_count"] == len(ALL_DATES)

    # The pipeline reads the same table, so if the symbol-parameterized read were
    # replaced by date/price matching, this run would close with verified_unchanged
    # and no repair; the guarded run below still reports the open session.
    pipeline = Harness(tmp_path, codes={BOND: warehouse_rows(PRESENT_DATES)})
    report, _ = asyncio.run(pipeline.run_apply())
    outcome = report["outcomes"][0]

    assert outcome["comparison_before"]["warehouse_observation_count"] == len(PRESENT_DATES)
    assert outcome["status"] == "verified_source_sequence"
    assert len(pipeline.managed_calls) == 1


def test_gap_classification_keeps_an_unproven_head_open() -> None:
    baseline = warehouse_rows(["2020-01-08", "2020-01-09"])
    comparison = controller.compare_daily_ledgers(source_payload(ALL_DATES)["rows"], baseline)
    gaps = controller.classify_source_only_dates(comparison, baseline)

    assert gaps["head_count"] == 2
    assert gaps["internal_count"] == 0
    assert gaps["tail_count"] == 0
    assert gaps["warehouse_first_date"] == "2020-01-08"

    no_baseline = controller.compare_daily_ledgers(source_payload(ALL_DATES)["rows"], [])
    unclassified = controller.classify_source_only_dates(no_baseline, [])
    assert unclassified["unclassified_no_warehouse_baseline_count"] == len(ALL_DATES)
    assert unclassified["warehouse_first_date"] is None


def test_source_native_nulls_survive_normalization() -> None:
    payload = {
        "columns": SOURCE_COLUMNS,
        "rows": [
            {
                "date": "2020-01-06",
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "volume": None,
            }
        ],
    }

    snapshot = controller.normalize_source_payload(BOND, payload)

    assert snapshot.normalized_ledger[0] == {
        "data_date": "2020-01-06",
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "volume": None,
    }
    assert snapshot.first_source_date == "2020-01-06"
    assert snapshot.source_row_count == 1


def test_per_code_reader_is_parameterized_by_the_exact_symbol() -> None:
    connection = RecordingConnection(columns=_WAREHOUSE_COLUMNS, rows=[])

    with controller.MySQLConvertibleReader(connection) as reader:
        reader.read_convertible_bars_with_provenance("SH113062")

    per_code = [item for item in connection.executed if "WHERE symbol = %s" in item[0]]
    assert len(per_code) == 1
    sql, parameters = per_code[0]
    assert parameters == ("sh113062",)
    assert " ORDER BY data_date" in sql
    assert "data_date BETWEEN" not in sql
    assert "close =" not in sql, "no price matching"


def test_overview_reader_aggregates_unattributable_rows_and_provenance() -> None:
    connection = RecordingConnection(columns=_WAREHOUSE_COLUMNS, rows=[])

    with controller.MySQLConvertibleReader(connection) as reader:
        _, evidence = reader.read_convertible_history_overview()

    assert evidence["unattributable_rows"]["attribution_policy"]
    assert evidence["source_provenance"]["canonical_source_semantics"]
    executed = " ".join(sql for sql, _ in connection.executed)
    assert "GROUP BY symbol_key, source" in executed
    assert "WHERE symbol IS NULL" in executed


def test_parameterless_select_keeps_literal_percent_formats() -> None:
    """pymysql interpolates whenever args is not None, so () breaks a literal '%d'."""
    connection = RecordingConnection(columns=_WAREHOUSE_COLUMNS, rows=[])
    sql = (
        "SELECT SUM(CASE WHEN `date` <> DATE_FORMAT(data_date, '%Y-%m-%d') "
        "THEN 1 ELSE 0 END) AS rows_where_data_date_differs "
        "FROM BOND_ZH_HS_COV_DAILY WHERE symbol IS NULL"
    )

    with controller.MySQLConvertibleReader(connection) as reader:
        reader._execute(sql)

    assert connection.executed == [(sql, None)]
    with pytest.raises(TypeError, match="not enough arguments for format string"):
        sql % ()


def test_overview_business_date_probe_passes_no_args_to_the_driver() -> None:
    connection = RecordingConnection(columns=_WAREHOUSE_COLUMNS, rows=[])

    with controller.MySQLConvertibleReader(connection) as reader:
        reader.read_convertible_history_overview()

    probes = [item for item in connection.executed if "DATE_FORMAT(data_date" in item[0]]
    assert probes, "the overview must probe business-date drift"
    assert all(parameters is None for _, parameters in probes)
    assert all("%Y-%m-%d" in sql for sql, _ in probes)


def test_reader_refuses_any_statement_that_is_not_a_select() -> None:
    reader = controller.MySQLConvertibleReader(RecordingConnection(columns={"symbol"}, rows=[]))

    with pytest.raises(ValueError, match="SELECT"):
        reader._execute("UPDATE BOND_ZH_HS_COV_DAILY SET symbol = NULL")
    with pytest.raises(ValueError, match="SELECT"):
        reader._execute("SELECT 1; DROP TABLE BOND_ZH_HS_COV_DAILY")
    with pytest.raises(ValueError, match="unsupported warehouse table"):
        reader._table_columns("STOCK_ZH_A_HIST")


_WAREHOUSE_COLUMNS = {
    "symbol",
    "name",
    "date",
    "data_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
}


class RecordingConnection:
    def __init__(self, *, columns: set[str], rows: list[dict[str, Any]]) -> None:
        self.columns = columns
        self.rows = rows
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self)

    def close(self) -> None:
        return None


class RecordingCursor:
    def __init__(self, connection: RecordingConnection) -> None:
        self.connection = connection
        self._result: list[dict[str, Any]] = []

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, parameters: tuple[Any, ...] | None = ()) -> None:
        self.connection.executed.append((sql, parameters))
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            self._result = [{"column_name": name} for name in sorted(self.connection.columns)]
        elif "GROUP BY symbol_key" in sql:
            self._result = [
                {"symbol_key": "<no-symbol>", "source": "legacy_unknown", "row_count": 3}
            ]
        elif "AS source, COUNT(*) AS row_count" in sql:
            self._result = [{"symbol": BOND, "source": "sina", "row_count": 2}]
        elif "symbol IS NULL" in sql:
            self._result = [
                {
                    "row_count": 3,
                    "distinct_business_dates": 2,
                    "first_business_date": "2020-01-07",
                    "last_business_date": "2020-01-08",
                    "first_collection_date": "2026-01-01",
                    "last_collection_date": "2026-01-01",
                    "rows_where_data_date_differs": 3,
                }
            ]
        elif "MAX(observed_at)" in sql:
            self._result = [{"snapshot_at": None}]
        else:
            self._result = list(self.connection.rows)

    def fetchall(self) -> list[dict[str, Any]]:
        return self._result


# ---------------------------------------------------------------------------
# The report shape the recovery worker parses.
# ---------------------------------------------------------------------------


def classify_bond(returncode: int, report: dict[str, Any]) -> tuple[str, bool, list[str]]:
    """Vendored copy of the worker's bond classifier.

    Mirrors ``_classify_bond`` in ``src/backend/scripts/ops/run_full_history_recovery_worker.py``
    (lines 902-1027).  The worker is a runtime asset owned by another agent and is not on
    this branch, so the contract it enforces is pinned here instead of imported.
    """

    max_codes, batch_seconds, source_timeout = 5, 240, 45
    success = {"verified_unchanged", "verified_source_sequence"}
    normal_incomplete = {
        "source_empty_unverified",
        "deferred_budget",
        "deferred_failure_cooldown",
        "deferred_failure_cooldown_summary",
    }
    source_failure = {"source_failed", "source_invalid"}
    attention = {
        "source_worker_crashed",
        "verification_failed",
        "managed_preflight_failed",
        "managed_preflight_timed_out",
        "managed_execution_pending",
        "managed_execution_failed",
        "managed_outcome_unknown",
        "post_write_mismatch",
    }
    if (
        report.get("report_type") != "bond-convertible-history-controller-v1"
        or report.get("mode") != "managed_bounded_convertible_history_reconciliation"
        or not isinstance(report.get("outcomes"), list)
    ):
        return "attention_required", True, ["report contract"]
    outcomes = report["outcomes"]
    if len(outcomes) > max_codes:
        return "attention_required", True, ["symbol limit"]
    if outcomes:
        expected = {
            "max_codes": max_codes,
            "time_budget_seconds": batch_seconds,
            "source_timeout_seconds_max": source_timeout,
        }
        if any(report.get(key) != value for key, value in expected.items()):
            return "attention_required", True, ["limits differ from the bounded command"]
    elif report.get("status") in {"no_runnable_candidates", "no_inventory_candidates"}:
        if (
            report.get("apply_max_codes") != max_codes
            or report.get("source_requests_made") is not False
            or report.get("writes_database") is not False
        ):
            return "attention_required", True, ["empty run lacks no-work evidence"]
    else:
        return "attention_required", True, ["no outcomes and no recognized no-work status"]
    if any(not isinstance(row, dict) or not isinstance(row.get("status"), str) for row in outcomes):
        return "attention_required", True, ["malformed outcome"]
    statuses = [row["status"] for row in outcomes]
    known = success | normal_incomplete | source_failure | attention
    if set(statuses) - known:
        return "attention_required", True, [f"unhandled outcomes: {sorted(set(statuses) - known)}"]
    status_set = set(statuses)
    if returncode == 1:
        retryable = success | source_failure
        if (
            "controller_failed" not in status_set
            and "source_worker_crashed" not in status_set
            and status_set & source_failure
            and status_set <= retryable
        ):
            return "source_failed_retryable", False, []
        return "attention_required", True, ["exit 1 disagrees with outcomes"]
    if status_set & attention:
        return "attention_required", True, ["attention statuses present"]
    if returncode == 3 and statuses and status_set <= (success | normal_incomplete):
        if status_set & {"deferred_budget"}:
            return "deferred_budget_retryable", False, []
        return "source_deferred", False, []
    if (
        returncode == 3
        and not statuses
        and report.get("status") in {"no_runnable_candidates", "no_inventory_candidates"}
    ):
        return "source_deferred", False, []
    if returncode == 0 and statuses and status_set <= success:
        return "batch_reconciled_history_incomplete", False, []
    return "attention_required", True, [f"exit {returncode} disagrees with outcomes"]


def test_verified_batch_parses_as_reconciled_but_not_certified(tmp_path: Path) -> None:
    harness = Harness(tmp_path)

    report, exit_code = asyncio.run(harness.run_apply())
    status, needs_attention, reasons = classify_bond(exit_code, report)

    assert status == "batch_reconciled_history_incomplete"
    assert needs_attention is False
    assert reasons == []
    assert report["report_type"] == controller.REPORT_VERSION
    assert report["history_completeness"] == "not_certified"
    assert report["lifecycle_policy"] == controller.LIFECYCLE_POLICY
    assert report["budget_enforcement"]["outer_process_hard_stop_required"] is True
    assert report["scope_hash"] and report["progress_file"] and report["snapshot_dir"]


def test_deferred_batch_parses_as_retryable(tmp_path: Path) -> None:
    codes = {
        f"sh1100{index:02d}": warehouse_rows([], symbol=f"sh1100{index:02d}")
        for index in range(1, 4)
    }
    payloads = {symbol: source_payload(ALL_DATES) for symbol in codes}
    harness = Harness(tmp_path, codes=codes, payloads=payloads)
    clock = FakeClock(step=240.0)

    report, exit_code = asyncio.run(harness.run_apply(budget=240, monotonic=clock.monotonic))
    status, needs_attention, _ = classify_bond(exit_code, report)

    assert {row["status"] for row in report["outcomes"]} == {"deferred_budget"}
    assert harness.source_calls == []
    assert status == "deferred_budget_retryable"
    assert needs_attention is False


def test_source_only_batch_parses_as_retryable_source_failure(tmp_path: Path) -> None:
    harness = Harness(tmp_path, failing={BOND})

    report, exit_code = asyncio.run(harness.run_apply())
    status, needs_attention, _ = classify_bond(exit_code, report)

    assert status == "source_failed_retryable"
    assert needs_attention is False


def test_no_work_batch_parses_as_source_deferred(tmp_path: Path) -> None:
    harness = Harness(tmp_path, codes={})

    report, exit_code = asyncio.run(harness.run_apply())
    status, needs_attention, _ = classify_bond(exit_code, report)

    assert status == "source_deferred"
    assert needs_attention is False


def test_managed_failure_batch_is_flagged_for_attention(tmp_path: Path) -> None:
    harness = Harness(tmp_path)

    async def failing_scheduler(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("managed execution rejected")

    report, exit_code = asyncio.run(harness.run_apply(scheduler_run=failing_scheduler))
    status, needs_attention, _ = classify_bond(exit_code, report)

    assert report["outcomes"][0]["status"] == "managed_execution_failed"
    assert report["outcomes"][0]["database_write_may_have_occurred"] is True
    assert report["writes_database"] is True
    assert status == "attention_required"
    assert needs_attention is True
    assert exit_code == controller.EXIT_ATTENTION_REQUIRED


def test_managed_timeout_keeps_unknown_commit_state(tmp_path: Path) -> None:
    harness = Harness(tmp_path)

    async def hanging_scheduler(*_args: Any, **_kwargs: Any) -> None:
        await asyncio.sleep(30)

    report, exit_code = asyncio.run(
        harness.run_apply(budget=240, source_timeout=2, scheduler_run=hanging_scheduler)
    )
    outcome = report["outcomes"][0]

    assert outcome["status"] == "managed_outcome_unknown"
    assert outcome["database_write_may_have_occurred"] is True
    assert "commit state is unknown" in outcome["error"]
    assert report["writes_database"] is True
    assert classify_bond(exit_code, report)[0] == "attention_required"


def test_managed_pending_execution_is_not_reported_as_verified(tmp_path: Path) -> None:
    harness = Harness(tmp_path)

    async def pending_scheduler(*_args: Any, **_kwargs: Any) -> SimpleExecution:
        return SimpleExecution(execution_id="exec-pending", status="pending")

    report, exit_code = asyncio.run(harness.run_apply(scheduler_run=pending_scheduler))
    outcome = report["outcomes"][0]

    assert outcome["status"] == "managed_execution_pending"
    assert outcome["execution_id"] == "exec-pending"
    assert classify_bond(exit_code, report)[0] == "attention_required"


def test_preflight_failure_dispatches_nothing(tmp_path: Path) -> None:
    harness = Harness(tmp_path)

    async def unavailable_resolver() -> str:
        raise RuntimeError("bond_zh_hs_cov_daily is missing or inactive")

    report, exit_code = asyncio.run(
        controller.run_apply(
            [],
            universe_for([BOND]),
            max_codes=5,
            progress_path=harness.progress_path,
            snapshot_dir=harness.snapshot_dir,
            time_budget_seconds=240,
            source_timeout_seconds=45,
            reader_factory=lambda: harness.reader,
            source_fetcher=harness.source_fetcher,
            scheduler_run=harness.scheduler_run,
            source_resolver=unavailable_resolver,
        )
    )
    outcome = report["outcomes"][0]

    assert outcome["status"] == "managed_preflight_failed"
    assert outcome["database_write_may_have_occurred"] is False
    assert harness.managed_calls == []
    assert report["writes_database"] is False
    assert classify_bond(exit_code, report)[0] == "attention_required"


def test_epoch_and_compact_dates_normalise_to_the_stored_key() -> None:
    """AKShare returns epoch seconds; the warehouse stores YYYY-MM-DD."""

    assert controller._as_day("1629763200") == "2021-08-24"
    assert controller._as_day(1629763200) == "2021-08-24"
    assert controller._as_day("20210824") == "2021-08-24"
    assert controller._as_day("2021-08-24") == "2021-08-24"


def test_comparison_matches_an_epoch_source_against_iso_warehouse_rows() -> None:
    """Before normalisation every date looked source-only, so every run mismatched."""

    common = {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}
    source = [{"data_date": "1629763200", **common}]
    warehouse = [{"data_date": "2021-08-24", **common}]

    comparison = controller.compare_daily_ledgers(source, warehouse)

    assert comparison["source_only_count"] == 0
    assert comparison["warehouse_only_count"] == 0
    assert comparison["ohlc_mismatch_count"] == 0
    assert comparison["date_key_and_ohlc_match"] is True
