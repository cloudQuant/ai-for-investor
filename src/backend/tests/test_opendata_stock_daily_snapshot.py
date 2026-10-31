"""Offline synthetic tests for the fixed OpenData stock-daily v2 reader."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

import app.services.market_data.opendata_provider as opendata_provider_module
from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.market_data.opendata_provider import OpendataProvider
from app.services.market_data.opendata_stock_daily_snapshot import (
    OpendataStockDailySnapshotError,
    OpendataStockDailySnapshotReader,
)
from app.services.market_data.provider_models import MarketDataProviderRequest

UTC = timezone.utc
PUBLICATION_ID = "a" * 32
SNAPSHOT_ID = "b" * 32
SELECTION = {"market": "CN-SSE", "symbol": "600519"}
STORAGE_ORDER = [
    {"field": "business_date", "direction": "asc", "nulls": "last", "comparison": "native"},
    {"field": "business_key", "direction": "asc", "comparison": "binary_lexicographic"},
]
BUSINESS_KEY_FIELDS = ["market", "symbol", "trade_date"]
ORDERING_FIELDS = ["trade_date", "market", "symbol"]
TEMPORAL_FIELDS = {
    "business_date": "business-date bucket; null ordering last (route rejects null time values)",
    "observed_at": "source observation time",
    "source_published_at": "source publication time",
    "available_at": "platform availability time",
    "event_at": "source event time",
}
IDENTITY_SEMANTICS = {
    "version": 1,
    "identity_key_encoding": "canonical-json-array-v1",
    "revision": "latest non-deleted revision per business_key at the pinned publication sequence",
    "temporal_fields": TEMPORAL_FIELDS,
    "business_key_fields": BUSINESS_KEY_FIELDS,
    "ordering_fields": ORDERING_FIELDS,
    "storage_order": STORAGE_ORDER,
    "temporal_semantics": "business_date",
    "time_field": "trade_date",
}


def _request(**changes: object) -> MarketDataProviderRequest:
    values: dict[str, object] = {
        "query_fingerprint": "c" * 64,
        "canonical_id": "instrument:stock:CN-SSE:600519",
        "asset_type": "stock",
        "provider_symbol": "600519",
        "market": "CN-SSE",
        "data_kind": "bars",
        "frequency": "1d",
        "start_at": datetime(2026, 10, 27, tzinfo=UTC),
        "end_at": datetime(2026, 10, 29, tzinfo=UTC),
        "required_fields": frozenset({"close", "turnover"}),
        "provider": "opendata",
        "adjustment": "unadjusted",
        "price_basis": "close",
        "currency": "CNY",
        "unit": "share",
        "route_id": "opendata-stock-daily-v1",
        "family_id": "stock.realtime",
        "family_contract_version": "market-data-family-v1",
        "request_id": "A" * 43,
        "source_policy_id": "market-default-v1",
    }
    values.update(changes)
    return MarketDataProviderRequest(**values)  # type: ignore[arg-type]


def _snapshot(*, record_count: int = 2) -> dict[str, Any]:
    return {
        "dataset_id": "cn-equity-stock-daily",
        "publication_id": PUBLICATION_ID,
        "sequence": 7,
        "schema_version": "1.0.0",
        "semantic_version": "stock-daily-raw-v1",
        "contract_sha256": "d" * 64,
        "source": {"source_id": "akshare.daily", "source": "akshare"},
        "schema": [
            {"name": "market", "data_type": "string", "nullable": False},
            {"name": "symbol", "data_type": "string", "nullable": False},
            {"name": "trade_date", "data_type": "date", "nullable": False},
            {"name": "open", "data_type": "number", "nullable": False},
            {"name": "high", "data_type": "number", "nullable": False},
            {"name": "low", "data_type": "number", "nullable": False},
            {"name": "close", "data_type": "number", "nullable": False},
            {"name": "volume", "data_type": "number", "nullable": False},
            {"name": "amount", "data_type": "number", "nullable": False},
        ],
        "quality": {
            "status": "warning",
            "report_id": "stock-daily-offline-normalization-v1",
            "issue_count": 0,
        },
        "field_units": {
            "open": "CNY/share",
            "high": "CNY/share",
            "low": "CNY/share",
            "close": "CNY/share",
            "volume": "share",
            "amount": "CNY",
        },
        "field_currencies": {
            "open": "CNY",
            "high": "CNY",
            "low": "CNY",
            "close": "CNY",
            "amount": "CNY",
        },
        "field_adjustments": {
            "open": "raw",
            "high": "raw",
            "low": "raw",
            "close": "raw",
            "volume": "not_applicable",
            "amount": "not_applicable",
        },
        "currency": "CNY",
        "adjustment_basis": "raw",
        "asset_class": "equity",
        "frequency": "1d",
        "record_kind": "time_series",
        "business_key_fields": BUSINESS_KEY_FIELDS,
        "ordering_fields": ORDERING_FIELDS,
        "storage_order": STORAGE_ORDER,
        "identity_key_encoding": "canonical-json-array-v1",
        "filter_fields": ["market", "symbol"],
        "time_field": "trade_date",
        "temporal_semantics": "business_date",
        "source_available_at_field": None,
        "calendar_id": "SSE",
        "timezone": "Asia/Shanghai",
        "pit_policy": "unsupported",
        "identity_semantics": IDENTITY_SEMANTICS,
        "stock_selection": SELECTION,
        "window": {"start": "2026-10-27", "end": "2026-10-29", "end_exclusive": True},
        "snapshot_id": SNAPSHOT_ID,
        "page_size": 1000,
        "as_of": "2026-10-30T00:00:00+00:00",
        "created_at": "2026-10-30T00:00:00+00:00",
        "expires_at": "2026-11-01T00:00:00+00:00",
        "record_count": record_count,
        "selection_sha256": "e" * 64,
        "content_sha256": "f" * 64,
    }


def _coverage(status: str = "unknown") -> dict[str, Any]:
    return {
        "status": status,
        "scope": "unknown" if status == "unknown" else "business_history",
        "requested": {"start": "2026-10-27", "end": "2026-10-29"},
        "observed": None,
        "missing_ranges": [],
        "evidence_refs": [],
        "limitation": "Coverage is unknown and does not establish complete history.",
    }


def _row(trade_date: str) -> dict[str, Any]:
    return {
        "dataset_id": "cn-equity-stock-daily",
        "business_key": json.dumps(
            ["cn", "600519", trade_date], ensure_ascii=False, separators=(",", ":")
        ),
        "revision": 1,
        "publication_id": PUBLICATION_ID,
        "publication_sequence": 7,
        "business_date": trade_date,
        "event_at": None,
        "observed_at": "2026-10-27T09:30:00+08:00",
        "source_published_at": None,
        "available_at": "2026-10-28T02:00:00+00:00",
        "payload": {
            "market": "cn",
            "symbol": "600519",
            "trade_date": trade_date,
            "open": 1800.0,
            "high": 1820.0,
            "low": 1790.0,
            "close": 1810.0,
            "volume": 1000.0,
            "amount": 1_000_000.0,
        },
        "record_hash": "1" * 64,
    }


def _page(
    rows: list[dict[str, Any]],
    *,
    snapshot: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    pinned = _snapshot() if snapshot is None else snapshot
    return {
        **pinned,
        "coverage": _coverage() if coverage is None else coverage,
        "rows": rows,
        "count": len(rows),
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
        "meta": {
            "snapshot": copy.deepcopy(pinned),
            "ordering_fields": ORDERING_FIELDS,
            "storage_order": STORAGE_ORDER,
            "identity_key_encoding": "canonical-json-array-v1",
        },
    }


def _reader(handler: Any) -> tuple[OpendataStockDailySnapshotReader, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpendataProvider(
        client=client,
        credentials=OpendataCredentials("synthetic-key", base_url="http://opendata.test"),
        max_retries=0,
        retry_backoff_seconds=0,
    )
    return OpendataStockDailySnapshotReader(provider), client


def _response(payload: dict[str, Any], status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        headers={"content-type": "application/json"},
    )


@pytest.mark.asyncio
async def test_reads_one_fixed_publication_across_consistent_cursor_pages() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/api/v2/stock-daily/records"
        params = dict(request.url.params)
        assert params["market"] == "CN-SSE"
        assert params["symbol"] == "600519"
        assert params["publication_id"] == PUBLICATION_ID
        if len(calls) == 1:
            assert params == {
                "market": "CN-SSE",
                "symbol": "600519",
                "publication_id": PUBLICATION_ID,
                "start_date": "2026-10-27",
                "end_date": "2026-10-29",
                "page_size": "1000",
            }
            return _response(_page([_row("2026-10-27")], next_cursor="cursor-1"))
        assert params == {
            "market": "CN-SSE",
            "symbol": "600519",
            "publication_id": PUBLICATION_ID,
            "snapshot_id": SNAPSHOT_ID,
            "cursor": "cursor-1",
        }
        return _response(_page([_row("2026-10-28")]))

    reader, client = _reader(handler)
    try:
        result = await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert len(calls) == 2
    assert result.snapshot["publication_id"] == PUBLICATION_ID
    assert result.snapshot["stock_selection"] == SELECTION
    assert result.page_count == 2
    assert [row["business_date"] for row in result.records] == ["2026-10-27", "2026-10-28"]
    assert [row["payload"]["market"] for row in result.records] == ["cn", "cn"]
    assert result.coverage["status"] == "unknown"
    assert result.coverage["scope"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quality",),
    [
        (
            {
                "status": "warning",
                "report_id": "stock-daily-offline-normalization-v1",
                "issue_count": 0,
            },
        ),
        ({"status": "warning", "report_id": "OD204-STOCK-API", "issue_count": 0},),
        ({"status": "passed", "report_id": None, "issue_count": 1},),
    ],
)
async def test_preserves_open_data_quality_receipts_without_pinning_report_id(
    quality: dict[str, Any],
) -> None:
    snapshot = _snapshot(record_count=1)
    snapshot["quality"] = quality

    async def handler(_request: httpx.Request) -> httpx.Response:
        return _response(_page([_row("2026-10-27")], snapshot=snapshot))

    reader, client = _reader(handler)
    try:
        result = await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert result.snapshot["quality"] == quality


@pytest.mark.asyncio
async def test_rejects_quality_receipts_outside_the_open_data_dto() -> None:
    snapshot = _snapshot(record_count=1)
    snapshot["quality"] = {"status": [], "report_id": "OD204-STOCK-API", "issue_count": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        return _response(_page([_row("2026-10-27")], snapshot=snapshot))

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "opendata_snapshot_contract_mismatch"


@pytest.mark.asyncio
async def test_rejects_venue_symbol_mismatch_before_network_access() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response({})

    reader, client = _reader(handler)
    request = _request(
        market="CN-SZSE",
        canonical_id="instrument:stock:CN-SZSE:600519",
    )
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(request, publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "stock_identity_rejected"
    assert calls == 0


@pytest.mark.asyncio
async def test_does_not_fallback_when_pinned_publication_is_unavailable() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, json={"error": {"code": "not_found"}})

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "opendata_fetch_failed"
    assert calls == 1


@pytest.mark.asyncio
async def test_rejects_snapshot_metadata_drift_on_a_continuation_page() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _response(_page([_row("2026-10-27")], next_cursor="cursor-1"))
        changed = _snapshot()
        changed["content_sha256"] = "2" * 64
        return _response(_page([_row("2026-10-28")], snapshot=changed))

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "opendata_snapshot_page_invalid"
    assert calls == 2


@pytest.mark.asyncio
async def test_preserves_unknown_coverage_and_rejects_claimed_completeness() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return _response(
            _page(
                [_row("2026-10-27"), _row("2026-10-28")],
                coverage=_coverage(status="complete"),
            )
        )

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "opendata_coverage_contract_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda row: row["payload"].__setitem__("market", "CN-SSE"),
            "opendata_record_identity_invalid",
        ),
        (
            lambda row: row.__setitem__("business_key", '["cn", "600519", "2026-10-28"]'),
            "opendata_record_date_invalid",
        ),
        (lambda row: row["payload"].__setitem__("open", True), "opendata_record_value_invalid"),
    ],
)
async def test_rejects_inconsistent_or_invalid_stock_rows(
    mutate: Any,
    expected_code: str,
) -> None:
    bad_row = _row("2026-10-27")
    mutate(bad_row)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return _response(_page([bad_row], snapshot=_snapshot(record_count=1)))

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == expected_code


@pytest.mark.asyncio
async def test_rejects_stock_contract_unit_drift() -> None:
    changed = _snapshot(record_count=1)
    changed["field_units"] = {**changed["field_units"], "volume": "lot"}

    async def handler(_request: httpx.Request) -> httpx.Response:
        return _response(_page([_row("2026-10-27")], snapshot=changed))

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "opendata_snapshot_contract_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "opendata_credentials_rejected"),
        (403, "opendata_dataset_grant_denied"),
        (410, "opendata_snapshot_expired"),
    ],
)
async def test_maps_auth_grant_and_expired_snapshot_failures_without_fallback(
    status_code: int,
    expected_code: str,
) -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, json={"error": {"code": "synthetic"}})

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == expected_code
    assert calls == 1


@pytest.mark.asyncio
async def test_rejects_expired_snapshot_metadata() -> None:
    snapshot = _snapshot(record_count=1)
    snapshot["expires_at"] = "2026-10-30T00:00:00+00:00"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return _response(_page([_row("2026-10-27")], snapshot=snapshot))

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "opendata_snapshot_contract_mismatch"


@pytest.mark.asyncio
async def test_rejects_a_repeated_cursor_cycle() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        pages = {
            1: _page(
                [_row("2026-10-27")], snapshot=_snapshot(record_count=3), next_cursor="cursor-a"
            ),
            2: _page(
                [_row("2026-10-28")], snapshot=_snapshot(record_count=3), next_cursor="cursor-b"
            ),
            3: _page(
                [_row("2026-10-29")], snapshot=_snapshot(record_count=3), next_cursor="cursor-a"
            ),
        }
        return _response(pages[calls])

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "opendata_snapshot_cursor_invalid"
    assert calls == 3


@pytest.mark.asyncio
async def test_enforces_page_count_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opendata_provider_module, "_PUBLISHED_SNAPSHOT_MAX_PAGES", 1)
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(_page([_row("2026-10-27")], next_cursor="cursor-1"))

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "opendata_snapshot_limit_exceeded"
    assert calls == 1


@pytest.mark.asyncio
async def test_enforces_record_count_limit_before_paging() -> None:
    snapshot = _snapshot(record_count=50_001)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return _response(_page([], snapshot=snapshot))

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "opendata_snapshot_limit_exceeded"


@pytest.mark.asyncio
async def test_enforces_accumulated_row_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opendata_provider_module, "_PUBLISHED_SNAPSHOT_MAX_ROWS", 1)

    async def handler(_request: httpx.Request) -> httpx.Response:
        rows = [_row("2026-10-27"), _row("2026-10-28")]
        return _response(_page(rows, snapshot=_snapshot(record_count=2)))

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "opendata_snapshot_limit_exceeded"


@pytest.mark.asyncio
async def test_enforces_page_row_limit() -> None:
    snapshot = _snapshot(record_count=2)
    snapshot["page_size"] = 1

    async def handler(_request: httpx.Request) -> httpx.Response:
        return _response(_page([_row("2026-10-27"), _row("2026-10-28")], snapshot=snapshot))

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "opendata_snapshot_page_invalid"


@pytest.mark.asyncio
async def test_enforces_response_byte_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opendata_provider_module, "_PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES", 100)
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(_page([_row("2026-10-27")], snapshot=_snapshot(record_count=1)))

    reader, client = _reader(handler)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read(_request(), publication_id=PUBLICATION_ID)
    finally:
        await client.aclose()

    assert failure.value.code == "opendata_snapshot_limit_exceeded"
    assert calls == 1
