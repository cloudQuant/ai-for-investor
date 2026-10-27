"""Focused contract tests for the fixed OpenData stock-daily freshness proxy."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.api.data import trust as trust_api
from app.schemas.market_data_trust import OpenDataStockDailyFreshnessResponse
from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.opendata_stock_daily_freshness import (
    OpenDataStockDailyFreshnessError,
    OpenDataStockDailyFreshnessService,
)
from tests.conftest import app, register_and_login

pytestmark = pytest.mark.asyncio

_PATH = "/api/v1/data/trust/opendata/stock-daily/freshness"
_UPSTREAM_PATH = "/api/v1/data/domains/stock_daily/freshness"


def _upstream_payload(
    *,
    status: str = "fresh",
    latest: str | None = "2026-10-26",
    expected: str = "2026-10-26",
    lag_days: int | None = 0,
    field: str | None = "trade_date",
) -> dict[str, Any]:
    return {
        "success": True,
        "message": "success",
        "data": {
            "domain": "stock_daily",
            "source": None,
            "status": status,
            "latest": latest,
            "expected_data_date": expected,
            "field": field,
            "lag_days": lag_days,
        },
    }


def _credentials() -> OpendataCredentials:
    return OpendataCredentials("test-opendata-key", base_url="https://opendata.test")


class _BodyStream(httpx.AsyncByteStream):
    """Small real async stream for MockTransport response bodies."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def __aiter__(self) -> AsyncIterator[bytes]:
        midpoint = len(self._body) // 2
        yield self._body[:midpoint]
        if midpoint < len(self._body):
            yield self._body[midpoint:]

    async def aclose(self) -> None:
        return None


