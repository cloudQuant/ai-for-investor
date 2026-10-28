"""Mock-only coverage for stock-analysis OpenData financial evidence."""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.stock_analysis.analysis_engine import StockAnalysisEngine
from app.services.stock_analysis.data_collector import StockAnalysisDataCollector
from app.services.stock_analysis.opendata_financial_archive import (
    OpenDataFinancialArchiveError,
    OpenDataFinancialArchiveReader,
)
from app.services.stock_analysis.pipeline import StockAnalysisPipeline
from app.services.stock_analysis.report_builder import StockAnalysisReportBuilder

_ANALYSIS_DATE = date(2026, 7, 30)
_SYMBOL = "600519.SH"
_API_KEY = "fixture-financial-api-key"


class _Frame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_dict(self, *, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return list(self._rows)


def _successful_payload(params: httpx.QueryParams) -> dict[str, object]:
    scope = {
        key: params[key]
        for key in (
            "source_id",
            "instrument_id",
            "statement_type",
            "periodicity",
            "start_report_period",
            "end_report_period",
        )
    }
    return {
        "scope": scope,
        "records": [
            {
                "source_id": scope["source_id"],
                "instrument_id": scope["instrument_id"],
                "statement_type": scope["statement_type"],
                "periodicity": scope["periodicity"],
                "report_period": "2025-12-31",
                "source_disclosure_date": "2026-04-30",
                "observed_at_utc": "2026-10-28T02:15:30.123456Z",
                "item_code": "revenue_total",
                "value_decimal_text": "123456789.2300",
                "native_unit": "CNY",
            }
        ],
        "completeness": "unknown",
        "point_in_time_reconstruction": "unavailable",
        "period_amount_semantics": "unknown",
    }


def _collector(
    *,
    enabled: bool,
    reader: OpenDataFinancialArchiveReader | None = None,
) -> StockAnalysisDataCollector:
    return StockAnalysisDataCollector(
        SimpleNamespace(),
        settings=SimpleNamespace(
            STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ENABLED=enabled
        ),
        financial_archive_reader=reader,
    )


async def _collect_snapshot(
    collector: StockAnalysisDataCollector,
    *,
    market_type: str = "A股",
) -> dict[str, object]:
    collector._collect_market = AsyncMock(
        return_value={
            "symbol": _SYMBOL,
            "snapshot": {"symbol": _SYMBOL, "name": "贵州茅台", "price": 1500},
            "history": {"rows": []},
            "indicators": {},
        }
    )
    collector._collect_company_context = AsyncMock(
        return_value=({"symbol": _SYMBOL, "name": "贵州茅台"}, {"items": [], "total": 0})
    )
    collector._collect_news = AsyncMock(return_value={"items": [], "total": 0})
    return await collector.collect(
        user_id="fixture-user",
        symbol=_SYMBOL,
        market_type=market_type,
        analysis_date=_ANALYSIS_DATE,
    )


def test_stock_analysis_financial_archive_flag_is_default_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ENABLED", raising=False)
    monkeypatch.delenv(
        "STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ALLOWED_HOSTS",
        raising=False,
    )
    settings = Settings(_env_file=None)

    assert settings.STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ENABLED is False
    assert settings.STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ALLOWED_HOSTS == ""


@pytest.mark.asyncio
async def test_disabled_archive_keeps_existing_akshare_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    abstract = _Frame([{"指标": "营业总收入", "20241231": "100.00"}])
    indicators = _Frame([])
    monkeypatch.setattr(
        StockAnalysisDataCollector,
        "_fetch_cn_financial_frames",
        staticmethod(lambda _symbol, _start_year: (abstract, indicators)),
    )
    collector = _collector(enabled=False)

    financials = await collector._collect_financials(
        symbol=_SYMBOL,
        market_type="A股",
        analysis_date=_ANALYSIS_DATE,
        market_payload={"symbol": _SYMBOL, "snapshot": {}},
    )

    assert financials["provider"] == "akshare"
    assert financials["annual"] == [{"report_date": "2024-12-31", "revenue": 100.0}]
    assert financials["quarterly"] == []
    assert "raw_archive" not in financials


@pytest.mark.asyncio
async def test_enabled_reader_preserves_raw_rows_and_never_sends_them_to_llm() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/api/v2/data/financial-statements/archive"
        assert request.headers["X-API-Key"] == _API_KEY
        return httpx.Response(200, json=_successful_payload(request.url.params))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url="https://opendata.example.test"),
            client=client,
            allowed_hosts={"opendata.example.test"},
        )
        collector = _collector(enabled=True, reader=reader)
        collector._fetch_cn_financial_frames = lambda *_args: pytest.fail(
            "AkShare fallback must not run"
        )
        snapshot = await _collect_snapshot(collector)

    financials = snapshot["financials"]
    archive = financials["raw_archive"]
    assert len(requests) == 6
    assert {request.url.params["source_id"] for request in requests} == {"ths_fuyao"}
    assert {request.url.params["instrument_id"] for request in requests} == {_SYMBOL}
    assert {request.url.params["statement_type"] for request in requests} == {
        "income",
        "balance",
        "cashflow",
    }
    periodicities = {request.url.params["periodicity"] for request in requests}
    assert periodicities == {"annual", "quarterly"}
    assert all(request.url.params["page_size"] == "199" for request in requests)
    assert all(_API_KEY not in str(request.url) for request in requests)
    assert financials["annual"] == []
    assert financials["quarterly"] == []
    assert financials["provider"] == "opendata"
    assert archive["status"] == "observed"
    assert archive["records"][0]["value_decimal_text"] == "123456789.2300"
    assert archive["records"][0]["report_period"] == "2025-12-31"
    assert archive["records"][0]["source_disclosure_date"] == "2026-04-30"
    assert archive["records"][0]["observed_at_utc"] == "2026-10-28T02:15:30.123456Z"
    assert archive["records"][0]["native_unit"] == "CNY"
    assert archive["completeness"] == "unknown"
    assert archive["point_in_time_reconstruction"] == "unavailable"
    assert archive["period_amount_semantics"] == "unknown"
    assert archive["provenance_status"] == "incomplete"
    assert archive["observation_time_semantics"] == (
        "deduplicated_observation_timestamp_not_capture_time"
    )
    assert archive["eligible_for_decision_or_backtest"] is False
    assert snapshot["data_quality"]["status"] == "degraded"
    assert any(
        "provenance不完整" in item
        for item in snapshot["data_quality"]["degraded_reasons"]
    )

    engine = object.__new__(StockAnalysisEngine)
    source_context = json.loads(engine._source_context(snapshot))
    assert source_context["latest_financial"] == {}
    assert "raw_archive" not in source_context
    assert _API_KEY not in json.dumps(snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_reason", "expected_requests"),
    [
        (401, "http_401_unauthorized", 1),
        (403, "http_403_forbidden", 1),
        (413, "archive_scope_page_limit_exceeded", 6),
        (503, "http_503_server_error", 6),
    ],
)
async def test_http_failures_degrade_without_akshare_fallback(
    status_code: int,
    expected_reason: str,
    expected_requests: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(status_code, json={"message": _API_KEY})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url="https://opendata.example.test"),
            client=client,
            allowed_hosts={"opendata.example.test"},
        )
        collector = _collector(enabled=True, reader=reader)
        monkeypatch.setattr(
            collector,
            "_fetch_cn_financial_frames",
            lambda *_args: pytest.fail("AkShare fallback must not run"),
        )
        snapshot = await _collect_snapshot(collector)

    archive = snapshot["financials"]["raw_archive"]
    assert requests == expected_requests
    assert archive["status"] == "unavailable"
    assert all(not query.get("records") for query in archive["queries"])
    assert expected_reason in {query.get("reason_code") for query in archive["queries"]}
    assert _API_KEY not in json.dumps(archive)
    assert snapshot["data_quality"]["status"] == "degraded"
    assert any(
        expected_reason in item
        for item in snapshot["data_quality"]["degraded_reasons"]
    )
    assert snapshot["financials"]["annual"] == []
    assert snapshot["financials"]["quarterly"] == []


