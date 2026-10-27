"""MockTransport reader tests; no external database, suite fixtures use in-memory SQLite."""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.stock_signal import batch as batch_module
from app.services.stock_signal.opendata_sse50_benchmark import (
    OpenDataSse50BenchmarkError,
    OpenDataSse50BenchmarkReader,
)
from app.services.stock_signal.outcomes import evaluate_outcome


def _payload(
    rows: list[dict[str, Any]],
    *,
    page: int,
    page_size: int,
    **overrides: object,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "domain": "index_daily",
        "asset_class": "index",
        "layer": "dwd",
        "source": "ths",
        "adjust": "none",
        "columns": ["symbol", "trade_date", "open", "close"],
        "rows": rows,
        "page": page,
        "page_size": page_size,
        "count": len(rows),
    }
    data.update(overrides)
    return {"success": True, "message": "success", "data": data}


def _bar(
    day: str,
    *,
    symbol: str = "000016",
    open_price: object = 2_000,
    close: object = 2_010,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_date": day,
        "open": open_price,
        "close": close,
    }


def _reader(
    client: httpx.AsyncClient,
    *,
    page_size: int = 2,
    max_rows: int = 10,
    max_pages: int = 6,
) -> OpenDataSse50BenchmarkReader:
    return OpenDataSse50BenchmarkReader(
        OpendataCredentials("test-key", base_url="https://opendata.example"),
        client=client,
        page_size=page_size,
        max_rows=max_rows,
        max_pages=max_pages,
    )


def _injected_reader_factory(reader: OpenDataSse50BenchmarkReader) -> type[Any]:
    class InjectedReader:
        @classmethod
        def from_environment(cls) -> OpenDataSse50BenchmarkReader:
            return reader

    return InjectedReader


@pytest.mark.asyncio
async def test_reader_uses_fixed_authenticated_contract_and_inclusive_dates() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/api/v1/data/index/index_daily"
        assert request.headers["x-api-key"] == "test-key"
        assert request.headers["accept"] == "application/json"
        assert request.url.params["symbols"] == "000016"
        assert request.url.params["start"] == "2026-07-01"
        assert request.url.params["end"] == "2026-07-31"
        assert request.url.params["source"] == "ths"
        assert request.url.params["layer"] == "dwd"
        assert request.url.params["adjust"] == "none"
        assert request.url.params["fields"] == "trade_date,open,close"
        page = int(request.url.params["page"])
        assert request.url.params["page_size"] == "2"
        rows = (
            [_bar("2026-07-01"), _bar("2026-07-02")]
            if page == 1
            else [_bar("2026-07-03", open_price=2_020, close=2_030)]
        )
        return httpx.Response(200, json=_payload(rows, page=page, page_size=2))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), trust_env=False, follow_redirects=True
    ) as client:
        reader = _reader(client)
        rows = await reader.fetch_rows(start_date=date(2026, 7, 1), end_date=date(2026, 7, 31))

    assert len(requests) == 2
    assert rows == [
        {"date": "2026-07-01", "open": 2_000.0, "close": 2_010.0},
        {"date": "2026-07-02", "open": 2_000.0, "close": 2_010.0},
        {"date": "2026-07-03", "open": 2_020.0, "close": 2_030.0},
    ]


