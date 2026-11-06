"""Run one bounded history-recovery batch per invocation.

The default plan is read-only. The default ``--apply`` rotation remains stock
and crypto; the opt-in four-asset registry adds convertible bonds and ETF NAV.
The worker does not start an APScheduler or bypass a controller's claims,
source limits, or verification checks.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import stat
import subprocess
import time
from calendar import monthrange
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = REPO_ROOT / "src" / "backend"
PYTHON_BIN = BACKEND_ROOT / ".venv" / "bin" / "python"
STOCK_SCRIPT = BACKEND_ROOT / "scripts" / "stock_full_history_controller.py"
CRYPTO_SCRIPT = BACKEND_ROOT / "scripts" / "crypto_full_history_recovery.py"
BOND_SCRIPT = BACKEND_ROOT / "scripts" / "bond_convertible_history_controller.py"
ETF_SCRIPT = BACKEND_ROOT / "scripts" / "backfill_etf_nav_controller.py"
OPTION_SCRIPT = BACKEND_ROOT / "scripts" / "cffex_option_history_controller.py"
CRYPTO_MANIFEST = REPO_ROOT / "var" / "reports" / "iteration203" / "crypto-inception-manifest.json"

STOCK_PROGRESS = (
    REPO_ROOT / "var" / "reports" / "iteration203" / "stock-controller" / "progress.jsonl"
)
CRYPTO_PROGRESS = (
    REPO_ROOT / "var" / "reports" / "iteration203" / "crypto-hourly-full-history-progress.jsonl"
)
BOND_PROGRESS = (
    REPO_ROOT
    / "var"
    / "reports"
    / "iteration203"
    / "bond-convertible-history-controller"
    / "progress.jsonl"
)
BOND_SNAPSHOTS = (
    REPO_ROOT
    / "var"
    / "reports"
    / "iteration203"
    / "bond-convertible-history-controller"
    / "snapshots"
)
ETF_OUTPUT_DIR = REPO_ROOT / "var" / "reports" / "iteration203" / "etf_nav_controller"
OPTION_OUTPUT_DIR = (
    REPO_ROOT / "var" / "reports" / "iteration203" / "cffex-option-history-controller"
)

WORKER_DIR = REPO_ROOT / "var" / "reports" / "iteration203" / "full-history-recovery-worker"
CURSOR_FILE = WORKER_DIR / "cursor.json"
LOCK_FILE = WORKER_DIR / "worker.lock"
RUNS_DIR = WORKER_DIR / "runs"

STOCK_BATCH_MINUTES = 6.0
STOCK_SOURCE_TIMEOUT_SECONDS = 45
STOCK_MAX_CODES = 10
CRYPTO_BATCH_MINUTES = 4.0
CRYPTO_MAX_SHARDS = 25
CRYPTO_PAUSE_SECONDS = 5.0
CRYPTO_TIMEOUT_SECONDS = 120
RETRY_COOLDOWN_HOURS = 24.0
OUTER_TIMEOUT_GRACE_SECONDS = 20
TERMINATE_GRACE_SECONDS = 10
DEFAULT_ASSETS = ("stock", "crypto")
FOUR_ASSET_ORDER = ("stock", "crypto", "bond", "etf")
FIVE_ASSET_ORDER = ("stock", "crypto", "bond", "etf", "option")
ALLOWED_ASSET_ORDERS = (DEFAULT_ASSETS, FOUR_ASSET_ORDER, FIVE_ASSET_ORDER)
BOND_MAX_CODES = 5
BOND_BATCH_SECONDS = 240
BOND_SOURCE_TIMEOUT_SECONDS = 45
ETF_MAX_CODES = 5
ETF_BATCH_SECONDS = 240
OPTION_BATCH_SECONDS = 180
OPTION_SOURCE_TIMEOUT_SECONDS = 90
OPTION_OUTER_TIMEOUT_SECONDS = 200
OPTION_MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
OPTION_TABLE_NAME = "OPTION_CFFEX_DAILY_HISTORY"
OPTION_SOURCE_URL_TEMPLATE = "http://www.cffex.com.cn/sj/historysj/{month}/zip/{month}.zip"
OPTION_COMPARE_FIELDS = (
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
    "OBSERVED_AT_TIME_ZONE",
    "SOURCE_SCOPE",
    "SOURCE_SEQUENCE_COMPLETE",
    "SOURCE_COMPLETE",
    "QUALITY_STATUS",
)
OPTION_SUCCESS_STATUS = "verified_source_archive_snapshot"
OPTION_SOURCE_FAILURE_STATUSES = {"source_failed", "source_invalid"}

STOCK_SUCCESS_STATUSES = {"verified_match", "scheduled_verified"}
STOCK_RETRYABLE_SOURCE_STATUSES = STOCK_SUCCESS_STATUSES | {"source_failed"}
STOCK_BUDGET_DEFERRED_STATUSES = STOCK_SUCCESS_STATUSES | {"deferred_budget"}
CRYPTO_TERMINAL_STATUSES = {"closed", "source_absent", "source_invalid"}
CRYPTO_NORMAL_STATUSES = CRYPTO_TERMINAL_STATUSES | {
    "unresolved_coverage",
    "deferred_unresolved_cooldown",
    "deferred_failed_cooldown",
    "not_run_batch_budget",
}
BOND_SUCCESS_STATUSES = {"verified_unchanged", "verified_source_sequence"}
BOND_NORMAL_INCOMPLETE_STATUSES = {
    "source_empty_unverified",
    "deferred_budget",
    "deferred_failure_cooldown",
    "deferred_failure_cooldown_summary",
}
BOND_SOURCE_FAILURE_STATUSES = {"source_failed", "source_invalid"}
BOND_ATTENTION_STATUSES = {
    "source_worker_crashed",
    "verification_failed",
    "managed_preflight_failed",
    "managed_preflight_timed_out",
    "managed_execution_pending",
    "managed_execution_failed",
    "managed_outcome_unknown",
    "post_write_mismatch",
}
ETF_SUCCESS_STATUSES = {"verified_read_only", "applied_and_verified"}
ETF_SOURCE_DEFERRED_STATUSES = {"source_probe_timeout"}
ETF_BUDGET_DEFERRED_STATUSES = {
    "not_started_time_budget_exhausted",
    "not_applied_time_budget_insufficient",
}
ETF_ATTENTION_STATUSES = {
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
    "protected_legacy_after_read_failed",
}
ETF_PROTECTED_SCOPE = {
    "codes_count": 29,
    "codes_sha256": "b8dd0a9d32736f5a7438800ef2b3d8f064e8c446d5eb91f57d801501553cf6fa",
    "nav_rows": 60329,
    "nav_sha256": "59f142e2571d94a4ec1e4b0600c6b82715f3867ea0d641f7820aa32f15cc7268",
    "cache_rows": 357,
    "cache_sha256": "79935043a66b47a84ce986a4a088230eb3d62dd65f390a57b0cf7ec96a7536a7",
}


@dataclass(frozen=True)
class WorkerPaths:
    repo: Path
    backend: Path
    python: Path
    stock_script: Path
    crypto_script: Path
    bond_script: Path
    etf_script: Path
    option_script: Path
    crypto_manifest: Path
    stock_progress: Path
    crypto_progress: Path
    bond_progress: Path
    bond_snapshots: Path
    etf_output_dir: Path
    option_output_dir: Path
    worker_dir: Path
    cursor_file: Path
    lock_file: Path
    runs_dir: Path

    @classmethod
    def for_repo(cls, repo: Path) -> WorkerPaths:
        backend = repo / "src" / "backend"
        worker_dir = repo / "var" / "reports" / "iteration203" / "full-history-recovery-worker"
        return cls(
            repo=repo,
            backend=backend,
            python=backend / ".venv" / "bin" / "python",
            stock_script=backend / "scripts" / "stock_full_history_controller.py",
            crypto_script=backend / "scripts" / "crypto_full_history_recovery.py",
            bond_script=backend / "scripts" / "bond_convertible_history_controller.py",
            etf_script=backend / "scripts" / "backfill_etf_nav_controller.py",
            option_script=backend / "scripts" / "cffex_option_history_controller.py",
            crypto_manifest=repo
            / "var"
            / "reports"
            / "iteration203"
            / "crypto-inception-manifest.json",
            stock_progress=repo
            / "var"
            / "reports"
            / "iteration203"
            / "stock-controller"
            / "progress.jsonl",
            crypto_progress=repo
            / "var"
            / "reports"
            / "iteration203"
            / "crypto-hourly-full-history-progress.jsonl",
            bond_progress=repo
            / "var"
            / "reports"
            / "iteration203"
            / "bond-convertible-history-controller"
            / "progress.jsonl",
            bond_snapshots=repo
            / "var"
            / "reports"
            / "iteration203"
            / "bond-convertible-history-controller"
            / "snapshots",
            etf_output_dir=repo / "var" / "reports" / "iteration203" / "etf_nav_controller",
            option_output_dir=repo
            / "var"
            / "reports"
            / "iteration203"
            / "cffex-option-history-controller",
            worker_dir=worker_dir,
            cursor_file=worker_dir / "cursor.json",
            lock_file=worker_dir / "worker.lock",
            runs_dir=worker_dir / "runs",
        )


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    timed_out: bool = False
    launch_error: str | None = None
    interrupted_by_signal: int | None = None


class _WorkerTermination(Exception):
    def __init__(self, signum: int) -> None:
        super().__init__(f"worker received signal {signum}")
        self.signum = signum


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _validate_asset_order(assets: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = tuple(assets)
    if len(set(normalized)) != len(normalized):
        raise ValueError("--assets cannot contain duplicates")
    if normalized not in ALLOWED_ASSET_ORDERS:
        raise ValueError(
            "--assets must be exactly 'stock crypto', the fixed order "
            "'stock crypto bond etf', or the fixed order 'stock crypto bond etf option'"
        )
    return normalized


def _read_cursor_payload(
    path: Path, assets: tuple[str, ...] = DEFAULT_ASSETS
) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"cursor is unreadable: {type(exc).__name__}"
    if not isinstance(payload, dict):
        return None, "cursor root is not a JSON object; refusing to reset it"
    schema_version = payload.get("schema_version")
    if schema_version == 1:
        allowed_fields = {
            "schema_version",
            "next_asset",
            "last_asset",
            "last_run_id",
            "last_started_at_utc",
            "last_finished_at_utc",
            "last_status",
        }
        if set(payload) - allowed_fields:
            return None, "cursor v1 has unrecognized fields; refusing to reset it"
        if payload.get("next_asset") not in DEFAULT_ASSETS:
            return None, "cursor v1 next_asset is invalid; refusing to reset it"
        if assets == DEFAULT_ASSETS:
            return payload, None
        # A schema-v1 cursor can be losslessly migrated only when opt-in is explicit.
        return payload, None
    if schema_version == 2:
        if assets == DEFAULT_ASSETS:
            return None, "cursor v2 is reserved for the opt-in four-asset registry"
        if assets not in {FOUR_ASSET_ORDER, FIVE_ASSET_ORDER}:
            return None, "cursor v2 is reserved for opt-in four- or five-asset registries"
        allowed_fields = {
            "schema_version",
            "rotation_order",
            "next_asset",
            "last_asset",
            "last_run_id",
            "last_started_at_utc",
            "last_finished_at_utc",
            "last_status",
        }
        if set(payload) - allowed_fields:
            return None, "cursor v2 has unrecognized fields; refusing to reset it"
        rotation_order = payload.get("rotation_order")
        if not isinstance(rotation_order, list) or tuple(rotation_order) != FOUR_ASSET_ORDER:
            return None, "cursor v2 rotation_order is invalid; refusing to reset it"
        if assets == FOUR_ASSET_ORDER:
            if payload.get("next_asset") not in assets:
                return None, "cursor v2 next_asset is invalid; refusing to reset it"
            return payload, None
        if assets == FIVE_ASSET_ORDER:
            if payload.get("next_asset") not in FOUR_ASSET_ORDER:
                return None, "cursor v2 next_asset cannot be preserved in v3; refusing to reset it"
            return payload, None
        return None, "cursor v2 is reserved for the opt-in four-asset registry"
    if schema_version == 3:
        if assets != FIVE_ASSET_ORDER:
            return None, "cursor v3 is reserved for the opt-in five-asset registry"
        allowed_fields = {
            "schema_version",
            "rotation_order",
            "next_asset",
            "last_asset",
            "last_run_id",
            "last_started_at_utc",
            "last_finished_at_utc",
            "last_status",
        }
        if set(payload) - allowed_fields:
            return None, "cursor v3 has unrecognized fields; refusing to reset it"
        rotation_order = payload.get("rotation_order")
        if not isinstance(rotation_order, list) or tuple(rotation_order) != FIVE_ASSET_ORDER:
            return None, "cursor v3 rotation_order does not match --assets; refusing to reset it"
        if payload.get("next_asset") not in FIVE_ASSET_ORDER:
            return None, "cursor v3 next_asset is invalid; refusing to reset it"
        return payload, None
    return None, "cursor schema is unrecognized; refusing to reset it"


def _read_cursor(path: Path, assets: tuple[str, ...] = DEFAULT_ASSETS) -> tuple[str, str | None]:
    payload, error = _read_cursor_payload(path, assets)
    if error:
        return "", error
    if payload is None:
        return assets[0], None
    return str(payload["next_asset"]), None


def _asset_command(asset: str, paths: WorkerPaths, run_dir: Path) -> tuple[list[str], Path]:
    if asset == "stock":
        report = run_dir / "stock-report.json"
        command = [
            str(paths.python),
            str(paths.stock_script),
            "--apply",
            "--max-codes",
            str(STOCK_MAX_CODES),
            "--max-minutes",
            str(STOCK_BATCH_MINUTES),
            "--source-timeout-seconds",
            str(STOCK_SOURCE_TIMEOUT_SECONDS),
            "--retry-cooldown-hours",
            str(RETRY_COOLDOWN_HOURS),
            "--progress",
            str(paths.stock_progress),
            "--report",
            str(report),
        ]
        return command, report
    if asset == "crypto":
        report = run_dir / "crypto-report.json"
        command = [
            str(paths.python),
            str(paths.crypto_script),
            "--apply",
            "--manifest",
            str(paths.crypto_manifest),
            "--intervals",
            "1h",
            "--max-shards",
            str(CRYPTO_MAX_SHARDS),
            "--max-minutes",
            str(CRYPTO_BATCH_MINUTES),
            "--pause-seconds",
            str(CRYPTO_PAUSE_SECONDS),
            "--timeout-seconds",
            str(CRYPTO_TIMEOUT_SECONDS),
            "--retry-cooldown-hours",
            str(RETRY_COOLDOWN_HOURS),
            "--progress-file",
            str(paths.crypto_progress),
            "--output",
            str(report),
        ]
        return command, report
    if asset == "bond":
        report = run_dir / "bond-report.json"
        command = [
            str(paths.python),
            str(paths.bond_script),
            "--apply",
            "--max-codes",
            str(BOND_MAX_CODES),
            "--time-budget-seconds",
            str(BOND_BATCH_SECONDS),
            "--source-timeout-seconds",
            str(BOND_SOURCE_TIMEOUT_SECONDS),
            "--progress-file",
            str(paths.bond_progress),
            "--snapshot-dir",
            str(paths.bond_snapshots),
            "--report",
            str(report),
        ]
        return command, report
    if asset == "etf":
        report = run_dir / "etf-report.json"
        command = [
            str(paths.python),
            str(paths.etf_script),
            "--probe",
            "--apply",
            "--max-codes",
            str(ETF_MAX_CODES),
            "--time-budget-seconds",
            str(ETF_BATCH_SECONDS),
            "--output-dir",
            str(paths.etf_output_dir),
            "--report",
            str(report),
        ]
        return command, report
    if asset == "option":
        report = run_dir / "option-report.json"
        command = [
            str(paths.python),
            str(paths.option_script),
            "--apply",
            "--max-minutes",
            str(OPTION_BATCH_SECONDS // 60),
            "--source-timeout-seconds",
            str(OPTION_SOURCE_TIMEOUT_SECONDS),
            "--progress",
            str(paths.option_output_dir / "progress.jsonl"),
            "--artifacts",
            str(paths.option_output_dir / "snapshots"),
            "--output",
            str(report),
        ]
        return command, report
    raise ValueError(f"unsupported recovery asset {asset!r}")


def _build_plan(paths: WorkerPaths, assets: tuple[str, ...] = DEFAULT_ASSETS) -> dict[str, Any]:
    assets = _validate_asset_order(assets)
    cursor_payload, cursor_error = _read_cursor_payload(paths.cursor_file, assets)
    next_asset = str(cursor_payload["next_asset"]) if cursor_payload else assets[0]
    migration_preview = None
    if (
        cursor_error is None
        and assets == FOUR_ASSET_ORDER
        and cursor_payload is not None
        and cursor_payload.get("schema_version") == 1
    ):
        migration_preview = {
            "from_schema_version": 1,
            "to_schema_version": 2,
            "preserved_next_asset": next_asset,
            "rotation_order": list(assets),
            "plan_writes_cursor": False,
        }
    elif (
        cursor_error is None
        and assets == FIVE_ASSET_ORDER
        and cursor_payload is not None
        and cursor_payload.get("schema_version") in {1, 2}
    ):
        migration_preview = {
            "from_schema_version": cursor_payload["schema_version"],
            "to_schema_version": 3,
            "preserved_next_asset": next_asset,
            "rotation_order": list(assets),
            "plan_writes_cursor": False,
        }
    preview_dir = paths.runs_dir / "<RUN_ID>"
    commands: dict[str, list[str]] = {}
    for asset in assets:
        commands[asset] = _asset_command(asset, paths, preview_dir)[0]
    budgets: dict[str, Any] = {
        "retry_cooldown_hours": RETRY_COOLDOWN_HOURS,
    }
    if "stock" in assets:
        budgets["stock"] = {
            "max_codes": STOCK_MAX_CODES,
            "batch_minutes": STOCK_BATCH_MINUTES,
            "per_code_source_timeout_seconds": STOCK_SOURCE_TIMEOUT_SECONDS,
            "outer_wall_seconds": int(STOCK_BATCH_MINUTES * 60) + OUTER_TIMEOUT_GRACE_SECONDS,
            "progress_file": str(paths.stock_progress),
        }
    if "crypto" in assets:
        budgets["crypto_hourly"] = {
            "max_shards": CRYPTO_MAX_SHARDS,
            "batch_minutes": CRYPTO_BATCH_MINUTES,
            "minimum_pause_seconds": CRYPTO_PAUSE_SECONDS,
            "per_shard_timeout_seconds": CRYPTO_TIMEOUT_SECONDS,
            "outer_wall_seconds": int(CRYPTO_BATCH_MINUTES * 60) + OUTER_TIMEOUT_GRACE_SECONDS,
            "progress_file": str(paths.crypto_progress),
            "manifest": str(paths.crypto_manifest),
        }
    if "bond" in assets:
        budgets["bond_convertible"] = {
            "max_codes": BOND_MAX_CODES,
            "time_budget_seconds": BOND_BATCH_SECONDS,
            "source_timeout_seconds": BOND_SOURCE_TIMEOUT_SECONDS,
            "outer_wall_seconds": BOND_BATCH_SECONDS + OUTER_TIMEOUT_GRACE_SECONDS,
            "progress_file": str(paths.bond_progress),
            "snapshot_dir": str(paths.bond_snapshots),
        }
    if "etf" in assets:
        budgets["etf_nav"] = {
            "max_codes": ETF_MAX_CODES,
            "time_budget_seconds": ETF_BATCH_SECONDS,
            "outer_wall_seconds": ETF_BATCH_SECONDS + OUTER_TIMEOUT_GRACE_SECONDS,
            "canonical_output_dir": str(paths.etf_output_dir),
            "fresh_sina_listing_probe_outside_scheduler_gate": True,
        }
    if "option" in assets:
        budgets["cffex_option_archive"] = {
            "months_per_run": 1,
            "soft_time_budget_seconds": OPTION_BATCH_SECONDS,
            "source_timeout_seconds": OPTION_SOURCE_TIMEOUT_SECONDS,
            "outer_wall_seconds": OPTION_OUTER_TIMEOUT_SECONDS,
            "progress_file": str(paths.option_output_dir / "progress.jsonl"),
            "snapshot_dir": str(paths.option_output_dir / "snapshots"),
            "unique_report_per_run": True,
            "source_lifecycle_and_calendar_completeness": "unknown",
        }
    safety = [
        "The worker does not call get_akshare_scheduler().start() or create an APScheduler.",
        "A host-local nonblocking flock makes concurrent worker invocations a successful skip.",
        "A hard timeout or worker termination signal drains the CLI process group and records write_possible=true without inventing a source failure or controller cooldown record.",
        "Bounded batch completion does not certify complete full-history coverage.",
    ]
    if "stock" in assets:
        safety.append(
            "The stock CLI receives no explicit symbol subset, so its own source-universe freshness and fair-cursor checks remain active."
        )
    if "crypto" in assets:
        safety.append(
            "Crypto open/unresolved gaps are expected incomplete work; only verified closure is counted as closed."
        )
    if "etf" in assets:
        safety.append(
            "ETF refreshes the Sina listing before managed work, outside the shared scheduler gate; this bounded network request is recorded and is not called full-history proof."
        )
    if "option" in assets:
        safety.append(
            "CFFEX option work is one exact archive month per invocation; source snapshot verification does not certify calendar, contract lifecycle, or global full-history completeness."
        )
    return {
        "mode": "plan",
        "exit_code": 2 if cursor_error else 0,
        "read_only": True,
        "attention_required": cursor_error is not None,
        "source_or_database_calls": 0,
        "scheduler_started": False,
        "assets": list(assets),
        "rotation_order": list(assets),
        "next_asset": next_asset or None,
        "cursor_file": str(paths.cursor_file),
        "cursor_status": "default_stock"
        if cursor_error is None and not paths.cursor_file.exists()
        else (
            "valid_v1_migration_preview"
            if migration_preview is not None
            and migration_preview["from_schema_version"] == 1
            and assets == FOUR_ASSET_ORDER
            else (
                f"valid_v{migration_preview['from_schema_version']}_to_v3_migration_preview"
                if migration_preview is not None and assets == FIVE_ASSET_ORDER
                else ("valid" if cursor_error is None else "invalid")
            )
        ),
        "cursor_error": cursor_error,
        "cursor_migration_preview": migration_preview,
        "commands": commands,
        "budgets": budgets,
        "rotation": "One CLI batch per invocation; cursor advances before dispatch so interruption does not starve another registered asset.",
        "safety": safety,
    }


def _create_run_directory(paths: WorkerPaths, run_id: str) -> Path:
    paths.runs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir = paths.runs_dir / run_id
    run_dir.mkdir(mode=0o700, exist_ok=False)
    if run_dir.stat().st_uid != os.getuid() or run_dir.stat().st_mode & 0o077:
        raise PermissionError("run directory must be owned by the service user and private")
    return run_dir


def _acquire_lock(path: Path) -> int | None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    info = os.fstat(fd)
    if info.st_uid != os.getuid():
        os.close(fd)
        raise PermissionError("worker lock is not owned by the service user")
    os.fchmod(fd, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    process_group_id = process.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        pass

    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    while _process_group_exists(process_group_id) and time.monotonic() < deadline:
        # poll() also reaps the group leader if it has exited. The group may
        # still contain a source collector that ignored SIGTERM.
        process.poll()
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    if _process_group_exists(process_group_id):
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:  # pragma: no cover - kernel process teardown failure
        pass


def _execute_cli(command: list[str], run_dir: Path, timeout_seconds: int) -> ProcessResult:
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    process: subprocess.Popen[bytes] | None = None
    previous_handlers: dict[int, Any] = {}

    def terminate_worker(signum: int, _frame: Any) -> None:
        raise _WorkerTermination(signum)

    try:
        with stdout_path.open("xb") as stdout_stream, stderr_path.open("xb") as stderr_stream:
            try:
                for signum in (signal.SIGTERM, signal.SIGINT):
                    previous_handlers[signum] = signal.signal(signum, terminate_worker)
                process = subprocess.Popen(
                    command,
                    cwd=BACKEND_ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    start_new_session=True,
                )
                try:
                    return ProcessResult(returncode=process.wait(timeout=timeout_seconds))
                except subprocess.TimeoutExpired:
                    _kill_process_group(process)
                    return ProcessResult(returncode=process.returncode, timed_out=True)
            finally:
                for signum, previous_handler in previous_handlers.items():
                    signal.signal(signum, previous_handler)
    except _WorkerTermination as exc:
        # A signal can arrive before or during Popen/wait. Cleanup covers the
        # entire process group even if the CLI leader has already exited.
        if process is not None:
            for signum in (signal.SIGTERM, signal.SIGINT):
                signal.signal(signum, signal.SIG_IGN)
            try:
                _kill_process_group(process)
            finally:
                for signum, previous_handler in previous_handlers.items():
                    signal.signal(signum, previous_handler)
        return ProcessResult(
            returncode=process.returncode if process is not None else None,
            interrupted_by_signal=exc.signum,
        )
    except OSError as exc:
        stderr_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        return ProcessResult(returncode=None, launch_error=type(exc).__name__)


def _load_report(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "expected CLI report was not created"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"CLI report is unreadable: {type(exc).__name__}"
    if not isinstance(payload, dict):
        return None, "CLI report root is not a JSON object"
    return payload, None


def _classify_stock(returncode: int, report: dict[str, Any]) -> tuple[str, bool, list[str]]:
    if report.get("mode") != "apply" or not isinstance(report.get("outcomes"), list):
        return "attention_required", True, ["stock CLI report does not match the apply contract"]
    statuses = [
        str(row.get("status", "unknown")) for row in report["outcomes"] if isinstance(row, dict)
    ]
    if len(statuses) != len(report["outcomes"]):
        return "attention_required", True, ["stock CLI report contains a malformed outcome"]
    known_statuses = STOCK_SUCCESS_STATUSES | {
        "source_failed",
        "deferred_budget",
        "deferred_scheduler_budget",
        "verification_failed",
        "backfill_failed",
        "unresolved_difference",
        "source_worker_crashed",
    }
    unknown = sorted(set(statuses) - known_statuses)
    if unknown:
        return "attention_required", True, [f"unhandled stock outcome statuses: {unknown}"]
    status_set = set(statuses)
    if "source_failed" in status_set:
        if returncode == 2 and status_set <= STOCK_RETRYABLE_SOURCE_STATUSES:
            return (
                "source_failed_retryable",
                False,
                ["source failures remain in the controller's cooldown progress"],
            )
        return (
            "attention_required",
            True,
            ["stock source failure did not match the known CLI exit contract"],
        )
    if returncode == 3 and "deferred_budget" in status_set:
        if status_set <= STOCK_BUDGET_DEFERRED_STATUSES:
            return (
                "deferred_budget_retryable",
                False,
                [
                    "the stock controller exhausted its batch budget; deferred symbols remain pending"
                ],
            )
        return (
            "attention_required",
            True,
            ["stock budget deferral was mixed with a non-budget outcome"],
        )
    if status_set & {
        "deferred_budget",
        "deferred_scheduler_budget",
        "verification_failed",
        "backfill_failed",
        "unresolved_difference",
        "source_worker_crashed",
    }:
        return "attention_required", True, ["stock outcomes include a deferred or failed status"]
    if returncode != 0:
        return "attention_required", True, [f"stock CLI returned unexpected exit code {returncode}"]
    return "completed", False, []


def _classify_crypto(returncode: int, report: dict[str, Any]) -> tuple[str, bool, list[str]]:
    summary = report.get("apply_summary")
    outcomes = report.get("apply")
    if not isinstance(summary, dict) or not isinstance(outcomes, list):
        return "attention_required", True, ["crypto CLI report does not match the apply contract"]
    statuses = [str(row.get("status", "unknown")) for row in outcomes if isinstance(row, dict)]
    if len(statuses) != len(outcomes):
        return "attention_required", True, ["crypto CLI report contains a malformed outcome"]
    terminal_counts = [summary.get(status, 0) for status in CRYPTO_TERMINAL_STATUSES]
    if any(type(count) is not int or count < 0 for count in terminal_counts):
        return "attention_required", True, ["crypto terminal shard counts are malformed"]
    terminal_count = sum(terminal_counts)
    open_count = sum(status not in CRYPTO_TERMINAL_STATUSES for status in statuses)
    if summary.get("open") != open_count:
        return "attention_required", True, ["crypto open count disagrees with individual outcomes"]
    plan_open = summary.get("plan_open_remaining_shards", open_count)
    if type(plan_open) is not int or plan_open < 0:
        return "attention_required", True, ["crypto plan-open shard count is malformed"]
    planned_shards = summary.get("planned_shards")
    if planned_shards is not None:
        if (
            type(planned_shards) is not int
            or planned_shards < terminal_count
            or plan_open != planned_shards - terminal_count
        ):
            return (
                "attention_required",
                True,
                ["crypto plan-open count disagrees with planned and terminal shard counts"],
            )
    if open_count > plan_open:
        return (
            "attention_required",
            True,
            ["crypto selected open count exceeds the remaining planned shard count"],
        )
    unexpected = sorted(set(statuses) - CRYPTO_NORMAL_STATUSES)
    if unexpected:
        return "attention_required", True, [f"crypto outcomes need review: {unexpected}"]
    expected_exit = 1 if plan_open else 0
    if returncode != expected_exit:
        return (
            "attention_required",
            True,
            [f"crypto CLI exit {returncode} disagrees with its remaining={plan_open} contract"],
        )
    if plan_open:
        return (
            "incomplete_open_shards",
            False,
            [
                f"{open_count} selected crypto shards remain open; "
                f"{plan_open} planned shards remain outside the closed set"
            ],
        )
    return "completed", False, []


def _classify_bond(returncode: int, report: dict[str, Any]) -> tuple[str, bool, list[str]]:
    if (
        report.get("report_type") != "bond-convertible-history-controller-v1"
        or report.get("mode") != "managed_bounded_convertible_history_reconciliation"
        or not isinstance(report.get("outcomes"), list)
    ):
        return (
            "attention_required",
            True,
            ["convertible-bond report does not match its apply contract"],
        )
    outcomes = report["outcomes"]
    if len(outcomes) > BOND_MAX_CODES:
        return (
            "attention_required",
            True,
            ["convertible-bond report exceeds the configured per-run symbol limit"],
        )
    if outcomes:
        expected_limits = {
            "max_codes": BOND_MAX_CODES,
            "time_budget_seconds": BOND_BATCH_SECONDS,
            "source_timeout_seconds_max": BOND_SOURCE_TIMEOUT_SECONDS,
        }
        if any(report.get(key) != expected for key, expected in expected_limits.items()):
            return (
                "attention_required",
                True,
                ["convertible-bond report limits differ from the worker's bounded command"],
            )
    elif report.get("status") in {"no_runnable_candidates", "no_inventory_candidates"}:
        if (
            report.get("apply_max_codes") != BOND_MAX_CODES
            or report.get("source_requests_made") is not False
            or report.get("writes_database") is not False
        ):
            return (
                "attention_required",
                True,
                ["empty convertible-bond run lacks the expected no-work evidence"],
            )
    else:
        return (
            "attention_required",
            True,
            ["convertible-bond report has no outcomes and no recognized no-work status"],
        )
    if any(not isinstance(row, dict) or not isinstance(row.get("status"), str) for row in outcomes):
        return "attention_required", True, ["convertible-bond report contains a malformed outcome"]
    statuses = [str(row["status"]) for row in outcomes]
    known = (
        BOND_SUCCESS_STATUSES
        | BOND_NORMAL_INCOMPLETE_STATUSES
        | BOND_SOURCE_FAILURE_STATUSES
        | BOND_ATTENTION_STATUSES
    )
    unknown = sorted(set(statuses) - known)
    if unknown:
        return "attention_required", True, [f"unhandled convertible-bond outcomes: {unknown}"]

    status_set = set(statuses)
    if returncode == 1:
        retryable = BOND_SUCCESS_STATUSES | BOND_SOURCE_FAILURE_STATUSES
        if (
            "controller_failed" not in status_set
            and "source_worker_crashed" not in status_set
            and status_set & BOND_SOURCE_FAILURE_STATUSES
            and status_set <= retryable
        ):
            return (
                "source_failed_retryable",
                False,
                [
                    "the controller recorded only a real source failure/invalid response; managed and verification outcomes are absent"
                ],
            )
        return (
            "attention_required",
            True,
            ["convertible-bond exit 1 includes non-source or unclassified failure"],
        )
    if status_set & BOND_ATTENTION_STATUSES:
        return (
            "attention_required",
            True,
            ["convertible-bond outcomes include infrastructure, managed, or verification failure"],
        )
    if (
        returncode == 3
        and statuses
        and status_set <= (BOND_SUCCESS_STATUSES | BOND_NORMAL_INCOMPLETE_STATUSES)
    ):
        if status_set & {"deferred_budget"}:
            return (
                "deferred_budget_retryable",
                False,
                ["convertible-bond symbol work remains deferred by its batch budget"],
            )
        return (
            "source_deferred",
            False,
            ["convertible-bond source scope remains unresolved or cooling down"],
        )
    if (
        returncode == 3
        and not statuses
        and report.get("status") in {"no_runnable_candidates", "no_inventory_candidates"}
    ):
        return (
            "source_deferred",
            False,
            ["no convertible-bond code was eligible in this bounded run"],
        )
    if returncode == 0 and statuses and status_set <= BOND_SUCCESS_STATUSES:
        return (
            "batch_reconciled_history_incomplete",
            False,
            [
                "the selected convertible-bond batch matched fresh SQL; global source retention and full-history scope remain uncertified"
            ],
        )
    return (
        "attention_required",
        True,
        [f"convertible-bond exit {returncode} disagrees with outcome statuses"],
    )


def _classify_etf(returncode: int, report: dict[str, Any]) -> tuple[str, bool, list[str]]:
    run_event = report.get("run_event")
    outcomes = report.get("outcomes")
    if (
        report.get("schema_version") != "etf-nav-controller-run-report-v1"
        or report.get("report_type") != "etf_nav_controller_run"
        or not isinstance(run_event, dict)
        or not isinstance(outcomes, list)
    ):
        return (
            "attention_required",
            True,
            ["ETF report does not match the immutable per-run report contract"],
        )
    run_id = report.get("run_id")
    if (
        not isinstance(run_id, str)
        or len(run_id) != 32
        or any(character not in "0123456789abcdef" for character in run_id)
        or run_event.get("run_id") != run_id
        or any(not isinstance(row, dict) or row.get("run_id") != run_id for row in outcomes)
    ):
        return (
            "attention_required",
            True,
            ["ETF run_id does not bind the summary and every outcome"],
        )
    if (
        run_event.get("mode") != "apply"
        or run_event.get("apply_enabled") is not True
        or run_event.get("network_used") is not True
        or run_event.get("max_codes") != ETF_MAX_CODES
        or run_event.get("time_budget_seconds") != ETF_BATCH_SECONDS
        or run_event.get("full_history_complete") is not False
    ):
        return (
            "attention_required",
            True,
            ["ETF terminal run event does not match the bounded apply contract"],
        )
    if returncode != 0:
        return (
            "attention_required",
            True,
            [f"ETF controller returned unexpected exit code {returncode}"],
        )

    refresh_error = run_event.get("sina_refresh_error")
    snapshot = run_event.get("current_sina_snapshot")
    probe_ready = (
        report.get("fresh_sina_probe_ready") is True
        and run_event.get("probe_ready") is True
        and isinstance(snapshot, dict)
        and snapshot.get("complete") is True
        and isinstance(snapshot.get("source_row_count"), int)
        and snapshot.get("source_row_count", 0) > 0
        and isinstance(snapshot.get("unique_code_count"), int)
        and snapshot.get("unique_code_count", 0) > 0
        and snapshot.get("unique_code_count", 0) <= snapshot.get("source_row_count", 0)
        and isinstance(run_event.get("current_sina_snapshot_path"), str)
        and bool(run_event.get("current_sina_snapshot_path"))
        and refresh_error is None
    )
    if not probe_ready:
        if refresh_error and not outcomes and run_event.get("processed_codes") == 0:
            return (
                "source_deferred",
                False,
                [
                    "fresh Sina listing refresh failed; no fund-history probe was treated as complete"
                ],
            )
        return (
            "attention_required",
            True,
            ["ETF fresh listing probe is absent, partial, or inconsistent"],
        )

    selected = run_event.get("selected_codes")
    if (
        not isinstance(selected, list)
        or len(selected) > ETF_MAX_CODES
        or any(not isinstance(code, str) for code in selected)
        or len(set(selected)) != len(selected)
        or report.get("selected_codes") != selected
    ):
        return (
            "attention_required",
            True,
            ["ETF selected-code evidence is malformed or exceeds the bounded batch"],
        )
    listing_evidence = run_event.get("selected_listing_evidence")
    if (
        not isinstance(listing_evidence, list)
        or report.get("selected_listing_evidence") != listing_evidence
        or len(listing_evidence) != len(selected)
    ):
        return (
            "attention_required",
            True,
            ["ETF fresh listing identity evidence is missing or inconsistent"],
        )
    listing_by_code: dict[str, dict[str, Any]] = {}
    for item in listing_evidence:
        if not isinstance(item, dict) or not isinstance(item.get("fund_code"), str):
            return (
                "attention_required",
                True,
                ["ETF selected listing evidence contains a malformed row"],
            )
        code = item["fund_code"]
        if code in listing_by_code:
            return (
                "attention_required",
                True,
                ["ETF selected listing evidence contains duplicate codes"],
            )
        listing_by_code[code] = item
        identity_status = item.get("product_identity_status")
        identity_proven = identity_status in {
            "verified_by_sina_etf_node",
            "verified_by_etf_daily_master",
            "verified_by_reviewed_lifecycle_manifest",
        }
        if (
            item.get("eligible_for_nav_probe") is not True
            or item.get("lifecycle_identity_conflict") is True
            or not identity_proven
            or not (
                item.get("current_sina_node_member") is True
                or bool(item.get("reviewed_lifecycle"))
                or identity_status == "verified_by_etf_daily_master"
            )
        ):
            return (
                "attention_required",
                True,
                [f"ETF code {code} lacks reviewed listing/product identity"],
            )
    if set(listing_by_code) != set(selected):
        return (
            "attention_required",
            True,
            ["ETF listing evidence does not cover the exact selected codes"],
        )
    if any(
        row.get("event") != "nav_probe" or row.get("fund_code") not in selected for row in outcomes
    ):
        return (
            "attention_required",
            True,
            ["ETF outcome list contains a foreign or malformed code event"],
        )
    outcome_codes = [row.get("fund_code") for row in outcomes]
    if len(set(outcome_codes)) != len(outcome_codes):
        return "attention_required", True, ["ETF run contains duplicate per-code outcomes"]
    if set(outcome_codes) != set(selected):
        return (
            "attention_required",
            True,
            ["ETF outcomes do not cover every selected code exactly once"],
        )
    processed_codes = run_event.get("processed_codes")
    if not isinstance(processed_codes, int) or processed_codes < 0:
        return "attention_required", True, ["ETF processed count is missing or invalid"]
    not_started = sum(row.get("status") == "not_started_time_budget_exhausted" for row in outcomes)
    if processed_codes != len(outcomes) - not_started:
        return (
            "attention_required",
            True,
            ["ETF processed count disagrees with this run's outcome events"],
        )

    for row in outcomes:
        if row.get("status") not in ETF_SUCCESS_STATUSES:
            continue
        has_hashes = all(
            isinstance(row.get(key), str)
            and len(row[key]) == 64
            and all(character in "0123456789abcdef" for character in row[key])
            for key in ("business_keys_sha256", "values_sha256", "snapshot_sha256")
        )
        if (
            row.get("source_complete") is not True
            or not isinstance(row.get("provider"), str)
            or not row.get("provider")
            or not isinstance(row.get("source_snapshot_path"), str)
            or not row.get("source_snapshot_path")
            or not has_hashes
            or not isinstance(row.get("diff_after"), dict)
            or row["diff_after"].get("exact_match") is not True
        ):
            return (
                "attention_required",
                True,
                ["ETF success outcome lacks source hashes and exact fresh-SQL proof"],
            )
        if row.get("status") == "applied_and_verified":
            execution = row.get("scheduler_execution")
            if (
                not isinstance(execution, dict)
                or str(execution.get("status", "")).casefold() != "completed"
                or execution.get("error_message")
            ):
                return (
                    "attention_required",
                    True,
                    ["ETF applied outcome lacks a completed managed execution"],
                )

    statuses = [row.get("status") for row in outcomes]
    known = (
        ETF_SUCCESS_STATUSES
        | ETF_SOURCE_DEFERRED_STATUSES
        | ETF_BUDGET_DEFERRED_STATUSES
        | ETF_ATTENTION_STATUSES
    )
    unknown = sorted({str(status) for status in statuses if status not in known})
    if unknown:
        return "attention_required", True, [f"unhandled ETF outcome statuses: {unknown}"]

    protection = run_event.get("protected_legacy_scope")
    if not isinstance(protection, dict):
        return "attention_required", True, ["ETF protected legacy scope evidence is missing"]
    expected_protection = {
        "codes_count": ETF_PROTECTED_SCOPE["codes_count"],
        "codes_sha256": ETF_PROTECTED_SCOPE["codes_sha256"],
        "expected_nav_rows": ETF_PROTECTED_SCOPE["nav_rows"],
        "expected_nav_sha256": ETF_PROTECTED_SCOPE["nav_sha256"],
        "expected_cache_rows": ETF_PROTECTED_SCOPE["cache_rows"],
        "expected_cache_sha256": ETF_PROTECTED_SCOPE["cache_sha256"],
    }
    if any(protection.get(key) != value for key, value in expected_protection.items()):
        return (
            "attention_required",
            True,
            ["ETF protected legacy baseline differs from the reviewed scope"],
        )
    checks = protection.get("checks")
    if not isinstance(checks, list) or any(not isinstance(check, dict) for check in checks):
        return "attention_required", True, ["ETF protected legacy checks are malformed"]
    if any(check.get("status") != "before_and_after_match" for check in checks):
        return "attention_required", True, ["ETF protected legacy before/after check failed"]
    for check in checks:
        for snapshot_key in ("before", "after"):
            value = check.get(snapshot_key)
            if not isinstance(value, dict) or any(
                value.get(key) != expected
                for key, expected in (
                    ("protected_scope_codes_count", ETF_PROTECTED_SCOPE["codes_count"]),
                    ("protected_scope_codes_sha256", ETF_PROTECTED_SCOPE["codes_sha256"]),
                    ("protected_legacy_nav_rows", ETF_PROTECTED_SCOPE["nav_rows"]),
                    ("protected_legacy_nav_sha256", ETF_PROTECTED_SCOPE["nav_sha256"]),
                    ("protected_cache_rows", ETF_PROTECTED_SCOPE["cache_rows"]),
                    ("protected_cache_sha256", ETF_PROTECTED_SCOPE["cache_sha256"]),
                )
            ):
                return (
                    "attention_required",
                    True,
                    ["ETF protected legacy check does not match the frozen baseline"],
                )
    managed_codes = {
        row["fund_code"] for row in outcomes if isinstance(row.get("scheduler_execution"), dict)
    }
    protected_codes = {check.get("fund_code") for check in checks}
    if not managed_codes <= protected_codes:
        return (
            "attention_required",
            True,
            ["ETF managed dispatch lacks a matching protected legacy before/after check"],
        )

    status_set = set(statuses)
    if status_set & ETF_ATTENTION_STATUSES:
        return (
            "attention_required",
            True,
            [
                "ETF outcomes include source-semantic, managed, verification, or legacy-scope attention"
            ],
        )
    if status_set & ETF_BUDGET_DEFERRED_STATUSES:
        return (
            "deferred_budget_retryable",
            False,
            ["ETF per-code work remains deferred by its bounded time budget"],
        )
    if status_set & ETF_SOURCE_DEFERRED_STATUSES:
        return (
            "source_deferred",
            False,
            ["ETF history source probe timed out; no source failure cooldown was fabricated"],
        )
    if statuses and status_set <= ETF_SUCCESS_STATUSES:
        return (
            "batch_reconciled_history_incomplete",
            False,
            [
                "the selected ETF NAV batch matched source and fresh SQL; unknown listing boundaries and global full-history scope remain open"
            ],
        )
    if not statuses and selected == [] and run_event.get("processed_codes") == 0:
        return (
            "deferred_no_candidates",
            False,
            ["no eligible ETF code was selected in this bounded run"],
        )
    return "attention_required", True, ["ETF run has no recognized terminal outcome"]


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _private_regular_file(path: Path, expected: Path) -> bytes | None:
    """Read one expected private artifact without following aliases or symlinks."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        resolved = path.resolve(strict=True)
        if resolved != expected:
            return None
        file_stat = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(file_stat.st_mode):
            return None
        if file_stat.st_uid != os.getuid() or file_stat.st_mode & 0o077:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _option_capture_matches(
    result: dict[str, Any], *, artifact_root: Path, month: str, run_id: str
) -> tuple[bool, str | None]:
    capture = result.get("wire_capture")
    if not isinstance(capture, dict):
        return False, "option wire capture manifest is absent"
    required = {
        "schema_version": 1,
        "run_id": run_id,
        "month": month,
        "expected_url": OPTION_SOURCE_URL_TEMPLATE.format(month=month),
        "requested_url": OPTION_SOURCE_URL_TEMPLATE.format(month=month),
        "final_url": OPTION_SOURCE_URL_TEMPLATE.format(month=month),
        "request_count": 1,
        "status_code": 200,
        "body_complete": True,
        "transport_verifiable": True,
        "capture_error": None,
        "redirect_chain": [],
        "recording_semantics": "same real iter_content bytes delivered to the existing strict parser",
    }
    if any(capture.get(key) != value for key, value in required.items()):
        return False, "option capture does not prove one exact successful month request"
    body_sha = capture.get("body_sha256")
    manifest_sha = capture.get("manifest_sha256")
    body_bytes = capture.get("body_bytes")
    if (
        not _is_sha256(body_sha)
        or not _is_sha256(manifest_sha)
        or not isinstance(body_bytes, int)
        or isinstance(body_bytes, bool)
        or not 0 < body_bytes <= OPTION_MAX_ARCHIVE_BYTES
    ):
        return False, "option capture has invalid body size or digest metadata"

    try:
        root = artifact_root.resolve(strict=True)
    except OSError:
        return False, "option snapshot root is unavailable"
    if artifact_root.is_symlink():
        return False, "option snapshot root must not be a symlink"
    capture_dir = root / month / run_id
    body_path = capture_dir / "source-response.zip"
    manifest_path = capture_dir / "wire-capture.json"
    if capture.get("body_path") != str(body_path) or capture.get("manifest_path") != str(
        manifest_path
    ):
        return (
            False,
            "option capture paths do not match the fixed month/run snapshot layout",
        )
    for path in (root / month, capture_dir):
        if path.is_symlink():
            return False, "option snapshot directory contains a symlink"
        try:
            resolved_path = path.resolve(strict=True)
        except OSError:
            return False, "option snapshot directory is missing"
        if resolved_path != path:
            return False, "option snapshot directory resolves outside its fixed layout"
        try:
            directory_stat = path.stat(follow_symlinks=False)
        except OSError:
            return False, "option snapshot directory cannot be inspected"
        if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_uid != os.getuid():
            return False, "option snapshot directory is not a service-owned directory"
        if path == capture_dir and directory_stat.st_mode & 0o077:
            return False, "option capture run directory is not private"
    body = _private_regular_file(body_path, body_path)
    manifest_bytes = _private_regular_file(manifest_path, manifest_path)
    if body is None or manifest_bytes is None:
        return False, "option body or manifest is missing, aliased, or not private"
    if len(body) != body_bytes or hashlib.sha256(body).hexdigest() != body_sha:
        return (
            False,
            "option persisted response body does not match its reported digest",
        )
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha:
        return (
            False,
            "option persisted capture manifest does not match its reported digest",
        )
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, "option persisted capture manifest is invalid JSON"
    if not isinstance(manifest, dict):
        return False, "option persisted capture manifest is not an object"
    if any(
        manifest.get(key) != value
        for key, value in required.items()
        if key != "transport_verifiable"
    ):
        return (
            False,
            "option persisted manifest disagrees with the report's request identity",
        )
    if (
        manifest.get("body_bytes") != body_bytes
        or manifest.get("body_sha256") != body_sha
        or manifest.get("body_path") != str(body_path)
        or manifest.get("transport_verifiable") is not True
    ):
        return (
            False,
            "option persisted manifest does not bind the captured response body",
        )
    if any(capture.get(key) != value for key, value in manifest.items()):
        return (
            False,
            "option reported capture metadata differs from its persisted manifest",
        )
    return True, None