@pytest.mark.asyncio
async def test_empty_archive_is_visible_and_does_not_fall_back() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = _successful_payload(request.url.params)
        payload["records"] = []
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url="https://opendata.example.test"),
            client=client,
            allowed_hosts={"opendata.example.test"},
        )
        collector = _collector(enabled=True, reader=reader)
        collector._fetch_cn_financial_frames = lambda *_args: pytest.fail(
            "AkShare fallback must not run"
        )
        snapshot = await _collect_snapshot(collector)

    assert snapshot["financials"]["raw_archive"]["status"] == "empty"
    assert snapshot["financials"]["raw_archive"]["records"] == []
    assert snapshot["financials"]["annual"] == []
    assert snapshot["financials"]["quarterly"] == []
    assert any("未返回记录" in item for item in snapshot["data_quality"]["degraded_reasons"])


@pytest.mark.asyncio
async def test_scope_mismatch_is_rejected_and_only_valid_scopes_are_preserved() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = _successful_payload(request.url.params)
        if request.url.params["statement_type"] == "income":
            payload["scope"]["instrument_id"] = "000001.SZ"
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url="https://opendata.example.test"),
            client=client,
            allowed_hosts={"opendata.example.test"},
        )
        evidence = await reader.fetch_analysis_evidence(
            instrument_id=_SYMBOL,
            analysis_date=_ANALYSIS_DATE,
        )

    assert evidence["status"] == "partial"
    assert len(evidence["records"]) == 4
    assert {
        query.get("reason_code")
        for query in evidence["queries"]
        if query["status"] == "failed"
    } == {"response_scope_mismatch"}


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("600519", "600519.SH"),
        ("600519.SH", "600519.SH"),
        ("SH600519", "600519.SH"),
        ("000001", "000001.SZ"),
        ("920001", "920001.BJ"),
        ("920001.BJ", "920001.BJ"),
        ("BJ920001", "920001.BJ"),
        ("900001", None),
        ("920001.SH", None),
        ("BJ600519", None),
        ("200001.SZ", None),
    ],
)
def test_opendata_instrument_id_fails_closed_on_ambiguous_or_conflicting_venue(
    symbol: str,
    expected: str | None,
) -> None:
    assert StockAnalysisDataCollector._opendata_instrument_id(symbol) == expected


