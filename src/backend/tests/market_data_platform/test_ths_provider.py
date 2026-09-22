"""THS provider 与 HTTP 客户端的 fixture 测试（AC-07、AC-15、AC-23）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.services.market_data.providers import MarketDataProviderRequest
from app.services.market_data.ths_credentials import ThsCredentials
from app.services.market_data.ths_http import ThsHttpClient, ThsHttpError
from app.services.market_data.ths_provider import ThsProvider, ThsProviderError
from app.services.market_data.ths_rate_limiter import ThsRateLimiter

UTC = timezone.utc


def _request(**changes: object) -> MarketDataProviderRequest:
    values: dict[str, object] = {
        "query_fingerprint": "a" * 64,
        "canonical_id": "instrument:stock:CN-SSE:600519",
        "asset_type": "stock",
        "provider_symbol": "600519.SH",
        "market": "CN-SSE",
        "data_kind": "bars",
        "frequency": "1d",
        "start_at": datetime(2026, 1, 2, tzinfo=UTC),
        "end_at": datetime(2026, 1, 4, tzinfo=UTC),
        "required_fields": frozenset({"close"}),
        "provider": "ths",
        "route_id": "ths-stock-primary-v1",
        "family_id": "stock.realtime",
        "family_contract_version": "market-data-family-v1",
        "request_id": "A" * 43,
        "source_policy_id": "market-default-v1",
    }
    values.update(changes)
    return MarketDataProviderRequest(**values)  # type: ignore[arg-type]


def _historical_response(*rows: dict) -> bytes:
    payload = {
        "code": 0,
        "message": "success",
        "request_id": "req-abc",
        "data": {"timestamp": 1716105600000, "item": list(rows)},
    }
    return json.dumps(payload).encode("utf-8")


def _provider(transport: httpx.AsyncBaseTransport) -> ThsProvider:
    credentials = ThsCredentials("test-key-123")
    client = httpx.AsyncClient(transport=transport)
    return ThsProvider(client=client, credentials=credentials, rate_limiter=ThsRateLimiter())


class TestProviderFetch:
    async def test_fetch_historical_normalizes_observations(self) -> None:
        """AC-15 部分：A 股日线走 THS，source 标识 THS。"""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-api-key"] == "test-key-123"
            return httpx.Response(
                200,
                content=_historical_response(
                    {"date_ms": 1767369600000, "open_price": 1.0, "close_price": 2.0},
                ),
            )

        provider = _provider(httpx.MockTransport(handler))
        result = await provider.fetch(_request())
        assert result.provider_id == "ths"
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.fields["close"] == 2.0
        assert obs.fields["open"] == 1.0

    async def test_fetch_minute_frequency_unsupported(self) -> None:
        """AC-14：分钟频 UNSUPPORTED。"""
        provider = _provider(httpx.MockTransport(lambda r: httpx.Response(200)))
        with pytest.raises(ThsProviderError) as exc:
            await provider.fetch(_request(frequency="5min"))
        assert exc.value.code == "THS_FREQUENCY_UNSUPPORTED"

    async def test_fetch_auth_error_maps_to_thsauth(self) -> None:
        """AC-02：2001 映射为不可重试 auth 错误。"""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=json.dumps(
                    {"code": 2001, "message": "unauthorized", "request_id": "r"}
                ).encode(),
            )

        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(ThsProviderError) as exc:
            await provider.fetch(_request())
        assert exc.value.code == "THS_AUTH_DENIED"


class TestHttpClientBounds:
    async def test_response_too_large_rejected(self) -> None:
        """AC-23：响应体超限拒绝且不 OOM。"""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 1024)

        credentials = ThsCredentials("k")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        http = ThsHttpClient(
            client=client,
            credentials=credentials,
            rate_limiter=ThsRateLimiter(),
            max_response_bytes=64,
        )
        with pytest.raises(ThsHttpError) as exc:
            await http.get("/api/test")
        assert exc.value.code == "THS_HTTP_RESPONSE_TOO_LARGE"

    async def test_timeout_maps_to_thstimeout(self) -> None:
        """AC-23：超时生效。"""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timeout")

        credentials = ThsCredentials("k")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        http = ThsHttpClient(
            client=client,
            credentials=credentials,
            rate_limiter=ThsRateLimiter(),
            timeout_seconds=20.0,
        )
        with pytest.raises(ThsHttpError) as exc:
            await http.get("/api/test")
        assert exc.value.code == "THS_HTTP_TIMEOUT"


class TestCredentials:
    def test_missing_key_returns_none(self) -> None:
        """AC-07：未配置 API Key → 失败关闭（from_environment 返回 None）。"""
        from app.services.market_data.ths_credentials import ThsCredentials as TC

        assert TC.from_environment(environment={}) is None

    def test_repr_masks_key(self) -> None:
        """AC-08：API Key 明文不出现在 repr。"""
        credentials = ThsCredentials("secret-key-123")
        assert "secret-key-123" not in repr(credentials)
        assert "secret-key-123" not in str(credentials)