def _json_stream_response(
    payload: Any,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    response_headers = {"content-type": "application/json", **(headers or {})}
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return httpx.Response(status_code, headers=response_headers, stream=_BodyStream(body))


async def test_service_uses_only_fixed_route_and_projects_business_date_freshness():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _json_stream_response(_upstream_payload())

    service = OpenDataStockDailyFreshnessService(
        credentials=_credentials(), transport=httpx.MockTransport(handler)
    )
    result = await service.read()

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == f"https://opendata.test{_UPSTREAM_PATH}"
    assert requests[0].headers["X-API-Key"] == "test-opendata-key"
    assert requests[0].headers["Accept-Encoding"] == "identity"
    assert "source" not in requests[0].url.params
    assert result.provider == "opendata"
    assert result.domain == "stock_daily"
    assert result.source is None
    assert result.field == "trade_date"
    assert result.latest == date(2026, 10, 26)
    assert result.expected_data_date == date(2026, 10, 26)
    assert result.lag_days == 0
    assert result.status == "fresh"
    assert result.checked_at.tzinfo is not None
    assert result.checked_at.utcoffset() == timezone.utc.utcoffset(result.checked_at)


async def test_service_preserves_missing_as_domain_status():
    service = OpenDataStockDailyFreshnessService(
        credentials=_credentials(),
        transport=httpx.MockTransport(
            lambda request: _json_stream_response(
                _upstream_payload(status="missing", latest=None, lag_days=None, field=None)
            )
        ),
    )

    result = await service.read()

    assert result.status == "missing"
    assert result.latest is None
    assert result.field is None
    assert result.lag_days is None


async def test_service_accepts_negative_lag_as_fresh():
    service = OpenDataStockDailyFreshnessService(
        credentials=_credentials(),
        transport=httpx.MockTransport(
            lambda request: _json_stream_response(
                _upstream_payload(latest="2026-10-27", expected="2026-10-26", lag_days=-1)
            )
        ),
    )

    result = await service.read()

    assert result.status == "fresh"
    assert result.lag_days == -1


@pytest.mark.parametrize(
    ("status", "latest", "lag_days"),
    [
        ("fresh", "2026-10-25", 1),
        ("stale", "2026-10-26", 0),
    ],
)
async def test_service_rejects_status_that_disagrees_with_lag(status, latest, lag_days):
    service = OpenDataStockDailyFreshnessService(
        credentials=_credentials(),
        transport=httpx.MockTransport(
            lambda request: _json_stream_response(
                _upstream_payload(status=status, latest=latest, lag_days=lag_days)
            )
        ),
    )

    with pytest.raises(OpenDataStockDailyFreshnessError) as captured:
        await service.read()

    assert captured.value.code == "OPENDATA_FRESHNESS_RESPONSE_INVALID"


@pytest.mark.parametrize(
    "payload",
    [
        {**_upstream_payload(), "unexpected": "field"},
        _upstream_payload(status="missing", latest="2026-10-26", lag_days=0, field=None),
        _upstream_payload(lag_days=7),
        _upstream_payload(latest="2026-10-26T00:00:00Z"),
        {"success": False, "message": "upstream secret text", "data": {}},
    ],
)
async def test_service_rejects_malformed_upstream_without_echoing_body(payload: Any):
    service = OpenDataStockDailyFreshnessService(
        credentials=_credentials(),
        transport=httpx.MockTransport(lambda request: _json_stream_response(payload)),
    )

    with pytest.raises(OpenDataStockDailyFreshnessError) as captured:
        await service.read()

    assert captured.value.code == "OPENDATA_FRESHNESS_RESPONSE_INVALID"
    assert "secret" not in str(captured.value).lower()


async def test_service_maps_upstream_failure_without_forwarding_body():
    service = OpenDataStockDailyFreshnessService(
        credentials=_credentials(),
        transport=httpx.MockTransport(
            lambda request: _json_stream_response(
                {"detail": "upstream credential secret"}, status_code=503
            )
        ),
    )

    with pytest.raises(OpenDataStockDailyFreshnessError) as captured:
        await service.read()

    assert captured.value.code == "OPENDATA_FRESHNESS_UNAVAILABLE"
    assert "secret" not in str(captured.value).lower()


async def test_service_rejects_oversized_upstream_body():
    service = OpenDataStockDailyFreshnessService(
        credentials=_credentials(),
        max_response_bytes=32,
        transport=httpx.MockTransport(lambda request: _json_stream_response(_upstream_payload())),
    )

    with pytest.raises(OpenDataStockDailyFreshnessError) as captured:
        await service.read()

    assert captured.value.code == "OPENDATA_FRESHNESS_RESPONSE_INVALID"


async def test_service_rejects_compressed_wire_body():
    service = OpenDataStockDailyFreshnessService(
        credentials=_credentials(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={
                    "content-type": "application/json",
                    "content-encoding": "gzip",
                },
                stream=_BodyStream(b"compressed-wire-bytes"),
            )
        ),
    )

    with pytest.raises(OpenDataStockDailyFreshnessError) as captured:
        await service.read()

    assert captured.value.code == "OPENDATA_FRESHNESS_RESPONSE_INVALID"


async def test_service_total_deadline_cancels_stream_and_closes_response():
    class _SlowStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.closed = asyncio.Event()

        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(10):
                await asyncio.sleep(0.02)
                yield b"x"

        async def aclose(self) -> None:
            self.closed.set()

    stream = _SlowStream()
    service = OpenDataStockDailyFreshnessService(
        credentials=_credentials(),
        timeout_seconds=0.055,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=stream,
            )
        ),
    )

    with pytest.raises(OpenDataStockDailyFreshnessError) as captured:
        await service.read()

    assert captured.value.code == "OPENDATA_FRESHNESS_UNAVAILABLE"
    assert stream.closed.is_set()


async def test_service_maps_stream_protocol_exception_to_safe_unavailable():
    class _BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            raise RuntimeError("raw stream secret")
            yield b"unreachable"

        async def aclose(self) -> None:
            return None

    service = OpenDataStockDailyFreshnessService(
        credentials=_credentials(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_BrokenStream(),
            )
        ),
    )

    with pytest.raises(OpenDataStockDailyFreshnessError) as captured:
        await service.read()

    assert captured.value.code == "OPENDATA_FRESHNESS_UNAVAILABLE"
    assert "secret" not in str(captured.value).lower()