@pytest.mark.asyncio
async def test_non_loopback_http_is_rejected_before_sending_api_key() -> None:
    sent_requests = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal sent_requests
        sent_requests += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url="http://opendata.example.test"),
            client=client,
        )
        evidence = await reader.fetch_analysis_evidence(
            instrument_id=_SYMBOL,
            analysis_date=_ANALYSIS_DATE,
        )

    assert sent_requests == 0
    assert evidence["status"] == "unavailable"
    assert {
        query.get("reason_code") for query in evidence["queries"]
    } == {"base_url_insecure_transport"}
    assert _API_KEY not in json.dumps(evidence)


@pytest.mark.asyncio
async def test_unlisted_https_host_is_rejected_before_sending_api_key() -> None:
    sent_requests = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal sent_requests
        sent_requests += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url="https://opendata.example.test"),
            client=client,
            allowed_hosts={"approved.example.test"},
        )
        evidence = await reader.fetch_analysis_evidence(
            instrument_id=_SYMBOL,
            analysis_date=_ANALYSIS_DATE,
        )

    assert sent_requests == 0
    assert evidence["status"] == "unavailable"
    assert {
        query.get("reason_code") for query in evidence["queries"]
    } == {"base_url_host_not_allowed"}
    assert _API_KEY not in json.dumps(evidence)


