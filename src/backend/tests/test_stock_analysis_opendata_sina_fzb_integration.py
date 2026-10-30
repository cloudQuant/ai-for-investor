"""Mock-only tests for the opt-in Sina FZB stock-analysis integration."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from app.config import Settings
from app.schemas.stock_analysis import (
    StockAnalysisParams,
    StockAnalysisSinaFzbSnapshotSelection,
)
from app.services.stock_analysis import tasks as stock_analysis_tasks_module
from app.services.stock_analysis.data_collector import StockAnalysisDataCollector
from app.services.stock_analysis.opendata_sina_fzb_snapshot import (
    OpenDataSinaFzbSnapshotError,
    OpenDataSinaFzbSnapshotReader,
)
from app.services.stock_analysis.report_builder import StockAnalysisReportBuilder
from app.services.stock_analysis.tasks import StockAnalysisTaskService

_INSTRUMENT_ID = "600519.SH"
_PUBLICATION_ID = "a" * 32
_CAPTURE_ID = "b" * 64


def _selection() -> StockAnalysisSinaFzbSnapshotSelection:
    return StockAnalysisSinaFzbSnapshotSelection(
        instrument_id=_INSTRUMENT_ID,
        publication_id=_PUBLICATION_ID,
        capture_id=_CAPTURE_ID,
    )


def _params_with_selection() -> StockAnalysisParams:
    return StockAnalysisParams(
        symbol=_INSTRUMENT_ID,
        opendata_sina_fzb_snapshot={
            "instrument_id": _INSTRUMENT_ID,
            "publication_id": _PUBLICATION_ID,
            "capture_id": _CAPTURE_ID,
        },
    )


def _reader_result(*, records: tuple[dict[str, Any], ...]) -> SimpleNamespace:
    return SimpleNamespace(
        snapshot={
            "snapshot_id": "c" * 32,
            "dataset_id": "sina_fzb_report_observations",
            "sequence": 7,
            "selection_sha256": "d" * 64,
            "content_sha256": "e" * 64,
            "contract_sha256": "f" * 64,
            "as_of": "2026-10-30T01:00:00+00:00",
            "expires_at": "2026-10-30T01:10:00+00:00",
        },
        records=records,
        page_count=1,
        completeness="unknown",
        historical_as_of_status="unavailable",
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
            STOCK_ANALYSIS_OPENDATA_SINA_FZB_SNAPSHOT_ENABLED=enabled,
            STOCK_ANALYSIS_OPENDATA_SINA_FZB_ALLOWED_HOSTS="",
        ),
        sina_fzb_snapshot_reader=reader,  # type: ignore[arg-type]
    )


async def _collect_with_sina_reader(
    collector: StockAnalysisDataCollector,
    monkeypatch: pytest.MonkeyPatch,
    *,
    selection: StockAnalysisSinaFzbSnapshotSelection | None,
) -> dict[str, Any]:
    market_payload = {
        "symbol": _INSTRUMENT_ID,
        "name": "sample",
        "provider": "fixture",
        "snapshot": {"symbol": _INSTRUMENT_ID, "name": "sample", "price": 100.0},
        "history": {"rows": [{"trade_date": "2026-10-30"}]},
        "indicators": {"rsi": 50.0},
    }
    monkeypatch.setattr(
        collector, "_collect_market", AsyncMock(return_value=market_payload)
    )
    monkeypatch.setattr(
        collector,
        "_collect_company_context",
        AsyncMock(return_value=({"symbol": _INSTRUMENT_ID}, {"items": [], "total": 0})),
    )
    monkeypatch.setattr(
        collector,
        "_collect_news",
        AsyncMock(return_value={"items": [{"title": "fixture"}], "total": 1}),
    )

    akshare_fetch = Mock(return_value=(None, None))
    monkeypatch.setattr(collector, "_fetch_cn_financial_frames", akshare_fetch)
    result = await collector.collect(
        user_id="user-1",
        symbol=_INSTRUMENT_ID,
        market_type="A股",
        analysis_date=date(2026, 10, 30),
        opendata_sina_fzb_snapshot=selection,
    )
    akshare_fetch.assert_not_called()
    return result


@pytest.mark.parametrize(
    "legacy_payload",
    [
        {"symbol": _INSTRUMENT_ID},
        {"symbol": "600519.SH", "market_type": "A股", "research_depth": "标准"},
    ],
)
def test_legacy_stock_analysis_parameters_default_to_no_sina_snapshot(
    legacy_payload: dict[str, str],
) -> None:
    params = StockAnalysisParams.model_validate(legacy_payload)

    assert params.opendata_sina_fzb_snapshot is None
    assert params.model_dump(mode="json")["opendata_sina_fzb_snapshot"] is None


def test_sina_snapshot_server_switch_defaults_off() -> None:
    assert Settings.model_fields["STOCK_ANALYSIS_OPENDATA_SINA_FZB_SNAPSHOT_ENABLED"].default is False


def test_sina_snapshot_selection_is_explicit_and_bound_to_analysis_symbol() -> None:
    params = _params_with_selection()

    assert params.opendata_sina_fzb_snapshot is not None
    assert params.model_dump(mode="json")["opendata_sina_fzb_snapshot"] == {
        "instrument_id": _INSTRUMENT_ID,
        "publication_id": _PUBLICATION_ID,
        "capture_id": _CAPTURE_ID,
    }

    with pytest.raises(ValueError):
        StockAnalysisParams(
            symbol="600519.SH",
            opendata_sina_fzb_snapshot={
                "instrument_id": "000001.SZ",
                "publication_id": _PUBLICATION_ID,
                "capture_id": _CAPTURE_ID,
            },
        )
    with pytest.raises(ValueError):
        StockAnalysisSinaFzbSnapshotSelection(
            instrument_id="600519.BJ",
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )


def test_report_attributes_successful_sina_snapshot_without_copying_source_records() -> None:
    provenance = {
        "status": "ok",
        "source": "sina-fzb",
        "instrument_id": _INSTRUMENT_ID,
        "publication_id": _PUBLICATION_ID,
        "capture_id": _CAPTURE_ID,
        "record_count": 1,
        "content_sha256": "e" * 64,
        "temporal_semantics": "none",
        "eligible_for_decision_or_backtest": False,
    }
    snapshot = {
        "financials": {
            "provider": "opendata",
            "annual": [],
            "quarterly": [],
            "opendata_sina_fzb_snapshot": provenance,
        },
        "data_quality": {"status": "degraded"},
    }

    report = StockAnalysisReportBuilder().build(
        symbol=_INSTRUMENT_ID,
        symbol_name="贵州茅台",
        market_type="A股",
        analysis_date="2026-10-30",
        research_depth="标准",
        snapshot=snapshot,
        pipeline_output={},
    )

    assert "opendata:sina_fzb_snapshot" in report["data_sources"]
    assert "opendata:financial_archive" not in report["data_sources"]
    assert report["source_snapshot"]["financials"]["opendata_sina_fzb_snapshot"] == provenance
    assert "records" not in report["source_snapshot"]["financials"]["opendata_sina_fzb_snapshot"]


@pytest.mark.asyncio
async def test_explicit_sina_snapshot_keeps_only_provenance_and_never_uses_akshare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_marker = "private-source-native-value-must-not-escape"
    reader = _FakeReader(_reader_result(records=({"raw_value": raw_marker},)))
    collector = _collector(enabled=True, reader=reader)

    akshare_fetch = Mock(return_value=(None, None))
    monkeypatch.setattr(collector, "_fetch_cn_financial_frames", akshare_fetch)
    financials = await collector._collect_financials(
        symbol=_INSTRUMENT_ID,
        market_type="A股",
        analysis_date=date(2026, 10, 30),
        market_payload={
            "symbol": _INSTRUMENT_ID,
            "provider": "local-cache",
            "snapshot": {"revenue": 123.0},
        },
        opendata_sina_fzb_snapshot=_selection(),
    )

    akshare_fetch.assert_not_called()
    assert reader.calls == [
        {
            "instrument_id": _INSTRUMENT_ID,
            "publication_id": _PUBLICATION_ID,
            "capture_id": _CAPTURE_ID,
        }
    ]
    assert financials["provider"] == "opendata"
    assert financials["annual"] == []
    assert financials["quarterly"] == []
    assert financials["opendata_sina_fzb_snapshot"] == {
        "status": "ok",
        "source": "sina-fzb",
        "dataset_id": "sina_fzb_report_observations",
        "instrument_id": _INSTRUMENT_ID,
        "publication_id": _PUBLICATION_ID,
        "capture_id": _CAPTURE_ID,
        "record_count": 1,
        "page_count": 1,
        "reason_code": None,
        "temporal_semantics": "none",
        "eligible_for_decision_or_backtest": False,
        "snapshot_id": "c" * 32,
        "publication_sequence": 7,
        "selection_sha256": "d" * 64,
        "content_sha256": "e" * 64,
        "contract_sha256": "f" * 64,
        "as_of": "2026-10-30T01:00:00+00:00",
        "expires_at": "2026-10-30T01:10:00+00:00",
        "completeness": "unknown",
        "historical_as_of_status": "unavailable",
    }
    assert raw_marker not in repr(financials)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled", "selection", "expected_reason"),
    [
        (True, None, "selector_missing"),
        (False, _selection(), "feature_disabled"),
    ],
)
async def test_sina_snapshot_requires_both_server_switch_and_request_selector(
    enabled: bool,
    selection: StockAnalysisSinaFzbSnapshotSelection | None,
    expected_reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _FakeReader(_reader_result(records=()))
    collector = _collector(enabled=enabled, reader=reader)

    akshare_fetch = Mock(return_value=(None, None))
    monkeypatch.setattr(collector, "_fetch_cn_financial_frames", akshare_fetch)
    financials = await collector._collect_financials(
        symbol=_INSTRUMENT_ID,
        market_type="A股",
        analysis_date=date(2026, 10, 30),
        market_payload={"symbol": _INSTRUMENT_ID},
        opendata_sina_fzb_snapshot=selection,
    )

    akshare_fetch.assert_not_called()
    assert reader.calls == []
    assert financials["opendata_sina_fzb_snapshot"]["reason_code"] == expected_reason
    assert financials["annual"] == []
    assert financials["quarterly"] == []


@pytest.mark.asyncio
async def test_reader_failure_or_empty_capture_is_fail_closed_without_raw_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for reader, expected_status, expected_reason in (
        (
            _FakeReader(OpenDataSinaFzbSnapshotError("http_503")),
            "unavailable",
            "http_503",
        ),
        (_FakeReader(_reader_result(records=())), "empty", "snapshot_empty"),
    ):
        collector = _collector(enabled=True, reader=reader)

        akshare_fetch = Mock(return_value=(None, None))
        monkeypatch.setattr(collector, "_fetch_cn_financial_frames", akshare_fetch)
        financials = await collector._collect_financials(
            symbol=_INSTRUMENT_ID,
            market_type="A股",
            analysis_date=date(2026, 10, 30),
            market_payload={"symbol": _INSTRUMENT_ID},
            opendata_sina_fzb_snapshot=_selection(),
        )

        akshare_fetch.assert_not_called()
        evidence = financials["opendata_sina_fzb_snapshot"]
        assert evidence["status"] == expected_status
        assert evidence["reason_code"] == expected_reason
        assert "records" not in evidence
        assert financials["annual"] == []
        assert financials["quarterly"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "error_code",
        "expected_code",
        "expected_description",
        "injected_sensitive_markers",
    ),
    [
        (
            "http_503",
            "http_503",
            "OpenData 服务暂时不可用（503）。",
            (),
        ),
        (
            "http_server_error",
            "http_server_error",
            "OpenData 服务返回了服务器错误。",
            (),
        ),
        (
            "http_403_forbidden",
            "http_403_forbidden",
            "OpenData 数据集或操作权限不足（403）。",
            (),
        ),
        (
            "Authorization: Bearer sk-test-secret-marker; "
            "URL=https://private.example.test/path; body=private-response-body",
            "reader_error",
            "OpenData 未能提供符合冻结合同的完整快照。",
            (
                "sk-test-secret-marker",
                "private.example.test",
                "Authorization",
                "private-response-body",
            ),
        ),
    ],
)
async def test_explicit_sina_failure_has_safe_reason_in_collector_and_report(
    error_code: str,
    expected_code: str,
    expected_description: str,
    injected_sensitive_markers: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _FakeReader(OpenDataSinaFzbSnapshotError(error_code))
    result = await _collect_with_sina_reader(
        _collector(enabled=True, reader=reader), monkeypatch, selection=_selection()
    )

    evidence = result["financials"]["opendata_sina_fzb_snapshot"]
    assert evidence["status"] == "unavailable"
    assert evidence["reason_code"] == expected_code
    failure_reason = next(
        reason
        for reason in result["data_quality"]["degraded_reasons"]
        if reason.startswith("新浪 FZB OpenData 快照读取失败（")
    )
    assert f"（{expected_code}）：" in failure_reason
    assert expected_description in failure_reason

    report = StockAnalysisReportBuilder().build(
        symbol=_INSTRUMENT_ID,
        symbol_name="sample",
        market_type="A股",
        analysis_date="2026-10-30",
        research_depth="标准",
        snapshot=result,
        pipeline_output={},
    )
    assert report["data_quality"] == result["data_quality"]
    assert (
        report["source_snapshot"]["financials"]["opendata_sina_fzb_snapshot"]["reason_code"]
        == expected_code
    )
    serialized_report = repr(report)
    for marker in injected_sensitive_markers:
        assert marker not in serialized_report


@pytest.mark.asyncio
async def test_sina_failure_detail_is_limited_to_explicit_failed_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _FakeReader(_reader_result(records=()))
    result = await _collect_with_sina_reader(
        _collector(enabled=True, reader=reader), monkeypatch, selection=None
    )

    assert reader.calls == []
    assert result["financials"]["opendata_sina_fzb_snapshot"]["reason_code"] == (
        "selector_missing"
    )
    assert all(
        "快照读取失败" not in reason
        for reason in result["data_quality"]["degraded_reasons"]
    )
    assert "selector_missing" not in repr(result["data_quality"])


@pytest.mark.asyncio
async def test_successful_sina_selection_does_not_add_failure_degraded_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_marker = "source-native-secret-shaped-value"
    reader = _FakeReader(_reader_result(records=({"raw_value": raw_marker},)))
    result = await _collect_with_sina_reader(
        _collector(enabled=True, reader=reader), monkeypatch, selection=_selection()
    )

    assert result["financials"]["opendata_sina_fzb_snapshot"]["status"] == "ok"
    assert result["financials"]["opendata_sina_fzb_snapshot"]["reason_code"] is None
    assert all(
        "快照读取失败" not in reason
        for reason in result["data_quality"]["degraded_reasons"]
    )
    assert raw_marker not in repr(result)


@pytest.mark.asyncio
async def test_environment_reader_factory_receives_allowlist_without_exposing_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _FakeReader(_reader_result(records=()))
    seen_allowlists: list[str] = []

    def fake_from_environment(
        cls: type[OpenDataSinaFzbSnapshotReader], *, allowed_hosts: str
    ) -> _FakeReader:
        del cls
        seen_allowlists.append(allowed_hosts)
        return reader

    monkeypatch.setattr(
        OpenDataSinaFzbSnapshotReader,
        "from_environment",
        classmethod(fake_from_environment),
    )
    collector = StockAnalysisDataCollector(
        object(),
        settings=SimpleNamespace(
            STOCK_ANALYSIS_OPENDATA_SINA_FZB_SNAPSHOT_ENABLED=True,
            STOCK_ANALYSIS_OPENDATA_SINA_FZB_ALLOWED_HOSTS="opendata.example.test",
        ),
    )

    financials = await collector._collect_financials(
        symbol=_INSTRUMENT_ID,
        market_type="A股",
        analysis_date=date(2026, 10, 30),
        market_payload={"symbol": _INSTRUMENT_ID},
        opendata_sina_fzb_snapshot=_selection(),
    )

    assert seen_allowlists == ["opendata.example.test"]
    assert reader.calls[0]["publication_id"] == _PUBLICATION_ID
    assert financials["opendata_sina_fzb_snapshot"]["status"] == "empty"


class _ScalarResult:
    def scalar_one(self) -> int:
        return 0


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    async def execute(self, _statement: Any) -> _ScalarResult:
        return _ScalarResult()

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_task_parameters_persist_and_rehydrate_explicit_snapshot_selector() -> None:
    session = _FakeSession()
    task = await StockAnalysisTaskService(session).create_pending(
        user_id="user-1",
        params=_params_with_selection(),
        request_text="review request",
    )

    assert task.parameters_json is not None
    restored = StockAnalysisParams.model_validate(task.parameters_json)
    assert restored.opendata_sina_fzb_snapshot == _selection()

    # Existing durable task rows predate the optional selector and must remain readable.
    legacy = StockAnalysisParams.model_validate({"symbol": _INSTRUMENT_ID})
    assert legacy.opendata_sina_fzb_snapshot is None


@pytest.mark.asyncio
async def test_background_task_runner_forwards_persisted_selector_to_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = StockAnalysisTaskService(session)
    pending = await service.create_pending(
        user_id="user-1",
        params=_params_with_selection(),
        request_text="review request",
    )
    restored = StockAnalysisParams.model_validate(pending.parameters_json or {})
    collector_call: dict[str, Any] = {}

    async def collect(**kwargs: Any) -> dict[str, Any]:
        collector_call.update(kwargs)
        return {
            "info": {"name": "贵州茅台"},
            "data_quality": {"status": "degraded"},
        }

    service.collector = SimpleNamespace(collect=collect)  # type: ignore[assignment]
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

        async def create_prediction(self, **_kwargs: Any) -> SimpleNamespace:
            return signal_prediction

        async def attach_report(self, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(stock_analysis_tasks_module, "StockSignalService", _FakeSignalService)
    service.pipeline = SimpleNamespace(
        run=AsyncMock(return_value={"scores": {}, "decision": {}})
    )  # type: ignore[assignment]
    service.report_builder = SimpleNamespace(
        build=lambda **_kwargs: {"decision": {}, "executive_summary": "report"}
    )  # type: ignore[assignment]
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
    )

    await service._run_task(task, restored, date(2026, 10, 30))

    assert collector_call["opendata_sina_fzb_snapshot"] == _selection()
