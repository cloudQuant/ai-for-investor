from __future__ import annotations

import fcntl
import hashlib
import json
import os
import signal
import sys
from pathlib import Path

import pytest

from scripts.ops import run_full_history_recovery_worker as worker


def _runtime_tree(root: Path) -> worker.WorkerPaths:
    paths = worker.WorkerPaths.for_repo(root)
    for path in (
        paths.python,
        paths.stock_script,
        paths.crypto_script,
        paths.bond_script,
        paths.etf_script,
        paths.option_script,
        paths.crypto_manifest,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")
    paths.python.chmod(0o755)
    return paths


def _write_report_from_command(command: list[str], report: dict[str, object]) -> Path:
    output_flag = "--report" if "--report" in command else "--output"
    report_path = Path(command[command.index(output_flag) + 1])
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report_path


def _valid_etf_run_report(*, status: str = "verified_read_only") -> dict[str, object]:
    run_id = "0123456789abcdef0123456789abcdef"
    run_event = {
        "run_id": run_id,
        "mode": "apply",
        "apply_enabled": True,
        "network_used": True,
        "probe_ready": True,
        "max_codes": worker.ETF_MAX_CODES,
        "time_budget_seconds": worker.ETF_BATCH_SECONDS,
        "full_history_complete": False,
        "sina_refresh_error": None,
        "current_sina_snapshot": {
            "complete": True,
            "source_row_count": 1,
            "unique_code_count": 1,
        },
        "current_sina_snapshot_path": "sina-listing-snapshot.json.gz",
        "selected_codes": ["510300"],
        "selected_listing_evidence": [
            {
                "fund_code": "510300",
                "eligible_for_nav_probe": True,
                "product_identity_status": "verified_by_sina_etf_node",
                "current_sina_node_member": True,
                "reviewed_lifecycle": False,
                "lifecycle_identity_conflict": False,
                "listing_boundary_status": "unknown",
            }
        ],
        "processed_codes": 1,
        "protected_legacy_scope": {
            "codes_count": worker.ETF_PROTECTED_SCOPE["codes_count"],
            "codes_sha256": worker.ETF_PROTECTED_SCOPE["codes_sha256"],
            "expected_nav_rows": worker.ETF_PROTECTED_SCOPE["nav_rows"],
            "expected_nav_sha256": worker.ETF_PROTECTED_SCOPE["nav_sha256"],
            "expected_cache_rows": worker.ETF_PROTECTED_SCOPE["cache_rows"],
            "expected_cache_sha256": worker.ETF_PROTECTED_SCOPE["cache_sha256"],
            "checks": [],
        },
    }
    outcomes = [
        {
            "event": "nav_probe",
            "run_id": run_id,
            "fund_code": "510300",
            "status": status,
            "provider": "pingzhongdata_verified",
            "source_complete": True,
            "source_snapshot_path": "immutable-source-snapshot.json.gz",
            "business_keys_sha256": "a" * 64,
            "values_sha256": "b" * 64,
            "snapshot_sha256": "c" * 64,
            "diff_after": {"exact_match": True},
            "scheduler_execution": None,
        }
    ]
    return {
        "schema_version": "etf-nav-controller-run-report-v1",
        "report_type": "etf_nav_controller_run",
        "run_id": run_id,
        "run_event": run_event,
        "outcomes": outcomes,
        "selected_codes": ["510300"],
        "selected_listing_evidence": run_event["selected_listing_evidence"],
        "fresh_sina_probe_ready": True,
        "full_history_complete": False,
    }


def test_default_plan_is_read_only_and_has_exact_batch_contracts(tmp_path: Path) -> None:
    paths = worker.WorkerPaths.for_repo(tmp_path)

    result = worker._build_plan(paths)

    assert result["read_only"] is True
    assert result["source_or_database_calls"] == 0
    assert result["scheduler_started"] is False
    assert result["next_asset"] == "stock"
    assert set(result["commands"]) == {"stock", "crypto"}
    stock = result["commands"]["stock"]
    crypto = result["commands"]["crypto"]
    assert stock[stock.index("--max-codes") + 1] == "10"
    assert stock[stock.index("--max-minutes") + 1] == "6.0"
    assert stock[stock.index("--source-timeout-seconds") + 1] == "45"
    assert Path(stock[stock.index("--progress") + 1]) == paths.stock_progress
    assert crypto[crypto.index("--intervals") + 1] == "1h"
    assert crypto[crypto.index("--max-shards") + 1] == "25"
    assert crypto[crypto.index("--max-minutes") + 1] == "4.0"
    assert crypto[crypto.index("--pause-seconds") + 1] == "5.0"
    assert crypto[crypto.index("--timeout-seconds") + 1] == "120"
    assert Path(crypto[crypto.index("--progress-file") + 1]) == paths.crypto_progress
    assert result["budgets"]["stock"]["outer_wall_seconds"] == 380
    assert result["budgets"]["crypto_hourly"]["outer_wall_seconds"] == 260
    assert not paths.cursor_file.exists()
    assert not paths.runs_dir.exists()


def test_plan_uses_saved_cursor_without_mutating_it(tmp_path: Path) -> None:
    paths = worker.WorkerPaths.for_repo(tmp_path)
    paths.worker_dir.mkdir(parents=True)
    paths.cursor_file.write_text(
        json.dumps({"schema_version": 1, "next_asset": "crypto"}), encoding="utf-8"
    )

    result = worker._build_plan(paths)

    assert result["next_asset"] == "crypto"
    assert result["cursor_status"] == "valid"
    assert json.loads(paths.cursor_file.read_text(encoding="utf-8"))["next_asset"] == "crypto"


def test_four_asset_plan_preview_is_read_only_and_exposes_exact_budgets(tmp_path: Path) -> None:
    paths = worker.WorkerPaths.for_repo(tmp_path)
    paths.worker_dir.mkdir(parents=True)
    old_cursor = {"schema_version": 1, "next_asset": "crypto", "last_status": "old"}
    paths.cursor_file.write_text(json.dumps(old_cursor), encoding="utf-8")

    result = worker._build_plan(paths, worker.FOUR_ASSET_ORDER)

    assert result["assets"] == ["stock", "crypto", "bond", "etf"]
    assert result["cursor_status"] == "valid_v1_migration_preview"
    assert result["cursor_migration_preview"] == {
        "from_schema_version": 1,
        "to_schema_version": 2,
        "preserved_next_asset": "crypto",
        "rotation_order": ["stock", "crypto", "bond", "etf"],
        "plan_writes_cursor": False,
    }
    assert set(result["commands"]) == set(worker.FOUR_ASSET_ORDER)
    bond = result["commands"]["bond"]
    assert Path(bond[1]) == paths.bond_script
    assert bond[bond.index("--max-codes") + 1] == "5"
    assert bond[bond.index("--time-budget-seconds") + 1] == "240"
    assert bond[bond.index("--source-timeout-seconds") + 1] == "45"
    assert Path(bond[bond.index("--progress-file") + 1]) == paths.bond_progress
    assert Path(bond[bond.index("--snapshot-dir") + 1]) == paths.bond_snapshots
    etf = result["commands"]["etf"]
    assert Path(etf[1]) == paths.etf_script
    assert "--probe" in etf
    assert etf[etf.index("--apply")] == "--apply"
    assert etf[etf.index("--max-codes") + 1] == "5"
    assert etf[etf.index("--time-budget-seconds") + 1] == "240"
    assert Path(etf[etf.index("--output-dir") + 1]) == paths.etf_output_dir
    assert Path(etf[etf.index("--report") + 1]).parent.name == "<RUN_ID>"
    assert result["budgets"]["bond_convertible"]["outer_wall_seconds"] == 260
    assert result["budgets"]["etf_nav"]["outer_wall_seconds"] == 260
    assert result["budgets"]["etf_nav"]["fresh_sina_listing_probe_outside_scheduler_gate"] is True
    assert json.loads(paths.cursor_file.read_text(encoding="utf-8")) == old_cursor


def test_assets_accept_only_the_known_fixed_registries() -> None:
    assert worker._validate_asset_order(worker.DEFAULT_ASSETS) == worker.DEFAULT_ASSETS
    assert worker._validate_asset_order(worker.FOUR_ASSET_ORDER) == worker.FOUR_ASSET_ORDER
    assert worker._validate_asset_order(worker.FIVE_ASSET_ORDER) == worker.FIVE_ASSET_ORDER
    with pytest.raises(ValueError, match="duplicates"):
        worker._validate_asset_order(("stock", "crypto", "bond", "bond"))
    with pytest.raises(ValueError, match="fixed order"):
        worker._validate_asset_order(("crypto", "stock"))
    with pytest.raises(ValueError, match="fixed order"):
        worker._validate_asset_order(("stock", "crypto", "etf"))
    with pytest.raises(ValueError, match="fixed order"):
        worker._validate_asset_order(("stock", "crypto", "bond", "option", "etf"))


def test_four_asset_apply_migrates_v1_cursor_without_losing_next_asset(tmp_path: Path) -> None:
    paths = _runtime_tree(tmp_path)
    paths.worker_dir.mkdir(parents=True, exist_ok=True)
    paths.cursor_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "next_asset": "crypto",
                "last_asset": "stock",
                "last_run_id": "previous-run",
            }
        ),
        encoding="utf-8",
    )
    seen: list[str] = []

    def fake_executor(
        command: list[str], _run_dir: Path, timeout_seconds: int
    ) -> worker.ProcessResult:
        migrated = json.loads(paths.cursor_file.read_text(encoding="utf-8"))
        assert migrated["schema_version"] == 2
        assert migrated["rotation_order"] == list(worker.FOUR_ASSET_ORDER)
        assert migrated["next_asset"] == "bond"
        assert migrated["last_asset"] == "crypto"
        seen.append(command[1])
        _write_report_from_command(
            command,
            {
                "report_type": "crypto-hourly-full-history-v1",
                "apply_summary": {"open": 0},
                "apply": [],
            },
        )
        assert timeout_seconds == 260
        return worker.ProcessResult(returncode=0)

    result = worker._run_apply(paths, assets=worker.FOUR_ASSET_ORDER, executor=fake_executor)
    final_cursor = json.loads(paths.cursor_file.read_text(encoding="utf-8"))

    assert result["asset"] == "crypto"
    assert result["status"] == "completed"
    assert seen == [str(paths.crypto_script)]
    assert final_cursor["schema_version"] == 2
    assert final_cursor["rotation_order"] == list(worker.FOUR_ASSET_ORDER)
    assert final_cursor["next_asset"] == "bond"


