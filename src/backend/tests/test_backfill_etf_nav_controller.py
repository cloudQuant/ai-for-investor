"""Contract tests for the bounded ETF NAV recovery controller (iteration 204, 204-B05-03).

Everything here runs offline: adapters are in-memory harnesses or JSON fixtures, so no live
warehouse is written and no vendor is contacted.  Paths that need the real source are
labelled NOT_RUN in the controller itself.

Each guard is paired with a counterfactual that shows the guard is load-bearing rather than
decorative: the same fixture produces the *successful/false* result once the guard is removed.
"""

from __future__ import annotations

import fcntl
import gzip
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "src" / "backend" / "scripts" / "backfill_etf_nav_controller.py"

#: Key sets the recovery worker's ``_classify_etf`` reads off the report.
WORKER_TOP_LEVEL_KEYS = (
    "schema_version",
    "report_type",
    "run_id",
    "run_event",
    "outcomes",
    "selected_codes",
    "selected_listing_evidence",
    "fresh_sina_probe_ready",
    "full_history_complete",
)
WORKER_RUN_EVENT_KEYS = (
    "run_id",
    "mode",
    "apply_enabled",
    "network_used",
    "max_codes",
    "time_budget_seconds",
    "full_history_complete",
    "probe_ready",
    "current_sina_snapshot",
    "current_sina_snapshot_path",
    "sina_refresh_error",
    "selected_codes",
    "selected_listing_evidence",
    "processed_codes",
    "protected_legacy_scope",
)
WORKER_PROTECTION_KEYS = (
    "codes_count",
    "codes_sha256",
    "expected_nav_rows",
    "expected_nav_sha256",
    "expected_cache_rows",
    "expected_cache_sha256",
)
WORKER_FINGERPRINT_KEYS = (
    "protected_scope_codes_count",
    "protected_scope_codes_sha256",
    "protected_legacy_nav_rows",
    "protected_legacy_nav_sha256",
    "protected_cache_rows",
    "protected_cache_sha256",
)