@pytest.mark.asyncio
async def test_reader_does_not_follow_redirect_or_forward_api_key() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"location": "https://redirect.example/collect"},
        )

    # The client is deliberately configured to follow redirects; the reader must
    # override that per request so credentials stay on the configured OpenData origin.
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
        trust_env=False,
        follow_redirects=True,
    ) as client:
        reader = _reader(client)
        with pytest.raises(OpenDataSse50BenchmarkError) as raised:
            await reader.fetch_rows(start_date=date(2026, 7, 1), end_date=date(2026, 7, 31))

    assert raised.value.code == "OPENDATA_SSE50_HTTP_ERROR"
    assert len(requests) == 1
    assert requests[0].url.host == "opendata.example"
    assert requests[0].headers["x-api-key"] == "test-key"
    assert all(request.url.host != "redirect.example" for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "rows", "expected_code"),
    [
        ({"source": "auto"}, [_bar("2026-07-01")], "OPENDATA_SSE50_IDENTITY_MISMATCH"),
        ({}, [_bar("2026-08-01")], "OPENDATA_SSE50_DATE_OUT_OF_RANGE"),
        ({}, [_bar("2026-07-1")], "OPENDATA_SSE50_DATE_INVALID"),
        ({}, [_bar("2026-07-01", symbol="000300")], "OPENDATA_SSE50_SYMBOL_MISMATCH"),
        ({}, [_bar("2026-07-01", close=0)], "OPENDATA_SSE50_PRICE_INVALID"),
        ({}, [_bar("2026-07-01", open_price=10**400)], "OPENDATA_SSE50_PRICE_INVALID"),
        (
            {},
            [_bar("2026-07-01", close=float("nan"))],
            "OPENDATA_SSE50_RESPONSE_INVALID_JSON",
        ),
        ({"count": 2}, [_bar("2026-07-01")], "OPENDATA_SSE50_COUNT_INVALID"),
        ({"page": 2}, [_bar("2026-07-01")], "OPENDATA_SSE50_PAGE_MISMATCH"),
        ({"page_size": 5}, [_bar("2026-07-01")], "OPENDATA_SSE50_PAGE_SIZE_MISMATCH"),
    ],
)
async def test_reader_rejects_invalid_identity_dates_and_rows(
    overrides: dict[str, object], rows: list[dict[str, Any]], expected_code: str
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        payload = _payload(rows, page=1, page_size=2)
        payload["data"].update(overrides)
        body = json.dumps(payload, allow_nan=True).encode("utf-8")
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "application/json"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        reader = _reader(client)
        with pytest.raises(OpenDataSse50BenchmarkError) as raised:
            await reader.fetch_rows(start_date=date(2026, 7, 1), end_date=date(2026, 7, 31))

    assert raised.value.code == expected_code


@pytest.mark.asyncio
async def test_reader_rejects_repeated_page_dates_and_never_returns_partial_rows() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json=_payload([_bar("2026-07-01")], page=page, page_size=1),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        reader = _reader(client, page_size=1, max_pages=4)
        with pytest.raises(OpenDataSse50BenchmarkError) as raised:
            await reader.fetch_rows(start_date=date(2026, 7, 1), end_date=date(2026, 7, 31))

    assert raised.value.code == "OPENDATA_SSE50_DATE_ORDER_INVALID"


@pytest.mark.asyncio
async def test_reader_enforces_row_limit_without_exposing_a_truncated_page() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        day = "2026-07-01" if page == 1 else "2026-07-02"
        return httpx.Response(200, json=_payload([_bar(day)], page=page, page_size=1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        reader = _reader(client, page_size=1, max_rows=1, max_pages=3)
        with pytest.raises(OpenDataSse50BenchmarkError) as raised:
            await reader.fetch_rows(start_date=date(2026, 7, 1), end_date=date(2026, 7, 31))

    assert raised.value.code == "OPENDATA_SSE50_ROW_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_reader_requires_credentials_and_rejects_invalid_base_url() -> None:
    reader = OpenDataSse50BenchmarkReader(None)
    with pytest.raises(OpenDataSse50BenchmarkError) as missing:
        await reader.fetch_rows(start_date=date(2026, 7, 1), end_date=date(2026, 7, 31))
    assert missing.value.code == "OPENDATA_SSE50_CREDENTIAL_MISSING"

    invalid_base_reader = OpenDataSse50BenchmarkReader(
        OpendataCredentials("test-key", base_url="https://user:password@opendata.example")
    )
    with pytest.raises(OpenDataSse50BenchmarkError) as invalid_base:
        await invalid_base_reader.fetch_rows(
            start_date=date(2026, 7, 1), end_date=date(2026, 7, 31)
        )
    assert invalid_base.value.code == "OPENDATA_SSE50_BASE_URL_INVALID"


@pytest.mark.asyncio
async def test_enabled_batch_returns_empty_on_opendata_failure_without_akshare_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = batch_module.Sse50SignalBatchRunner.__new__(batch_module.Sse50SignalBatchRunner)
    runner.settings = SimpleNamespace(STOCK_SIGNAL_BENCHMARK_OPENDATA_ENABLED=True)

    class FailedReader:
        @classmethod
        def from_environment(cls) -> FailedReader:
            return cls()

        async def fetch_rows(self, **_kwargs: object) -> list[dict[str, Any]]:
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_FORBIDDEN")

    def forbidden_fallback(*_args: object) -> list[dict[str, Any]]:
        raise AssertionError("enabled OpenData mode must never fall back to AkShare")

    monkeypatch.setattr(batch_module, "OpenDataSse50BenchmarkReader", FailedReader)
    monkeypatch.setattr(runner, "_fetch_sse50_benchmark_rows", forbidden_fallback)

    rows = await runner._sse50_benchmark_rows(
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 31)
    )

    assert rows == []


@pytest.mark.asyncio
async def test_enabled_batch_logs_empty_success_separately_from_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = batch_module.Sse50SignalBatchRunner.__new__(batch_module.Sse50SignalBatchRunner)
    runner.settings = SimpleNamespace(STOCK_SIGNAL_BENCHMARK_OPENDATA_ENABLED=True)
    messages: list[str] = []
    monkeypatch.setattr(
        batch_module,
        "logger",
        SimpleNamespace(
            warning=lambda message, *args: messages.append(message % args if args else message)
        ),
    )

    class EmptyReader:
        @classmethod
        def from_environment(cls) -> EmptyReader:
            return cls()

        async def fetch_rows(self, **_kwargs: object) -> list[dict[str, Any]]:
            return []

    class FailedReader:
        @classmethod
        def from_environment(cls) -> FailedReader:
            return cls()

        async def fetch_rows(self, **_kwargs: object) -> list[dict[str, Any]]:
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_FORBIDDEN")

    monkeypatch.setattr(batch_module, "OpenDataSse50BenchmarkReader", EmptyReader)
    empty_rows = await runner._sse50_benchmark_rows(
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 31)
    )
    monkeypatch.setattr(batch_module, "OpenDataSse50BenchmarkReader", FailedReader)
    failed_rows = await runner._sse50_benchmark_rows(
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 31)
    )

    assert empty_rows == failed_rows == []
    assert messages == [
        "OpenData SSE50 benchmark empty code=OPENDATA_SSE50_EMPTY_SUCCESS",
        "OpenData SSE50 benchmark unavailable code=OPENDATA_SSE50_FORBIDDEN",
    ]