def test_four_asset_rotation_visits_each_asset_once_in_fixed_order(tmp_path: Path) -> None:
    paths = _runtime_tree(tmp_path)
    seen: list[str] = []

    def fake_executor(
        command: list[str], _run_dir: Path, timeout_seconds: int
    ) -> worker.ProcessResult:
        script_path = command[1]
        asset = next(
            name
            for name, script in (
                ("stock", paths.stock_script),
                ("crypto", paths.crypto_script),
                ("bond", paths.bond_script),
                ("etf", paths.etf_script),
            )
            if script_path == str(script)
        )
        seen.append(asset)
        cursor = json.loads(paths.cursor_file.read_text(encoding="utf-8"))
        expected_next = worker.FOUR_ASSET_ORDER[
            (worker.FOUR_ASSET_ORDER.index(asset) + 1) % len(worker.FOUR_ASSET_ORDER)
        ]
        assert cursor["schema_version"] == 2
        assert cursor["rotation_order"] == list(worker.FOUR_ASSET_ORDER)
        assert cursor["next_asset"] == expected_next
        if asset == "stock":
            _write_report_from_command(
                command, {"mode": "apply", "outcomes": [{"status": "scheduled_verified"}]}
            )
            return worker.ProcessResult(returncode=0)
        if asset == "crypto":
            _write_report_from_command(command, {"apply_summary": {"open": 0}, "apply": []})
            return worker.ProcessResult(returncode=0)
        if asset == "bond":
            _write_report_from_command(
                command,
                {
                    "report_type": "bond-convertible-history-controller-v1",
                    "mode": "managed_bounded_convertible_history_reconciliation",
                    "max_codes": worker.BOND_MAX_CODES,
                    "time_budget_seconds": worker.BOND_BATCH_SECONDS,
                    "source_timeout_seconds_max": worker.BOND_SOURCE_TIMEOUT_SECONDS,
                    "outcomes": [{"status": "verified_unchanged"}],
                },
            )
            assert timeout_seconds == 260
            return worker.ProcessResult(returncode=0)
        _write_report_from_command(command, _valid_etf_run_report())
        assert timeout_seconds == 260
        return worker.ProcessResult(returncode=0)

    results = [
        worker._run_apply(paths, assets=worker.FOUR_ASSET_ORDER, executor=fake_executor)
        for _ in range(4)
    ]

    assert seen == list(worker.FOUR_ASSET_ORDER)
    assert [result["asset"] for result in results] == list(worker.FOUR_ASSET_ORDER)
    assert results[2]["status"] == "batch_reconciled_history_incomplete"
    assert results[2]["full_history_complete"] is False
    assert results[3]["status"] == "batch_reconciled_history_incomplete"
    assert results[3]["full_history_complete"] is False
    assert json.loads(paths.cursor_file.read_text(encoding="utf-8"))["next_asset"] == "stock"


def test_invalid_cursor_fails_closed_without_resetting_state(tmp_path: Path) -> None:
    paths = worker.WorkerPaths.for_repo(tmp_path)
    paths.worker_dir.mkdir(parents=True)
    paths.cursor_file.write_text("[]\n", encoding="utf-8")

    plan = worker._build_plan(paths)
    result = worker._run_apply(
        paths, executor=lambda *_args: (_ for _ in ()).throw(AssertionError())
    )

    assert plan["cursor_status"] == "invalid"
    assert plan["exit_code"] == 2
    assert result["status"] == "attention_required"
    assert result["batch_started"] is False
    assert paths.cursor_file.read_text(encoding="utf-8") == "[]\n"