def _controller() -> ModuleType:
    spec = importlib.util.spec_from_file_location("backfill_etf_nav_controller", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _nav_rows(module: ModuleType, start: str, count: int, step_days: int = 1) -> list[Any]:
    from datetime import date, timedelta

    first = date.fromisoformat(start)
    return [
        module.NavRow(
            business_date=(first + timedelta(days=index * step_days)).isoformat(),
            unit_nav=1 + index * 0.01,
            accumulated_nav=1 + index * 0.01,
            daily_growth=0.1 * index,
        )
        for index in range(count)
    ]


def _target_rows(module: ModuleType, rows: list[Any]) -> list[Any]:
    return [
        module.TargetNavRow(
            business_date=row.business_date,
            unit_nav=row.unit_nav,
            accumulated_nav=row.accumulated_nav,
            daily_growth=row.daily_growth,
        )
        for row in rows
    ]


class Harness:
    """Offline stand-in for the listing source, NAV source, warehouse, scope probe and dispatcher."""

    def __init__(
        self,
        module: ModuleType,
        *,
        listing_codes: tuple[str, ...] = ("159001", "159767", "159768", "159770"),
        nav: dict[str, list[Any]] | None = None,
        target: dict[str, list[Any]] | None = None,
        quarantine: tuple[str, ...] = (),
        lifecycle: dict[str, dict[str, Any]] | None = None,
        source_complete: bool = True,
        first_nav_date_unknown: bool = False,
        is_nav_metric: bool = True,
        fail_codes: tuple[str, ...] = (),
        timeout_codes: tuple[str, ...] = (),
        probe_cost_seconds: float = 0.0,
        apply_cost_seconds: float = 0.0,
        protected_baseline: dict[str, Any] | None = None,
        protected_changes_after_write: bool = False,
        observed_at: str = "2026-10-27T15:00:00+08:00",
    ) -> None:
        self.module = module
        self.listing_codes = listing_codes
        self.nav = dict(nav or {})
        self.target = {code: list(rows) for code, rows in (target or {}).items()}
        self.quarantine = {code: {"metric_type": "income_per_100_shares"} for code in quarantine}
        self.lifecycle = dict(lifecycle or {})
        self.source_complete = source_complete
        self.first_nav_date_unknown = first_nav_date_unknown
        self.is_nav_metric = is_nav_metric
        self.fail_codes = fail_codes
        self.timeout_codes = timeout_codes
        self.probe_cost_seconds = probe_cost_seconds
        self.apply_cost_seconds = apply_cost_seconds
        self.protected_changes_after_write = protected_changes_after_write
        self.observed_at = observed_at
        self.clock_time = 0.0
        self.probe_calls: list[str] = []
        self.write_calls: list[str] = []
        self.dispatch_calls: list[str] = []
        self.fingerprint_calls = 0
        self._wrote_once = False
        self._baseline = protected_baseline or _default_baseline()

    def clock(self) -> float:
        return self.clock_time

    # --- listing -------------------------------------------------------------
    def refresh(self) -> Any:
        rows = [{"fund_code": code, "fund_name": f"ETF {code}"} for code in self.listing_codes]
        return self.module.ListingSnapshot(
            observed_at=self.observed_at,
            source="fixture_etf_node",
            rows=tuple(rows),
            complete=True,
        )

    # --- NAV source ----------------------------------------------------------
    def probe(self, fund_code: str, start_date: str, end_date: str) -> Any:
        if fund_code in self.fail_codes:
            raise RuntimeError(f"fixture source failure for {fund_code}")
        self.clock_time += self.probe_cost_seconds
        self.probe_calls.append(fund_code)
        rows = tuple(self.nav.get(fund_code, ()))
        if fund_code in self.timeout_codes:
            return self.module.NavProbe(
                fund_code=fund_code,
                provider="fixture",
                source_complete=False,
                rows=(),
                first_nav_date=None,
                last_nav_date=None,
                observed_at=self.observed_at,
                timed_out=True,
            )
        first = None if self.first_nav_date_unknown else (rows[0].business_date if rows else None)
        return self.module.NavProbe(
            fund_code=fund_code,
            provider="pingzhongdata_verified",
            source_complete=self.source_complete,
            rows=rows,
            first_nav_date=first,
            last_nav_date=rows[-1].business_date if rows else None,
            observed_at=self.observed_at,
            semantic_evidence={
                "semantic_status": "verified_nav" if self.is_nav_metric else "not_nav_metric",
                "metric_type": "unit_cumulative_nav"
                if self.is_nav_metric
                else "income_per_100_shares",
            },
            is_nav_metric=self.is_nav_metric,
        )

    # --- warehouse -----------------------------------------------------------
    def read_rows(self, fund_code: str) -> list[Any]:
        return list(self.target.get(fund_code, []))

    def codes_with_rows(self) -> set[str]:
        return set(self.target)

    def row_count(self) -> int:
        return sum(len(rows) for rows in self.target.values())

    def apply_rows(self, fund_code: str, rows: Any) -> dict[str, int]:
        self.write_calls.append(fund_code)
        self.clock_time += self.apply_cost_seconds
        self.target[fund_code] = [_target_row(self.module, row) for row in rows]
        self._wrote_once = True
        return {"inserted": len(rows), "unchanged": 0}

    # --- protected legacy scope + managed dispatch --------------------------
    def fingerprint(self, codes: Any) -> dict[str, Any]:
        self.fingerprint_calls += 1
        drift = 1 if (self.protected_changes_after_write and self._wrote_once) else 0
        return {
            "protected_scope_codes_count": self._baseline["codes_count"],
            "protected_scope_codes_sha256": self._baseline["codes_sha256"],
            "protected_legacy_nav_rows": self._baseline["nav_rows"] + drift,
            "protected_legacy_nav_sha256": self._baseline["nav_sha256"],
            "protected_cache_rows": self._baseline["cache_rows"],
            "protected_cache_sha256": self._baseline["cache_sha256"],
        }

    def dispatch(self, fund_code: str, rows: Any, run_id: str) -> dict[str, Any]:
        self.dispatch_calls.append(fund_code)
        return {
            "execution_id": f"ak_exec_fixture_{fund_code}",
            "status": "completed",
            "error_message": None,
            "run_id": run_id,
        }

    # --- reviewed manifests --------------------------------------------------
    def reviewed_lifecycle(self) -> dict[str, dict[str, Any]]:
        return self.lifecycle

    def semantic_quarantine(self) -> dict[str, dict[str, Any]]:
        return self.quarantine


def _default_baseline() -> dict[str, Any]:
    return {
        "codes_count": 1,
        "codes_sha256": "a" * 64,
        "nav_rows": 60329,
        "nav_sha256": "b" * 64,
        "cache_rows": 357,
        "cache_sha256": "c" * 64,
    }


def _target_row(module: ModuleType, row: Any) -> Any:
    return module.TargetNavRow(
        business_date=row.business_date,
        unit_nav=row.unit_nav,
        accumulated_nav=row.accumulated_nav,
        daily_growth=row.daily_growth,
    )


def write_protected_manifest(path: Path, *, nav_rows: int = 60329) -> Path:
    payload = {
        "protected_codes": ["510300"],
        "codes_count": 1,
        "codes_sha256": "a" * 64,
        "nav_rows": nav_rows,
        "nav_sha256": "b" * 64,
        "cache_rows": 357,
        "cache_sha256": "c" * 64,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def run_with(
    module: ModuleType,
    harness: Harness,
    output_dir: Path,
    report_path: Path,
    *,
    probe: bool = False,
    apply: bool = False,
    max_codes: int = 5,
    time_budget_seconds: float = 240.0,
    manifest: Path | None = None,
    shard_lookahead: int = 400,
    shard_inflight_runs: int = 2,
    skip_shard_guard: bool = False,
    run_id: str = "0" * 32,
) -> dict[str, Any]:
    options = module.ControllerOptions(
        probe=probe,
        apply=apply,
        max_codes=max_codes,
        time_budget_seconds=time_budget_seconds,
        output_dir=output_dir,
        report_path=report_path,
        source_start_date="19000101",
        source_end_date="20261027",
        protected_scope_manifest=manifest,
        shard_lookahead=shard_lookahead,
        shard_inflight_runs=shard_inflight_runs,
        skip_shard_guard=skip_shard_guard,
    )
    return module.run_controller(
        options,
        listing=harness,
        probe_source=harness,
        target=harness,
        protected_probe=harness,
        dispatcher=harness,
        manifests=harness,
        run_id=run_id,
        clock=harness.clock,
    )


@pytest.fixture
def module() -> ModuleType:
    return _controller()


@pytest.fixture
def full_source(module: ModuleType) -> dict[str, list[Any]]:
    return {code: _nav_rows(module, "2026-08-14", 3) for code in ("159767", "159768", "159770")}


# --- read-only default ------------------------------------------------------


def test_default_run_is_a_read_only_plan_with_no_state_writes(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    output_dir = tmp_path / "state"
    # In plan mode the live listing node is not contacted, so the identity plane available
    # offline is the canonical NAV table itself.
    harness = Harness(
        module,
        listing_codes=(),
        nav=full_source,
        target={code: _target_rows(module, rows) for code, rows in full_source.items()},
    )
    report = run_with(module, harness, output_dir, tmp_path / "report.json")

    assert report["run_event"]["mode"] == "plan"
    assert report["run_event"]["network_used"] is False
    assert report["run_event"]["apply_enabled"] is False
    assert report["outcomes"] == []
    assert report["selected_codes"] == []
    # The plan still names the codes a later bounded batch would take.
    assert report["plan"]["candidate_preview"]
    assert harness.probe_calls == []
    assert harness.write_calls == []
    assert not output_dir.exists(), "read-only mode must not create the state namespace"


def test_default_run_counterfactual_apply_writes_and_probes(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    """Counterfactual for the read-only guard: --apply on the same fixture does write."""
    harness = Harness(
        module,
        listing_codes=("159767", "159768", "159770"),
        nav=full_source,
        target={},
    )
    manifest = write_protected_manifest(tmp_path / "protected.json")
    run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        manifest=manifest,
    )
    assert harness.probe_calls
    assert harness.write_calls == harness.probe_calls


# --- probe without apply ----------------------------------------------------


def test_probe_without_apply_performs_no_writes(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    output_dir = tmp_path / "state"
    harness = Harness(module, nav=full_source)
    report = run_with(module, harness, output_dir, tmp_path / "report.json", probe=True)

    assert report["run_event"]["mode"] == "probe"
    assert report["run_event"]["network_used"] is True
    assert report["run_event"]["apply_enabled"] is False
    assert harness.write_calls == []
    assert harness.dispatch_calls == []
    assert (output_dir / "checkpoints.jsonl").exists() is False
    assert (output_dir / "cursor.json").exists() is False
    assert (output_dir / "source-snapshots").exists() is False
    for outcome in report["outcomes"]:
        assert outcome["writes_performed"] is False
        assert outcome["status"] in {
            "verified_read_only",
            "pending_target_reconciliation",
            "not_started_time_budget_exhausted",
        }


def test_probe_reports_source_dates_without_certifying_history(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    harness = Harness(module, nav=full_source)
    report = run_with(module, harness, tmp_path / "state", tmp_path / "report.json", probe=True)

    assert report["full_history_complete"] is False
    assert report["run_event"]["history_completeness"] == (
        "not_certified_by_a_bounded_batch_or_source_snapshot"
    )
    by_code = {row["fund_code"]: row for row in report["outcomes"]}
    assert by_code["159767"]["source_first_nav_date"] == "2026-08-14"
    assert by_code["159767"]["source_last_nav_date"] == "2026-08-16"


# --- budgets ----------------------------------------------------------------


def test_max_codes_bounds_the_selected_batch(module: ModuleType, tmp_path: Path) -> None:
    codes = ("159767", "159768", "159770", "159776", "159782", "159787", "159788")
    nav = {code: _nav_rows(module, "2026-08-14", 2) for code in codes}
    harness = Harness(module, listing_codes=codes, nav=nav)
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        max_codes=3,
    )
    assert len(report["selected_codes"]) == 3
    assert len(harness.probe_calls) == 3
    assert report["run_event"]["max_codes"] == 3
    assert report["run_event"]["time_budget_seconds"] == 240.0


def test_larger_max_codes_counterfactual_selects_more_codes(
    module: ModuleType, tmp_path: Path
) -> None:
    """Counterfactual for the code bound: the same universe yields a wider batch."""
    codes = ("159767", "159768", "159770", "159776", "159782", "159787", "159788")
    nav = {code: _nav_rows(module, "2026-08-14", 2) for code in codes}
    harness = Harness(module, listing_codes=codes, nav=nav)
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        max_codes=7,
    )
    assert len(report["selected_codes"]) == 7


def test_time_budget_defers_probes_and_keeps_processed_accounting(
    module: ModuleType, tmp_path: Path
) -> None:
    codes = ("159767", "159768", "159770", "159776", "159782")
    nav = {code: _nav_rows(module, "2026-08-14", 2) for code in codes}
    target = {code: _target_rows(module, rows) for code, rows in nav.items()}
    harness = Harness(module, listing_codes=codes, nav=nav, target=target, probe_cost_seconds=100.0)
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        max_codes=5,
        time_budget_seconds=240.0,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    statuses = [row["status"] for row in report["outcomes"]]
    assert statuses[:2] == ["verified_read_only", "verified_read_only"]
    assert statuses[2:] == ["not_started_time_budget_exhausted"] * 3
    assert report["run_event"]["processed_codes"] == len(statuses) - statuses.count(
        "not_started_time_budget_exhausted"
    )
    assert len(harness.probe_calls) == 2


def test_generous_budget_counterfactual_probes_every_selected_code(
    module: ModuleType, tmp_path: Path
) -> None:
    codes = ("159767", "159768", "159770", "159776", "159782")
    nav = {code: _nav_rows(module, "2026-08-14", 2) for code in codes}
    target = {code: _target_rows(module, rows) for code, rows in nav.items()}
    harness = Harness(module, listing_codes=codes, nav=nav, target=target, probe_cost_seconds=100.0)
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        max_codes=5,
        time_budget_seconds=5_000.0,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    assert len(harness.probe_calls) == 5
    assert [row["status"] for row in report["outcomes"]] == ["verified_read_only"] * 5


def test_insufficient_budget_for_apply_defers_the_write_only(
    module: ModuleType, tmp_path: Path
) -> None:
    """A cheap probe plus an expensive apply must defer the write, not skip the probe."""
    codes = ("159767", "159768")
    nav = {code: _nav_rows(module, "2026-08-14", 3) for code in codes}
    harness = Harness(
        module,
        listing_codes=codes,
        nav=nav,
        target={},
        probe_cost_seconds=0.0,
        apply_cost_seconds=0.0,
    )
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        time_budget_seconds=module.PROBE_SECONDS_SEED + 5.0,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    statuses = [row["status"] for row in report["outcomes"]]
    assert statuses == [
        "not_applied_time_budget_insufficient",
        "not_applied_time_budget_insufficient",
    ]
    assert harness.write_calls == []
    assert report["run_event"]["budget_accounting"]["codes_deferred_not_applied"] == 2


# --- checkpoint idempotency -------------------------------------------------


def _seed_checkpoint(output_dir: Path, record: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "checkpoints.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def test_verified_checkpoint_is_skipped_on_the_next_run(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    output_dir = tmp_path / "state"
    _seed_checkpoint(
        output_dir,
        {
            "event": "checkpoint",
            "fund_code": "159767",
            "status": "verified_for_source_snapshot",
            "snapshot_sha256": "d" * 64,
            "verified_at": "2026-10-20T01:21:01+08:00",
        },
    )
    harness = Harness(module, nav=full_source)
    report = run_with(module, harness, output_dir, tmp_path / "report.json", probe=True)

    assert "159767" not in report["selected_codes"]
    assert report["plan"]["skipped"]["skip_verified"] >= 1
    assert "159767" not in harness.probe_calls


def test_missing_checkpoint_counterfactual_selects_the_same_code(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    harness = Harness(module, nav=full_source)
    report = run_with(
        module, harness, tmp_path / "state", tmp_path / "report.json", probe=True, shard_lookahead=0
    )
    assert "159767" in report["selected_codes"]


def test_apply_writes_a_checkpoint_and_the_next_run_skips_it(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    output_dir = tmp_path / "state"
    codes = tuple(full_source)
    harness = Harness(module, listing_codes=codes, nav=full_source, target={})
    manifest = write_protected_manifest(tmp_path / "protected.json")
    run_with(
        module,
        harness,
        output_dir,
        tmp_path / "report.json",
        probe=True,
        apply=True,
        max_codes=1,
        manifest=manifest,
    )
    checkpoints = (output_dir / "checkpoints.jsonl").read_text(encoding="utf-8").splitlines()
    assert checkpoints
    record = json.loads(checkpoints[-1])
    assert record["status"] == "verified_for_source_snapshot"
    assert record["fund_code"] == harness.probe_calls[-1]

    second = Harness(module, listing_codes=codes, nav=full_source, target=harness.target)
    report = run_with(
        module,
        second,
        output_dir,
        tmp_path / "report2.json",
        probe=True,
        apply=True,
        max_codes=1,
        manifest=manifest,
    )
    assert report["selected_codes"][0] != record["fund_code"]
    assert record["fund_code"] not in second.probe_calls


# --- quarantine -------------------------------------------------------------


def test_quarantined_code_stays_quarantined(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    output_dir = tmp_path / "state"
    _seed_checkpoint(
        output_dir,
        {
            "event": "checkpoint",
            "fund_code": "159001",
            "status": "verified_for_source_snapshot",
            "snapshot_sha256": "e" * 64,
        },
    )
    _seed_checkpoint(
        output_dir,
        {
            "event": "checkpoint_invalidated",
            "fund_code": "159001",
            "status": "invalidated_source_metric_not_nav",
            "reason": "source_product_metric_metadata_does_not_describe_unit_cumulative_nav",
            "invalidated_at": "2026-10-20T03:35:47+08:00",
            "evidence": {"metric_type": "income_per_100_shares"},
        },
    )
    # A later verify event must not un-quarantine a non-NAV metric.
    _seed_checkpoint(
        output_dir,
        {
            "event": "checkpoint",
            "fund_code": "159001",
            "status": "verified_for_source_snapshot",
            "snapshot_sha256": "f" * 64,
        },
    )
    harness = Harness(module, nav=full_source)
    report = run_with(module, harness, output_dir, tmp_path / "report.json", probe=True)

    assert "159001" not in report["selected_codes"]
    assert "159001" not in harness.probe_calls
    assert report["plan"]["quarantine_sticky_conflicts"] == 1
    assert report["run_event"]["semantic_quarantine_codes"] == ["159001"]


def test_semantic_non_nav_probe_is_quarantined_instead_of_written(
    module: ModuleType, tmp_path: Path
) -> None:
    output_dir = tmp_path / "state"
    harness = Harness(
        module,
        listing_codes=("159001",),
        nav={"159001": _nav_rows(module, "2026-08-14", 2)},
        target={},
        is_nav_metric=False,
    )
    report = run_with(
        module,
        harness,
        output_dir,
        tmp_path / "report.json",
        probe=True,
        apply=True,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    assert [row["status"] for row in report["outcomes"]] == ["source_semantic_rejected"]
    assert harness.write_calls == []
    events = (output_dir / "checkpoints.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["status"] for line in events] == ["invalidated_source_metric_not_nav"]

    rerun = Harness(module, listing_codes=("159001",), nav={"159001": []})
    second = run_with(rerun.module, rerun, output_dir, tmp_path / "report2.json", probe=True)
    assert second["selected_codes"] == []
    assert second["plan"]["skipped"]["skip_quarantined"] == 1


def test_unquarantined_counterfactual_probes_the_same_code(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    """Counterfactual: without the invalidation record, 159001 is a normal probe candidate."""
    harness = Harness(module, nav=full_source)
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        shard_lookahead=0,
        max_codes=5,
    )
    assert "159001" in report["selected_codes"]
    assert "159001" in harness.probe_calls


# --- snapshots and diffs ----------------------------------------------------


def test_snapshot_and_diff_hashes_are_stable_for_identical_source_content(
    module: ModuleType, tmp_path: Path
) -> None:
    probe = module.NavProbe(
        fund_code="159767",
        provider="pingzhongdata_verified",
        source_complete=True,
        rows=tuple(_nav_rows(module, "2026-08-14", 3)),
        first_nav_date="2026-08-14",
        last_nav_date="2026-08-16",
        observed_at="2026-10-27T15:00:00+08:00",
    )
    content = module.build_snapshot_content(probe, "unknown")
    digest = module.snapshot_sha256_of(content)
    first_path, first_digest = module.write_snapshot(
        tmp_path, content, captured_at="2026-10-27T15:00:00+08:00", sha256=digest
    )
    second_path, second_digest = module.write_snapshot(
        tmp_path, content, captured_at="2026-11-01T09:00:00+08:00", sha256=digest
    )

    assert first_digest == second_digest == digest
    assert first_path == second_path
    assert first_path.read_bytes() == second_path.read_bytes()
    payload = json.loads(gzip.decompress(first_path.read_bytes()).decode("utf-8"))
    assert set(payload) >= {
        "fund_code",
        "captured_at",
        "provider",
        "source_complete",
        "source_first_nav_date",
        "source_last_nav_date",
        "row_count",
        "business_keys_sha256",
        "values_sha256",
        "snapshot_sha256",
        "listing_boundary_status",
        "rows",
    }
    assert payload["captured_at"] == "2026-10-27T15:00:00+08:00"


def test_changed_nav_value_changes_the_digest_and_breaks_exact_match(
    module: ModuleType, tmp_path: Path
) -> None:
    """Counterfactual for the hash guard: an edited NAV value is not treated as a match."""
    rows = _nav_rows(module, "2026-08-14", 3)
    probe = module.NavProbe(
        fund_code="159767",
        provider="pingzhongdata_verified",
        source_complete=True,
        rows=tuple(rows),
        first_nav_date="2026-08-14",
        last_nav_date="2026-08-16",
        observed_at="2026-10-27T15:00:00+08:00",
    )
    digest = module.snapshot_sha256_of(module.build_snapshot_content(probe, "unknown"))
    edited = rows[:-1] + [
        module.NavRow(
            business_date=rows[-1].business_date,
            unit_nav=9.9,
            accumulated_nav=rows[-1].accumulated_nav,
            daily_growth=rows[-1].daily_growth,
        )
    ]
    edited_probe = module.NavProbe(
        fund_code="159767",
        provider="pingzhongdata_verified",
        source_complete=True,
        rows=tuple(edited),
        first_nav_date="2026-08-14",
        last_nav_date="2026-08-16",
        observed_at="2026-10-27T15:00:00+08:00",
    )
    edited_digest = module.snapshot_sha256_of(
        module.build_snapshot_content(edited_probe, "unknown")
    )
    assert edited_digest != digest

    matched = module.diff_summary(probe.rows, _target_rows(module, rows))
    drifted = module.diff_summary(probe.rows, _target_rows(module, edited))
    assert matched["exact_match"] is True
    assert drifted["exact_match"] is False
    assert drifted["value_mismatch_counts"]["unit_nav"] == 1

    diff_path = module.write_diff(
        tmp_path,
        "159767",
        digest,
        "before-apply",
        drifted,
        module.build_snapshot_content(probe, "unknown"),
    )
    diff_payload = json.loads(gzip.decompress(diff_path.read_bytes()).decode("utf-8"))
    assert diff_payload["summary"]["exact_match"] is False
    assert diff_payload["details"]["value_mismatches"]


# --- source limits, lag, no fabrication ------------------------------------


def test_unknown_first_nav_date_stays_reported_as_source_limited(
    module: ModuleType, tmp_path: Path
) -> None:
    rows = _nav_rows(module, "2026-08-14", 2)
    harness = Harness(
        module,
        listing_codes=("159767",),
        nav={"159767": rows},
        target={"159767": _target_rows(module, rows)},
        first_nav_date_unknown=True,
    )
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    outcome = report["outcomes"][0]
    assert outcome["listing_boundary_status"] == "SOURCE_LIMITED"
    assert outcome["source_first_nav_date"] is None
    assert "source_limited" in outcome["historical_scope_status"]
    assert report["full_history_complete"] is False


def test_incomplete_source_probe_never_fabricates_a_write(
    module: ModuleType, tmp_path: Path
) -> None:
    harness = Harness(
        module,
        listing_codes=("159767",),
        nav={"159767": _nav_rows(module, "2026-08-14", 3)},
        target={},
        source_complete=False,
    )
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    assert [row["status"] for row in report["outcomes"]] == ["pending_target_reconciliation"]
    assert harness.write_calls == []
    assert report["outcomes"][0]["reason"] == (
        "source_incomplete_probe_retention_limited_no_write_fabricated"
    )


def test_empty_nav_series_is_never_certified_as_verified(
    module: ModuleType, tmp_path: Path
) -> None:
    """An empty probe has no evidential value, so it cannot become a skipping checkpoint."""
    harness = Harness(module, listing_codes=("159999",), nav={}, target={})
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    outcome = report["outcomes"][0]
    assert outcome["status"] == "pending_target_reconciliation"
    assert outcome["reason"] == "source_probe_returned_no_rows_no_certification"
    assert harness.write_calls == []
    assert not (tmp_path / "state" / "checkpoints.jsonl").exists()


def test_lagged_nav_tail_is_reported_as_lag_not_as_missing_bars(
    module: ModuleType, tmp_path: Path
) -> None:
    rows = _nav_rows(module, "2026-10-19", 2, step_days=1)
    harness = Harness(
        module,
        listing_codes=("159767",),
        nav={"159767": rows},
        target={"159767": _target_rows(module, rows)},
    )
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    tail = report["outcomes"][0]["source_tail"]
    assert tail["source_last_nav_date"] == "2026-10-20"
    assert tail["requested_end_date"] == "2026-10-27"
    assert tail["calendar_day_lag"] == 7
    assert tail["freshness_proven"] is False
    assert tail["status"] == "lagged_publication_tail_not_evidence_of_missing_bars"
    # Only the dates the source published are kept; nothing is invented for the lagged days.
    assert report["outcomes"][0]["source_row_count"] == 2


def test_timeout_defers_without_a_fabricated_cooldown(module: ModuleType, tmp_path: Path) -> None:
    harness = Harness(
        module,
        listing_codes=("159767",),
        nav={"159767": _nav_rows(module, "2026-08-14", 2)},
        timeout_codes=("159767",),
    )
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    assert [row["status"] for row in report["outcomes"]] == ["source_probe_timeout"]
    assert harness.write_calls == []
    assert not (tmp_path / "state" / "checkpoints.jsonl").exists()


# --- shard non-collision ----------------------------------------------------


def make_shard_state(
    output_dir: Path, shard: str, cursor_code: str, in_flight: tuple[str, ...]
) -> Path:
    shard_dir = output_dir / shard
    (shard_dir / "runs").mkdir(parents=True, exist_ok=True)
    (shard_dir / "cursor.json").write_text(
        json.dumps({"last_fund_code": cursor_code, "updated_at": "2026-10-27T08:56:45+08:00"}),
        encoding="utf-8",
    )
    (shard_dir / "runs" / "20261027T005603.json").write_text(
        json.dumps({"selected_codes": list(in_flight)}), encoding="utf-8"
    )
    return shard_dir


def test_sibling_shard_window_is_excluded(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    output_dir = tmp_path / "state"
    shard_dir = make_shard_state(output_dir, "shard-0", "159767", ("159768",))

    harness = Harness(
        module,
        listing_codes=("159767", "159768", "159770"),
        nav=full_source,
    )
    report = run_with(
        module,
        harness,
        output_dir,
        tmp_path / "report.json",
        probe=True,
        max_codes=5,
        shard_lookahead=2,
    )
    assert "159768" not in report["selected_codes"], "in-flight shard code must not be probed"
    assert "159770" not in report["selected_codes"], "shard forward window must not be probed"
    # The sibling's state stays untouched.
    assert sorted(path.name for path in shard_dir.iterdir()) == ["cursor.json", "runs"]
    assert json.loads((shard_dir / "cursor.json").read_text())["last_fund_code"] == "159767"


def test_shard_guard_off_counterfactual_selects_the_shards_code(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    output_dir = tmp_path / "state"
    make_shard_state(output_dir, "shard-0", "159767", ("159768",))
    harness = Harness(module, listing_codes=("159767", "159768", "159770"), nav=full_source)
    report = run_with(
        module,
        harness,
        output_dir,
        tmp_path / "report.json",
        probe=True,
        skip_shard_guard=True,
    )
    assert "159768" in report["selected_codes"]
    assert report["run_event"]["sibling_shard_guard"]["enabled"] is False


def test_apply_never_writes_inside_a_shard_directory(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    output_dir = tmp_path / "state"
    shard_dir = make_shard_state(output_dir, "shard-2", "510300", ("510310",))
    before = {path.name: path.read_bytes() for path in shard_dir.rglob("*") if path.is_file()}
    harness = Harness(module, nav=full_source, target={})
    run_with(
        module,
        harness,
        output_dir,
        tmp_path / "report.json",
        probe=True,
        apply=True,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    after = {path.name: path.read_bytes() for path in shard_dir.rglob("*") if path.is_file()}
    assert before == after
    assert sorted(path.name for path in output_dir.iterdir() if path.is_file()) != []


# --- resumability -----------------------------------------------------------


def test_mid_batch_failure_resumes_without_reprobing_verified_codes(
    module: ModuleType, tmp_path: Path
) -> None:
    codes = ("159767", "159768", "159770")
    nav = {code: _nav_rows(module, "2026-08-14", 2) for code in codes}
    output_dir = tmp_path / "state"
    manifest = write_protected_manifest(tmp_path / "protected.json")

    first = Harness(module, listing_codes=codes, nav=nav, target={}, fail_codes=("159770",))
    report = run_with(
        module,
        first,
        output_dir,
        tmp_path / "report.json",
        probe=True,
        apply=True,
        max_codes=3,
        manifest=manifest,
    )
    statuses = [row["status"] for row in report["outcomes"]]
    assert statuses == ["applied_and_verified", "applied_and_verified", "source_or_apply_error"]
    cursor = json.loads((output_dir / "cursor.json").read_text())
    assert cursor["last_fund_code"] == "159770"
    assert len(first.write_calls) == 2

    second = Harness(module, listing_codes=codes, nav=nav, target=first.target)
    resumed = run_with(
        module,
        second,
        output_dir,
        tmp_path / "report2.json",
        probe=True,
        apply=True,
        max_codes=3,
        manifest=manifest,
    )
    assert resumed["selected_codes"] == ["159770"], "the two verified codes must not be re-probed"
    assert [row["status"] for row in resumed["outcomes"]] == ["applied_and_verified"]
    assert second.probe_calls == ["159770"]


# --- protected legacy scope -------------------------------------------------


def test_protected_scope_drift_blocks_the_success_claim(module: ModuleType, tmp_path: Path) -> None:
    rows = _nav_rows(module, "2026-08-14", 2)
    harness = Harness(
        module,
        listing_codes=("159767",),
        nav={"159767": rows},
        target={},
        protected_changes_after_write=True,
    )
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    outcome = report["outcomes"][0]
    assert outcome["status"] == "protected_legacy_scope_changed_after_managed"
    assert "scheduler_execution" not in outcome
    assert not (tmp_path / "state" / "checkpoints.jsonl").exists()


def test_missing_protected_manifest_refuses_the_write(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    """Counterfactual for the protected-scope guard: without the manifest, apply is refused."""
    harness = Harness(module, listing_codes=("159767",), nav=full_source, target={})
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        max_codes=1,
    )
    assert [row["status"] for row in report["outcomes"]] == [
        "protected_legacy_baseline_read_failed"
    ]
    assert harness.write_calls == []


def test_stable_protected_scope_counterfactual_applies_and_verifies(
    module: ModuleType, tmp_path: Path
) -> None:
    rows = _nav_rows(module, "2026-08-14", 2)
    harness = Harness(module, listing_codes=("159767",), nav={"159767": rows}, target={})
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    outcome = report["outcomes"][0]
    assert outcome["status"] == "applied_and_verified"
    assert outcome["scheduler_execution"]["status"] == "completed"
    check = outcome["protected_legacy_checks"][0]
    assert check["status"] == "before_and_after_match"
    assert set(check["before"]) == set(WORKER_FINGERPRINT_KEYS)


# --- report shape -----------------------------------------------------------


def test_apply_report_matches_the_worker_parse_contract(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    harness = Harness(module, nav=full_source, target={})
    report = run_with(
        module,
        harness,
        tmp_path / "state",
        tmp_path / "report.json",
        probe=True,
        apply=True,
        max_codes=3,
        time_budget_seconds=240.0,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )

    assert report["schema_version"] == "etf-nav-controller-run-report-v1"
    assert report["report_type"] == "etf_nav_controller_run"
    assert report["contract_problems"] == []
    for key in WORKER_TOP_LEVEL_KEYS:
        assert key in report, key
    run_event = report["run_event"]
    for key in WORKER_RUN_EVENT_KEYS:
        assert key in run_event, key
    for key in WORKER_PROTECTION_KEYS:
        assert key in run_event["protected_legacy_scope"], key

    assert run_event["mode"] == "apply"
    assert run_event["apply_enabled"] is True
    assert run_event["network_used"] is True
    assert run_event["full_history_complete"] is False
    assert run_event["max_codes"] == 3
    assert run_event["time_budget_seconds"] == 240.0
    assert run_event["probe_ready"] is True
    snapshot = run_event["current_sina_snapshot"]
    assert snapshot["complete"] is True
    assert snapshot["source_row_count"] > 0
    assert 0 < snapshot["unique_code_count"] <= snapshot["source_row_count"]
    assert run_event["current_sina_snapshot_path"]
    assert run_event["sina_refresh_error"] is None
    assert report["fresh_sina_probe_ready"] is True

    assert report["selected_codes"] == run_event["selected_codes"]
    assert report["selected_listing_evidence"] == run_event["selected_listing_evidence"]
    assert len(run_event["selected_listing_evidence"]) == len(run_event["selected_codes"])
    for evidence in run_event["selected_listing_evidence"]:
        assert evidence["eligible_for_nav_probe"] is True
        assert evidence["lifecycle_identity_conflict"] is False
        assert evidence["product_identity_status"] in {
            "verified_by_sina_etf_node",
            "verified_by_etf_daily_master",
            "verified_by_reviewed_lifecycle_manifest",
        }
    for outcome in report["outcomes"]:
        assert outcome["event"] == "nav_probe"
        assert outcome["run_id"] == report["run_id"]
        assert outcome["fund_code"] in report["selected_codes"]
    assert len({row["fund_code"] for row in report["outcomes"]}) == len(report["outcomes"])


def test_report_is_written_atomically_at_the_requested_path(
    module: ModuleType, tmp_path: Path, full_source: dict[str, list[Any]]
) -> None:
    harness = Harness(module, nav=full_source, target={})
    report_path = tmp_path / "runs" / "etf-report.json"
    run_with(
        module,
        harness,
        tmp_path / "state",
        report_path,
        probe=True,
        apply=True,
        max_codes=1,
        manifest=write_protected_manifest(tmp_path / "protected.json"),
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["report_path"] == str(report_path)
    assert not list(report_path.parent.glob("*.tmp"))


# --- CLI --------------------------------------------------------------------


def test_cli_without_apply_writes_only_the_report(module: ModuleType, tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    codes = ("159767", "159768")
    rows = [
        [row.business_date, row.unit_nav, row.accumulated_nav, row.daily_growth]
        for row in _nav_rows(module, "2026-08-14", 2)
    ]
    (fixture / "listing.json").write_text(
        json.dumps(
            {
                "observed_at": "2026-10-27T15:00:00+08:00",
                "source": "fixture_etf_node",
                "complete": True,
                "rows": [{"fund_code": code, "fund_name": f"ETF {code}"} for code in codes],
            }
        ),
        encoding="utf-8",
    )
    (fixture / "nav").mkdir()
    for code in codes:
        (fixture / "nav" / f"{code}.json").write_text(
            json.dumps(
                {
                    "provider": "pingzhongdata_verified",
                    "source_complete": True,
                    "first_nav_date": "2026-08-14",
                    "last_nav_date": "2026-08-15",
                    "observed_at": "2026-10-27T15:00:00+08:00",
                    "rows": rows,
                }
            ),
            encoding="utf-8",
        )
    (fixture / "target.json").write_text(json.dumps(dict.fromkeys(codes, rows)), encoding="utf-8")
    (fixture / "protected.json").write_text(json.dumps({}), encoding="utf-8")

    output_dir = tmp_path / "state"
    report_path = tmp_path / "report.json"
    exit_code = module.main(
        [
            "--probe",
            "--max-codes",
            "2",
            "--time-budget-seconds",
            "240",
            "--output-dir",
            str(output_dir),
            "--report",
            str(report_path),
            "--fixture-dir",
            str(fixture),
        ]
    )
    assert exit_code == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["run_event"]["mode"] == "probe"
    assert payload["selected_codes"] == list(codes)
    assert not (output_dir / "checkpoints.jsonl").exists()
    assert not (output_dir / "controller.lock").exists()
    assert not (output_dir / "source-snapshots").exists()


def test_cli_apply_writes_state_through_the_fixture_adapters(
    tmp_path: Path, module: ModuleType
) -> None:
    fixture = _write_cli_fixture(tmp_path, module)
    output_dir = tmp_path / "state"
    report_path = tmp_path / "report.json"
    manifest = write_protected_manifest(tmp_path / "protected-manifest.json")

    exit_code = module.main(
        [
            "--probe",
            "--apply",
            "--max-codes",
            "2",
            "--time-budget-seconds",
            "240",
            "--output-dir",
            str(output_dir),
            "--report",
            str(report_path),
            "--protected-scope-manifest",
            str(manifest),
            "--fixture-dir",
            str(fixture),
        ]
    )
    assert exit_code == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["run_event"]["mode"] == "apply"
    assert payload["contract_problems"] == []
    assert [row["status"] for row in payload["outcomes"]] == [
        "applied_and_verified",
        "applied_and_verified",
    ]
    protection = payload["run_event"]["protected_legacy_scope"]
    assert protection["codes_count"] == 1
    assert protection["expected_nav_rows"] == 60329
    assert protection["expected_cache_sha256"] == "c" * 64
    assert all(check["status"] == "before_and_after_match" for check in protection["checks"])
    assert (output_dir / "checkpoints.jsonl").is_file()
    assert (output_dir / "cursor.json").is_file()
    assert (output_dir / "sina-listing-snapshots").is_dir()
    assert list((output_dir / "source-snapshots").glob("*.json.gz"))
    assert list((output_dir / "source-snapshots" / "diffs").glob("*before-apply.diff.json.gz"))


def test_cli_held_lock_produces_a_deferred_report(tmp_path: Path, module: ModuleType) -> None:
    fixture = _write_cli_fixture(tmp_path, module)
    output_dir = tmp_path / "state"
    output_dir.mkdir(parents=True)
    lock_path = output_dir / "controller.lock"
    with lock_path.open("a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        exit_code = module.main(
            [
                "--probe",
                "--apply",
                "--output-dir",
                str(output_dir),
                "--report",
                str(tmp_path / "report.json"),
                "--protected-scope-manifest",
                str(write_protected_manifest(tmp_path / "protected-manifest.json")),
                "--fixture-dir",
                str(fixture),
            ]
        )
    assert exit_code == 0
    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert payload["outcomes"] == []
    assert payload["run_event"]["processed_codes"] == 0
    assert "lock" in str(payload["run_event"]["sina_refresh_error"])
    assert not (output_dir / "checkpoints.jsonl").exists()


def _write_cli_fixture(tmp_path: Path, module: ModuleType) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir(exist_ok=True)
    codes = ("159767", "159768")
    rows = [
        [row.business_date, row.unit_nav, row.accumulated_nav, row.daily_growth]
        for row in _nav_rows(module, "2026-08-14", 2)
    ]
    (fixture / "listing.json").write_text(
        json.dumps(
            {
                "observed_at": "2026-10-27T15:00:00+08:00",
                "source": "fixture_etf_node",
                "complete": True,
                "rows": [{"fund_code": code, "fund_name": f"ETF {code}"} for code in codes],
            }
        ),
        encoding="utf-8",
    )
    (fixture / "nav").mkdir(exist_ok=True)
    for code in codes:
        (fixture / "nav" / f"{code}.json").write_text(
            json.dumps(
                {
                    "provider": "pingzhongdata_verified",
                    "source_complete": True,
                    "first_nav_date": "2026-08-14",
                    "last_nav_date": "2026-08-15",
                    "observed_at": "2026-10-27T15:00:00+08:00",
                    "rows": rows,
                }
            ),
            encoding="utf-8",
        )
    (fixture / "target.json").write_text(json.dumps({}), encoding="utf-8")
    (fixture / "protected.json").write_text(
        json.dumps(
            {
                "protected_scope_codes_count": 1,
                "protected_scope_codes_sha256": "a" * 64,
                "protected_legacy_nav_rows": 60329,
                "protected_legacy_nav_sha256": "b" * 64,
                "protected_cache_rows": 357,
                "protected_cache_sha256": "c" * 64,
            }
        ),
        encoding="utf-8",
    )
    return fixture


def test_script_entrypoint_runs_as_the_worker_invokes_it(tmp_path: Path) -> None:
    """A subprocess guard: the worker shells out, so the file must be executable as a script."""
    fixture = _write_cli_fixture(tmp_path, _controller())
    report = tmp_path / "report.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--probe",
            "--max-codes",
            "2",
            "--time-budget-seconds",
            "240",
            "--output-dir",
            str(tmp_path / "state"),
            "--report",
            str(report),
            "--fixture-dir",
            str(fixture),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert report.is_file(), "the controller must always leave a readable per-run report"
    assert not (tmp_path / "state" / "checkpoints.jsonl").exists()


def test_live_adapters_fail_closed_without_any_state_evidence(tmp_path: Path) -> None:
    """Every live adapter is NOT_RUN: an apply attempt must not fabricate probe or checkpoint proof."""
    report = tmp_path / "report.json"
    state = tmp_path / "state"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--probe",
            "--apply",
            "--output-dir",
            str(state),
            "--report",
            str(report),
            "--allow-live-sources",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    run_event = payload["run_event"]
    assert run_event["mode"] == "apply"
    assert run_event["network_used"] is True
    assert run_event["probe_ready"] is False
    assert payload["outcomes"] == []
    assert str(run_event["sina_refresh_error"]).startswith("NotRunError")
    assert not (state / "checkpoints.jsonl").exists()
    assert not (state / "source-snapshots").exists()


# --- pure helper guards -----------------------------------------------------


def test_checkpoint_merge_keeps_terminal_and_consolidated_records(module: ModuleType) -> None:
    lines = [
        json.dumps(
            {"event": "checkpoint", "fund_code": "511280", "status": "archived_history_complete"}
        ),
        json.dumps(
            {
                "event": "checkpoint",
                "fund_code": "159767",
                "status": "verified_for_source_snapshot",
                "consolidated_at": "2026-10-21T00:00:00+08:00",
            }
        ),
        "{ not json",
    ]
    merge = module.merge_checkpoint_events(lines)
    assert merge.verified_codes == {"511280", "159767"}
    assert merge.malformed_lines == 1


def test_pingzhongdata_parser_keeps_published_dates_only(module: ModuleType) -> None:
    script = (
        "var Data_netWorthTrend = ["
        '{"x":1735660800000,"y":1.2345},{"x":1735747200000,"y":1.2400}];\n'
        "var Data_ACWorthTrend = [[1735660800000,2.0]];\n"
    )
    rows = module.parse_pingzhongdata_rows(script)
    assert [row.business_date for row in rows] == ["2025-01-01", "2025-01-02"]
    assert rows[0].accumulated_nav == 2.0
    # A date the cumulative series does not publish stays unknown rather than filled in.
    assert rows[1].accumulated_nav is None
    assert module.parse_pingzhongdata_rows("var unrelated = 1;") == []
