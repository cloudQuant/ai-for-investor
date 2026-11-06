"""Tests for the CFFEX option-history month controller (iteration 204 asset rebuild).

All fixtures run against owned temporary storage only. No live warehouse
connection, no real CFFEX request, and no managed scheduler is ever invoked;
the exchange/warehouse adapters are replaced by in-process fakes. Anything
that requires the live exchange or the live warehouse stays NOT_RUN here.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
import stat
import sys
import types
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[1]
CONTROLLER_PATH = BACKEND / "scripts" / "cffex_option_history_controller.py"
WORKER_CANDIDATES = (
    BACKEND / "scripts" / "ops" / "run_full_history_recovery_worker.py",
    Path(
        "/home/yun/Documents/ai-for-investor/src/backend/scripts/ops"
        "/run_full_history_recovery_worker.py"
    ),
)
WORKER_PATH = next((path for path in WORKER_CANDIDATES if path.exists()), WORKER_CANDIDATES[0])
_REPO_CANDIDATES = (
    BACKEND.parents[1],
    Path("/home/yun/Documents/ai-for-investor"),
)
_LIVE_RELATIVE = Path("var/reports/iteration203/cffex-option-history-controller/progress.jsonl")
LIVE_PROGRESS = next(
    (repo / _LIVE_RELATIVE for repo in _REPO_CANDIDATES if (repo / _LIVE_RELATIVE).exists()),
    _REPO_CANDIDATES[0] / _LIVE_RELATIVE,
)

PROVIDER_MODULE = "app.data_fetch.providers.cffex_option_history_source"

ZIP_BODY = b"PK\x03\x04fake-cffex-monthly-archive-body"
ZIP_SHA = hashlib.sha256(ZIP_BODY).hexdigest()
MONTH = "202001"
EXPECTED_URL = f"http://www.cffex.com.cn/sj/historysj/{MONTH}/zip/{MONTH}.zip"
EXPECTED_SCOPE = "cffex:option-history:monthly-archive:20200101-20200131"


class CffexOptionSourceError(RuntimeError):
    pass


def _source_row(symbol: str, contract_month: str, day: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "SOURCE": "cffex",
        "MARKET": "CFFEX",
        "OPTION_PRODUCT": symbol[:2],
        "SOURCE_SYMBOL": symbol,
        "CONTRACT_MONTH": contract_month,
        "OPTION_SIDE": symbol.split("-")[1],
        "STRIKE_PRICE": symbol.split("-")[2],
        "TRADE_DATE": date.fromisoformat(day),
        "OPEN_PRICE": "3.4",
        "HIGH_PRICE": "5.2",
        "LOW_PRICE": "2.1",
        "CLOSE_PRICE": "4.0",
        "SETTLEMENT_PRICE": "4.2",
        "PREVIOUS_SETTLEMENT_PRICE": "4.1",
        "CHANGE_1": "0.1",
        "CHANGE_2": "0.2",
        "VOLUME": 120,
        "AMOUNT_SOURCE_VALUE": "50400.0",
        "AMOUNT_UNIT": "unknown",
        "OPEN_INTEREST": 300,
        "OPEN_INTEREST_CHANGE": -5,
        "SOURCE_DELTA": "0.5213",
        "SOURCE_DELTA_RAW": "0.5213",
        "SOURCE_ROW_JSON": f'{{"合约代码": {symbol!r}}}',
        "SOURCE_ROW_SHA256": hashlib.sha256(symbol.encode()).hexdigest(),
        "SOURCE_URL": EXPECTED_URL,
        "SOURCE_ARCHIVE_MONTH": MONTH,
        "SOURCE_ARCHIVE_SHA256": ZIP_SHA,
        "SOURCE_ARCHIVE_MEMBER_COUNT": 2,
        "SOURCE_MEMBER_NAME": f"{day.replace('-', '')}_1.csv",
        "SOURCE_MEMBER_SHA256": hashlib.sha256(day.encode()).hexdigest(),
        "SOURCE_MEMBER_OPTION_ROW_COUNT": 2,
        "OBSERVED_AT": datetime(2020, 1, 31, 15, 5, 0),
        "OBSERVED_AT_TIME_ZONE": "Asia/Shanghai",
        "SOURCE_SCOPE": EXPECTED_SCOPE,
        "SOURCE_SEQUENCE_COMPLETE": 1,
        "SOURCE_COMPLETE": 0,
        "QUALITY_STATUS": "partial",
    }
    row.update(overrides)
    return row


# Parser-faithful rows: per-contract identities only. IO2003-C-3650 keeps the
# recorded 2019-12-24 trap shape (OHLC NULLs with zero volume); its settlement
# fields stay NULL exactly as the archive published them.
CANONICAL_ROWS = [
    _source_row(
        "IO2003-C-3650",
        "2003",
        "2020-01-03",
        **dict.fromkeys(
            (
                "OPEN_PRICE",
                "HIGH_PRICE",
                "LOW_PRICE",
                "CLOSE_PRICE",
                "SETTLEMENT_PRICE",
                "CHANGE_1",
                "CHANGE_2",
                "SOURCE_DELTA",
            ),
            None,
        ),
        VOLUME=0,
        AMOUNT_SOURCE_VALUE="0",
    ),
    _source_row("IO2003-C-3700", "2003", "2020-01-03"),
    _source_row("MO2003-P-6000", "2003", "2020-01-03", STRIKE_PRICE="6000"),
]


class _ParsedRows:
    def __init__(self) -> None:
        self.attrs = {
            "source_archive_month": MONTH,
            "source_archive_sha256": ZIP_SHA,
            "source_member_count": 2,
            "source_row_count": len(CANONICAL_ROWS),
            "source_member_date_start": "2020-01-03",
            "source_member_date_end": "2020-01-03",
            "source_member_inventory": [],
            "source_ignored_row_counts": {"non_option_cffex_futures": 0},
            "source_archive_ignored_row_counts": {"non_option_cffex_futures": 0},
            "source_sequence_complete": True,
            "source_complete": False,
            "source_date_basis": "YYYYMMDD member filename",
            "source_lifecycle_complete": False,
            "amount_unit": "unknown",
        }

    def __iter__(self) -> Any:
        return iter(copy.deepcopy(CANONICAL_ROWS))


def _install_provider_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = types.ModuleType(PROVIDER_MODULE)
    stub.CffexOptionSourceError = CffexOptionSourceError
    stub.normalize_date = _normalize_date
    stub.parse_monthly_archive = lambda *a, **k: _ParsedRows()
    stub.SOURCE = "cffex"
    stub.SOURCE_TIME_ZONE = "Asia/Shanghai"
    stub.SOURCE_URL_TEMPLATE = "http://www.cffex.com.cn/sj/historysj/{month}/zip/{month}.zip"
    monkeypatch.setitem(sys.modules, PROVIDER_MODULE, stub)


def _normalize_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.status_code = 200
        self.url = EXPECTED_URL
        self.headers = {"Content-Type": "application/zip", "Content-Length": str(len(body))}
        self.history: list[Any] = []
        self._body = body
        self.closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 1) -> Any:
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.get_urls: list[str] = []
        self.closed = False

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_urls.append(url)
        return FakeResponse(self._body)

    def close(self) -> None:
        self.closed = True


class FakeWarehouse:
    """SELECT-only in-memory stand-in for the canonical option-history table."""

    instances: list[FakeWarehouse] = []

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = copy.deepcopy(CANONICAL_ROWS if rows is None else rows)
        self.opened = 0
        self.closed = 0
        FakeWarehouse.instances.append(self)

    def __enter__(self) -> FakeWarehouse:
        self.opened += 1
        return self

    def __exit__(self, *args: Any) -> None:
        self.closed += 1

    def check_schema(self) -> dict[str, Any]:
        return {
            "sha256": hashlib.sha256(b"cffex-option-table-schema").hexdigest(),
            "statements": [],
        }

    def read_month(self, month: str) -> list[dict[str, Any]]:
        assert month == MONTH
        return copy.deepcopy(self.rows)

    def read_overview(self) -> dict[str, Any]:
        return {
            "table": "OPTION_CFFEX_DAILY_HISTORY",
            "total_rows": len(self.rows),
            "months": [{"archive_month": MONTH, "row_count": len(self.rows)}],
        }


@pytest.fixture()
def controller(monkeypatch: pytest.MonkeyPatch):
    sys.path.insert(0, str(BACKEND / "scripts"))
    module = importlib.import_module("cffex_option_history_controller")
    importlib.reload(module)
    _install_provider_stub(monkeypatch)
    FakeWarehouse.instances = []
    monkeypatch.setattr(module, "MySQLOptionHistoryReader", FakeWarehouse)
    return module


def _sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def make_dispatch(controller: Any, month: str, run_id: str) -> dict[str, Any]:
    parameters = controller.managed_parameters(month, source_timeout_seconds=90)
    period_key = f"cffex-month-controller-v1:{month}:{run_id}"
    parameter_hash = _sha(json.dumps(parameters, sort_keys=True))
    claim_key = _sha("cffex", period_key, parameter_hash)
    return {
        "registration": {
            "script_id": "cffex_option_daily_history",
            "source": "cffex",
            "module_path": "app.data_fetch.scripts.options.daily.cffex_option_daily_history",
            "function_name": "main",
            "target_table": "OPTION_CFFEX_DAILY_HISTORY",
        },
        "parameters": parameters,
        "operator_id": None,
        "task_id": None,
        "managed_timeout_seconds": 150,
        "outer_wait_timeout_seconds": 155,
        "period_key": period_key,
        "parameter_hash": parameter_hash,
        "claim_key": claim_key,
        "claim_reuse_policy": "unique run id; no completed claim reused for refresh",
    }


def verified_managed_runner(controller: Any, sql_rows: list[dict[str, Any]] | None = None):
    """Fake of ``_managed_month_call`` that drives the real recorder stack."""

    calls: list[dict[str, Any]] = []

    def runner(
        *, month: str, run_id: str, capture: Any, budget_seconds: int, source_timeout_seconds: int
    ) -> tuple[Any, dict[str, Any], bool]:
        calls.append({"month": month, "run_id": run_id, "budget": budget_seconds})
        session = controller.RecordingSession(
            capture, session_factory=lambda: FakeSession(ZIP_BODY)
        )
        wrapped = session.get(EXPECTED_URL)
        wrapped.raise_for_status()
        delivered = b"".join(wrapped.iter_content(chunk_size=64))
        assert delivered == ZIP_BODY
        rows = CANONICAL_ROWS if sql_rows is None else sql_rows
        execution = {
            "execution_id": "ak_exec_testfence0001",
            "status": "completed",
            "error_message": None,
            "result": {
                "run_mode": "backfill",
                "row_count": len(rows),
                "rows_before": 0,
                "rows_after": len(rows),
                "rows_delta": len(rows),
                "table_name": "OPTION_CFFEX_DAILY_HISTORY",
                "quality_status": "partial",
                "source_complete": False,
                "valid_row_count": len(rows),
                "source_row_count": len(rows),
                "source_scope": EXPECTED_SCOPE,
                "source_note": "{}",
                "committed_write_count": 1,
            },
        }
        return execution, make_dispatch(controller, month, run_id), False

    runner.calls = calls
    return runner


async def run_apply(controller: Any, tmp_path: Path, **kwargs: Any) -> dict[str, Any]:
    return await controller.apply_one_month(
        MONTH,
        progress_path=tmp_path / "progress.jsonl",
        artifact_root=tmp_path / "snapshots",
        time_budget_seconds=kwargs.pop("time_budget_seconds", 180),
        source_timeout_seconds=kwargs.pop("source_timeout_seconds", 90),
        **kwargs,
    )


class TestReadOnlyDefault:
    def test_plan_is_offline_and_does_not_write(self, controller, tmp_path, capsys) -> None:
        before = set(tmp_path.iterdir())
        exit_code = controller.main(
            [
                "--progress",
                str(tmp_path / "progress.jsonl"),
                "--artifacts",
                str(tmp_path / "snapshots"),
            ]
        )
        assert exit_code == 0
        report = json.loads(capsys.readouterr().out)
        assert report["mode"] == "read_only_plan"
        assert report["table"] == "OPTION_CFFEX_DAILY_HISTORY"
        assert report["source_completeness"] is False
        assert report["calendar_completeness"] == "unknown"
        assert report["candidate_start_basis"] == (
            "observed archive candidate only; not verified inception/listing"
        )
        assert not (tmp_path / "progress.jsonl").exists()
        assert set(tmp_path.iterdir()) == before

    def test_plan_never_claims_inception_or_full_history(
        self, controller, tmp_path, capsys
    ) -> None:
        exit_code = controller.main(
            ["--end-month", "202003", "--progress", str(tmp_path / "progress.jsonl")]
        )
        assert exit_code == 0
        report = json.loads(capsys.readouterr().out)
        assert report["selection"]["candidate_start_is_inception"] is False
        assert report["selection"]["source_lifecycle"] == "unknown"
        for row in report["months"]:
            assert row["exchange_calendar_coverage"] == "unknown"
            assert row["contract_lifecycle_coverage"] == "unknown"

    def test_output_aliases_progress_are_refused(self, controller, tmp_path) -> None:
        ledger = tmp_path / "progress.jsonl"
        ledger.write_text("", encoding="utf-8")
        exit_code = controller.main(["--output", str(ledger), "--progress", str(ledger)])
        assert exit_code == 2
        assert ledger.read_text(encoding="utf-8") == ""


class TestBoundedBudget:
    def test_cli_rejects_out_of_range_bounds(self, controller, tmp_path) -> None:
        for argv in (
            ["--apply", "--max-minutes", "1"],
            ["--apply", "--max-minutes", "4"],
            ["--apply", "--source-timeout-seconds", "0"],
            ["--apply", "--source-timeout-seconds", "91"],
        ):
            exit_code = controller.main(argv + ["--progress", str(tmp_path / "p.jsonl")])
            assert exit_code == 2

    async def test_core_rejects_invalid_bounds(self, controller, tmp_path) -> None:
        with pytest.raises(ValueError):
            await run_apply(controller, tmp_path, time_budget_seconds=60)
        with pytest.raises(ValueError):
            await run_apply(controller, tmp_path, time_budget_seconds=3600)
        with pytest.raises(ValueError):
            await run_apply(controller, tmp_path, source_timeout_seconds=91)
        assert not (tmp_path / "progress.jsonl").exists()

    async def test_wall_budget_defers_before_any_source_request(self, controller, tmp_path) -> None:
        runner = verified_managed_runner(controller)
        ticks = iter([0.0, 121.0, 122.0, 123.0])
        result = await run_apply(
            controller,
            tmp_path,
            managed_runner=runner,
            monotonic=lambda: next(ticks),
        )
        assert result["status"] == "deferred_budget"
        assert result["failure_phase"] == "wall_clock_budget_before_managed_dispatch"
        assert result["execution"] is None
        assert result["database_write_possible"] is False
        assert result["timed_out"] is False
        assert runner.calls == []
        assert result["wire_capture"]["request_count"] == 0
        assert result["wire_capture"]["body_bytes"] == 0

    def test_managed_parameters_and_timeout_bound(self, controller) -> None:
        parameters = controller.managed_parameters("202002", source_timeout_seconds=90)
        assert parameters["start_date"] == "20200201"
        assert parameters["end_date"] == "20200229"
        assert parameters["max_codes"] == 1
        assert parameters["_ingest_mode"] == "backfill"
        with pytest.raises(ValueError):
            controller.managed_parameters("202002", source_timeout_seconds=91)


class TestIdempotencyAndResume:
    async def test_successful_month_is_skipped_on_next_selection(
        self, controller, tmp_path
    ) -> None:
        result = await run_apply(
            controller, tmp_path, managed_runner=verified_managed_runner(controller)
        )
        assert result["status"] == "verified_source_archive_snapshot"
        events = controller.read_progress(tmp_path / "progress.jsonl")
        # Re-running over the exact verified window skips the month idempotently;
        # no new source request, no rewrite, no re-verification.
        verified, decision = controller.select_next_month(
            start_month=MONTH,
            end_month=MONTH,
            current_month="202611",
            events=events,
            now=datetime.now(UTC),
        )
        assert verified is None
        assert decision["deferred"] == [
            {"month": MONTH, "status": "verified_archive_snapshot_recorded"}
        ]
        verified_next, _ = controller.select_next_month(
            start_month=MONTH,
            end_month="202002",
            current_month="202611",
            events=events,
            now=datetime.now(UTC),
        )
        assert verified_next == "202002"

    async def test_mid_batch_failure_resumes_without_cursor_reset(
        self, controller, tmp_path
    ) -> None:
        class CrashAfterRequest(Exception):
            pass

        def crasher(*, month: str, run_id: str, capture: Any, **kwargs: Any):
            capture.begin_request(EXPECTED_URL)
            capture.add_chunk(ZIP_BODY[:16])
            raise CrashAfterRequest("worker died mid-batch")

        first = await run_apply(controller, tmp_path, managed_runner=crasher)
        assert first["status"] in {"source_failed", "source_invalid"}
        assert first["preimage_unchanged_after_failed_month"] is True
        assert first["source_failure_cooldown_hours"] == 24.0

        events = controller.read_progress(tmp_path / "progress.jsonl")
        assert len(events) == 2  # attempt_started + terminal, chain intact

        verified, decision = controller.select_next_month(
            start_month=MONTH,
            end_month="202002",
            current_month="202611",
            events=events,
            now=datetime.now(UTC),
        )
        # Fairness cursor was preserved across the mid-batch failure (no reset).
        assert decision["fairness_cursor_month"] == MONTH
        # Work resumes at the next month after the cursor, not from the start.
        assert verified == "202002"
        # The failed month itself stays cooling down and is not re-verified...
        only_failed, failed_decision = controller.select_next_month(
            start_month=MONTH,
            end_month=MONTH,
            current_month="202611",
            events=events,
            now=datetime.now(UTC),
        )
        assert only_failed is None
        assert {
            "month": MONTH,
            "status": "deferred_failure_cooldown",
            "previous_status": first["status"],
        } in failed_decision["deferred"]
        # ...and no cooldown was cleared or cursor rewritten in the ledger.
        reloaded = controller.read_progress(tmp_path / "progress.jsonl")
        assert [e["status"] for e in reloaded] == ["attempt_started", first["status"]]

    async def test_cooldown_event_without_terminal_is_not_fabricated_as_verified(
        self, controller, tmp_path
    ) -> None:
        base_event = {"month": MONTH, "status": "attempt_started"}
        later = datetime.now(UTC) + timedelta(minutes=1)
        attempt = {**base_event, "recorded_at_utc": later.isoformat()}
        assert controller._is_cooling_down(attempt, later) is True
        assert (
            controller._is_cooling_down(
                {
                    "month": MONTH,
                    "status": "verified_source_archive_snapshot",
                    "recorded_at_utc": later.isoformat(),
                },
                later,
            )
            is False
        )


class TestNullAndContractSemantics:
    def test_normalized_null_stays_null(self, controller) -> None:
        assert controller._normalize_scalar("SETTLEMENT_PRICE", None) is None
        assert controller._normalize_scalar("OPEN_PRICE", None) is None

    def test_zero_fill_counterfactual_breaks_the_reconciliation(self, controller) -> None:
        source = copy.deepcopy(CANONICAL_ROWS)
        warehouse = copy.deepcopy(CANONICAL_ROWS)
        # A hypothetical writer that "helpfully" zero-filled the NULL settles.
        warehouse[0]["SETTLEMENT_PRICE"] = 0
        comparison = controller.compare_source_rows_to_sql(source, warehouse, month=MONTH)
        assert comparison["matched"] is False
        assert comparison["field_mismatch_count"] >= 1
        fields = {row["field"] for row in comparison["field_mismatches"]}
        assert "SETTLEMENT_PRICE" in fields
        assert comparison["source_fields_sha256"] != comparison["sql_fields_sha256"]

    def test_per_contract_rows_are_never_a_continuous_series(self, controller) -> None:
        source = [
            _source_row("IF2312-C-3800", "2312", "2020-01-03", OPTION_PRODUCT="IF"),
            _source_row("IF2403-C-3800", "2403", "2020-01-03", OPTION_PRODUCT="IF"),
        ]
        comparison = controller.compare_source_rows_to_sql(source, source, month=MONTH)
        # Both distinct expiries survive as two exact-contract keys.
        assert comparison["source_key_count"] == 2
        assert comparison["matched"] is True

        continuous = [
            {
                **source[0],
                "SOURCE_SYMBOL": "IF0",
                "CONTRACT_MONTH": "main",
                "TRADE_DATE": date(2020, 1, 3),
            }
        ]
        collapsed = controller.compare_source_rows_to_sql(source, continuous, month=MONTH)
        assert collapsed["matched"] is False
        assert collapsed["missing_in_sql"] and collapsed["sql_only_keys"]

    def test_rows_cannot_escape_the_requested_archive_month(self, controller) -> None:
        escapee = copy.deepcopy(CANONICAL_ROWS)
        escapee[1]["TRADE_DATE"] = date(2020, 2, 5)
        escapee[1]["SOURCE_ARCHIVE_MONTH"] = "202002"
        with pytest.raises(ValueError, match="escaped requested month"):
            controller.compare_source_rows_to_sql(escapee, escapee, month=MONTH)

    async def test_apply_refuses_to_verify_when_sql_collapses_contracts(
        self, controller, tmp_path
    ) -> None:
        collapsed_rows = [
            {**CANONICAL_ROWS[0], "SOURCE_SYMBOL": "IO-main", "CONTRACT_MONTH": "main"},
        ]
        result = await run_apply(
            controller,
            tmp_path,
            managed_runner=verified_managed_runner(controller, sql_rows=collapsed_rows),
            reader_factory=lambda: FakeWarehouse(collapsed_rows),
        )
        # A front-month/continuous aggregate in the warehouse can never match the
        # per-contract archive rows, so no verified receipt is issued.
        assert result["status"] == "verification_failed"
        assert result["failure_phase"] == "source_sql_comparison"

    def test_future_dated_archive_rows_are_rejected(self, controller) -> None:
        rows = copy.deepcopy(CANONICAL_ROWS)
        rows[1]["TRADE_DATE"] = date(2099, 1, 5)
        with pytest.raises(CffexOptionSourceError, match="future TRADE_DATE"):
            controller._reject_future_source_dates(rows, date(2026, 1, 1))


class TestWriteTargetInvariants:
    def test_controller_targets_only_the_cffex_canonical_table(self, controller) -> None:
        source_text = CONTROLLER_PATH.read_text(encoding="utf-8")
        assert controller.TABLE_NAME == "OPTION_CFFEX_DAILY_HISTORY"
        # The commodity canonical table and the disabled legacy producers (tasks
        # 477, 487-491) are outside this controller's write contract entirely.
        for forbidden in (
            "OPTION_COMMODITY_DAILY_HISTORY",
            "option_cffex_hs300_daily_sina",
            "option_cffex_sz50_daily_sina",
            "option_cffex_zz1000_daily_sina",
        ):
            assert forbidden not in source_text

    def test_registration_must_match_the_reviewed_contract(self, controller) -> None:
        assert controller.SCRIPT_ID == "cffex_option_daily_history"
        assert controller.SCRIPT_MODULE.endswith(".cffex_option_daily_history")
        assert controller.SCRIPT_FUNCTION == "main"

    async def test_apply_writes_only_progress_and_artifacts(self, controller, tmp_path) -> None:
        await run_apply(controller, tmp_path, managed_runner=verified_managed_runner(controller))
        created = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
        assert all(
            name.startswith("progress.jsonl")
            or name.startswith(f"snapshots/{MONTH}/")
            or name in {"snapshots", f"snapshots/{MONTH}"}
            for name in created
        )
        assert any(name.endswith("source-response.zip") for name in created)
        assert any(name.endswith("wire-capture.json") for name in created)
        # The ledger is append-only JSONL; nothing else was written.
        assert (tmp_path / "progress.jsonl").read_text(encoding="utf-8").count("\n") == 2


class TestEvidenceShapes:
    async def test_progress_and_manifest_match_recorded_production_shapes(
        self, controller, tmp_path
    ) -> None:
        result = await run_apply(
            controller, tmp_path, managed_runner=verified_managed_runner(controller)
        )
        events = controller.read_progress(tmp_path / "progress.jsonl")
        assert [event["status"] for event in events] == [
            "attempt_started",
            "verified_source_archive_snapshot",
        ]
        for event in events:
            assert event["schema_version"] == 1
            assert event["request_scope"] == (
                "one exact full calendar month archive; no trading calendar imputation"
            )
            assert _looks_sha256(event["event_sha256"])
            assert _looks_sha256(event["previous_event_sha256"])

        run_id = result["run_id"]
        capture_dir = tmp_path / "snapshots" / MONTH / run_id
        manifest_bytes = (capture_dir / "wire-capture.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        body = (capture_dir / "source-response.zip").read_bytes()
        assert manifest["body_sha256"] == hashlib.sha256(body).hexdigest()
        # Like the recorded production manifests, the persisted file excludes the
        # self-referential digests; the report binds them.
        assert "manifest_sha256" not in manifest
        assert (
            result["wire_capture"]["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
        )
        assert result["wire_capture"]["manifest_path"] == str(capture_dir / "wire-capture.json")
        assert manifest["recording_semantics"] == (
            "same real iter_content bytes delivered to the existing strict parser"
        )
        assert stat.S_IMODE(capture_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE((capture_dir / "wire-capture.json").stat().st_mode) == 0o600
        assert stat.S_IMODE((tmp_path / "progress.jsonl").stat().st_mode) == 0o600

    @pytest.mark.skipif(
        not LIVE_PROGRESS.exists(), reason="recorded production ledger is not present"
    )
    def test_ledger_event_shapes_equal_recorded_evidence(self, tmp_path) -> None:
        """Rebuilt ledger keys must match the recorded production ledger shapes."""
        sys.path.insert(0, str(BACKEND / "scripts"))
        module = importlib.import_module("cffex_option_history_controller")
        events = module.read_progress(LIVE_PROGRESS)
        attempt = next(e for e in events if e["status"] == "attempt_started")
        verified = next(e for e in events if e["status"] == "verified_source_archive_snapshot")
        result = {
            "month": MONTH,
            "run_id": "0" * 32,
            "attempted_at_utc": datetime.now(UTC).isoformat(),
            "controller_as_of_date": "2026-01-01",
            "request_scope": (
                "one exact full calendar month archive; no trading calendar imputation"
            ),
            "candidate_start_month_is_inception": False,
            "source_lifecycle": "unknown",
            "source_complete": False,
            "calendar_coverage": "unknown",
            "execution_budget": module._budget_semantics(180),
            "status": "attempt_started",
            "schema_sha256": "a" * 64,
            "preimage_sql_rows": 0,
            "preimage_fields_sha256": "b" * 64,
            "artifact_directory": "/tmp/x",
            "source_timeout_seconds": 90,
            "wall_clock_budget_seconds": 180,
        }
        event = module.append_progress(tmp_path / "progress.jsonl", result)
        assert set(event) == set(attempt)
        terminal_keys = set(verified)
        base = {
            k: v
            for k, v in result.items()
            if k
            not in {
                "artifact_directory",
                "source_timeout_seconds",
                "wall_clock_budget_seconds",
                "status",
            }
        }
        rebuilt = {
            **base,
            "source_sql_comparison": {},
            "managed_quality_receipt_matches_parser": True,
            "managed_quality_receipt_errors": [],
            "status": "verified_source_archive_snapshot",
            "postimage_sql_rows": 0,
            "postimage_fields_sha256": "c" * 64,
            "database_write_possible": True,
            "dispatch": {},
            "execution": None,
            "timed_out": False,
            "managed_call_error": None,
            "post_sql_read_error": None,
            "wire_capture": {},
            "archive_sha256": None,
            "independent_parser": "x",
            "contract_lifecycle": "unknown",
            "independent_parse_error": None,
            "source_month_evidence": {},
            "verified_at_utc": datetime.now(UTC).isoformat(),
            "source_sequence_complete": True,
            "archive_snapshot_verified": True,
            "month_calendar_coverage_verified": False,
            "candidate_inception_verified": False,
            "elapsed_seconds": 1.0,
        }
        event2 = module.append_progress(tmp_path / "progress.jsonl", rebuilt)
        assert terminal_keys == set(event2)

    def test_compare_fields_match_recorded_evidence_order(self, controller) -> None:
        if not WORKER_PATH.exists():
            pytest.skip("worker script not present in this checkout")
        spec = importlib.util.spec_from_file_location("recovery_worker", WORKER_PATH)
        assert spec is not None and spec.loader is not None
        worker = importlib.util.module_from_spec(spec)
        sys.modules["recovery_worker"] = worker
        spec.loader.exec_module(worker)
        assert list(controller.COMPARE_FIELDS) == list(worker.OPTION_COMPARE_FIELDS)


def _looks_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


class TestWorkerReportContract:
    @pytest.mark.skipif(
        not WORKER_PATH.exists(), reason="worker script not present in this checkout"
    )
    async def test_worker_classifies_verified_report_as_bounded_batch(
        self, controller, tmp_path
    ) -> None:
        spec = importlib.util.spec_from_file_location("recovery_worker", WORKER_PATH)
        assert spec is not None and spec.loader is not None
        worker = importlib.util.module_from_spec(spec)
        sys.modules["recovery_worker"] = worker
        spec.loader.exec_module(worker)

        result = await run_apply(
            controller, tmp_path, managed_runner=verified_managed_runner(controller)
        )
        selection = {
            "selected_month": MONTH,
            "selection_reason": "next_unverified_month_after_fairness_cursor",
            "fairness_cursor_month": None,
            "verified_month_count": 0,
            "deferred": [],
            "source_lifecycle": "unknown",
            "candidate_start_is_inception": False,
        }
        report = {"mode": "apply", "selection": selection, "result": result}
        status, attention, reasons = worker._classify_option(
            0, report, artifact_root=tmp_path / "snapshots"
        )
        assert (status, attention) == ("batch_reconciled_history_incomplete", False), reasons

    @pytest.mark.skipif(
        not WORKER_PATH.exists(), reason="worker script not present in this checkout"
    )
    async def test_worker_classifies_source_failure_as_retryable(
        self, controller, tmp_path
    ) -> None:
        spec = importlib.util.spec_from_file_location("recovery_worker", WORKER_PATH)
        assert spec is not None and spec.loader is not None
        worker = importlib.util.module_from_spec(spec)
        sys.modules["recovery_worker"] = worker
        spec.loader.exec_module(worker)

        def crasher(*, month: str, run_id: str, capture: Any, **kwargs: Any):
            capture.begin_request(EXPECTED_URL)
            capture.response_started(FakeResponse(b"partial"))
            capture.add_chunk(ZIP_BODY[:16])
            capture.finish_stream(True)
            raise RuntimeError("transport cut after full stream flag")

        result = await run_apply(controller, tmp_path, managed_runner=crasher)
        report = {
            "mode": "apply",
            "selection": {"selected_month": MONTH},
            "result": result,
        }
        status, attention, reasons = worker._classify_option(
            1, report, artifact_root=tmp_path / "snapshots"
        )
        assert result["status"] in worker.OPTION_SOURCE_FAILURE_STATUSES
        assert (status, attention) == ("source_failed_retryable", False), reasons

    @pytest.mark.skipif(
        not WORKER_PATH.exists(), reason="worker script not present in this checkout"
    )
    async def test_worker_classifies_no_work_and_deferral_contracts(
        self, controller, tmp_path
    ) -> None:
        spec = importlib.util.spec_from_file_location("recovery_worker", WORKER_PATH)
        assert spec is not None and spec.loader is not None
        worker = importlib.util.module_from_spec(spec)
        sys.modules["recovery_worker"] = worker
        spec.loader.exec_module(worker)

        no_work = {
            "mode": "apply",
            "status": "no_eligible_month",
            "selected_month": None,
            "selection": {
                "selected_month": None,
                "selection_reason": "no_eligible_month_before_current_month_refresh_fallback",
                "fairness_cursor_month": None,
                "verified_month_count": 0,
                "deferred": [],
                "source_lifecycle": "unknown",
                "candidate_start_is_inception": False,
            },
            "execution_budget": controller._budget_semantics(180),
        }
        status, attention, _ = worker._classify_option(
            0, no_work, artifact_root=tmp_path / "snapshots"
        )
        assert (status, attention) == ("source_deferred", False)

        runner = verified_managed_runner(controller)
        ticks = iter([0.0, 121.0, 122.0, 123.0])
        deferred = await run_apply(
            controller, tmp_path, managed_runner=runner, monotonic=lambda: next(ticks)
        )
        deferred_report = {
            "mode": "apply",
            "selection": {"selected_month": MONTH},
            "result": deferred,
        }
        status, attention, _ = worker._classify_option(
            1, deferred_report, artifact_root=tmp_path / "snapshots"
        )
        assert (status, attention) == ("deferred_budget_retryable", False)


class TestCliEndToEnd:
    def test_cli_apply_reports_and_exits_by_contract(
        self, controller, monkeypatch, tmp_path
    ) -> None:
        runner = verified_managed_runner(controller)

        async def fake_month_call(
            month: str, run_id: str, capture: Any, budget_seconds: int, source_timeout_seconds: int
        ):
            return runner(
                month=month,
                run_id=run_id,
                capture=capture,
                budget_seconds=budget_seconds,
                source_timeout_seconds=source_timeout_seconds,
            )

        monkeypatch.setattr(controller, "_managed_month_call", fake_month_call)
        output = tmp_path / "option-report.json"
        exit_code = controller.main(
            [
                "--apply",
                "--max-minutes",
                "3",
                "--source-timeout-seconds",
                "90",
                "--start-month",
                MONTH,
                "--end-month",
                MONTH,
                "--progress",
                str(tmp_path / "progress.jsonl"),
                "--artifacts",
                str(tmp_path / "snapshots"),
                "--output",
                str(output),
            ]
        )
        assert exit_code == 0
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["mode"] == "apply"
        assert report["result"]["status"] == "verified_source_archive_snapshot"
        assert report["result"]["candidate_start_month_is_inception"] is False

    def test_cli_apply_without_candidates_is_a_clean_no_work_run(
        self, controller, tmp_path, capsys
    ) -> None:
        ledger = tmp_path / "progress.jsonl"
        now_iso = datetime.now(UTC).isoformat()
        genesis = "0" * 64
        event = {
            "schema_version": 1,
            "month": MONTH,
            "status": "verified_source_archive_snapshot",
            "recorded_at_utc": now_iso,
            "previous_event_sha256": genesis,
        }
        event["event_sha256"] = controller._event_sha256(event)
        ledger.write_text(json.dumps(event) + "\n", encoding="utf-8")
        exit_code = controller.main(
            [
                "--apply",
                "--start-month",
                MONTH,
                "--end-month",
                MONTH,
                "--progress",
                str(ledger),
                "--artifacts",
                str(tmp_path / "snapshots"),
            ]
        )
        assert exit_code == 0
        report = json.loads(capsys.readouterr().out)
        assert report["status"] == "no_eligible_month"
        assert report["selection"]["selected_month"] is None
        assert report["selection"]["source_lifecycle"] == "unknown"
        assert report["selection"]["candidate_start_is_inception"] is False
        assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1