@pytest.mark.asyncio
async def test_remote_https_nonstandard_port_requires_exact_host_port_allowlist() -> None:
    sent_requests = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal sent_requests
        sent_requests += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(
                _API_KEY,
                base_url="https://opendata.example.test:8443",
            ),
            client=client,
            allowed_hosts={"opendata.example.test"},
        )
        evidence = await reader.fetch_analysis_evidence(
            instrument_id=_SYMBOL,
            analysis_date=_ANALYSIS_DATE,
        )

    assert sent_requests == 0
    assert evidence["status"] == "unavailable"
    assert {
        query.get("reason_code") for query in evidence["queries"]
    } == {"base_url_host_not_allowed"}
    assert _API_KEY not in json.dumps(evidence)


@pytest.mark.asyncio
async def test_remote_https_nonstandard_port_can_be_explicitly_allowlisted() -> None:
    sent_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent_requests
        sent_requests += 1
        assert request.url.port == 8443
        return httpx.Response(200, json=_successful_payload(request.url.params))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(
                _API_KEY,
                base_url="https://opendata.example.test:8443",
            ),
            client=client,
            allowed_hosts={"opendata.example.test:8443"},
        )
        evidence = await reader.fetch_analysis_evidence(
            instrument_id=_SYMBOL,
            analysis_date=_ANALYSIS_DATE,
        )

    assert sent_requests == 6
    assert evidence["status"] == "observed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:password@opendata.example.test",
        "https://opendata.example.test/proxy",
        "https://opendata.example.test/?token=unsafe",
        "https://opendata.example.test/#fragment",
    ],
)
async def test_unsafe_base_url_shapes_are_rejected_before_sending_api_key(
    base_url: str,
) -> None:
    sent_requests = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal sent_requests
        sent_requests += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url=base_url),
            client=client,
            allowed_hosts={"opendata.example.test"},
        )
        evidence = await reader.fetch_analysis_evidence(
            instrument_id=_SYMBOL,
            analysis_date=_ANALYSIS_DATE,
        )

    assert sent_requests == 0
    assert evidence["status"] == "unavailable"
    assert {
        query.get("reason_code") for query in evidence["queries"]
    } == {"base_url_invalid"}
    assert _API_KEY not in json.dumps(evidence)


@pytest.mark.asyncio
async def test_loopback_http_is_allowed_for_local_opendata_development() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "127.0.0.1"
        assert request.url.port == 8123
        return httpx.Response(200, json=_successful_payload(request.url.params))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url="http://127.0.0.1:8123"),
            client=client,
        )
        evidence = await reader.fetch_analysis_evidence(
            instrument_id=_SYMBOL,
            analysis_date=_ANALYSIS_DATE,
        )

    assert evidence["status"] == "observed"


@pytest.mark.asyncio
async def test_archive_aggregate_byte_limit_fails_closed_at_exceeding_scope() -> None:
    first_scope = httpx.QueryParams(
        {
            "source_id": "ths_fuyao",
            "instrument_id": _SYMBOL,
            "statement_type": "income",
            "periodicity": "annual",
            "start_report_period": "2024-01-01",
            "end_report_period": _ANALYSIS_DATE.isoformat(),
        }
    )
    second_scope = httpx.QueryParams({**dict(first_scope), "periodicity": "quarterly"})
    first_body = json.dumps(_successful_payload(first_scope), separators=(",", ":")).encode()
    second_body = json.dumps(_successful_payload(second_scope), separators=(",", ":")).encode()
    request_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        payload = _successful_payload(request.url.params)
        return httpx.Response(
            200,
            content=json.dumps(payload, separators=(",", ":")).encode(),
            headers={"content-type": "application/json"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url="https://opendata.example.test"),
            client=client,
            max_archive_response_bytes=len(first_body) + len(second_body) - 1,
            allowed_hosts={"opendata.example.test"},
        )
        evidence = await reader.fetch_analysis_evidence(
            instrument_id=_SYMBOL,
            analysis_date=_ANALYSIS_DATE,
        )

    assert len(first_body) <= len(second_body)
    assert request_count == 2
    assert evidence["status"] == "partial"
    assert len(evidence["records"]) == 1
    assert evidence["queries"][0]["status"] == "ok"
    assert evidence["queries"][1]["reason_code"] == "archive_response_too_large"
    assert all(query["status"] == "not_attempted" for query in evidence["queries"][2:])
    assert evidence["completeness"] == "unknown"