def _classify_option(
    returncode: int, report: dict[str, Any], *, artifact_root: Path
) -> tuple[str, bool, list[str]]:
    if report.get("mode") != "apply":
        return (
            "attention_required",
            True,
            ["option controller report is not an apply report"],
        )
    result = report.get("result")
    if result is None and report.get("status") == "no_eligible_month":
        selection = report.get("selection")
        if (
            returncode == 0
            and report.get("selected_month") is None
            and isinstance(selection, dict)
            and selection.get("selected_month") is None
            and selection.get("source_lifecycle") == "unknown"
            and selection.get("candidate_start_is_inception") is False
        ):
            return (
                "source_deferred",
                False,
                ["no eligible CFFEX option month was selected"],
            )
        return (
            "attention_required",
            True,
            ["option no-work report lacks the controller's exact contract"],
        )
    if not isinstance(result, dict):
        return (
            "attention_required",
            True,
            ["option controller result is missing or malformed"],
        )

    status = result.get("status")
    if status in OPTION_SOURCE_FAILURE_STATUSES:
        if (
            returncode == 1
            and result.get("preimage_unchanged_after_failed_month") is True
            and result.get("source_failure_cooldown_hours") == RETRY_COOLDOWN_HOURS
            and result.get("failure_phase") in {"archive_parse_or_capture", None}
            and not (
                isinstance(result.get("execution"), dict)
                and result["execution"].get("status") == "completed"
            )
        ):
            return (
                "source_failed_retryable",
                False,
                [
                    f"CFFEX source returned {status}; month remains unverified and is cooled down by its controller"
                ],
            )
        return (
            "attention_required",
            True,
            ["option source failure does not match the strict retryable contract"],
        )
    if status == "deferred_budget":
        if (
            returncode == 1
            and result.get("failure_phase") == "wall_clock_budget_before_managed_dispatch"
            and result.get("execution") is None
            and result.get("database_write_possible") is False
            and result.get("timed_out") is False
        ):
            return (
                "deferred_budget_retryable",
                False,
                ["option month was deferred before managed dispatch by its time budget"],
            )
        return (
            "attention_required",
            True,
            ["option budget deferral does not match the pre-dispatch contract"],
        )
    if status != OPTION_SUCCESS_STATUS:
        return (
            "attention_required",
            True,
            [f"option month ended with nonverified status {status!r}"],
        )
    if returncode != 0:
        return (
            "attention_required",
            True,
            [f"verified option month has unexpected CLI exit code {returncode}"],
        )

    month = result.get("month")
    run_id = result.get("run_id")
    if (
        not isinstance(month, str)
        or len(month) != 6
        or not month.isdigit()
        or not isinstance(run_id, str)
        or len(run_id) != 32
        or any(character not in "0123456789abcdef" for character in run_id)
    ):
        return (
            "attention_required",
            True,
            ["verified option month has invalid month/run identity"],
        )
    selection = report.get("selection")
    if not isinstance(selection, dict) or selection.get("selected_month") != month:
        return (
            "attention_required",
            True,
            ["option selection and verified month do not agree"],
        )
    if (
        result.get("candidate_start_month_is_inception") is not False
        or result.get("candidate_inception_verified") is not False
        or result.get("source_complete") is not False
        or result.get("source_sequence_complete") is not True
        or result.get("calendar_coverage") != "unknown"
        or result.get("month_calendar_coverage_verified") is not False
        or result.get("contract_lifecycle") != "unknown"
        or result.get("source_lifecycle") != "unknown"
        or result.get("archive_snapshot_verified") is not True
        or result.get("request_scope")
        != "one exact full calendar month archive; no trading calendar imputation"
        or result.get("independent_parse_error") is not None
        or result.get("post_sql_read_error") is not None
        or result.get("timed_out") is not False
    ):
        return (
            "attention_required",
            True,
            ["option verified status overstates or lacks its bounded evidence"],
        )
    budget = result.get("execution_budget")
    if (
        not isinstance(budget, dict)
        or budget.get("kind") != "soft_total_wall_budget"
        or budget.get("seconds") != OPTION_BATCH_SECONDS
        or budget.get("recommended_outer_timeout_seconds") != OPTION_OUTER_TIMEOUT_SECONDS
        or budget.get("outer_process_hard_stop_required") is not True
    ):
        return (
            "attention_required",
            True,
            ["option execution budget does not match the worker's bounded contract"],
        )

    dispatch = result.get("dispatch")
    registration = dispatch.get("registration") if isinstance(dispatch, dict) else None
    parameters = dispatch.get("parameters") if isinstance(dispatch, dict) else None
    try:
        month_start = datetime.strptime(month, "%Y%m").date().replace(day=1)
        expected_start = month_start.strftime("%Y%m%d")
        expected_end = (
            f"{month_start.year:04d}{month_start.month:02d}"
            f"{monthrange(month_start.year, month_start.month)[1]:02d}"
        )
    except ValueError:
        return (
            "attention_required",
            True,
            ["verified option month is not a valid calendar month"],
        )
    claim_key = dispatch.get("claim_key") if isinstance(dispatch, dict) else None
    parameter_hash = dispatch.get("parameter_hash") if isinstance(dispatch, dict) else None
    expected_registration = {
        "script_id": "cffex_option_daily_history",
        "source": "cffex",
        "module_path": "app.data_fetch.scripts.options.daily.cffex_option_daily_history",
        "function_name": "main",
        "target_table": OPTION_TABLE_NAME,
    }
    try:
        raw_source_timeout = (
            parameters.get("source_timeout_seconds") if isinstance(parameters, dict) else None
        )
        source_timeout = float(raw_source_timeout)
        if isinstance(raw_source_timeout, bool):
            source_timeout = -1
    except (TypeError, ValueError, OverflowError):
        source_timeout = -1
    try:
        managed_timeout = (
            int(dispatch.get("managed_timeout_seconds")) if isinstance(dispatch, dict) else -1
        )
        outer_wait_timeout = (
            int(dispatch.get("outer_wait_timeout_seconds")) if isinstance(dispatch, dict) else -1
        )
        if isinstance(dispatch, dict) and (
            isinstance(dispatch.get("managed_timeout_seconds"), bool)
            or str(managed_timeout) != str(dispatch.get("managed_timeout_seconds"))
            or isinstance(dispatch.get("outer_wait_timeout_seconds"), bool)
            or str(outer_wait_timeout) != str(dispatch.get("outer_wait_timeout_seconds"))
        ):
            managed_timeout = outer_wait_timeout = -1
    except (TypeError, ValueError, OverflowError):
        managed_timeout = outer_wait_timeout = -1
    if (
        registration != expected_registration
        or not isinstance(parameters, dict)
        or parameters.get("start_date") != expected_start
        or parameters.get("end_date") != expected_end
        or parameters.get("max_codes") != 1
        or isinstance(parameters.get("max_codes"), bool)
        or parameters.get("_ingest_mode") != "backfill"
        or not 0 < source_timeout <= OPTION_SOURCE_TIMEOUT_SECONDS
        or not isinstance(dispatch, dict)
        or dispatch.get("operator_id") is not None
        or dispatch.get("task_id") is not None
        or dispatch.get("period_key") != f"cffex-month-controller-v1:{month}:{run_id}"
        or dispatch.get("claim_reuse_policy")
        != "unique run id; no completed claim reused for refresh"
        or not _is_sha256(claim_key)
        or not _is_sha256(parameter_hash)
        or not 1 <= managed_timeout <= OPTION_BATCH_SECONDS
        or not 1 <= outer_wait_timeout <= OPTION_OUTER_TIMEOUT_SECONDS
    ):
        return (
            "attention_required",
            True,
            ["option managed dispatch does not match the exact one-month fenced contract"],
        )

    captured, capture_error = _option_capture_matches(
        result, artifact_root=artifact_root, month=month, run_id=run_id
    )
    if not captured:
        return (
            "attention_required",
            True,
            [capture_error or "option wire capture is unverified"],
        )
    evidence = result.get("source_month_evidence")
    comparison = result.get("source_sql_comparison")
    execution = result.get("execution")
    execution_result = execution.get("result") if isinstance(execution, dict) else None
    if (
        not isinstance(evidence, dict)
        or not isinstance(comparison, dict)
        or not isinstance(execution, dict)
        or not isinstance(execution_result, dict)
    ):
        return (
            "attention_required",
            True,
            ["option month is missing source, SQL, or managed execution evidence"],
        )
    source_rows = evidence.get("source_row_count")
    if (
        not isinstance(source_rows, int)
        or isinstance(source_rows, bool)
        or source_rows <= 0
        or evidence.get("source_archive_month") != month
        or evidence.get("source_archive_sha256") != result.get("archive_sha256")
        or evidence.get("source_sequence_complete") is not True
        or evidence.get("source_complete") is not False
        or result.get("archive_sha256") != result.get("wire_capture", {}).get("body_sha256")
        or execution.get("status") != "completed"
        or execution.get("error_message") is not None
        or not isinstance(execution.get("execution_id"), str)
        or not execution["execution_id"].startswith("ak_exec_")
        or result.get("managed_quality_receipt_matches_parser") is not True
        or result.get("managed_quality_receipt_errors") != []
    ):
        return (
            "attention_required",
            True,
            ["option source evidence or managed quality receipt is inconsistent"],
        )
    expected_scope = f"cffex:option-history:monthly-archive:{expected_start}-{expected_end}"
    managed_source_rows = execution_result.get("source_row_count")
    managed_valid_rows = execution_result.get("valid_row_count")
    if (
        execution_result.get("run_mode") != "backfill"
        or execution_result.get("table_name") != OPTION_TABLE_NAME
        or execution_result.get("quality_status") != "partial"
        or execution_result.get("source_complete") is not False
        or not isinstance(managed_source_rows, int)
        or isinstance(managed_source_rows, bool)
        or managed_source_rows != source_rows
        or not isinstance(managed_valid_rows, int)
        or isinstance(managed_valid_rows, bool)
        or managed_valid_rows != source_rows
        or execution_result.get("source_scope") != expected_scope
    ):
        return (
            "attention_required",
            True,
            ["option managed receipt does not match the exact parsed source scope"],
        )
    try:
        row_count = execution_result.get("row_count")
        rows_after = execution_result.get("rows_after")
        if (
            isinstance(row_count, bool)
            or isinstance(rows_after, bool)
            or int(row_count) != int(rows_after)
            or int(rows_after) < source_rows
            or int(rows_after) != rows_after
            or int(row_count) != row_count
        ):
            raise ValueError("invalid table counts")
    except (TypeError, ValueError, OverflowError):
        return (
            "attention_required",
            True,
            ["option managed table-wide row counts are inconsistent"],
        )

    invalid_lists = (
        "source_duplicate_keys",
        "sql_duplicate_keys",
        "missing_in_sql",
        "sql_only_keys",
        "field_mismatches",
        "policy_errors",
    )
    source_key_count = comparison.get("source_key_count")
    sql_key_count = comparison.get("sql_key_count")
    mismatch_count = comparison.get("field_mismatch_count")
    postimage_month_rows = result.get("postimage_sql_rows")
    if (
        comparison.get("month") != month
        or comparison.get("matched") is not True
        or not isinstance(source_key_count, int)
        or isinstance(source_key_count, bool)
        or source_key_count != source_rows
        or not isinstance(sql_key_count, int)
        or isinstance(sql_key_count, bool)
        or sql_key_count != source_rows
        or not isinstance(postimage_month_rows, int)
        or isinstance(postimage_month_rows, bool)
        or postimage_month_rows != source_rows
        or not isinstance(mismatch_count, int)
        or isinstance(mismatch_count, bool)
        or mismatch_count != 0
        or comparison.get("compared_fields") != list(OPTION_COMPARE_FIELDS)
        or not _is_sha256(comparison.get("source_fields_sha256"))
        or comparison.get("source_fields_sha256") != comparison.get("sql_fields_sha256")
        or any(comparison.get(key) != [] for key in invalid_lists)
    ):
        return (
            "attention_required",
            True,
            ["option fresh SQL does not exactly reconcile source keys and fields"],
        )
    return (
        "batch_reconciled_history_incomplete",
        False,
        [
            "one CFFEX archive month matched the persisted exact response, producer receipt, and fresh SQL; calendar, lifecycle, and global full-history coverage remain unknown"
        ],
    )