def test_unknown_v2_cursor_is_not_downgraded_by_default_registry(tmp_path: Path) -> None:
    paths = _runtime_tree(tmp_path)
    paths.worker_dir.mkdir(parents=True, exist_ok=True)
    original = {
        "schema_version": 2,
        "rotation_order": list(worker.FOUR_ASSET_ORDER),
        "next_asset": "bond",
    }
    paths.cursor_file.write_text(json.dumps(original), encoding="utf-8")

    result = worker._run_apply(
        paths,
        executor=lambda *_args: (_ for _ in ()).throw(AssertionError("must fail before CLI")),
    )

    assert result["status"] == "attention_required"
    assert result["batch_started"] is False
    assert "reserved for the opt-in" in result["error"]
    assert json.loads(paths.cursor_file.read_text(encoding="utf-8")) == original


def test_unrecognized_cursor_fields_or_rotation_order_fail_closed(tmp_path: Path) -> None:
    paths = worker.WorkerPaths.for_repo(tmp_path)
    paths.worker_dir.mkdir(parents=True)
    invalid_payloads = [
        {"schema_version": 1, "next_asset": "stock", "mystery": "keep"},
        {
            "schema_version": 2,
            "rotation_order": ["stock", "crypto", "etf", "bond"],
            "next_asset": "stock",
        },
        {
            "schema_version": 2,
            "rotation_order": list(worker.FOUR_ASSET_ORDER),
            "next_asset": "stock",
            "unknown_state": True,
        },
    ]
    for payload in invalid_payloads:
        raw = json.dumps(payload)
        paths.cursor_file.write_text(raw, encoding="utf-8")
        result = worker._build_plan(paths, worker.FOUR_ASSET_ORDER)
        assert result["exit_code"] == 2
        assert result["cursor_status"] == "invalid"
        assert paths.cursor_file.read_text(encoding="utf-8") == raw


def test_cursor_rotates_before_one_stock_batch_then_crypto_batch(tmp_path: Path) -> None:
    paths = _runtime_tree(tmp_path)
    seen: list[tuple[str, list[str], int]] = []

    def fake_executor(
        command: list[str], run_dir: Path, timeout_seconds: int
    ) -> worker.ProcessResult:
        cursor = json.loads(paths.cursor_file.read_text(encoding="utf-8"))
        asset = "stock" if "stock_full_history_controller.py" in command[1] else "crypto"
        seen.append((asset, command, timeout_seconds))
        if asset == "stock":
            assert cursor["next_asset"] == "crypto"
            _write_report_from_command(
                command,
                {"mode": "apply", "outcomes": [{"status": "source_failed"}]},
            )
            return worker.ProcessResult(returncode=2)
        assert cursor["next_asset"] == "stock"
        _write_report_from_command(
            command,
            {
                "apply_summary": {"open": 1},
                "apply": [{"status": "unresolved_coverage", "remaining_missing_bars": 6}],
            },
        )
        return worker.ProcessResult(returncode=1)

    first = worker._run_apply(paths, executor=fake_executor)
    second = worker._run_apply(paths, executor=fake_executor)

    assert first["asset"] == "stock"
    assert first["status"] == "source_failed_retryable"
    assert first["exit_code"] == 0
    assert first["source_failure_recorded"] is True
    assert second["asset"] == "crypto"
    assert second["status"] == "incomplete_open_shards"
    assert second["exit_code"] == 0
    assert second["source_failure_recorded"] is False
    assert seen[0][2] == 380
    assert seen[1][2] == 260
    assert json.loads(paths.cursor_file.read_text(encoding="utf-8"))["next_asset"] == "stock"
    assert len(list(paths.runs_dir.iterdir())) == 2


def test_concurrent_invocation_is_a_successful_skip_without_cursor_change(tmp_path: Path) -> None:
    paths = _runtime_tree(tmp_path)
    holder = worker._acquire_lock(paths.lock_file)
    assert holder is not None
    try:
        result = worker._run_apply(
            paths,
            executor=lambda *_args: (_ for _ in ()).throw(AssertionError("must not run CLI")),
        )
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)

    assert result["status"] == "skipped_lock_busy"
    assert result["exit_code"] == 0
    assert result["cursor_advanced"] is False
    assert not paths.cursor_file.exists()
    assert not paths.runs_dir.exists()


def test_outer_timeout_is_uncertain_write_not_source_failure(tmp_path: Path) -> None:
    paths = _runtime_tree(tmp_path)

    result = worker._run_apply(
        paths,
        executor=lambda *_args: worker.ProcessResult(returncode=-15, timed_out=True),
    )

    assert result["status"] == "timed_out_write_possible"
    assert result["attention_required"] is True
    assert result["write_possible"] is True
    assert result["source_failure_recorded"] is False
    assert not paths.stock_progress.exists()
    run_record = json.loads((Path(result["run_directory"]) / "run.json").read_text())
    assert run_record["write_possible"] is True
    assert run_record["source_failure_recorded"] is False


def test_stock_verification_failure_requires_attention() -> None:
    status, attention, _reasons = worker._classify_stock(
        2, {"mode": "apply", "outcomes": [{"status": "verification_failed"}]}
    )

    assert status == "attention_required"
    assert attention is True


def test_stock_budget_defer_exit_three_is_normal_incomplete_work() -> None:
    report = {
        "mode": "apply",
        "outcomes": [
            *[{"status": "scheduled_verified"} for _ in range(6)],
            {"status": "deferred_budget"},
        ],
    }

    status, attention, reasons = worker._classify_stock(3, report)

    assert status == "deferred_budget_retryable"
    assert attention is False
    assert "batch budget" in reasons[0]


def test_apply_accepts_only_the_stock_cli_budget_exit_contract(tmp_path: Path) -> None:
    paths = _runtime_tree(tmp_path)

    def fake_executor(command: list[str], _run_dir: Path, _timeout: int) -> worker.ProcessResult:
        _write_report_from_command(
            command,
            {
                "mode": "apply",
                "outcomes": [
                    *[{"status": "scheduled_verified"} for _ in range(6)],
                    {"status": "deferred_budget"},
                ],
            },
        )
        return worker.ProcessResult(returncode=3)

    result = worker._run_apply(paths, executor=fake_executor)

    assert result["status"] == "deferred_budget_retryable"
    assert result["process_returncode"] == 3
    assert result["exit_code"] == 0
    assert result["attention_required"] is False


def test_stock_exit_three_rejects_mixed_managed_or_failed_outcomes() -> None:
    mixed_reports = [
        {
            "mode": "apply",
            "outcomes": [
                {"status": "scheduled_verified"},
                {"status": "deferred_budget"},
                {"status": "deferred_scheduler_budget"},
            ],
        },
        {
            "mode": "apply",
            "outcomes": [
                {"status": "deferred_budget"},
                {"status": "verification_failed"},
            ],
        },
        {
            "mode": "apply",
            "outcomes": [
                {"status": "deferred_budget"},
                {"status": "source_worker_crashed"},
            ],
        },
        {
            "mode": "apply",
            "outcomes": [{"status": "deferred_budget"}, {"status": "mystery_status"}],
        },
    ]

    for report in mixed_reports:
        status, attention, _reasons = worker._classify_stock(3, report)
        assert status == "attention_required"
        assert attention is True


def test_stock_budget_defer_with_wrong_exit_code_requires_attention() -> None:
    report = {"mode": "apply", "outcomes": [{"status": "deferred_budget"}]}

    status, attention, _reasons = worker._classify_stock(0, report)

    assert status == "attention_required"
    assert attention is True


