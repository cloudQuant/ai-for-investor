"""Validation and page-protocol helpers decomposed from opendata_provider."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import time, timedelta
from typing import Any

from app.services.market_data.opendata_contracts import (
    OPENDATA_INDEX_BENCHMARK_DATASET_IDS,
    OPENDATA_INDEX_BENCHMARK_DATASETS,
    OPENDATA_INDEX_BENCHMARK_FAMILY_ID,
    OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION,
    OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT,
    OPENDATA_INDEX_BENCHMARK_ROUTE_ID,
    has_complete_business_history_coverage,
)
from app.services.market_data.provider_contracts import ProviderContract, ProviderContractError
from app.services.market_data.providers import MarketDataProviderRequest

PUBLISHED_SNAPSHOT_PAGE_SIZE = 1000
PUBLISHED_SNAPSHOT_MAX_PAGES = 100
PUBLISHED_SNAPSHOT_MAX_ROWS = 50_000
PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES = 64 * 1024 * 1024
PUBLISHED_STOCK_DAILY_DATASET_ID = "cn-equity-stock-daily"

_META_KEYS = frozenset({"snapshot", "ordering_fields", "storage_order", "identity_key_encoding"})


def validate_index_snapshot_request(
    request: MarketDataProviderRequest,
    dataset_id: str,
    *,
    error_cls: type[Exception],
) -> tuple[str, str]:
    """Validate an allowlisted OpenData benchmark index snapshot request."""
    if not isinstance(request, MarketDataProviderRequest):
        raise error_cls("OPENDATA_INDEX_SNAPSHOT_REQUEST_INVALID")
    symbol_to_dataset = dict(OPENDATA_INDEX_BENCHMARK_DATASETS.values())
    benchmark_id = request.canonical_id.removeprefix("index:")
    expected_identity = OPENDATA_INDEX_BENCHMARK_DATASETS.get(benchmark_id)
    if (
        dataset_id not in OPENDATA_INDEX_BENCHMARK_DATASET_IDS
        or expected_identity != (request.provider_symbol, dataset_id)
        or symbol_to_dataset.get(request.provider_symbol) != dataset_id
        or request.provider != "opendata"
        or request.asset_type != "index"
        or request.market != "CN-SSE"
        or request.data_kind != "bars"
        or request.frequency != "1d"
        or request.required_fields != frozenset({"close"})
        or request.adjustment != "not_applicable"
        or request.price_basis != "close"
        or request.currency is not None
        or request.unit != "point"
        or request.route_id != OPENDATA_INDEX_BENCHMARK_ROUTE_ID
        or request.family_id != OPENDATA_INDEX_BENCHMARK_FAMILY_ID
        or request.family_contract_version != OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION
        or request.provider_endpoint != OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT
        or request.start_at.utcoffset() != timedelta(0)
        or request.end_at.utcoffset() != timedelta(0)
        or request.start_at.time() != time.min
        or request.end_at.time() != time.min
        or request.start_at >= request.end_at
    ):
        raise error_cls("OPENDATA_INDEX_SNAPSHOT_REQUEST_INVALID")
    return request.start_at.date().isoformat(), request.end_at.date().isoformat()


def validate_index_coverage_payload(
    coverage_payload: Mapping[str, Any],
    *,
    dataset_id: str,
    start_date: str,
    end_date: str,
    error_cls: type[Exception],
) -> tuple[str, str]:
    """Validate OpenData index coverage payload and return `(publication_id, contract_sha256)`."""
    coverage = coverage_payload.get("coverage")
    publication_id = coverage_payload.get("publication_id")
    contract_sha256 = coverage_payload.get("contract_sha256")
    if (
        coverage_payload.get("dataset_id") != dataset_id
        or not isinstance(publication_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", publication_id) is None
        or not isinstance(contract_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", contract_sha256) is None
        or not isinstance(coverage, Mapping)
        or not has_complete_business_history_coverage(
            coverage, requested_start=start_date, requested_end=end_date
        )
    ):
        raise error_cls("OPENDATA_INDEX_COVERAGE_UNAVAILABLE")
    return publication_id, contract_sha256


def validate_index_snapshot_metadata(
    snapshot_payload: Mapping[str, Any],
    *,
    dataset_id: str,
    publication_id: str,
    contract_sha256: str,
    start_date: str,
    end_date: str,
    page_size: int = PUBLISHED_SNAPSHOT_PAGE_SIZE,
    max_rows: int = PUBLISHED_SNAPSHOT_MAX_ROWS,
    error_cls: type[Exception],
) -> tuple[dict[str, Any], str, int]:
    """Validate created index snapshot metadata and return `(snapshot, snapshot_id, record_count)`."""
    snapshot_id = snapshot_payload.get("snapshot_id")
    window = snapshot_payload.get("window")
    record_count = snapshot_payload.get("record_count")
    if (
        not isinstance(snapshot_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", snapshot_id) is None
        or snapshot_payload.get("dataset_id") != dataset_id
        or snapshot_payload.get("publication_id") != publication_id
        or snapshot_payload.get("adjustment_basis") != "not_applicable"
        or snapshot_payload.get("contract_sha256") != contract_sha256
        or not isinstance(window, Mapping)
        or window.get("start") != start_date
        or window.get("end") != end_date
        or window.get("end_exclusive") is not True
        or snapshot_payload.get("page_size") != page_size
        or isinstance(snapshot_payload.get("page_size"), bool)
        or type(record_count) is not int
        or not 0 <= record_count <= max_rows
    ):
        raise error_cls("OPENDATA_INDEX_SNAPSHOT_METADATA_INVALID")
    return dict(snapshot_payload), snapshot_id, record_count


def _page_meta_consistent(page_meta: object, snapshot: Mapping[str, Any]) -> bool:
    if not isinstance(page_meta, Mapping) or set(page_meta) != _META_KEYS:
        return False
    return (
        page_meta.get("snapshot") == snapshot
        and page_meta.get("ordering_fields") == snapshot.get("ordering_fields")
        and page_meta.get("storage_order") == snapshot.get("storage_order")
        and page_meta.get("identity_key_encoding") == snapshot.get("identity_key_encoding")
    )


def validate_index_snapshot_page(
    page_payload: Mapping[str, Any],
    *,
    snapshot: Mapping[str, Any],
    record_count: int,
    total_bytes: int,
    records: list[Mapping[str, Any]],
    page_size: int = PUBLISHED_SNAPSHOT_PAGE_SIZE,
    max_rows: int = PUBLISHED_SNAPSHOT_MAX_ROWS,
    max_total_bytes: int = PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES,
    error_cls: type[Exception],
) -> tuple[bool, Any]:
    """Validate one index snapshot page, append records, and return `(has_more, next_cursor)`."""
    rows = page_payload.get("rows")
    count = page_payload.get("count")
    has_more = page_payload.get("has_more")
    next_cursor = page_payload.get("next_cursor")
    metadata_keys = set(snapshot)
    expected_page_keys = metadata_keys | {"rows", "count", "next_cursor", "has_more", "meta"}
    page_metadata = {key: page_payload.get(key) for key in metadata_keys}
    if (
        set(page_payload) != expected_page_keys
        or page_metadata != snapshot
        or not isinstance(rows, list)
        or type(count) is not int
        or count != len(rows)
        or count > page_size
        or type(has_more) is not bool
        or (next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor))
        or has_more != (next_cursor is not None)
        or (has_more and not rows)
        or not _page_meta_consistent(page_payload.get("meta"), snapshot)
        or any(not isinstance(row, Mapping) for row in rows)
    ):
        raise error_cls("OPENDATA_INDEX_SNAPSHOT_PAGE_INVALID")
    records.extend(rows)
    if len(records) > max_rows or len(records) > record_count or total_bytes > max_total_bytes:
        raise error_cls("OPENDATA_INDEX_SNAPSHOT_LIMIT_EXCEEDED")
    if not has_more and len(records) != record_count:
        raise error_cls("OPENDATA_INDEX_SNAPSHOT_INCOMPLETE")
    return has_more, next_cursor


def validate_next_snapshot_cursor(
    *,
    next_cursor: Any,
    cursor: str | None,
    seen_cursors: set[str],
    total_bytes: int,
    page_count: int,
    limit_code: str,
    cursor_code: str,
    max_total_bytes: int = PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES,
    max_pages: int = PUBLISHED_SNAPSHOT_MAX_PAGES,
    error_cls: type[Exception],
) -> str:
    """Validate budget and monotonic unseen cursor state before fetching the next page."""
    if total_bytes >= max_total_bytes or page_count >= max_pages:
        raise error_cls(limit_code)
    if (
        next_cursor is None
        or next_cursor == cursor
        or next_cursor in seen_cursors
        or len(next_cursor) > 8192
        or any(ord(character) < 32 for character in next_cursor)
    ):
        raise error_cls(cursor_code)
    seen_cursors.add(next_cursor)
    return str(next_cursor)


def validate_stock_daily_snapshot_request(
    request: MarketDataProviderRequest,
    publication_id: str,
    *,
    reviewed_contract_fn: Callable[[MarketDataProviderRequest], ProviderContract],
    error_cls: Callable[..., Exception],
) -> tuple[str, str]:
    """Validate stock-daily snapshot request and publication ID; return `(start_date, end_date)`."""
    if not isinstance(request, MarketDataProviderRequest):
        raise error_cls("OPENDATA_STOCK_DAILY_SNAPSHOT_REQUEST_INVALID")
    try:
        contract = reviewed_contract_fn(request)
    except ProviderContractError as exc:
        raise error_cls("OPENDATA_STOCK_DAILY_SNAPSHOT_REQUEST_INVALID", detail=exc.code) from exc
    if (
        contract.contract_id != "opendata.stock.daily.contract-v1"
        or request.asset_type != "stock"
        or request.market not in {"CN-SSE", "CN-SZSE"}
        or request.data_kind != "bars"
        or request.frequency != "1d"
        or request.adjustment != "unadjusted"
        or request.price_basis not in {None, "close"}
        or request.currency != "CNY"
        or request.unit != "share"
        or not re.fullmatch(r"[0-9]{6}", request.provider_symbol)
        or request.canonical_id != f"instrument:stock:{request.market}:{request.provider_symbol}"
        or request.start_at.utcoffset() != timedelta(0)
        or request.end_at.utcoffset() != timedelta(0)
        or request.start_at.time() != time.min
        or request.end_at.time() != time.min
        or request.start_at >= request.end_at
    ):
        raise error_cls("OPENDATA_STOCK_DAILY_SNAPSHOT_REQUEST_INVALID")
    symbol_prefix_matches = (
        request.market == "CN-SSE" and request.provider_symbol.startswith("6")
    ) or (request.market == "CN-SZSE" and request.provider_symbol.startswith(("0", "3")))
    if (
        not symbol_prefix_matches
        or not isinstance(publication_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", publication_id) is None
    ):
        raise error_cls("OPENDATA_STOCK_DAILY_SNAPSHOT_REQUEST_INVALID")
    return request.start_at.date().isoformat(), request.end_at.date().isoformat()


def validate_stock_daily_snapshot_page(
    page_payload: Mapping[str, Any],
    *,
    request: MarketDataProviderRequest,
    publication_id: str,
    snapshot: dict[str, Any] | None,
    coverage: dict[str, Any] | None,
    total_bytes: int,
    records: list[Mapping[str, Any]],
    page_size: int = PUBLISHED_SNAPSHOT_PAGE_SIZE,
    max_rows: int = PUBLISHED_SNAPSHOT_MAX_ROWS,
    max_total_bytes: int = PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES,
    error_cls: type[Exception],
) -> tuple[dict[str, Any], dict[str, Any] | None, bool, Any]:
    """Validate one stock-daily snapshot page and return `(snapshot, coverage, has_more, next_cursor)`."""
    page_meta = page_payload.get("meta")
    page_snapshot = page_meta.get("snapshot") if isinstance(page_meta, Mapping) else None
    page_coverage = page_payload.get("coverage")
    page_records = page_payload.get("rows")
    count = page_payload.get("count")
    has_more = page_payload.get("has_more")
    next_cursor = page_payload.get("next_cursor")
    if not isinstance(page_snapshot, Mapping):
        raise error_cls("OPENDATA_STOCK_DAILY_SNAPSHOT_PAGE_INVALID")
    if snapshot is None:
        snapshot = dict(page_snapshot)
    if coverage is None and isinstance(page_coverage, Mapping):
        coverage = dict(page_coverage)
    expected_page_keys = set(snapshot) | {
        "coverage",
        "rows",
        "count",
        "next_cursor",
        "has_more",
        "meta",
    }
    expected_selection = {"market": request.market, "symbol": request.provider_symbol}
    if (
        set(page_payload) != expected_page_keys
        or dict(page_snapshot) != snapshot
        or snapshot.get("dataset_id") != PUBLISHED_STOCK_DAILY_DATASET_ID
        or snapshot.get("publication_id") != publication_id
        or snapshot.get("adjustment_basis") != "raw"
        or {key: page_payload.get(key) for key in snapshot} != snapshot
        or page_payload.get("stock_selection") != expected_selection
        or snapshot.get("stock_selection") != expected_selection
        or not isinstance(page_coverage, Mapping)
        or dict(page_coverage) != coverage
        or not isinstance(page_records, list)
        or type(count) is not int
        or count != len(page_records)
        or count > page_size
        or type(snapshot.get("page_size")) is not int
        or snapshot["page_size"] != page_size
        or count > snapshot["page_size"]
        or type(has_more) is not bool
        or (next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor))
        or has_more != (next_cursor is not None)
        or (has_more and not page_records)
        or not _page_meta_consistent(page_meta, snapshot)
        or any(not isinstance(row, Mapping) for row in page_records)
    ):
        raise error_cls("OPENDATA_STOCK_DAILY_SNAPSHOT_PAGE_INVALID")
    records.extend(page_records)
    record_count = snapshot.get("record_count")
    if (
        len(records) > max_rows
        or type(record_count) is not int
        or record_count > max_rows
        or len(records) > record_count
        or total_bytes > max_total_bytes
    ):
        raise error_cls("OPENDATA_STOCK_DAILY_SNAPSHOT_LIMIT_EXCEEDED")
    if not has_more and len(records) != record_count:
        raise error_cls("OPENDATA_STOCK_DAILY_SNAPSHOT_INCOMPLETE")
    return snapshot, coverage, has_more, next_cursor