def _runtime_preflight(asset: str, paths: WorkerPaths) -> str | None:
    scripts = {
        "stock": paths.stock_script,
        "crypto": paths.crypto_script,
        "bond": paths.bond_script,
        "etf": paths.etf_script,
        "option": paths.option_script,
    }
    required = [paths.python, scripts[asset]]
    if asset == "crypto":
        required.append(paths.crypto_manifest)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        return "required runtime inputs missing: " + ", ".join(missing)
    if not os.access(paths.python, os.X_OK):
        return f"project Python is not executable: {paths.python}"
    return None


def _progress_path(asset: str, paths: WorkerPaths) -> Path:
    return {
        "stock": paths.stock_progress,
        "crypto": paths.crypto_progress,
        "bond": paths.bond_progress,
        "etf": paths.etf_output_dir / "events.jsonl",
        "option": paths.option_output_dir / "progress.jsonl",
    }[asset]


def _outer_timeout_seconds(asset: str) -> int:
    batch_seconds = {
        "stock": int(STOCK_BATCH_MINUTES * 60),
        "crypto": int(CRYPTO_BATCH_MINUTES * 60),
        "bond": BOND_BATCH_SECONDS,
        "etf": ETF_BATCH_SECONDS,
        "option": OPTION_BATCH_SECONDS,
    }[asset]
    if asset == "option":
        return OPTION_OUTER_TIMEOUT_SECONDS
    return batch_seconds + OUTER_TIMEOUT_GRACE_SECONDS