def test_crypto_open_unresolved_is_normal_but_unknown_or_failed_is_attention() -> None:
    report = {
        "apply_summary": {"open": 1},
        "apply": [
            {"status": "closed"},
            {"status": "unresolved_coverage", "remaining_missing_bars": 1},
        ],
    }
    status, attention, _reasons = worker._classify_crypto(1, report)
    assert status == "incomplete_open_shards"
    assert attention is False

    failed = {
        "apply_summary": {"open": 1},
        "apply": [{"status": "failed", "error": "scheduler failed"}],
    }
    status, attention, _reasons = worker._classify_crypto(1, failed)
    assert status == "attention_required"
    assert attention is True


def test_crypto_source_evidence_terminal_statuses_are_not_counted_open() -> None:
    report = {
        "apply_summary": {
            "open": 0,
            "closed": 1,
            "source_absent": 318,
            "source_invalid": 23,
            "planned_shards": 397,
            "plan_open_remaining_shards": 55,
        },
        "apply": [
            {"status": "closed"},
            {"status": "source_absent", "remaining_missing_bars": 1},
            {"status": "source_invalid", "remaining_missing_bars": 1},
        ],
    }

    status, attention, reasons = worker._classify_crypto(1, report)

    assert status == "incomplete_open_shards"
    assert attention is False
    assert any("55 planned shards" in reason for reason in reasons)

    completed = {
        **report,
        "apply_summary": {
            "open": 0,
            "closed": 2,
            "source_absent": 318,
            "source_invalid": 23,
            "planned_shards": 343,
            "plan_open_remaining_shards": 0,
        },
        "apply": [{"status": "closed"}, {"status": "source_absent"}],
    }
    status, attention, _reasons = worker._classify_crypto(0, completed)
    assert status == "completed"
    assert attention is False


def test_crypto_terminal_status_with_wrong_open_accounting_needs_attention() -> None:
    report = {
        "apply_summary": {
            "open": 1,
            "closed": 0,
            "source_absent": 1,
            "source_invalid": 0,
            "planned_shards": 2,
            "plan_open_remaining_shards": 1,
        },
        "apply": [{"status": "source_absent"}],
    }

    status, attention, _reasons = worker._classify_crypto(1, report)

    assert status == "attention_required"
    assert attention is True


def test_crypto_plan_accounting_keeps_unselected_shards_open() -> None:
    report = {
        "apply_summary": {
            "open": 0,
            "closed": 1,
            "planned_shards": 5,
            "plan_open_remaining_shards": 4,
        },
        "apply": [{"status": "closed"}],
    }

    status, attention, reasons = worker._classify_crypto(1, report)

    assert status == "incomplete_open_shards"
    assert attention is False
    assert any("4 planned shards" in reason for reason in reasons)


def test_crypto_plan_accounting_rejects_contradictory_counts() -> None:
    contradictory = {
        "apply_summary": {
            "open": 0,
            "closed": 1,
            "planned_shards": 5,
            "plan_open_remaining_shards": 0,
        },
        "apply": [{"status": "closed"}],
    }
    status, attention, _reasons = worker._classify_crypto(1, contradictory)

    assert status == "attention_required"
    assert attention is True

    wrong_exit = {
        "apply_summary": {
            "open": 0,
            "closed": 1,
            "planned_shards": 5,
            "plan_open_remaining_shards": 4,
        },
        "apply": [{"status": "closed"}],
    }
    status, attention, _reasons = worker._classify_crypto(0, wrong_exit)

    assert status == "attention_required"
    assert attention is True


def test_user_timer_examples_are_serial_and_uninstalled() -> None:
    repo = Path(__file__).resolve().parents[3]
    service = (
        repo / "deploy" / "systemd" / "ai-for-investor-full-history-recovery.service.example"
    ).read_text(encoding="utf-8")
    timer = (
        repo / "deploy" / "systemd" / "ai-for-investor-full-history-recovery.timer.example"
    ).read_text(encoding="utf-8")

    assert "Type=oneshot" in service
    assert "TimeoutStartSec=8min" in service
    assert "TimeoutStopSec=25s" in service
    assert "KillMode=control-group" in service
    assert "run_full_history_recovery_worker.py --apply" in service
    assert "scheduler.start" not in service
    assert "OnBootSec=2min" in timer
    assert "OnUnitInactiveSec=1min" in timer
    assert "WantedBy=timers.target" in timer


def test_real_timeout_terminates_child_process_group(tmp_path: Path) -> None:
    result = worker._execute_cli(
        [sys.executable, "-c", "import time; time.sleep(20)"],
        tmp_path,
        timeout_seconds=0.1,
    )

    assert result.timed_out is True
    assert result.returncode is not None
    assert (tmp_path / "stdout.log").exists()
    assert (tmp_path / "stderr.log").exists()


def test_kill_process_group_kills_descendants_after_leader_exits(monkeypatch) -> None:
    signals: list[int] = []
    clock_values = iter([0.0, 0.0, 0.0, 2.0])

    class ExitedLeader:
        pid = 12345
        returncode = 0

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float) -> int:
            return 0

    monkeypatch.setattr(worker, "TERMINATE_GRACE_SECONDS", 1)
    monkeypatch.setattr(worker.time, "monotonic", lambda: next(clock_values, 2.0))
    monkeypatch.setattr(worker.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(worker, "_process_group_exists", lambda _pgid: True)
    monkeypatch.setattr(worker.os, "killpg", lambda _pgid, signum: signals.append(signum))

    worker._kill_process_group(ExitedLeader())

    assert signals == [signal.SIGTERM, signal.SIGKILL]


def test_parent_signal_terminates_cli_process_group_and_reports_interruption(
    tmp_path: Path, monkeypatch
) -> None:
    previous_handler = signal.getsignal(signal.SIGTERM)
    cleanup_calls: list[int] = []

    class FakeProcess:
        pid = 12346
        returncode = None

        def wait(self, timeout: int) -> int:
            handler = signal.getsignal(signal.SIGTERM)
            handler(signal.SIGTERM, None)
            raise AssertionError("signal handler must interrupt wait")

    def fake_cleanup(process: FakeProcess) -> None:
        cleanup_calls.append(process.pid)
        process.returncode = -signal.SIGTERM

    monkeypatch.setattr(worker.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(worker, "_kill_process_group", fake_cleanup)

    result = worker._execute_cli(["unused"], tmp_path, timeout_seconds=5)

    assert result.interrupted_by_signal == signal.SIGTERM
    assert result.returncode == -signal.SIGTERM
    assert cleanup_calls == [12346]
    assert signal.getsignal(signal.SIGTERM) == previous_handler


def test_interrupted_apply_records_uncertain_write_and_advances_cursor(tmp_path: Path) -> None:
    paths = _runtime_tree(tmp_path)

    result = worker._run_apply(
        paths,
        executor=lambda *_args: worker.ProcessResult(
            returncode=-signal.SIGTERM,
            interrupted_by_signal=signal.SIGTERM,
        ),
    )

    assert result["status"] == "interrupted_write_possible"
    assert result["attention_required"] is True
    assert result["write_possible"] is True
    assert result["source_failure_recorded"] is False
    assert json.loads(paths.cursor_file.read_text())["next_asset"] == "crypto"


def test_four_asset_timeout_keeps_rotated_cursor_and_write_uncertainty(tmp_path: Path) -> None:
    paths = _runtime_tree(tmp_path)
    paths.worker_dir.mkdir(parents=True, exist_ok=True)
    paths.cursor_file.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "rotation_order": list(worker.FOUR_ASSET_ORDER),
                "next_asset": "etf",
            }
        ),
        encoding="utf-8",
    )
    seen: list[tuple[str, int]] = []

    def timeout_executor(command: list[str], _run_dir: Path, timeout: int) -> worker.ProcessResult:
        seen.append((command[1], timeout))
        return worker.ProcessResult(returncode=-signal.SIGKILL, timed_out=True)

    result = worker._run_apply(paths, assets=worker.FOUR_ASSET_ORDER, executor=timeout_executor)

    assert seen == [(str(paths.etf_script), 260)]
    assert result["status"] == "timed_out_write_possible"
    assert result["write_possible"] is True
    assert result["source_failure_recorded"] is False
    assert result["full_history_complete"] is False
    assert json.loads(paths.cursor_file.read_text(encoding="utf-8"))["next_asset"] == "stock"