def _weekdays(start: date, count: int) -> list[date]:
    dates: list[date] = []
    current = start
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates


@pytest.mark.asyncio
async def test_batch_benchmark_rows_feed_outcomes_and_missing_rows_stay_unbenchmarked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = _weekdays(date(2026, 7, 1), 20)
    stock_rows = [
        {"date": day.isoformat(), "open": 50.0, "close": 51.0 + index}
        for index, day in enumerate(dates)
    ]
    benchmark_source_rows = [
        _bar(
            day.isoformat(),
            open_price=100.0 + index,
            close=101.0 + index,
        )
        for index, day in enumerate(dates)
    ]
    expected_stock_returns = {1: 0.02, 5: 0.10, 20: 0.40}
    expected_benchmark_returns = {1: 0.01, 5: 0.05, 20: 0.20}

    cases = [
        ("success", benchmark_source_rows),
        ("empty", []),
        ("failure", []),
    ]
    for case, source_rows in cases:

        def handle(
            request: httpx.Request,
            _case: str = case,
            _source_rows: list[dict[str, object]] = source_rows,
        ) -> httpx.Response:
            if _case == "failure":
                return httpx.Response(403, json={"detail": "forbidden"})
            return httpx.Response(
                200,
                json=_payload(_source_rows, page=1, page_size=1_000),
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle),
            trust_env=False,
        ) as client:
            reader = _reader(client, page_size=1_000, max_rows=100, max_pages=2)

            monkeypatch.setattr(
                batch_module,
                "OpenDataSse50BenchmarkReader",
                _injected_reader_factory(reader),
            )
            runner = batch_module.Sse50SignalBatchRunner.__new__(
                batch_module.Sse50SignalBatchRunner
            )
            runner.settings = SimpleNamespace(STOCK_SIGNAL_BENCHMARK_OPENDATA_ENABLED=True)
            monkeypatch.setattr(
                runner,
                "_fetch_sse50_benchmark_rows",
                lambda *_args: pytest.fail("OpenData benchmark mode must not use AkShare"),
            )

            benchmark_rows = await runner._sse50_benchmark_rows(
                start_date=dates[0], end_date=dates[-1]
            )

        evaluation = evaluate_outcome(
            prediction_action="BUY",
            next_trading_date=dates[0],
            price_rows=stock_rows,
            benchmark_rows=benchmark_rows,
            policy_snapshot={
                "round_trip_cost_bps": 0,
                "buy_success_threshold_bps": 0,
                "sell_success_threshold_bps": 0,
            },
        )

        assert evaluation.status == "scored"
        assert evaluation.horizon_returns == pytest.approx(expected_stock_returns)
        if case == "success":
            assert evaluation.benchmark_returns == pytest.approx(expected_benchmark_returns)
            assert evaluation.excess_returns == pytest.approx({1: 0.01, 5: 0.05, 20: 0.20})
        else:
            assert evaluation.benchmark_returns == {1: None, 5: None, 20: None}
            assert evaluation.excess_returns == {1: None, 5: None, 20: None}


@pytest.mark.asyncio
async def test_disabled_batch_keeps_the_existing_benchmark_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = batch_module.Sse50SignalBatchRunner.__new__(batch_module.Sse50SignalBatchRunner)
    runner.settings = SimpleNamespace(STOCK_SIGNAL_BENCHMARK_OPENDATA_ENABLED=False)
    expected = [{"date": "2026-07-01", "open": 2_000, "close": 2_010}]

    def legacy_reader(_start: date, _end: date) -> list[dict[str, Any]]:
        return expected

    monkeypatch.setattr(runner, "_fetch_sse50_benchmark_rows", legacy_reader)

    rows = await runner._sse50_benchmark_rows(
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 31)
    )

    assert rows == expected


def test_opendata_benchmark_integration_is_disabled_by_default() -> None:
    assert Settings.model_fields["STOCK_SIGNAL_BENCHMARK_OPENDATA_ENABLED"].default is False