@pytest.mark.asyncio
async def test_archive_limit_equal_to_scope_cap_is_reported_as_archive_overflow() -> None:
    first_scope = httpx.QueryParams(
        {
            "source_id": "ths_fuyao",
            "instrument_id": _SYMBOL,
            "statement_type": "income",
            "periodicity": "annual",
            "start_report_period": "2024-01-01",
            "end_report_period": _ANALYSIS_DATE.isoformat(),
        }
    )
    first_payload = _successful_payload(first_scope)
    first_body = json.dumps(first_payload, separators=(",", ":")).encode()
    max_response_bytes = len(first_body)
    max_archive_response_bytes = len(first_body) + max_response_bytes
    request_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        payload = _successful_payload(request.url.params)
        if request.url.params["periodicity"] == "quarterly":
            payload["records"][0]["item_code"] = "x" * (max_response_bytes + 100)
        body = json.dumps(payload, separators=(",", ":")).encode()
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "application/json"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url="https://opendata.example.test"),
            client=client,
            max_response_bytes=max_response_bytes,
            max_archive_response_bytes=max_archive_response_bytes,
            allowed_hosts={"opendata.example.test"},
        )
        evidence = await reader.fetch_analysis_evidence(
            instrument_id=_SYMBOL,
            analysis_date=_ANALYSIS_DATE,
        )

    assert request_count == 2
    assert evidence["status"] == "partial"
    assert evidence["queries"][0]["status"] == "ok"
    assert evidence["queries"][1]["reason_code"] == "archive_response_too_large"
    assert all(query["status"] == "not_attempted" for query in evidence["queries"][2:])


@pytest.mark.asyncio
async def test_scope_overflow_counts_only_bytes_retained_within_budget() -> None:
    retained_limit = 128 * 1024
    scope = {
        "source_id": "ths_fuyao",
        "instrument_id": _SYMBOL,
        "statement_type": "income",
        "periodicity": "annual",
        "start_report_period": "2024-01-01",
        "end_report_period": _ANALYSIS_DATE.isoformat(),
    }

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b" " * (retained_limit + 1),
            headers={"content-type": "application/json"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url="https://opendata.example.test"),
            client=client,
            allowed_hosts={"opendata.example.test"},
        )
        with pytest.raises(OpenDataFinancialArchiveError) as raised:
            await reader._read_scope(
                client,
                scope,
                timeout_seconds=1,
                max_response_bytes=retained_limit,
                overflow_code="archive_response_too_large",
            )

    assert raised.value.code == "archive_response_too_large"
    assert raised.value.response_bytes == retained_limit


@pytest.mark.asyncio
async def test_future_disclosure_is_labeled_and_not_claimed_as_historical_as_of() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = _successful_payload(request.url.params)
        if request.url.params["statement_type"] == "income":
            payload["records"][0]["source_disclosure_date"] = "2026-08-30"
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url="https://opendata.example.test"),
            client=client,
            allowed_hosts={"opendata.example.test"},
        )
        evidence = await reader.fetch_analysis_evidence(
            instrument_id=_SYMBOL,
            analysis_date=_ANALYSIS_DATE,
        )

    assert evidence["future_disclosure_record_count"] == 2
    assert evidence["historical_as_of_status"] == "unavailable"
    assert evidence["analysis_date_filtering"] == "report_period_only"
    assert "2条记录披露日晚于分析日" in (
        StockAnalysisDataCollector._financial_archive_degradation_reason(evidence)
    )
    assert all(
        record["disclosure_date_relation_to_analysis_date"]
        == (
            "after_analysis_date"
            if record["statement_type"] == "income"
            else "on_or_before_analysis_date"
        )
        for record in evidence["records"]
    )