def test_etf_apply_never_reuses_shared_old_events_without_unique_run_report(tmp_path: Path) -> None:
    paths = _runtime_tree(tmp_path)
    paths.worker_dir.mkdir(parents=True, exist_ok=True)
    paths.cursor_file.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "rotation_order": list(worker.FOUR_ASSET_ORDER),
                "next_asset": "etf",
            }
        ),
        encoding="utf-8",
    )
    paths.etf_output_dir.mkdir(parents=True, exist_ok=True)
    (paths.etf_output_dir / "events.jsonl").write_text(
        '{"event":"controller_run","run_id":"stale-old-run"}\n', encoding="utf-8"
    )
    current_report_paths: list[Path] = []

    def no_report_executor(
        command: list[str], _run_dir: Path, _timeout: int
    ) -> worker.ProcessResult:
        current_report_paths.append(Path(command[command.index("--report") + 1]))
        return worker.ProcessResult(returncode=0)

    result = worker._run_apply(paths, assets=worker.FOUR_ASSET_ORDER, executor=no_report_executor)

    assert result["status"] == "invalid_or_missing_cli_report"
    assert result["attention_required"] is True
    assert result["write_possible"] is True
    assert current_report_paths[0].parent == Path(result["run_directory"])
    assert current_report_paths[0].name == "etf-report.json"
    assert not current_report_paths[0].exists()


def test_bond_classifier_distinguishes_real_source_failures_from_worker_crash() -> None:
    prefix = {
        "report_type": "bond-convertible-history-controller-v1",
        "mode": "managed_bounded_convertible_history_reconciliation",
        "max_codes": worker.BOND_MAX_CODES,
        "time_budget_seconds": worker.BOND_BATCH_SECONDS,
        "source_timeout_seconds_max": worker.BOND_SOURCE_TIMEOUT_SECONDS,
    }
    source_failure = {
        **prefix,
        "outcomes": [
            {"status": "verified_unchanged"},
            {"status": "source_invalid"},
        ],
    }
    status, attention, _ = worker._classify_bond(1, source_failure)
    assert status == "source_failed_retryable"
    assert attention is False

    worker_crash = {**prefix, "outcomes": [{"status": "source_worker_crashed"}]}
    status, attention, _ = worker._classify_bond(3, worker_crash)
    assert status == "attention_required"
    assert attention is True

    empty_source = {**prefix, "outcomes": [{"status": "source_empty_unverified"}]}
    status, attention, _ = worker._classify_bond(3, empty_source)
    assert status == "source_deferred"
    assert attention is False


def test_bond_classifier_binds_limits_and_outcome_count_to_worker_command() -> None:
    report = {
        "report_type": "bond-convertible-history-controller-v1",
        "mode": "managed_bounded_convertible_history_reconciliation",
        "max_codes": worker.BOND_MAX_CODES,
        "time_budget_seconds": worker.BOND_BATCH_SECONDS,
        "source_timeout_seconds_max": worker.BOND_SOURCE_TIMEOUT_SECONDS,
        "outcomes": [{"status": "verified_unchanged"}],
    }
    status, attention, _ = worker._classify_bond(0, report)
    assert status == "batch_reconciled_history_incomplete"
    assert attention is False

    for key, value in (
        ("max_codes", worker.BOND_MAX_CODES + 1),
        ("time_budget_seconds", worker.BOND_BATCH_SECONDS + 1),
        ("source_timeout_seconds_max", worker.BOND_SOURCE_TIMEOUT_SECONDS + 1),
    ):
        changed = {**report, key: value}
        status, attention, _ = worker._classify_bond(0, changed)
        assert status == "attention_required"
        assert attention is True

    too_many = {**report, "outcomes": [{"status": "verified_unchanged"}] * 6}
    status, attention, _ = worker._classify_bond(0, too_many)
    assert status == "attention_required"
    assert attention is True


def test_bond_classifier_requires_recognized_terminal_for_empty_outcomes() -> None:
    prefix = {
        "report_type": "bond-convertible-history-controller-v1",
        "mode": "managed_bounded_convertible_history_reconciliation",
        "outcomes": [],
    }

    for terminal_status in ("no_runnable_candidates", "no_inventory_candidates"):
        status, attention, _ = worker._classify_bond(
            3,
            {
                **prefix,
                "status": terminal_status,
                "apply_max_codes": worker.BOND_MAX_CODES,
                "source_requests_made": False,
                "writes_database": False,
            },
        )
        assert status == "source_deferred"
        assert attention is False

    for report in (prefix, {**prefix, "status": "unknown_terminal"}):
        status, attention, _ = worker._classify_bond(3, report)
        assert status == "attention_required"
        assert attention is True


