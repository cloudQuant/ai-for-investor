"""Total response-budget boundaries for the published index snapshot reader."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

import app.services.market_data.opendata_provider as opendata_provider_module
from app.services.market_data.opendata_contracts import (
    OPENDATA_INDEX_BENCHMARK_DATASETS,
    OPENDATA_INDEX_BENCHMARK_FAMILY_ID,
    OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION,
    OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT,
    OPENDATA_INDEX_BENCHMARK_ROUTE_ID,
)
from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.market_data.opendata_provider import OpendataProvider, OpendataProviderError
from app.services.market_data.provider_models import MarketDataProviderRequest

_UTC = timezone.utc
_DATASET_ID = OPENDATA_INDEX_BENCHMARK_DATASETS["hs300"][1]
_START = "2024-01-01"
_END = "2024-01-04"
_PUBLICATION_ID = "b" * 32
_CONTRACT_SHA256 = "c" * 64
_SNAPSHOT_ID = "a" * 32
_STORAGE_ORDER = [
    {"field": "business_date", "direction": "asc", "nulls": "last", "comparison": "native"},
    {"field": "business_key", "direction": "asc", "comparison": "binary_lexicographic"},
]


def _request() -> MarketDataProviderRequest:
    return MarketDataProviderRequest(
        query_fingerprint="a" * 64,
        canonical_id="index:hs300",
        asset_type="index",
        provider_symbol="000300.SH",
        market="CN-SSE",
        data_kind="bars",
        frequency="1d",
        start_at=datetime(2024, 1, 1, tzinfo=_UTC),
        end_at=datetime(2024, 1, 4, tzinfo=_UTC),
        required_fields=frozenset({"close"}),
        provider="opendata",
        adjustment="not_applicable",
        price_basis="close",
        currency=None,
        unit="point",
        source_policy_id="risk-index-benchmark-daily-v1",
        route_id=OPENDATA_INDEX_BENCHMARK_ROUTE_ID,
        family_id=OPENDATA_INDEX_BENCHMARK_FAMILY_ID,
        family_contract_version=OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION,
        provider_endpoint=OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT,
    )


def _snapshot(record_count: int) -> dict[str, Any]:
    return {
        "dataset_id": _DATASET_ID,
        "publication_id": _PUBLICATION_ID,
        "contract_sha256": _CONTRACT_SHA256,
        "snapshot_id": _SNAPSHOT_ID,
        "window": {"start": _START, "end": _END, "end_exclusive": True},
        "page_size": 1000,
        "record_count": record_count,
        "ordering_fields": ["trade_date", "symbol"],
        "storage_order": _STORAGE_ORDER,
        "identity_key_encoding": "canonical-json-array-v1",
    }


def _coverage() -> dict[str, Any]:
    return {
        "dataset_id": _DATASET_ID,
        "publication_id": _PUBLICATION_ID,
        "contract_sha256": _CONTRACT_SHA256,
        "coverage": {
            "status": "complete",
            "scope": "business_history",
            "requested": {"start": _START, "end": _END},
            "observed": {"start": _START, "end": _END},
            "missing_ranges": [],
            "evidence_refs": ["coverage-evidence:synthetic"],
            "limitation": None,
        },
    }


def _row(trade_date: str) -> dict[str, str]:
    return {"symbol": "000300.SH", "trade_date": trade_date}


def _page(
    snapshot: dict[str, Any], rows: list[dict[str, str]], next_cursor: str | None
) -> dict[str, Any]:
    return {
        **snapshot,
        "rows": rows,
        "count": len(rows),
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
        "meta": {
            "snapshot": snapshot,
            "ordering_fields": snapshot["ordering_fields"],
            "storage_order": snapshot["storage_order"],
            "identity_key_encoding": snapshot["identity_key_encoding"],
        },
    }


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _harness(
    *, record_count: int, pages: list[tuple[list[dict[str, str]], str | None]]
) -> tuple[OpendataProvider, httpx.AsyncClient, list[httpx.Request], list[int]]:
    snapshot = _snapshot(record_count)
    coverage_body = _json_bytes(_coverage())
    snapshot_body = _json_bytes(snapshot)
    page_bodies = [_json_bytes(_page(snapshot, rows, cursor)) for rows, cursor in pages]
    page_by_cursor = {
        (None if index == 0 else pages[index - 1][1]): body
        for index, body in enumerate(page_bodies)
    }
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/coverage"):
            return httpx.Response(
                200,
                content=coverage_body,
                headers={"content-type": "application/json"},
            )
        if request.method == "POST" and request.url.path == "/api/v2/snapshots":
            return httpx.Response(
                201,
                content=snapshot_body,
                headers={"content-type": "application/json"},
            )
        if request.url.path.endswith("/records"):
            cursor = request.url.params.get("cursor")
            body = page_by_cursor.get(cursor)
            if body is None:
                raise AssertionError(f"unexpected records cursor: {cursor!r}")
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/json"},
            )
        raise AssertionError(f"unexpected request path: {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    provider = OpendataProvider(
        client=client,
        credentials=OpendataCredentials("synthetic-test-key", base_url="http://opendata.test"),
        max_retries=0,
    )
    response_sizes = [len(coverage_body), len(snapshot_body), *(len(body) for body in page_bodies)]
    return provider, client, requests, response_sizes


@pytest.mark.asyncio
async def test_exact_budget_with_more_pages_fails_before_sending_next_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, client, requests, response_sizes = _harness(
        record_count=2,
        pages=[([_row("2024-01-02")], "cursor-page-two"), ([_row("2024-01-03")], None)],
    )
    monkeypatch.setattr(
        opendata_provider_module,
        "_PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES",
        sum(response_sizes[:3]),
    )

    try:
        with pytest.raises(OpendataProviderError) as raised:
            await provider.fetch_published_index_snapshot(_request(), dataset_id=_DATASET_ID)
    finally:
        await client.aclose()

    assert raised.value.code == "OPENDATA_INDEX_SNAPSHOT_LIMIT_EXCEEDED"
    records_requests = [request for request in requests if request.url.path.endswith("/records")]
    assert len(records_requests) == 1
    assert "cursor" not in records_requests[0].url.params


@pytest.mark.asyncio
async def test_exact_budget_on_final_page_still_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, client, requests, response_sizes = _harness(
        record_count=1,
        pages=[([_row("2024-01-02")], None)],
    )
    monkeypatch.setattr(
        opendata_provider_module,
        "_PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES",
        sum(response_sizes),
    )

    try:
        result = await provider.fetch_published_index_snapshot(_request(), dataset_id=_DATASET_ID)
    finally:
        await client.aclose()

    assert len(result.records) == 1
    assert result.page_count == 1
    assert len([request for request in requests if request.url.path.endswith("/records")]) == 1


@pytest.mark.asyncio
async def test_multi_page_read_succeeds_when_budget_remains_for_next_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, client, requests, response_sizes = _harness(
        record_count=2,
        pages=[([_row("2024-01-02")], "cursor-page-two"), ([_row("2024-01-03")], None)],
    )
    monkeypatch.setattr(
        opendata_provider_module,
        "_PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES",
        sum(response_sizes),
    )

    try:
        result = await provider.fetch_published_index_snapshot(_request(), dataset_id=_DATASET_ID)
    finally:
        await client.aclose()

    assert len(result.records) == 2
    assert result.page_count == 2
    assert len([request for request in requests if request.url.path.endswith("/records")]) == 2