@pytest.mark.asyncio
async def test_raw_only_archive_cannot_create_pipeline_financial_score_or_trade_signal() -> None:
    history_rows = []
    for index in range(70):
        close = 10.0 + index * 0.1
        history_rows.append(
            {
                "date": (_ANALYSIS_DATE - timedelta(days=69 - index)).isoformat(),
                "open": close - 0.02,
                "high": close + 0.1,
                "low": close - 0.1,
                "close": close,
                "volume": 1000 + index * 10,
            }
        )
    output = await StockAnalysisPipeline().run(
        symbol=_SYMBOL,
        market_type="A股",
        research_depth="标准",
        selected_modules=["fundamentals", "risk"],
        snapshot={
            "analysis_date": _ANALYSIS_DATE.isoformat(),
            "quote": {"symbol": _SYMBOL, "name": "贵州茅台", "price": 1500},
            "history": {"rows": history_rows},
            "financials": {
                "annual": [],
                "quarterly": [],
                "provider": "opendata",
                "raw_archive": {
                    "records": [
                        {
                            "item_code": "roe",
                            "value_decimal_text": "99.9999",
                            "native_unit": "%",
                        }
                    ]
                },
            },
            "news": {"items": []},
        },
    )

    assert output["scores"]["fundamental_score"] == 0
    assert output["decision"]["signal_action"] == "WATCH"
    assert output["decision"]["eligibility_status"] == "degraded"
    assert "financials_unavailable" in output["decision"]["quality_reasons"]


def test_report_lists_opendata_financial_archive_only_when_selected() -> None:
    builder = StockAnalysisReportBuilder()
    base = {
        "symbol": _SYMBOL,
        "symbol_name": "贵州茅台",
        "market_type": "A股",
        "analysis_date": _ANALYSIS_DATE.isoformat(),
        "research_depth": "标准",
        "pipeline_output": {},
    }
    selected = builder.build(
        **base,
        snapshot={
            "financials": {
                "annual": [],
                "quarterly": [],
                "provider": "opendata",
                "raw_archive": {"status": "observed", "records": []},
            }
        },
    )
    legacy = builder.build(**base, snapshot={"financials": {"provider": "akshare"}})

    assert selected["data_sources"] == [
        "market_data",
        "news_intelligence",
        "opendata:financial_archive",
    ]
    assert selected["source_snapshot"]["financials"]["raw_archive"]["status"] == "observed"
    assert legacy["data_sources"] == ["market_data", "news_intelligence"]


@pytest.mark.asyncio
async def test_oversized_body_is_rejected_without_exposing_its_contents() -> None:
    request_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            200,
            content=b"{" + (b" " * (256 * 1024)),
            headers={"content-type": "application/json"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = OpenDataFinancialArchiveReader(
            OpendataCredentials(_API_KEY, base_url="https://opendata.example.test"),
            client=client,
            allowed_hosts={"opendata.example.test"},
        )
        evidence = await reader.fetch_analysis_evidence(
            instrument_id=_SYMBOL,
            analysis_date=_ANALYSIS_DATE,
        )

    assert evidence["status"] == "unavailable"
    assert request_count == 4
    assert {
        query.get("reason_code") for query in evidence["queries"]
    } == {"response_too_large", "archive_response_too_large"}
    assert all(query["status"] == "not_attempted" for query in evidence["queries"][4:])
    assert evidence["records"] == []
    assert _API_KEY not in json.dumps(evidence)


@pytest.mark.asyncio
async def test_non_a_share_does_not_call_financial_archive_reader() -> None:
    collector = _collector(enabled=True)
    collector._financial_archive_reader = AsyncMock(
        side_effect=AssertionError("A-share-only reader was called")
    )

    financials = await collector._collect_financials(
        symbol="AAPL",
        market_type="美股",
        analysis_date=_ANALYSIS_DATE,
        market_payload={"symbol": "AAPL", "snapshot": {}},
    )

    assert financials["annual"] == []
    assert financials["quarterly"] == []
    assert "raw_archive" not in financials