def test_etf_classifier_requires_fresh_probe_matching_run_and_outcomes() -> None:
    report = _valid_etf_run_report()
    status, attention, _ = worker._classify_etf(0, report)
    assert status == "batch_reconciled_history_incomplete"
    assert attention is False

    mismatched = _valid_etf_run_report()
    mismatched["outcomes"][0]["run_id"] = "f" * 32
    status, attention, _ = worker._classify_etf(0, mismatched)
    assert status == "attention_required"
    assert attention is True

    wrong_count = _valid_etf_run_report()
    wrong_count["run_event"]["processed_codes"] = 0
    status, attention, _ = worker._classify_etf(0, wrong_count)
    assert status == "attention_required"
    assert attention is True

    missing_outcome = _valid_etf_run_report()
    selected = ["510300", "510500"]
    listing_evidence = [
        *missing_outcome["run_event"]["selected_listing_evidence"],
        {
            **missing_outcome["run_event"]["selected_listing_evidence"][0],
            "fund_code": "510500",
        },
    ]
    missing_outcome["selected_codes"] = selected
    missing_outcome["run_event"]["selected_codes"] = selected
    missing_outcome["selected_listing_evidence"] = listing_evidence
    missing_outcome["run_event"]["selected_listing_evidence"] = listing_evidence
    missing_outcome["run_event"]["current_sina_snapshot"].update(
        source_row_count=2, unique_code_count=2
    )
    status, attention, _ = worker._classify_etf(0, missing_outcome)
    assert status == "attention_required"
    assert attention is True

    budget_deferred_selection = _valid_etf_run_report()
    budget_deferred_selection["selected_codes"] = selected
    budget_event = budget_deferred_selection["run_event"]
    budget_event["selected_codes"] = selected
    budget_event["selected_listing_evidence"] = listing_evidence
    budget_event["processed_codes"] = 1
    budget_event["current_sina_snapshot"].update(source_row_count=2, unique_code_count=2)
    budget_deferred_selection["selected_listing_evidence"] = listing_evidence
    budget_deferred_selection["outcomes"].append(
        {
            "event": "nav_probe",
            "run_id": budget_deferred_selection["run_id"],
            "fund_code": "510500",
            "status": "not_started_time_budget_exhausted",
        }
    )
    status, attention, _ = worker._classify_etf(0, budget_deferred_selection)
    assert status == "deferred_budget_retryable"
    assert attention is False

    failed_probe = _valid_etf_run_report()
    failed_probe["run_event"]["probe_ready"] = False
    failed_probe["run_event"]["sina_refresh_error"] = "TimeoutError"
    failed_probe["run_event"]["current_sina_snapshot"]["complete"] = False
    failed_probe["run_event"]["selected_codes"] = []
    failed_probe["run_event"]["selected_listing_evidence"] = []
    failed_probe["run_event"]["processed_codes"] = 0
    failed_probe["selected_codes"] = []
    failed_probe["selected_listing_evidence"] = []
    failed_probe["outcomes"] = []
    failed_probe["fresh_sina_probe_ready"] = False
    status, attention, _ = worker._classify_etf(0, failed_probe)
    assert status == "source_deferred"
    assert attention is False


def test_etf_classifier_validates_protected_scope_around_managed_write() -> None:
    report = _valid_etf_run_report(status="applied_and_verified")
    report["outcomes"][0]["scheduler_execution"] = {
        "status": "completed",
        "error_message": None,
    }
    protected_snapshot = {
        "protected_scope_codes_count": worker.ETF_PROTECTED_SCOPE["codes_count"],
        "protected_scope_codes_sha256": worker.ETF_PROTECTED_SCOPE["codes_sha256"],
        "protected_legacy_nav_rows": worker.ETF_PROTECTED_SCOPE["nav_rows"],
        "protected_legacy_nav_sha256": worker.ETF_PROTECTED_SCOPE["nav_sha256"],
        "protected_cache_rows": worker.ETF_PROTECTED_SCOPE["cache_rows"],
        "protected_cache_sha256": worker.ETF_PROTECTED_SCOPE["cache_sha256"],
    }
    report["run_event"]["protected_legacy_scope"]["checks"] = [
        {
            "fund_code": "510300",
            "status": "before_and_after_match",
            "before": dict(protected_snapshot),
            "after": dict(protected_snapshot),
        }
    ]

    status, attention, _ = worker._classify_etf(0, report)
    assert status == "batch_reconciled_history_incomplete"
    assert attention is False

    report["run_event"]["protected_legacy_scope"]["checks"][0]["after"][
        "protected_legacy_nav_sha256"
    ] = "0" * 64
    status, attention, _ = worker._classify_etf(0, report)
    assert status == "attention_required"
    assert attention is True