def _run_apply(
    paths: WorkerPaths,
    *,
    assets: tuple[str, ...] = DEFAULT_ASSETS,
    executor: Callable[[list[str], Path, int], ProcessResult] = _execute_cli,
) -> dict[str, Any]:
    assets = _validate_asset_order(assets)
    lock_fd = _acquire_lock(paths.lock_file)
    if lock_fd is None:
        return {
            "mode": "apply",
            "status": "skipped_lock_busy",
            "exit_code": 0,
            "batch_started": False,
            "cursor_advanced": False,
        }

    try:
        cursor_payload, cursor_error = _read_cursor_payload(paths.cursor_file, assets)
        if cursor_error:
            return {
                "mode": "apply",
                "status": "attention_required",
                "exit_code": 2,
                "batch_started": False,
                "cursor_advanced": False,
                "error": cursor_error,
            }
        if cursor_payload is None:
            cursor_payload = (
                {"schema_version": 1, "next_asset": assets[0]}
                if assets == DEFAULT_ASSETS
                else {
                    "schema_version": 3 if assets == FIVE_ASSET_ORDER else 2,
                    "rotation_order": list(assets),
                    "next_asset": assets[0],
                }
            )
        elif cursor_payload.get("schema_version") == 1 and assets == FOUR_ASSET_ORDER:
            cursor_payload = {
                **cursor_payload,
                "schema_version": 2,
                "rotation_order": list(assets),
            }
        elif cursor_payload.get("schema_version") in {1, 2} and assets == FIVE_ASSET_ORDER:
            cursor_payload = {
                **cursor_payload,
                "schema_version": 3,
                "rotation_order": list(assets),
            }
        asset = str(cursor_payload["next_asset"])
        next_asset = assets[(assets.index(asset) + 1) % len(assets)]
        started_at = _utc_now()
        run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:12]}"
        run_dir = _create_run_directory(paths, run_id)
        command, report_path = _asset_command(asset, paths, run_dir)
        progress_path = _progress_path(asset, paths)
        run_record: dict[str, Any] = {
            "schema_version": 1,
            "run_id": run_id,
            "asset": asset,
            "status": "dispatching",
            "started_at_utc": started_at,
            "command": command,
            "report_path": str(report_path),
            "stdout_log": str(run_dir / "stdout.log"),
            "stderr_log": str(run_dir / "stderr.log"),
            "progress_file": str(progress_path),
            "rotation_order": list(assets),
            "source_failure_recorded": False,
            "scheduler_started": False,
        }
        if assets in {FOUR_ASSET_ORDER, FIVE_ASSET_ORDER}:
            run_record["completion_scope"] = "bounded_batch"
            run_record["full_history_complete"] = False
        if asset == "etf":
            run_record["network_gate_note"] = (
                "The fresh Sina listing snapshot runs before managed writes and outside the shared scheduler gate."
            )
        _write_json_atomic(run_dir / "run.json", run_record)
        _write_json_atomic(
            paths.cursor_file,
            {
                **cursor_payload,
                "next_asset": next_asset,
                "last_asset": asset,
                "last_run_id": run_id,
                "last_started_at_utc": started_at,
                "last_status": "dispatching",
            },
        )

        preflight_error = _runtime_preflight(asset, paths)
        if preflight_error:
            run_record.update(
                {
                    "status": "preflight_failed",
                    "error": preflight_error,
                    "finished_at_utc": _utc_now(),
                    "write_possible": False,
                }
            )
            result = {
                "mode": "apply",
                "status": "attention_required",
                "exit_code": 2,
                "asset": asset,
                "run_id": run_id,
                "run_directory": str(run_dir),
                "cursor_advanced": True,
                "source_failure_recorded": False,
                "write_possible": False,
                "error": preflight_error,
            }
        else:
            hard_timeout = _outer_timeout_seconds(asset)
            try:
                process = executor(command, run_dir, hard_timeout)
            except Exception as exc:  # pragma: no cover - defensive injection/OS boundary
                process = ProcessResult(returncode=None, launch_error=type(exc).__name__)

            report, report_error = _load_report(report_path)
            if process.timed_out:
                status = "timed_out_write_possible"
                needs_attention = True
                reasons = [
                    "outer wall-clock limit expired; the CLI process group was terminated",
                    "database writes may have committed before termination; no source-failure cooldown was fabricated",
                ]
                result = {
                    "mode": "apply",
                    "status": status,
                    "exit_code": 2,
                    "asset": asset,
                    "run_id": run_id,
                    "run_directory": str(run_dir),
                    "process_returncode": process.returncode,
                    "source_failure_recorded": False,
                    "write_possible": True,
                    "progress_file": run_record["progress_file"],
                    "report_path": str(report_path) if report_path.exists() else None,
                    "controller_run_id": report.get("run_id")
                    if asset == "etf" and report
                    else None,
                    "attention_required": needs_attention,
                    **(
                        {"completion_scope": "bounded_batch", "full_history_complete": False}
                        if assets in {FOUR_ASSET_ORDER, FIVE_ASSET_ORDER}
                        else {}
                    ),
                    "reasons": reasons,
                }
                run_record.update(
                    {
                        "status": status,
                        "finished_at_utc": _utc_now(),
                        "process_returncode": process.returncode,
                        "source_failure_recorded": False,
                        "write_possible": True,
                        "report_parse_error": report_error,
                        "partial_report_present": report is not None,
                        "attention_required": needs_attention,
                        "reasons": reasons,
                    }
                )
            elif process.interrupted_by_signal is not None:
                status = "interrupted_write_possible"
                reasons = [
                    f"worker received signal {process.interrupted_by_signal}; the CLI process group was terminated",
                    "database writes may have committed before termination; no source-failure cooldown was fabricated",
                ]
                result = {
                    "mode": "apply",
                    "status": status,
                    "exit_code": 2,
                    "asset": asset,
                    "run_id": run_id,
                    "run_directory": str(run_dir),
                    "process_returncode": process.returncode,
                    "source_failure_recorded": False,
                    "write_possible": True,
                    "progress_file": run_record["progress_file"],
                    "report_path": str(report_path) if report_path.exists() else None,
                    "controller_run_id": report.get("run_id")
                    if asset == "etf" and report
                    else None,
                    "attention_required": True,
                    **(
                        {"completion_scope": "bounded_batch", "full_history_complete": False}
                        if assets in {FOUR_ASSET_ORDER, FIVE_ASSET_ORDER}
                        else {}
                    ),
                    "reasons": reasons,
                }
                run_record.update(
                    {
                        "status": status,
                        "finished_at_utc": _utc_now(),
                        "process_returncode": process.returncode,
                        "source_failure_recorded": False,
                        "write_possible": True,
                        "report_parse_error": report_error,
                        "partial_report_present": report is not None,
                        "attention_required": True,
                        "reasons": reasons,
                    }
                )
            elif process.launch_error:
                status = "launch_failed"
                result = {
                    "mode": "apply",
                    "status": status,
                    "exit_code": 2,
                    "asset": asset,
                    "run_id": run_id,
                    "run_directory": str(run_dir),
                    "source_failure_recorded": False,
                    "write_possible": False,
                    "attention_required": True,
                    "error": process.launch_error,
                }
                run_record.update(
                    {
                        "status": status,
                        "finished_at_utc": _utc_now(),
                        "process_returncode": process.returncode,
                        "source_failure_recorded": False,
                        "write_possible": False,
                        "attention_required": True,
                        "error": process.launch_error,
                    }
                )
            elif report is None:
                status = "invalid_or_missing_cli_report"
                result = {
                    "mode": "apply",
                    "status": status,
                    "exit_code": 2,
                    "asset": asset,
                    "run_id": run_id,
                    "run_directory": str(run_dir),
                    "process_returncode": process.returncode,
                    "source_failure_recorded": False,
                    "write_possible": True,
                    "attention_required": True,
                    "error": report_error,
                }
                run_record.update(result)
                run_record["finished_at_utc"] = _utc_now()
            elif process.returncode is None:
                status = "unknown_process_exit"
                result = {
                    "mode": "apply",
                    "status": status,
                    "exit_code": 2,
                    "asset": asset,
                    "run_id": run_id,
                    "run_directory": str(run_dir),
                    "source_failure_recorded": False,
                    "write_possible": True,
                    "attention_required": True,
                }
                run_record.update(result)
                run_record["finished_at_utc"] = _utc_now()
            else:
                if asset == "stock":
                    status, needs_attention, reasons = _classify_stock(process.returncode, report)
                elif asset == "crypto":
                    status, needs_attention, reasons = _classify_crypto(process.returncode, report)
                elif asset == "bond":
                    status, needs_attention, reasons = _classify_bond(process.returncode, report)
                elif asset == "etf":
                    status, needs_attention, reasons = _classify_etf(process.returncode, report)
                else:
                    status, needs_attention, reasons = _classify_option(
                        process.returncode,
                        report,
                        artifact_root=paths.option_output_dir / "snapshots",
                    )
                source_statuses = (
                    {
                        "source_failed",
                        "source_invalid",
                    }
                    if asset == "bond"
                    else OPTION_SOURCE_FAILURE_STATUSES
                    if asset == "option"
                    else {"source_failed"}
                    if asset == "stock"
                    else set()
                )
                outcomes_key = "outcomes" if asset in {"stock", "bond"} else "apply"
                if asset == "option":
                    option_result = report.get("result")
                    source_failure_recorded = bool(
                        isinstance(option_result, dict)
                        and option_result.get("status") in OPTION_SOURCE_FAILURE_STATUSES
                    )
                else:
                    source_failure_recorded = any(
                        str(item.get("status")) in source_statuses
                        for item in report.get(outcomes_key, [])
                        if isinstance(item, dict)
                    )
                result = {
                    "mode": "apply",
                    "status": status,
                    "exit_code": 1 if needs_attention else 0,
                    "asset": asset,
                    "run_id": run_id,
                    "run_directory": str(run_dir),
                    "process_returncode": process.returncode,
                    "report_path": str(report_path),
                    **({"controller_run_id": report.get("run_id")} if asset == "etf" else {}),
                    **(
                        {"controller_run_id": report.get("result", {}).get("run_id")}
                        if asset == "option" and isinstance(report.get("result"), dict)
                        else {}
                    ),
                    "source_failure_recorded": source_failure_recorded,
                    "write_possible": True,
                    "attention_required": needs_attention,
                    **(
                        {"completion_scope": "bounded_batch", "full_history_complete": False}
                        if assets in {FOUR_ASSET_ORDER, FIVE_ASSET_ORDER}
                        else {}
                    ),
                    "reasons": reasons,
                }
                run_record.update(
                    {
                        **result,
                        "finished_at_utc": _utc_now(),
                        "cli_report_status": report.get("mode"),
                    }
                )

        _write_json_atomic(run_dir / "run.json", run_record)
        cursor_payload, final_cursor_error = _read_cursor_payload(paths.cursor_file, assets)
        if final_cursor_error or cursor_payload is None:
            # This path is defensive: only this locked worker writes the cursor.
            result = {
                **result,
                "status": "attention_required",
                "exit_code": 2,
                "attention_required": True,
                "cursor_error": final_cursor_error or "cursor disappeared during apply",
                "write_possible": True,
            }
        else:
            _write_json_atomic(
                paths.cursor_file,
                {
                    **cursor_payload,
                    "next_asset": next_asset,
                    "last_asset": asset,
                    "last_run_id": run_id,
                    "last_started_at_utc": started_at,
                    "last_finished_at_utc": run_record.get("finished_at_utc", _utc_now()),
                    "last_status": result["status"],
                },
            )
        return result
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def run_once(
    *,
    apply: bool,
    repo: Path = REPO_ROOT,
    assets: tuple[str, ...] = DEFAULT_ASSETS,
) -> dict[str, Any]:
    """Create a read-only plan or execute exactly one rotating batch."""
    assets = _validate_asset_order(assets)
    paths = WorkerPaths.for_repo(repo)
    if not apply:
        return _build_plan(paths, assets)
    return _run_apply(paths, assets=assets)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--plan", action="store_true", help="print the safe next-batch plan (default)"
    )
    mode.add_argument("--apply", action="store_true", help="run exactly one bounded asset batch")
    parser.add_argument(
        "--assets",
        nargs="+",
        metavar="ASSET",
        help="explicit fixed registry: stock crypto (default), stock crypto bond etf, or stock crypto bond etf option",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        assets = _validate_asset_order(
            tuple(args.assets) if args.assets is not None else DEFAULT_ASSETS
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        result = run_once(apply=args.apply, assets=assets)
    except Exception as exc:
        result = {
            "mode": "apply" if args.apply else "plan",
            "status": "runner_internal_error",
            "exit_code": 2,
            "attention_required": True,
            "source_failure_recorded": False,
            "write_possible": bool(args.apply),
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return int(result.get("exit_code", 0))


if __name__ == "__main__":
    raise SystemExit(main())
