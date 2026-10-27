"""opendata provider adapter 测试（消费方 provider 形式接入）。

覆盖：请求变换（复权映射、闭区间 end）、响应归一化（event_at = 交易日
UTC midnight、字段别名 amount→turnover）、分页、窗口客户端过滤、信封与
HTTP 错误码映射、契约选择失败关闭、凭据脱敏。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app.services.market_data.opendata_credentials import (
    OpendataCredentials,
    OpendataCredentialsError,
)
from app.services.market_data.opendata_provider import OpendataProvider, OpendataProviderError
from app.services.market_data.providers import MarketDataProviderRequest

UTC = timezone.utc
ENDPOINT = "/api/v1/data/equity/stock_daily"


def _request(**changes: object) -> MarketDataProviderRequest:
    values: dict[str, object] = {
        "query_fingerprint": "a" * 64,
        "canonical_id": "instrument:stock:CN-SSE:600519",
        "asset_type": "stock",
        "provider_symbol": "600519",
        "market": "CN-SSE",
        "data_kind": "bars",
        "frequency": "1d",
        "start_at": datetime(2026, 1, 2, tzinfo=UTC),
        "end_at": datetime(2026, 1, 4, tzinfo=UTC),
        "required_fields": frozenset({"close"}),
        "provider": "opendata",
        "route_id": "opendata-stock-daily-v1",
        "family_id": "stock.realtime",
        "family_contract_version": "market-data-family-v1",
        "request_id": "A" * 43,
        "source_policy_id": "market-default-v1",
    }
    values.update(changes)
    return MarketDataProviderRequest(**values)  # type: ignore[arg-type]


def _row(trade_date: str, *, close: float = 2.0, amount: float = 100.0) -> dict:
    return {
        "symbol": "600519",
        "trade_date": trade_date,
        "open": 1.0,
        "high": 2.5,
        "low": 0.9,
        "close": close,
        "volume": 10.0,
        "amount": amount,
        "_source": "akshare",
    }


def _full_page_rows() -> list[dict]:
    first_date = date(2023, 1, 1)
    return [_row((first_date + timedelta(days=offset)).isoformat()) for offset in range(1000)]


def _page(
    rows: list[dict],
    *,
    page: object = 1,
    page_size: object = 1000,
    count: object | None = None,
) -> bytes:
    payload = {
        "success": True,
        "message": "success",
        "data": {
            "domain": "stock_daily",
            "asset_class": "equity",
            "layer": "dwd",
            "columns": ["symbol", "trade_date", "open", "high", "low", "close", "volume", "amount"],
            "rows": rows,
            "page": page,
            "page_size": page_size,
            "count": len(rows) if count is None else count,
        },
    }
    return json.dumps(payload).encode("utf-8")


def _provider(
    transport: httpx.AsyncBaseTransport,
    *,
    base_url: str = "http://opendata.test",
    max_response_bytes: int = 32 * 1024 * 1024,
    max_total_response_bytes: int = 64 * 1024 * 1024,
) -> OpendataProvider:
    return OpendataProvider(
        client=httpx.AsyncClient(transport=transport),
        credentials=OpendataCredentials("od-test-key", base_url=base_url),
        max_response_bytes=max_response_bytes,
        max_total_response_bytes=max_total_response_bytes,
    )


class _TrackingByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.chunks_read = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.chunks_read += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class TestRequestTransform:
    async def test_fetch_sends_reviewed_query_parameters(self) -> None:
        """请求变换：闭区间 end、复权映射、dwd 层、分页。"""
        seen: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            seen["headers"] = dict(request.headers)
            return httpx.Response(200, content=_page([_row("2026-01-02")]))

        provider = _provider(httpx.MockTransport(handler))
        result = await provider.fetch(_request(adjustment="qfq"))

        assert seen["path"] == ENDPOINT
        params = seen["params"]
        assert params["symbols"] == "600519"
        assert params["start"] == "2026-01-02"
        assert params["end"] == "2026-01-03"  # 半开窗口 end - 1 天
        assert params["adjust"] == "qfq"
        assert params["layer"] == "dwd"
        assert params["source"] == "auto"
        assert seen["headers"]["x-api-key"] == "od-test-key"
        assert result.provider_id == "opendata"
        assert result.source_revision == "opendata-rest-v1"

    @pytest.mark.parametrize(
        ("adjustment", "expected"),
        [("unadjusted", "none"), ("qfq", "qfq"), ("hfq", "hfq"), (None, "none")],
    )
    async def test_adjustment_mapping(self, adjustment: str | None, expected: str) -> None:
        seen: dict[str, str] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.update(dict(request.url.params))
            return httpx.Response(200, content=_page([_row("2026-01-02")]))

        provider = _provider(httpx.MockTransport(handler))
        await provider.fetch(_request(adjustment=adjustment))

        assert seen["adjust"] == expected

    async def test_unsupported_frequency_is_blocked_before_io(self) -> None:
        calls: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append("called")
            return httpx.Response(200, content=_page([]))

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request(frequency="5min"))

        assert exc.value.code == "OPENDATA_FREQUENCY_UNSUPPORTED"
        assert calls == []

    async def test_provider_mismatch_is_refused(self) -> None:
        provider = _provider(httpx.MockTransport(lambda r: httpx.Response(200, content=_page([]))))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request(provider="akshare"))

        assert exc.value.code == "OPENDATA_PROVIDER_MISMATCH"

    async def test_unregistered_route_fails_closed(self) -> None:
        provider = _provider(httpx.MockTransport(lambda r: httpx.Response(200, content=_page([]))))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request(route_id="opendata-unknown-v1"))

        assert exc.value.code == "OPENDATA_CONTRACT_INVALID"


class TestObservationNormalization:
    async def test_rows_become_utc_midnight_observations(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_page(
                    [
                        _row("2026-01-02", close=10.5, amount=1234.0),
                        _row("2026-01-03", close=11.5),
                    ]
                ),
            )

        provider = _provider(httpx.MockTransport(handler))
        result = await provider.fetch(_request())

        assert [obs.event_at.isoformat() for obs in result.observations] == [
            "2026-01-02T00:00:00+00:00",
            "2026-01-03T00:00:00+00:00",
        ]
        first = result.observations[0]
        assert first.fields["close"] == 10.5
        assert first.fields["turnover"] == 1234.0  # amount → 中台 turnover
        assert first.fields["volume"] == 10.0
        assert "symbol" not in first.fields  # 身份列不进入字段载荷
        assert "trade_date" not in first.fields
        assert first.available_at == result.retrieved_at
        assert result.raw_payload["request"]["request_id"] == "A" * 43
        assert result.raw_payload["opendata_pages"][0]["count"] == 2

    async def test_rows_outside_the_half_open_window_are_dropped(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_page([_row("2026-01-04"), _row("2026-01-02")]),  # end 为排他
            )

        provider = _provider(httpx.MockTransport(handler))
        result = await provider.fetch(_request())

        assert [obs.event_at.date().isoformat() for obs in result.observations] == ["2026-01-02"]

    async def test_duplicate_event_dates_are_refused(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_page([_row("2026-01-02"), _row("2026-01-02")]))

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == "OPENDATA_RESPONSE_DUPLICATE_EVENT"

    @pytest.mark.parametrize(
        "trade_date",
        [
            "not-a-date",
            "2026-01-02T00:00:00Z",
            "2026-01-02trailing",
            " 2026-01-02",
            "2026-1-2",
        ],
    )
    async def test_non_date_only_timestamp_is_refused(self, trade_date: str) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            row = _row("2026-01-02")
            row["trade_date"] = trade_date
            return httpx.Response(200, content=_page([row]))

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == "OPENDATA_TIMESTAMP_INVALID"

    @pytest.mark.parametrize(
        ("symbol", "present", "expected"),
        [
            (None, False, "OPENDATA_RESPONSE_SYMBOL_INVALID"),
            (None, True, "OPENDATA_RESPONSE_SYMBOL_INVALID"),
            (600519, True, "OPENDATA_RESPONSE_SYMBOL_INVALID"),
            ("600519.SS", True, "OPENDATA_RESPONSE_SYMBOL_MISMATCH"),
            ("600000", True, "OPENDATA_RESPONSE_SYMBOL_MISMATCH"),
        ],
    )
    async def test_each_row_symbol_must_exactly_match_request(
        self, symbol: object, present: bool, expected: str
    ) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            row = _row("2026-01-02")
            if present:
                row["symbol"] = symbol
            else:
                row.pop("symbol")
            return httpx.Response(200, content=_page([row]))

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == expected

    async def test_out_of_window_row_still_requires_matching_symbol(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            row = _row("2026-01-04")  # request end is exclusive
            row["symbol"] = "600000"
            return httpx.Response(200, content=_page([row]))

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == "OPENDATA_RESPONSE_SYMBOL_MISMATCH"


class TestPagination:
    async def test_stops_on_a_short_page(self) -> None:
        """页内行数少于 page_size 即视为末页，不再翻页。"""
        seen_pages: list[int] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen_pages.append(int(dict(request.url.params)["page"]))
            return httpx.Response(200, content=_page([_row("2026-01-02"), _row("2026-01-03")]))

        provider = _provider(httpx.MockTransport(handler))
        result = await provider.fetch(_request(end_at=datetime(2026, 1, 10, tzinfo=UTC)))

        assert seen_pages == [1]  # page_size=1000，两行即短页
        assert len(result.observations) == 2

    async def test_follows_a_full_page(self) -> None:
        seen_pages: list[int] = []
        full_page = _full_page_rows()

        async def handler(request: httpx.Request) -> httpx.Response:
            page = int(dict(request.url.params)["page"])
            seen_pages.append(page)
            rows = full_page if page == 1 else []
            return httpx.Response(200, content=_page(rows, page=page))

        provider = _provider(httpx.MockTransport(handler))
        result = await provider.fetch(
            _request(
                start_at=datetime(2023, 1, 1, tzinfo=UTC),
                end_at=datetime(2026, 1, 10, tzinfo=UTC),
            )
        )

        assert seen_pages == [1, 2]
        assert len(result.observations) == 1000
        assert [page["count"] for page in result.raw_payload["opendata_pages"]] == [1000, 0]

    @pytest.mark.parametrize(
        ("page", "page_size", "count", "expected"),
        [
            ("1", 1000, 1, "OPENDATA_PAGE_INVALID"),
            (True, 1000, 1, "OPENDATA_PAGE_INVALID"),
            (2, 1000, 1, "OPENDATA_PAGE_MISMATCH"),
            (1, "1000", 1, "OPENDATA_PAGE_SIZE_INVALID"),
            (1, 1001, 1, "OPENDATA_PAGE_SIZE_INVALID"),
            (1, 500, 1, "OPENDATA_PAGE_SIZE_MISMATCH"),
            (1, 1000, "1", "OPENDATA_COUNT_INVALID"),
            (1, 1000, True, "OPENDATA_COUNT_INVALID"),
            (1, 1000, 1001, "OPENDATA_COUNT_INVALID"),
            (1, 1000, 2, "OPENDATA_COUNT_MISMATCH"),
        ],
    )
    async def test_invalid_pagination_metadata_fails_closed(
        self, page: object, page_size: object, count: object, expected: str
    ) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_page([_row("2026-01-02")], page=page, page_size=page_size, count=count),
            )

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == expected

    async def test_repeated_page_number_is_refused(self) -> None:
        seen_pages: list[int] = []
        full_page = _full_page_rows()

        async def handler(request: httpx.Request) -> httpx.Response:
            requested_page = int(dict(request.url.params)["page"])
            seen_pages.append(requested_page)
            return httpx.Response(
                200,
                content=_page(
                    full_page if requested_page == 1 else [],
                    page=1,
                ),
            )

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == "OPENDATA_PAGE_MISMATCH"
        assert seen_pages == [1, 2]

    async def test_repeated_page_rows_are_refused_even_when_page_number_advances(self) -> None:
        full_page = _full_page_rows()

        async def handler(request: httpx.Request) -> httpx.Response:
            page = int(dict(request.url.params)["page"])
            return httpx.Response(200, content=_page(full_page, page=page))

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == "OPENDATA_RESPONSE_DUPLICATE_PAGE"

    async def test_response_row_limit_fails_instead_of_truncating(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.market_data.opendata_provider.OPENDATA_MAX_ROWS", 1)

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_page([_row("2026-01-02"), _row("2026-01-03")]),
            )

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == "OPENDATA_RESPONSE_TOO_LARGE"

    async def test_streaming_response_limit_closes_without_reading_later_chunks(self) -> None:
        stream = _TrackingByteStream([b"x" * 17, b"remaining body"])

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=stream)

        provider = _provider(httpx.MockTransport(handler), max_response_bytes=16)
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == "OPENDATA_RESPONSE_TOO_LARGE"
        assert stream.chunks_read == 1
        assert stream.closed

    async def test_total_response_limit_stops_before_requesting_another_page(self) -> None:
        first_body = _page(_full_page_rows(), page=1)
        first_stream = _TrackingByteStream([first_body])
        second_stream = _TrackingByteStream([b"x" * 10, b"remaining response"])
        seen_pages: list[int] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            page = int(dict(request.url.params)["page"])
            seen_pages.append(page)
            if page == 1:
                return httpx.Response(200, stream=first_stream)
            return httpx.Response(200, stream=second_stream)

        provider = _provider(
            httpx.MockTransport(handler),
            max_total_response_bytes=len(first_body) + 5,
        )
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == "OPENDATA_RESPONSE_TOO_LARGE"
        assert seen_pages == [1, 2]
        assert first_stream.closed
        assert second_stream.chunks_read == 1
        assert second_stream.closed

    async def test_provenance_limit_stops_before_requesting_another_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.services.market_data.opendata_provider._MAX_PROVENANCE_BYTES", 512 * 1024
        )
        full_page = _full_page_rows()
        for row in full_page:
            row["large_field"] = "x" * 1024
        seen_pages: list[int] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            page = int(dict(request.url.params)["page"])
            seen_pages.append(page)
            rows = full_page if page == 1 else []
            return httpx.Response(200, content=_page(rows, page=page))

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == "OPENDATA_PROVENANCE_TOO_LARGE"
        assert seen_pages == [1]


class TestErrorMapping:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (401, "OPENDATA_UNAUTHORIZED"),
            (403, "OPENDATA_FORBIDDEN"),
            (429, "OPENDATA_RATE_LIMITED"),
            (501, "OPENDATA_HTTP_ERROR"),
            (500, "OPENDATA_HTTP_ERROR"),
        ],
    )
    async def test_http_statuses_map_to_stable_codes(self, status_code: int, expected: str) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, json={"detail": "nope"})

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == expected

    async def test_failure_envelope_is_refused(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"success": False, "message": "domain not registered", "data": None},
            )

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == "OPENDATA_ENVELOPE_FAILURE"
        assert exc.value.detail == "domain not registered"

    async def test_response_size_bound_is_enforced(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_page([_row("2026-01-02")]))

        provider = _provider(httpx.MockTransport(handler), max_response_bytes=16)
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == "OPENDATA_RESPONSE_TOO_LARGE"

    async def test_transport_failure_is_wrapped(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(OpendataProviderError) as exc:
            await provider.fetch(_request())

        assert exc.value.code == "OPENDATA_TRANSPORT_ERROR"


class TestCredentials:
    def test_missing_key_returns_none(self) -> None:
        assert OpendataCredentials.from_environment(environment={}) is None

    def test_environment_is_read_without_leaking(self) -> None:
        credentials = OpendataCredentials.from_environment(
            environment={"OPENDATA_API_KEY": "od-secret", "OPENDATA_BASE_URL": "http://host:9"}
        )

        assert credentials is not None
        assert credentials.api_key == "od-secret"
        assert credentials.base_url == "http://host:9"
        assert "od-secret" not in repr(credentials)
        assert "od-secret" not in str(credentials)

    def test_invalid_base_url_is_refused(self) -> None:
        with pytest.raises(OpendataCredentialsError) as exc:
            OpendataCredentials("od-secret", base_url="opendata-host")

        assert exc.value.code == "OPENDATA_BASE_URL_INVALID"


class TestFromEnvironment:
    def test_provider_is_none_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENDATA_API_KEY", raising=False)

        assert OpendataProvider.from_environment() is None