def test_unexpected_runner_error_is_structured_and_conservative(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        worker,
        "run_once",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("lock path unavailable")),
    )

    exit_code = worker.main(["--apply"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["status"] == "runner_internal_error"
    assert output["source_failure_recorded"] is False
    assert output["write_possible"] is True
    assert output["attention_required"] is True


def _valid_option_run_report(
    artifact_root: Path,
    *,
    month: str = "202001",
    run_id: str = "0123456789abcdef0123456789abcdef",
) -> dict[str, object]:
    response_body = b"offline-only CFFEX archive fixture; never sent to a source"
    body_sha = hashlib.sha256(response_body).hexdigest()
    capture_dir = artifact_root / month / run_id
    capture_dir.mkdir(parents=True, mode=0o700)
    capture_dir.chmod(0o700)
    body_path = capture_dir / "source-response.zip"
    body_path.write_bytes(response_body)
    body_path.chmod(0o600)
    expected_url = worker.OPTION_SOURCE_URL_TEMPLATE.format(month=month)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "month": month,
        "controller_as_of_date": "2026-10-20",
        "expected_url": expected_url,
        "request_count": 1,
        "requested_url": expected_url,
        "final_url": expected_url,
        "status_code": 200,
        "response_headers": {"content-type": "application/zip"},
        "redirect_chain": [],
        "body_complete": True,
        "body_bytes": len(response_body),
        "body_sha256": body_sha,
        "body_path": str(body_path),
        "capture_error": None,
        "transport_verifiable": True,
        "recording_semantics": "same real iter_content bytes delivered to the existing strict parser",
    }
    manifest_path = capture_dir / "wire-capture.json"
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    manifest_path.chmod(0o600)
    capture = {
        **manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    from calendar import monthrange

    year, month_number = int(month[:4]), int(month[-2:])
    first_day = f"{year:04d}{month_number:02d}01"
    last_day = f"{year:04d}{month_number:02d}{monthrange(year, month_number)[1]:02d}"
    expected_scope = f"cffex:option-history:monthly-archive:{first_day}-{last_day}"
    source_key_hash = "1" * 64
    execution_result = {
        "run_mode": "backfill",
        "row_count": 100,
        "rows_before": 90,
        "rows_after": 100,
        "rows_delta": 10,
        "table_name": worker.OPTION_TABLE_NAME,
        "quality_status": "partial",
        "source_complete": False,
        "valid_row_count": 2,
        "source_row_count": 2,
        "source_scope": expected_scope,
        "committed_write_count": 1,
    }
    compare = {
        "month": month,
        "source_key_count": 2,
        "sql_key_count": 2,
        "source_duplicate_keys": [],
        "sql_duplicate_keys": [],
        "missing_in_sql": [],
        "sql_only_keys": [],
        "field_mismatch_count": 0,
        "field_mismatches": [],
        "policy_errors": [],
        "source_fields_sha256": source_key_hash,
        "sql_fields_sha256": source_key_hash,
        "compared_fields": list(worker.OPTION_COMPARE_FIELDS),
        "matched": True,
    }
    result = {
        "month": month,
        "run_id": run_id,
        "attempted_at_utc": "2026-10-20T01:00:00+00:00",
        "controller_as_of_date": "2026-10-20",
        "request_scope": "one exact full calendar month archive; no trading calendar imputation",
        "candidate_start_month_is_inception": False,
        "source_lifecycle": "unknown",
        "source_complete": False,
        "calendar_coverage": "unknown",
        "contract_lifecycle": "unknown",
        "candidate_inception_verified": False,
        "month_calendar_coverage_verified": False,
        "source_sequence_complete": True,
        "archive_snapshot_verified": True,
        "status": worker.OPTION_SUCCESS_STATUS,
        "independent_parse_error": None,
        "post_sql_read_error": None,
        "timed_out": False,
        "archive_sha256": body_sha,
        "wire_capture": capture,
        "source_month_evidence": {
            "source_archive_month": month,
            "source_archive_sha256": body_sha,
            "source_row_count": 2,
            "source_sequence_complete": True,
            "source_complete": False,
        },
        "postimage_sql_rows": 2,
        "source_sql_comparison": compare,
        "managed_quality_receipt_matches_parser": True,
        "managed_quality_receipt_errors": [],
        "execution": {
            "execution_id": "ak_exec_1234567890ab",
            "status": "completed",
            "error_message": None,
            "result": execution_result,
        },
        "dispatch": {
            "registration": {
                "script_id": "cffex_option_daily_history",
                "source": "cffex",
                "module_path": "app.data_fetch.scripts.options.daily.cffex_option_daily_history",
                "function_name": "main",
                "target_table": worker.OPTION_TABLE_NAME,
            },
            "parameters": {
                "start_date": first_day,
                "end_date": last_day,
                "max_codes": 1,
                "source_timeout_seconds": 90.0,
                "_ingest_mode": "backfill",
            },
            "operator_id": None,
            "task_id": None,
            "managed_timeout_seconds": 149,
            "outer_wait_timeout_seconds": 154,
            "period_key": f"cffex-month-controller-v1:{month}:{run_id}",
            "parameter_hash": "2" * 64,
            "claim_key": "3" * 64,
            "claim_reuse_policy": "unique run id; no completed claim reused for refresh",
        },
        "execution_budget": {
            "kind": "soft_total_wall_budget",
            "seconds": worker.OPTION_BATCH_SECONDS,
            "outer_process_hard_stop_required": True,
            "recommended_outer_timeout_seconds": worker.OPTION_OUTER_TIMEOUT_SECONDS,
        },
    }
    return {
        "mode": "apply",
        "selection": {
            "selected_month": month,
            "source_lifecycle": "unknown",
            "candidate_start_is_inception": False,
        },
        "result": result,
    }


def _option_failure_report(status: str) -> dict[str, object]:
    return {
        "mode": "apply",
        "selection": {
            "selected_month": "201912",
            "source_lifecycle": "unknown",
            "candidate_start_is_inception": False,
        },
        "result": {
            "month": "201912",
            "run_id": "f" * 32,
            "status": status,
            "preimage_unchanged_after_failed_month": True,
            "source_failure_cooldown_hours": 24.0,
            "timed_out": False,
            "execution": None,
            "managed_call_error": "strict archive parser rejected source rows",
            "database_write_possible": True,
            "wire_capture": {
                "request_count": 1,
                "status_code": 200,
                "body_complete": True,
                "transport_verifiable": False,
            },
        },
    }


def test_five_asset_plan_previews_v2_to_v3_without_mutating_cursor(
    tmp_path: Path,
) -> None:
    paths = worker.WorkerPaths.for_repo(tmp_path)
    paths.worker_dir.mkdir(parents=True)
    old_cursor = {
        "schema_version": 2,
        "rotation_order": list(worker.FOUR_ASSET_ORDER),
        "next_asset": "etf",
        "last_run_id": "old-four-asset-run",
    }
    paths.cursor_file.write_text(json.dumps(old_cursor), encoding="utf-8")

    plan = worker._build_plan(paths, worker.FIVE_ASSET_ORDER)

    assert plan["assets"] == list(worker.FIVE_ASSET_ORDER)
    assert plan["cursor_status"] == "valid_v2_to_v3_migration_preview"
    assert plan["cursor_migration_preview"] == {
        "from_schema_version": 2,
        "to_schema_version": 3,
        "preserved_next_asset": "etf",
        "rotation_order": list(worker.FIVE_ASSET_ORDER),
        "plan_writes_cursor": False,
    }
    assert set(plan["commands"]) == set(worker.FIVE_ASSET_ORDER)
    option = plan["commands"]["option"]
    assert Path(option[1]) == paths.option_script
    assert option[option.index("--max-minutes") + 1] == "3"
    assert option[option.index("--source-timeout-seconds") + 1] == "90"
    assert (
        Path(option[option.index("--progress") + 1]) == paths.option_output_dir / "progress.jsonl"
    )
    assert Path(option[option.index("--artifacts") + 1]) == paths.option_output_dir / "snapshots"
    assert Path(option[option.index("--output") + 1]).parent.name == "<RUN_ID>"
    assert plan["budgets"]["cffex_option_archive"] == {
        "months_per_run": 1,
        "soft_time_budget_seconds": 180,
        "source_timeout_seconds": 90,
        "outer_wall_seconds": 200,
        "progress_file": str(paths.option_output_dir / "progress.jsonl"),
        "snapshot_dir": str(paths.option_output_dir / "snapshots"),
        "unique_report_per_run": True,
        "source_lifecycle_and_calendar_completeness": "unknown",
    }
    assert json.loads(paths.cursor_file.read_text(encoding="utf-8")) == old_cursor


def test_five_asset_plan_previews_v1_to_v3_preserving_cursor_without_write(
    tmp_path: Path,
) -> None:
    paths = worker.WorkerPaths.for_repo(tmp_path)
    paths.worker_dir.mkdir(parents=True)
    old_cursor = {"schema_version": 1, "next_asset": "crypto", "last_status": "old"}
    paths.cursor_file.write_text(json.dumps(old_cursor), encoding="utf-8")

    plan = worker._build_plan(paths, worker.FIVE_ASSET_ORDER)

    assert plan["cursor_migration_preview"]["from_schema_version"] == 1
    assert plan["cursor_migration_preview"]["to_schema_version"] == 3
    assert plan["cursor_migration_preview"]["preserved_next_asset"] == "crypto"
    assert json.loads(paths.cursor_file.read_text(encoding="utf-8")) == old_cursor


def test_five_asset_apply_migrates_v2_under_lock_and_preserves_rotation(
    tmp_path: Path,
) -> None:
    paths = _runtime_tree(tmp_path)
    paths.worker_dir.mkdir(parents=True, exist_ok=True)
    paths.cursor_file.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "rotation_order": list(worker.FOUR_ASSET_ORDER),
                "next_asset": "etf",
                "last_run_id": "old-four-asset-run",
            }
        ),
        encoding="utf-8",
    )
    seen: list[str] = []

    def fake_executor(command: list[str], _run_dir: Path, timeout: int) -> worker.ProcessResult:
        current = json.loads(paths.cursor_file.read_text(encoding="utf-8"))
        assert current["schema_version"] == 3
        assert current["rotation_order"] == list(worker.FIVE_ASSET_ORDER)
        assert current["next_asset"] == "option"
        assert timeout == worker.ETF_BATCH_SECONDS + worker.OUTER_TIMEOUT_GRACE_SECONDS
        seen.append(command[1])
        _write_report_from_command(command, _valid_etf_run_report())
        return worker.ProcessResult(returncode=0)

    result = worker._run_apply(paths, assets=worker.FIVE_ASSET_ORDER, executor=fake_executor)
    cursor = json.loads(paths.cursor_file.read_text(encoding="utf-8"))

    assert result["asset"] == "etf"
    assert result["full_history_complete"] is False
    assert seen == [str(paths.etf_script)]
    assert cursor["schema_version"] == 3
    assert cursor["rotation_order"] == list(worker.FIVE_ASSET_ORDER)
    assert cursor["next_asset"] == "option"
    assert cursor["last_asset"] == "etf"