async def test_api_requires_authentication_before_proxing(client, monkeypatch):
    monkeypatch.setattr(
        trust_api,
        "get_opendata_stock_daily_freshness_service",
        lambda: pytest.fail("unauthenticated request must not create an upstream client"),
    )

    response = await client.get(_PATH)

    assert response.status_code == 401


async def test_api_disabled_fails_closed_without_constructing_service(client, monkeypatch):
    _, headers = await register_and_login(client, username="opendata-freshness-disabled")
    app.dependency_overrides[trust_api.require_authorized_market_data_read] = lambda: None
    monkeypatch.setattr(
        trust_api, "get_settings", lambda: SimpleNamespace(MARKET_DATA_OPENDATA_ENABLED=False)
    )
    monkeypatch.setattr(
        trust_api,
        "get_opendata_stock_daily_freshness_service",
        lambda: pytest.fail("disabled OpenData route must not create an upstream client"),
    )

    response = await client.get(_PATH, headers=headers)

    assert response.status_code == 503
    assert response.json()["error"] == "HTTP_503"
    assert response.json()["details"] == {"code": "OPENDATA_FRESHNESS_DISABLED"}


async def test_api_returns_only_typed_domain_freshness_and_never_falls_back(client, monkeypatch):
    _, headers = await register_and_login(client, username="opendata-freshness-enabled")
    app.dependency_overrides[trust_api.require_authorized_market_data_read] = lambda: None
    monkeypatch.setattr(
        trust_api, "get_settings", lambda: SimpleNamespace(MARKET_DATA_OPENDATA_ENABLED=True)
    )

    class _Service:
        async def read(self) -> OpenDataStockDailyFreshnessResponse:
            return OpenDataStockDailyFreshnessResponse(
                provider="opendata",
                domain="stock_daily",
                source=None,
                field="trade_date",
                latest=date(2026, 10, 26),
                lag_days=0,
                status="fresh",
                expected_data_date=date(2026, 10, 26),
                checked_at=datetime(2026, 10, 27, tzinfo=timezone.utc),
            )

    monkeypatch.setattr(trust_api, "get_opendata_stock_daily_freshness_service", _Service)
    monkeypatch.setattr(
        trust_api,
        "get_market_data_coverage_service",
        lambda: pytest.fail("OpenData freshness must never consult local coverage"),
    )

    response = await client.get(_PATH, headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "provider": "opendata",
        "domain": "stock_daily",
        "source": None,
        "field": "trade_date",
        "latest": "2026-10-26",
        "lag_days": 0,
        "status": "fresh",
        "expected_data_date": "2026-10-26",
        "checked_at": "2026-10-27T00:00:00Z",
    }


async def test_api_upstream_error_does_not_masquerade_as_missing_or_local_fallback(
    client, monkeypatch
):
    _, headers = await register_and_login(client, username="opendata-freshness-failed")
    app.dependency_overrides[trust_api.require_authorized_market_data_read] = lambda: None
    monkeypatch.setattr(
        trust_api, "get_settings", lambda: SimpleNamespace(MARKET_DATA_OPENDATA_ENABLED=True)
    )

    class _BrokenService:
        async def read(self) -> OpenDataStockDailyFreshnessResponse:
            raise OpenDataStockDailyFreshnessError("OPENDATA_FRESHNESS_UNAVAILABLE")

    monkeypatch.setattr(trust_api, "get_opendata_stock_daily_freshness_service", _BrokenService)
    monkeypatch.setattr(
        trust_api,
        "get_market_data_coverage_service",
        lambda: pytest.fail("failed OpenData freshness must not consult local coverage"),
    )

    response = await client.get(_PATH, headers=headers)

    assert response.status_code == 503
    assert response.json()["error"] == "HTTP_503"
    assert response.json()["details"] == {"code": "OPENDATA_FRESHNESS_UNAVAILABLE"}
