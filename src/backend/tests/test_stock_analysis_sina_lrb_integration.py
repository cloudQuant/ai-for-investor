"""Static fixture tests for the opt-in Sina LRB stock-analysis selector."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas.stock_analysis import (
    StockAnalysisParams,
    StockAnalysisSinaLrbSnapshotSelection,
)
from app.services.stock_analysis import tasks as stock_analysis_tasks_module
from app.services.stock_analysis.data_collector import StockAnalysisDataCollector
from app.services.stock_analysis.opendata_sina_lrb_snapshot import (
    OpenDataSinaLrbSnapshotError,
)
from app.services.stock_analysis.report_builder import StockAnalysisReportBuilder
from app.services.stock_analysis.tasks import StockAnalysisTaskService

_INSTRUMENT_ID = "600519.SH"
_PUBLICATION_ID = "a" * 32
_CAPTURE_ID = "b" * 64
_RAW_NODE_MARKER = "SOURCE_NATIVE_LRB_NODE_MUST_NOT_ESCAPE"


def _selection() -> StockAnalysisSinaLrbSnapshotSelection:
    return StockAnalysisSinaLrbSnapshotSelection(
        instrument_id=_INSTRUMENT_ID,
        publication_id=_PUBLICATION_ID,
        capture_id=_CAPTURE_ID,
    )


def _reader_result(*, records: tuple[dict[str, Any], ...] | None = None) -> SimpleNamespace:
    source_records = records or (
        {
            "record_kind": "report",
            "payload": {"nodes": [{"name": "营业收入", "value": _RAW_NODE_MARKER}]},
        },
        {
            "record_kind": "node",
            "payload": {"name": "营业收入", "value": _RAW_NODE_MARKER},
        },
    )
    return SimpleNamespace(
        snapshot={
            "snapshot_id": "c" * 32,
            "dataset_id": "sina_lrb_report_observations",
            "sequence": 7,
            "content_sha256": "d" * 64,
            "contract_sha256": "e" * 64,
            "as_of": "2026-10-30T01:00:00+00:00",
            "expires_at": "2026-10-30T01:10:00+00:00",
        },
        records=source_records,
        page_count=1,
        response_bytes=4096,
        report_count=1,
        completeness="unknown",
        historical_as_of_status="unavailable",
        eligible_for_decision_or_backtest=False,
        record_hash_verification="verified",
        selection_hash_verification="unavailable_access_scope_not_returned",
        content_hash_verification="unavailable_access_scope_not_returned",
    )


class _FakeReader:
    def __init__(self, result: SimpleNamespace | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, str]] = []

    async def fetch_capture(self, **kwargs: str) -> SimpleNamespace:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _collector(*, enabled: bool, reader: _FakeReader) -> StockAnalysisDataCollector:
    return StockAnalysisDataCollector(
        object(),
        settings=SimpleNamespace(
            STOCK_ANALYSIS_OPENDATA_SINA_LRB_SNAPSHOT_ENABLED=enabled,
            STOCK_ANALYSIS_OPENDATA_SINA_LRB_ALLOWED_HOSTS="localhost",
            STOCK_ANALYSIS_OPENDATA_SINA_FZB_SNAPSHOT_ENABLED=False,
            STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ENABLED=False,
        ),
        sina_lrb_snapshot_reader=reader,  # type: ignore[arg-type]
    )


def _market_payload() -> dict[str, Any]:
    return {
        "symbol": _INSTRUMENT_ID,
        "name": "贵州茅台",
        "provider": "fixture",
        "snapshot": {"symbol": _INSTRUMENT_ID, "name": "贵州茅台", "price": 100.0},
        "history": {"rows": [{"trade_date": "2026-10-30", "close": 100.0}]},
        "indicators": {"rsi": 50.0},
    }


def test_lrb_selector_is_strict_scoped_and_incompatible_with_fzb() -> None:
    params = StockAnalysisParams(
        symbol=_INSTRUMENT_ID,
        opendata_sina_lrb_snapshot={
            "instrument_id": _INSTRUMENT_ID,
            "publication_id": _PUBLICATION_ID,
            "capture_id": _CAPTURE_ID,
        },
    )
    assert params.opendata_sina_lrb_snapshot == _selection()
    assert (
        StockAnalysisParams.model_validate({"symbol": _INSTRUMENT_ID}).opendata_sina_lrb_snapshot
        is None
    )

    with pytest.raises(ValidationError):
        StockAnalysisParams(
            symbol="000001.SZ",
            opendata_sina_lrb_snapshot={
                "instrument_id": _INSTRUMENT_ID,
                "publication_id": _PUBLICATION_ID,
                "capture_id": _CAPTURE_ID,
            },
        )
    with pytest.raises(ValidationError):
        StockAnalysisParams(
            symbol=_INSTRUMENT_ID,
            market_type="美股",
            opendata_sina_lrb_snapshot={
                "instrument_id": _INSTRUMENT_ID,
                "publication_id": _PUBLICATION_ID,
                "capture_id": _CAPTURE_ID,
            },
        )
    with pytest.raises(ValidationError):
        StockAnalysisParams(
            symbol=_INSTRUMENT_ID,
            opendata_sina_fzb_snapshot={
                "instrument_id": _INSTRUMENT_ID,
                "publication_id": _PUBLICATION_ID,
                "capture_id": _CAPTURE_ID,
            },
            opendata_sina_lrb_snapshot={
                "instrument_id": _INSTRUMENT_ID,
                "publication_id": _PUBLICATION_ID,
                "capture_id": _CAPTURE_ID,
            },
        )


def test_lrb_feature_switch_is_default_off() -> None:
    settings = Settings(_env_file=None)
    assert settings.STOCK_ANALYSIS_OPENDATA_SINA_LRB_SNAPSHOT_ENABLED is False
    assert settings.STOCK_ANALYSIS_OPENDATA_SINA_LRB_ALLOWED_HOSTS == ""


@pytest.mark.asyncio
async def test_explicit_lrb_capture_retains_only_provenance_and_skips_other_financial_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _FakeReader(_reader_result())
    collector = _collector(enabled=True, reader=reader)
    monkeypatch.setattr(
        collector,
        "_collect_market",
        AsyncMock(return_value=_market_payload()),
    )
    monkeypatch.setattr(
        collector,
        "_collect_company_context",
        AsyncMock(return_value=({"symbol": _INSTRUMENT_ID}, {"items": [], "total": 0})),
    )
    monkeypatch.setattr(
        collector,
        "_collect_news",
        AsyncMock(return_value={"items": [], "total": 0}),
    )
    akshare_fallback = Mock(side_effect=AssertionError("LRB selector must not fall back"))
    monkeypatch.setattr(collector, "_fetch_cn_financial_frames", akshare_fallback)

    result = await collector.collect(
        user_id="user-1",
        symbol=_INSTRUMENT_ID,
        market_type="A股",
        analysis_date=date(2026, 10, 30),
        opendata_sina_lrb_snapshot=_selection(),
    )

    assert reader.calls == [
        {
            "instrument_id": _INSTRUMENT_ID,
            "publication_id": _PUBLICATION_ID,
            "capture_id": _CAPTURE_ID,
        }
    ]
    akshare_fallback.assert_not_called()
    assert result["financials"]["annual"] == []
    assert result["financials"]["quarterly"] == []
    assert "opendata_sina_lrb_snapshot" not in result["financials"]
    provenance = result["opendata_sina_lrb_snapshot"]
    assert provenance["record_count"] == 2
    assert provenance["report_count"] == 1
    assert provenance["completeness"] == "unknown"
    assert provenance["historical_as_of_status"] == "unavailable"
    assert provenance["eligible_for_decision_or_backtest"] is False
    assert provenance["record_hash_verification"] == "verified"
    assert provenance["selection_hash_verification"] == "unavailable_access_scope_not_returned"
    assert provenance["content_hash_verification"] == "unavailable_access_scope_not_returned"
    assert _RAW_NODE_MARKER not in repr(result)


@pytest.mark.asyncio
async def test_disabled_explicit_lrb_selector_fails_closed_without_fetch_or_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _FakeReader(_reader_result())
    collector = _collector(enabled=False, reader=reader)
    fallback = Mock(side_effect=AssertionError("selected LRB request must not fall back"))
    monkeypatch.setattr(collector, "_fetch_cn_financial_frames", fallback)

    financials = await collector._collect_financials(
        symbol=_INSTRUMENT_ID,
        market_type="A股",
        analysis_date=date(2026, 10, 30),
        market_payload=_market_payload(),
        opendata_sina_lrb_snapshot=_selection(),
    )

    assert reader.calls == []
    fallback.assert_not_called()
    assert financials["annual"] == []
    assert financials["quarterly"] == []
    assert financials["opendata_sina_lrb_snapshot"]["reason_code"] == "feature_disabled"


@pytest.mark.asyncio
async def test_enabled_flag_without_lrb_selector_preserves_existing_financial_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _FakeReader(_reader_result())
    collector = _collector(enabled=True, reader=reader)
    original_fetch = Mock(return_value=(object(), object()))
    monkeypatch.setattr(
        StockAnalysisDataCollector,
        "_fetch_cn_financial_frames",
        staticmethod(original_fetch),
    )
    monkeypatch.setattr(
        StockAnalysisDataCollector,
        "_normalize_cn_financials",
        classmethod(lambda _cls, *_args, **_kwargs: ([{"report_date": "2026-09-30"}], [])),
    )

    financials = await collector._collect_financials(
        symbol=_INSTRUMENT_ID,
        market_type="A股",
        analysis_date=date(2026, 10, 30),
        market_payload=_market_payload(),
        opendata_sina_lrb_snapshot=None,
    )

    assert reader.calls == []
    original_fetch.assert_called_once()
    assert financials["provider"] == "akshare"
    assert financials["annual"] == [{"report_date": "2026-09-30"}]


@pytest.mark.asyncio
async def test_lrb_selection_failure_is_sanitized_and_does_not_fall_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _FakeReader(OpenDataSinaLrbSnapshotError("transport_error"))
    collector = _collector(enabled=True, reader=reader)
    fallback = Mock(side_effect=AssertionError("selected LRB request must not fall back"))
    monkeypatch.setattr(collector, "_fetch_cn_financial_frames", fallback)

    financials = await collector._collect_financials(
        symbol=_INSTRUMENT_ID,
        market_type="A股",
        analysis_date=date(2026, 10, 30),
        market_payload=_market_payload(),
        opendata_sina_lrb_snapshot=_selection(),
    )

    assert reader.calls
    fallback.assert_not_called()
    summary = financials["opendata_sina_lrb_snapshot"]
    assert summary["status"] == "unavailable"
    assert summary["reason_code"] == "transport_error"
    assert _RAW_NODE_MARKER not in repr(financials)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("record_hash_verification", None),
        ("selection_hash_verification", "untrusted-selection-state"),
        ("content_hash_verification", "untrusted-content-state"),
    ],
)
async def test_missing_or_unrecognized_reader_hash_status_fails_closed(
    field: str,
    value: str | None,
) -> None:
    reader_result = _reader_result()
    if value is None:
        delattr(reader_result, field)
    else:
        setattr(reader_result, field, value)
    reader = _FakeReader(reader_result)
    collector = _collector(enabled=True, reader=reader)

    financials = await collector._collect_financials(
        symbol=_INSTRUMENT_ID,
        market_type="A股",
        analysis_date=date(2026, 10, 30),
        market_payload=_market_payload(),
        opendata_sina_lrb_snapshot=_selection(),
    )

    summary = financials["opendata_sina_lrb_snapshot"]
    assert summary["status"] == "unavailable"
    assert summary["reason_code"] == "reader_error"
    expected_states = {
        "record_hash_verification": "verified",
        "selection_hash_verification": "unavailable_access_scope_not_returned",
        "content_hash_verification": "unavailable_access_scope_not_returned",
    }
    expected_states[field] = "unverified"
    assert {key: summary[key] for key in expected_states} == expected_states
    assert "content_sha256" not in summary
    assert "untrusted" not in repr(summary)


@pytest.mark.asyncio
async def test_lrb_record_hash_mismatch_is_preserved_as_fixed_safe_code() -> None:
    reader = _FakeReader(OpenDataSinaLrbSnapshotError("record_hash_mismatch"))
    collector = _collector(enabled=True, reader=reader)

    financials = await collector._collect_financials(
        symbol=_INSTRUMENT_ID,
        market_type="A股",
        analysis_date=date(2026, 10, 30),
        market_payload=_market_payload(),
        opendata_sina_lrb_snapshot=_selection(),
    )

    summary = financials["opendata_sina_lrb_snapshot"]
    assert summary["status"] == "unavailable"
    assert summary["reason_code"] == "record_hash_mismatch"
    assert _RAW_NODE_MARKER not in repr(summary)


def test_report_lists_successful_lrb_snapshot_as_provenance_only() -> None:
    provenance = {
        "status": "ok",
        "source": "sina-lrb",
        "dataset_id": "sina_lrb_report_observations",
        "instrument_id": _INSTRUMENT_ID,
        "publication_id": _PUBLICATION_ID,
        "capture_id": _CAPTURE_ID,
        "record_count": 2,
        "report_count": 1,
        "completeness": "unknown",
        "historical_as_of_status": "unavailable",
        "eligible_for_decision_or_backtest": False,
    }
    report = StockAnalysisReportBuilder().build(
        symbol=_INSTRUMENT_ID,
        symbol_name="贵州茅台",
        market_type="A股",
        analysis_date="2026-10-30",
        research_depth="标准",
        snapshot={
            "financials": {"annual": [], "quarterly": []},
            "opendata_sina_lrb_snapshot": provenance,
            "data_quality": {"status": "degraded"},
        },
        pipeline_output={"decision": {}, "scores": {}},
    )

    assert "opendata:sina_lrb_snapshot" in report["data_sources"]
    assert report["source_snapshot"]["opendata_sina_lrb_snapshot"] == provenance
    assert _RAW_NODE_MARKER not in repr(report)


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_task_keeps_lrb_provenance_out_of_scoring_and_ai_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = StockAnalysisTaskService(session)  # type: ignore[arg-type]
    task_params = StockAnalysisParams(
        symbol=_INSTRUMENT_ID,
        model_id="test-model",
        opendata_sina_lrb_snapshot=_selection(),
    )
    provenance = {
        "status": "ok",
        "source": "sina-lrb",
        "dataset_id": "sina_lrb_report_observations",
        "instrument_id": _INSTRUMENT_ID,
        "publication_id": _PUBLICATION_ID,
        "capture_id": _CAPTURE_ID,
        "record_count": 2,
        "report_count": 1,
        "completeness": "unknown",
        "historical_as_of_status": "unavailable",
        "eligible_for_decision_or_backtest": False,
    }
    collector_call: dict[str, Any] = {}

    async def collect(**kwargs: Any) -> dict[str, Any]:
        collector_call.update(kwargs)
        return {
            "info": {"name": "贵州茅台"},
            "quote": {"price": 100.0},
            "history": {"rows": []},
            "financials": {"annual": [], "quarterly": []},
            "technicals": {"factors": {}},
            "news": {"items": []},
            "data_quality": {"status": "degraded"},
            "opendata_sina_lrb_snapshot": provenance,
        }

    service.collector = SimpleNamespace(collect=collect)  # type: ignore[assignment]
    observed: dict[str, Any] = {}
    signal_prediction = SimpleNamespace(
        id="prediction-1",
        signal_action="WATCH",
        confidence_score=0.5,
        risk_score=0.5,
        expected_excess_return=None,
        eligibility_status="rejected",
        quality_reasons_json=[],
        feature_version="test-v1",
        decision_policy_version="test-v1",
        model_version="test-v1",
        feature_snapshot_json={},
        data_freshness_json={},
    )

    class _FakeSignalService:
        def __init__(self, _db: Any) -> None:
            return None

        @staticmethod
        def user_scope(user_id: str) -> str:
            return f"user:{user_id}"

        async def create_prediction(self, **kwargs: Any) -> SimpleNamespace:
            # _run_task later reuses this dict when restoring report-only
            # provenance. Capture the call-time payload, not its later state.
            observed["signal_snapshot"] = deepcopy(kwargs["snapshot"])
            return signal_prediction

        async def attach_report(self, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(stock_analysis_tasks_module, "StockSignalService", _FakeSignalService)

    async def pipeline_run(**kwargs: Any) -> dict[str, Any]:
        observed["pipeline_snapshot"] = deepcopy(kwargs["snapshot"])
        return {"scores": {}, "decision": {}}

    service.pipeline = SimpleNamespace(run=pipeline_run)  # type: ignore[assignment]

    async def can_generate(*, user_id: str, model_id: str) -> bool:
        observed["ai_gate"] = {"user_id": user_id, "model_id": model_id}
        return True

    async def enhance(**kwargs: Any) -> dict[str, Any]:
        observed["ai_snapshot"] = deepcopy(kwargs["snapshot"])
        observed["ai_model_id"] = kwargs["model_id"]
        return kwargs["pipeline_output"]

    service.analysis_engine = SimpleNamespace(
        can_generate=can_generate,
        enhance=enhance,
    )  # type: ignore[assignment]

    def build_report(**kwargs: Any) -> dict[str, Any]:
        observed["report_snapshot"] = deepcopy(kwargs["snapshot"])
        return {"decision": {}, "executive_summary": "report"}

    service.report_builder = SimpleNamespace(build=build_report)  # type: ignore[assignment]
    service.exporter = SimpleNamespace(
        render_markdown=lambda _payload: "markdown",
        render_html=lambda _payload: "html",
    )  # type: ignore[assignment]
    service._record_ai_observability = AsyncMock()  # type: ignore[method-assign]

    task = SimpleNamespace(
        id="task-1",
        user_id="user-1",
        symbol=_INSTRUMENT_ID,
        symbol_name=None,
        market_type="A股",
        research_depth="标准",
        selected_modules=[],
        analysis_date="2026-10-30",
        data_quality_json={},
        started_at=None,
        step_events_json=[],
        status="pending",
        progress=0,
        current_step="created",
        message="created",
        request_text="review request",
        conversation_id=None,
        report_id=None,
        completed_at=None,
    )

    await service._run_task(task, task_params, date(2026, 10, 30))

    assert collector_call["opendata_sina_lrb_snapshot"] == _selection()
    assert observed["ai_gate"] == {"user_id": "user-1", "model_id": "test-model"}
    assert observed["ai_model_id"] == "test-model"
    for stage in ("signal_snapshot", "pipeline_snapshot", "ai_snapshot"):
        assert "opendata_sina_lrb_snapshot" not in observed[stage]
        assert _RAW_NODE_MARKER not in repr(observed[stage])
    assert observed["report_snapshot"]["opendata_sina_lrb_snapshot"] == provenance