def test_five_asset_cursor_v3_rejects_corruption_and_other_registries(
    tmp_path: Path,
) -> None:
    paths = worker.WorkerPaths.for_repo(tmp_path)
    paths.worker_dir.mkdir(parents=True)
    cursor = {
        "schema_version": 3,
        "rotation_order": list(worker.FIVE_ASSET_ORDER),
        "next_asset": "option",
        "unexpected": "must not be silently dropped",
    }
    paths.cursor_file.write_text(json.dumps(cursor), encoding="utf-8")

    _payload, error = worker._read_cursor_payload(paths.cursor_file, worker.FIVE_ASSET_ORDER)
    assert error and "unrecognized fields" in error
    _payload, four_mode_error = worker._read_cursor_payload(
        paths.cursor_file, worker.FOUR_ASSET_ORDER
    )
    assert four_mode_error and "reserved" in four_mode_error
    assert json.loads(paths.cursor_file.read_text(encoding="utf-8")) == cursor


def test_option_classifier_requires_persisted_exact_source_and_managed_sql_proof(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "cffex" / "snapshots"
    artifact_root.mkdir(parents=True)
    report = _valid_option_run_report(artifact_root)
    status, attention, reasons = worker._classify_option(0, report, artifact_root=artifact_root)
    assert status == "batch_reconciled_history_incomplete"
    assert attention is False
    assert reasons

    body_path = Path(report["result"]["wire_capture"]["body_path"])
    body_path.write_bytes(b"body changed after capture")
    status, attention, _ = worker._classify_option(0, report, artifact_root=artifact_root)
    assert status == "attention_required"
    assert attention is True


def test_option_classifier_rejects_partial_wire_sql_or_managed_receipts(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "option-snapshots"
    artifact_root.mkdir()
    mutators = [
        lambda report: report["result"]["wire_capture"].update(request_count=2),
        lambda report: report["result"]["wire_capture"].update(
            final_url="https://attacker.invalid/archive"
        ),
        lambda report: report["result"]["source_sql_comparison"].update(matched=False),
        lambda report: report["result"]["source_sql_comparison"].update(compared_fields=[]),
        lambda report: report["result"]["source_sql_comparison"].update(sql_fields_sha256="4" * 64),
        lambda report: report["result"]["execution"]["result"].update(source_row_count=1),
        lambda report: report["result"]["execution"]["result"].update(run_mode="live"),
        lambda report: report["result"].update(source_complete=True),
    ]
    for index, mutate in enumerate(mutators):
        report = _valid_option_run_report(artifact_root, run_id=f"{index:032x}")
        mutate(report)
        status, attention, _ = worker._classify_option(0, report, artifact_root=artifact_root)
        assert status == "attention_required"
        assert attention is True


def test_option_failure_and_budget_are_deferred_but_managed_unknown_is_attention(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "option-snapshots"
    artifact_root.mkdir()
    for source_status in ("source_failed", "source_invalid"):
        status, attention, _ = worker._classify_option(
            1, _option_failure_report(source_status), artifact_root=artifact_root
        )
        assert status == "source_failed_retryable"
        assert attention is False

    budget_report = {
        "mode": "apply",
        "selection": {"selected_month": "202001"},
        "result": {
            "status": "deferred_budget",
            "failure_phase": "wall_clock_budget_before_managed_dispatch",
            "execution": None,
            "database_write_possible": False,
            "timed_out": False,
        },
    }
    status, attention, _ = worker._classify_option(1, budget_report, artifact_root=artifact_root)
    assert status == "deferred_budget_retryable"
    assert attention is False

    unknown_report = {
        "mode": "apply",
        "selection": {"selected_month": "202001"},
        "result": {"status": "managed_outcome_unknown"},
    }
    status, attention, _ = worker._classify_option(1, unknown_report, artifact_root=artifact_root)
    assert status == "attention_required"
    assert attention is True

    no_month = {
        "mode": "apply",
        "selected_month": None,
        "selection": {
            "selected_month": None,
            "source_lifecycle": "unknown",
            "candidate_start_is_inception": False,
        },
        "status": "no_eligible_month",
    }
    status, attention, _ = worker._classify_option(0, no_month, artifact_root=artifact_root)
    assert status == "source_deferred"
    assert attention is False


def test_option_source_invalid_advances_five_asset_rotation_without_attention(
    tmp_path: Path,
) -> None:
    paths = _runtime_tree(tmp_path)
    paths.worker_dir.mkdir(parents=True, exist_ok=True)
    paths.cursor_file.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "rotation_order": list(worker.FIVE_ASSET_ORDER),
                "next_asset": "option",
            }
        ),
        encoding="utf-8",
    )

    def source_invalid_executor(
        command: list[str], _run_dir: Path, timeout: int
    ) -> worker.ProcessResult:
        assert timeout == worker.OPTION_OUTER_TIMEOUT_SECONDS
        assert Path(command[1]) == paths.option_script
        _write_report_from_command(command, _option_failure_report("source_invalid"))
        return worker.ProcessResult(returncode=1)

    result = worker._run_apply(
        paths, assets=worker.FIVE_ASSET_ORDER, executor=source_invalid_executor
    )
    cursor = json.loads(paths.cursor_file.read_text(encoding="utf-8"))

    assert result["status"] == "source_failed_retryable"
    assert result["attention_required"] is False
    assert result["source_failure_recorded"] is True
    assert result["controller_run_id"] == "f" * 32
    assert result["full_history_complete"] is False
    assert cursor["next_asset"] == "stock"
    assert cursor["schema_version"] == 3


def test_five_asset_option_dispatch_uses_canonical_ledger_snapshot_and_unique_report(
    tmp_path: Path,
) -> None:
    paths = _runtime_tree(tmp_path)
    paths.worker_dir.mkdir(parents=True, exist_ok=True)
    paths.cursor_file.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "rotation_order": list(worker.FIVE_ASSET_ORDER),
                "next_asset": "option",
            }
        ),
        encoding="utf-8",
    )

    def successful_executor(
        command: list[str], run_dir: Path, timeout: int
    ) -> worker.ProcessResult:
        assert timeout == 200
        assert command[command.index("--max-minutes") + 1] == "3"
        assert command[command.index("--source-timeout-seconds") + 1] == "90"
        assert (
            Path(command[command.index("--progress") + 1])
            == paths.option_output_dir / "progress.jsonl"
        )
        assert (
            Path(command[command.index("--artifacts") + 1]) == paths.option_output_dir / "snapshots"
        )
        output = Path(command[command.index("--output") + 1])
        assert output == run_dir / "option-report.json"
        report = _valid_option_run_report(paths.option_output_dir / "snapshots")
        output.write_text(json.dumps(report), encoding="utf-8")
        return worker.ProcessResult(returncode=0)

    result = worker._run_apply(paths, assets=worker.FIVE_ASSET_ORDER, executor=successful_executor)
    cursor = json.loads(paths.cursor_file.read_text(encoding="utf-8"))
    assert result["asset"] == "option"
    assert result["status"] == "batch_reconciled_history_incomplete"
    assert result["write_possible"] is True
    assert result["full_history_complete"] is False
    assert result["controller_run_id"] == "0123456789abcdef0123456789abcdef"
    assert cursor["next_asset"] == "stock"
    assert cursor["schema_version"] == 3
