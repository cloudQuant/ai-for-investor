"""Read one explicitly pinned OpenData stock-daily publication.

This standalone reader validates the stock-daily v2 route against AFI's
existing OpenData stock-bar provider contract. The default ``read`` method is
not wired into stock business tasks, authorization policy, or fallback
providers. ``read_authorized`` is an opt-in path that requires current exact
user/source grants through ``StockDailySnapshotAuthorizationAdapter`` and runs
the policy both before provider I/O and again before returning the response.
Coverage is returned as ``unknown`` because no independent full-history
evidence is currently bound to this publication.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.market_data.opendata_contracts import OPENDATA_PROVIDER_CONTRACT_REGISTRY
from app.services.market_data.opendata_provider import (
    OpendataProvider,
    OpendataProviderError,
    OpendataPublishedSnapshotResult,
)
from app.services.market_data.provider_contracts import ProviderContract, ProviderContractError
from app.services.market_data.provider_models import MarketDataProviderRequest
from app.services.stock_analysis.opendata_snapshot_authorization import (
    StockAnalysisSnapshotScope,
)
from app.services.stock_analysis.stock_daily_snapshot_authorization_adapter import (
    DATASET_ID as _AUTHORIZATION_DATASET_ID,
)
from app.services.stock_analysis.stock_daily_snapshot_authorization_adapter import (
    SOURCE_ID as _AUTHORIZATION_SOURCE_ID,
)
from app.services.stock_analysis.stock_daily_snapshot_authorization_adapter import (
    StockDailySnapshotAuthorizationAdapter,
    StockDailySnapshotAuthorizationError,
)

_UTC = timezone.utc
_DATASET_ID = "cn-equity-stock-daily"
_SOURCE = {"source_id": "akshare.daily", "source": "akshare"}
_SCHEMA = [
    {"name": "market", "data_type": "string", "nullable": False},
    {"name": "symbol", "data_type": "string", "nullable": False},
    {"name": "trade_date", "data_type": "date", "nullable": False},
    {"name": "open", "data_type": "number", "nullable": False},
    {"name": "high", "data_type": "number", "nullable": False},
    {"name": "low", "data_type": "number", "nullable": False},
    {"name": "close", "data_type": "number", "nullable": False},
    {"name": "volume", "data_type": "number", "nullable": False},
    {"name": "amount", "data_type": "number", "nullable": False},
]
_FIELD_UNITS = {
    "open": "CNY/share",
    "high": "CNY/share",
    "low": "CNY/share",
    "close": "CNY/share",
    "volume": "share",
    "amount": "CNY",
}
_FIELD_CURRENCIES = {
    "open": "CNY",
    "high": "CNY",
    "low": "CNY",
    "close": "CNY",
    "amount": "CNY",
}
_FIELD_ADJUSTMENTS = {
    "open": "raw",
    "high": "raw",
    "low": "raw",
    "close": "raw",
    "volume": "not_applicable",
    "amount": "not_applicable",
}
_BUSINESS_KEY_FIELDS = ["market", "symbol", "trade_date"]
_ORDERING_FIELDS = ["trade_date", "market", "symbol"]
_STORAGE_ORDER = [
    {"field": "business_date", "direction": "asc", "nulls": "last", "comparison": "native"},
    {"field": "business_key", "direction": "asc", "comparison": "binary_lexicographic"},
]
_IDENTITY_SEMANTICS = {
    "version": 1,
    "business_key_fields": _BUSINESS_KEY_FIELDS,
    "identity_key_encoding": "canonical-json-array-v1",
    "revision": "latest non-deleted revision per business_key at the pinned publication sequence",
    "ordering_fields": _ORDERING_FIELDS,
    "storage_order": _STORAGE_ORDER,
    "temporal_semantics": "business_date",
    "time_field": "trade_date",
    "temporal_fields": {
        "business_date": "business-date bucket; null ordering last (route rejects null time values)",
        "observed_at": "source observation time",
        "source_published_at": "source publication time",
        "available_at": "platform availability time",
        "event_at": "source event time",
    },
}
_ROW_FIELDS = {
    "dataset_id",
    "business_key",
    "revision",
    "publication_id",
    "publication_sequence",
    "business_date",
    "event_at",
    "observed_at",
    "source_published_at",
    "available_at",
    "payload",
    "record_hash",
}
_PAYLOAD_FIELDS = {
    "market",
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
}
_HEX_32 = re.compile(r"[0-9a-f]{32}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_SYMBOL = re.compile(r"[0-9]{6}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class OpendataStockDailySnapshotError(RuntimeError):
    """Safe stable failure code for a fixed stock-daily publication read."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OpendataStockDailySnapshotReader:
    """Read and validate one exact symbol/window/publication tuple.

    The OpenData service performs API-key authentication and its dataset grant
    checks. ``read`` adds no authorization layer and never selects a fallback
    provider. ``read_authorized`` additionally requires current exact AFI
    grants and fails closed on any denial, expiry, or revocation.
    """

    def __init__(
        self,
        provider: OpendataProvider,
        *,
        authorization_adapter: StockDailySnapshotAuthorizationAdapter | None = None,
    ) -> None:
        self._provider = provider
        self._authorization_adapter = authorization_adapter

    async def read(
        self,
        request: MarketDataProviderRequest,
        *,
        publication_id: str,
    ) -> OpendataPublishedSnapshotResult:
        """Return validated raw rows plus the unchanged ``unknown`` coverage.

        Args:
            request: Exact AFI OpenData stock daily request.
            publication_id: Lowercase publication ID selected by the caller.

        Raises:
            OpendataStockDailySnapshotError: If the route, snapshot, coverage,
                row identity, or business data differs from the reviewed shape.
        """
        contract = _validate_request(request, publication_id)
        return await self._read_validated(
            request,
            publication_id=publication_id,
            contract=contract,
        )

    async def read_authorized(
        self,
        request: MarketDataProviderRequest,
        *,
        publication_id: str,
        content_sha256: str,
        user_id: str,
        session: AsyncSession,
    ) -> OpendataPublishedSnapshotResult:
        """Read one publication after exact current grants allow its content hash.

        Authorization runs after route validation and before provider I/O. The
        expected ``content_sha256`` is taken explicitly from the caller and is
        used as the policy ``capture_id``; it is never inferred from a response.
        A second revalidation runs after the response is validated and before
        it is returned.

        Args:
            request: Exact AFI OpenData stock daily request.
            publication_id: Lowercase publication ID selected by the caller.
            content_sha256: Expected platform publication content digest.
            user_id: Current authenticated principal.
            session: Caller-provided async session for current grant reads.

        Raises:
            OpendataStockDailySnapshotError: With the stable adapter denial code
                on any authorization failure, or with the ordinary contract
                codes on malformed route/snapshot/row content.
        """
        contract = _validate_request(request, publication_id)
        adapter = self._authorization_adapter
        if adapter is None:
            raise OpendataStockDailySnapshotError("stock_daily_authorization_unavailable")
        if not isinstance(content_sha256, str) or _HEX_64.fullmatch(content_sha256) is None:
            raise OpendataStockDailySnapshotError("invalid_content_sha256")
        scope = _authorized_scope(
            request,
            publication_id=publication_id,
            content_sha256=content_sha256,
            user_id=user_id,
        )
        try:
            receipt = await adapter.authorize(
                session=session,
                user_id=user_id,
                scope=scope,
            )
        except StockDailySnapshotAuthorizationError as exc:
            raise OpendataStockDailySnapshotError(exc.code) from exc
        result = await self._read_validated(
            request,
            publication_id=publication_id,
            contract=contract,
        )
        if result.snapshot["content_sha256"] != content_sha256:
            raise OpendataStockDailySnapshotError("opendata_snapshot_content_changed")
        try:
            await adapter.revalidate(
                session=session,
                user_id=user_id,
                scope=scope,
                receipt=receipt,
            )
        except StockDailySnapshotAuthorizationError as exc:
            raise OpendataStockDailySnapshotError(exc.code) from exc
        return result

    async def _read_validated(
        self,
        request: MarketDataProviderRequest,
        *,
        publication_id: str,
        contract: ProviderContract,
    ) -> OpendataPublishedSnapshotResult:
        """Perform provider I/O and validate the complete published response."""
        fetch_snapshot = getattr(self._provider, "fetch_published_stock_daily_snapshot", None)
        if not callable(fetch_snapshot):
            raise OpendataStockDailySnapshotError("opendata_route_contract_invalid")
        try:
            result = await fetch_snapshot(request, publication_id=publication_id)
        except OpendataProviderError as exc:
            raise OpendataStockDailySnapshotError(_provider_error_code(exc.code)) from exc
        except Exception as exc:
            raise OpendataStockDailySnapshotError("opendata_fetch_failed") from exc
        if not isinstance(result, OpendataPublishedSnapshotResult):
            raise OpendataStockDailySnapshotError("opendata_snapshot_receipt_invalid")
        if (
            not isinstance(result.snapshot, Mapping)
            or not isinstance(result.coverage, Mapping)
            or type(result.records) is not tuple
        ):
            raise OpendataStockDailySnapshotError("opendata_snapshot_receipt_invalid")

        start = request.start_at.date()
        end = request.end_at.date()
        _validate_snapshot(result.snapshot, request=request, publication_id=publication_id)
        _validate_coverage(result.coverage, start=start, end=end)
        _validate_records(
            result.records,
            snapshot=result.snapshot,
            request=request,
            contract=contract,
            start=start,
            end=end,
        )
        if (
            type(result.page_count) is not int
            or not 1 <= result.page_count <= 100
            or len(result.records) != result.snapshot["record_count"]
        ):
            raise OpendataStockDailySnapshotError("opendata_snapshot_incomplete")
        return result


def _authorized_scope(
    request: MarketDataProviderRequest,
    *,
    publication_id: str,
    content_sha256: str,
    user_id: str,
) -> StockAnalysisSnapshotScope:
    """Map the validated request to the policy's exact grant scope."""
    market = {"CN-SSE": "SH", "CN-SZSE": "SZ"}[request.market]
    return StockAnalysisSnapshotScope(
        user_id=user_id,
        dataset_id=_AUTHORIZATION_DATASET_ID,
        source_id=_AUTHORIZATION_SOURCE_ID,
        instrument_id=f"{request.provider_symbol}.{market}",
        market=market,
        publication_id=publication_id,
        capture_id=content_sha256,
    )


def _validate_request(
    request: MarketDataProviderRequest,
    publication_id: str,
) -> ProviderContract:
    """Bind route, instrument, native basis, and dates before provider I/O."""
    if not isinstance(request, MarketDataProviderRequest):
        raise OpendataStockDailySnapshotError("invalid_stock_daily_request")
    if not isinstance(publication_id, str) or _HEX_32.fullmatch(publication_id) is None:
        raise OpendataStockDailySnapshotError("invalid_publication_id")
    try:
        contract = OPENDATA_PROVIDER_CONTRACT_REGISTRY.select_for_request(request)
    except ProviderContractError as exc:
        raise OpendataStockDailySnapshotError("opendata_contract_invalid") from exc
    if (
        contract.contract_id != "opendata.stock.daily.contract-v1"
        or request.asset_type != "stock"
        or request.market not in {"CN-SSE", "CN-SZSE"}
        or request.data_kind != "bars"
        or request.frequency != "1d"
        or request.adjustment not in {None, "unadjusted"}
        or request.price_basis not in {None, "close"}
        or request.currency != "CNY"
        or request.unit != "share"
        or _SYMBOL.fullmatch(request.provider_symbol) is None
        or request.canonical_id != f"instrument:stock:{request.market}:{request.provider_symbol}"
        or request.start_at.utcoffset() != timedelta(0)
        or request.end_at.utcoffset() != timedelta(0)
        or request.start_at.time() != time.min
        or request.end_at.time() != time.min
        or request.start_at >= request.end_at
    ):
        raise OpendataStockDailySnapshotError("invalid_stock_daily_request")
    symbol_prefix_matches_market = (
        request.market == "CN-SSE" and request.provider_symbol.startswith("6")
    ) or (request.market == "CN-SZSE" and request.provider_symbol.startswith(("0", "3")))
    if not symbol_prefix_matches_market:
        raise OpendataStockDailySnapshotError("stock_identity_rejected")
    expected_fields = {"open", "high", "low", "close", "volume", "turnover"}
    if not request.required_fields <= expected_fields:
        raise OpendataStockDailySnapshotError("opendata_contract_invalid")
    return contract


def _validate_snapshot(
    snapshot: Mapping[str, Any],
    *,
    request: MarketDataProviderRequest,
    publication_id: str,
) -> None:
    """Require the exact raw stock-daily contract and selected date window."""
    start = request.start_at.date().isoformat()
    end = request.end_at.date().isoformat()
    stock_selection = {"market": request.market, "symbol": request.provider_symbol}
    if (
        snapshot.get("dataset_id") != _DATASET_ID
        or snapshot.get("publication_id") != publication_id
        or type(snapshot.get("sequence")) is not int
        or snapshot["sequence"] < 1
        or snapshot.get("schema_version") != "1.0.0"
        or snapshot.get("semantic_version") != "stock-daily-raw-v1"
        or _HEX_32.fullmatch(str(snapshot.get("snapshot_id", ""))) is None
        or _HEX_64.fullmatch(str(snapshot.get("contract_sha256", ""))) is None
        or snapshot.get("source") != _SOURCE
        or snapshot.get("schema") != _SCHEMA
        or not isinstance(snapshot.get("quality"), Mapping)
        or set(snapshot["quality"]) != {"status", "report_id", "issue_count"}
        or not isinstance(snapshot["quality"].get("status"), str)
        or snapshot["quality"].get("status") not in {"passed", "warning", "unknown"}
        or (
            snapshot["quality"].get("report_id") is not None
            and not isinstance(snapshot["quality"].get("report_id"), str)
        )
        or type(snapshot["quality"].get("issue_count")) is not int
        or snapshot["quality"].get("issue_count", -1) < 0
        or snapshot.get("field_units") != _FIELD_UNITS
        or snapshot.get("field_currencies") != _FIELD_CURRENCIES
        or snapshot.get("field_adjustments") != _FIELD_ADJUSTMENTS
        or snapshot.get("currency") != "CNY"
        or snapshot.get("adjustment_basis") != "raw"
        or snapshot.get("asset_class") != "equity"
        or snapshot.get("frequency") != "1d"
        or snapshot.get("record_kind") != "time_series"
        or snapshot.get("business_key_fields") != _BUSINESS_KEY_FIELDS
        or snapshot.get("ordering_fields") != _ORDERING_FIELDS
        or snapshot.get("storage_order") != _STORAGE_ORDER
        or snapshot.get("identity_key_encoding") != "canonical-json-array-v1"
        or snapshot.get("filter_fields") != ["market", "symbol"]
        or snapshot.get("time_field") != "trade_date"
        or snapshot.get("temporal_semantics") != "business_date"
        or snapshot.get("source_available_at_field") is not None
        or snapshot.get("calendar_id") != "SSE"
        or snapshot.get("timezone") != "Asia/Shanghai"
        or snapshot.get("pit_policy") != "unsupported"
        or snapshot.get("identity_semantics") != _IDENTITY_SEMANTICS
        or snapshot.get("stock_selection") != stock_selection
        or snapshot.get("window") != {"start": start, "end": end, "end_exclusive": True}
        or type(snapshot.get("page_size")) is not int
        or snapshot["page_size"] != 1000
        or type(snapshot.get("record_count")) is not int
        or not 0 <= snapshot["record_count"] <= 50_000
        or _HEX_64.fullmatch(str(snapshot.get("selection_sha256", ""))) is None
        or _HEX_64.fullmatch(str(snapshot.get("content_sha256", ""))) is None
        or not _aware_timestamp(snapshot.get("as_of"))
        or not _aware_timestamp(snapshot.get("created_at"))
        or not _aware_timestamp(snapshot.get("expires_at"))
    ):
        raise OpendataStockDailySnapshotError("opendata_snapshot_contract_mismatch")
    try:
        if _aware_timestamp_value(snapshot["expires_at"]) <= _aware_timestamp_value(
            snapshot["created_at"]
        ):
            raise OpendataStockDailySnapshotError("opendata_snapshot_contract_mismatch")
    except (OverflowError, TypeError, ValueError) as exc:
        raise OpendataStockDailySnapshotError("opendata_snapshot_contract_mismatch") from exc


def _validate_coverage(coverage: Mapping[str, Any], *, start: date, end: date) -> None:
    """Preserve UNKNOWN until independent historical evidence is bound."""
    if (
        set(coverage)
        != {
            "status",
            "scope",
            "requested",
            "observed",
            "missing_ranges",
            "evidence_refs",
            "limitation",
        }
        or coverage.get("status") != "unknown"
        or coverage.get("scope") != "unknown"
        or coverage.get("requested") != {"start": start.isoformat(), "end": end.isoformat()}
        or coverage.get("observed") is not None
        or coverage.get("missing_ranges") != []
        or coverage.get("evidence_refs") != []
        or not isinstance(coverage.get("limitation"), str)
        or not coverage["limitation"].strip()
    ):
        raise OpendataStockDailySnapshotError("opendata_coverage_contract_mismatch")


def _validate_records(
    records: tuple[Mapping[str, Any], ...],
    *,
    snapshot: Mapping[str, Any],
    request: MarketDataProviderRequest,
    contract: ProviderContract,
    start: date,
    end: date,
) -> None:
    """Validate every record's published identity, business date, and native values."""
    seen_dates: set[str] = set()
    previous_date: str | None = None
    normalized_names = {contract.normalized_field_name(field) for field in _PAYLOAD_FIELDS}
    if not request.required_fields <= normalized_names:
        raise OpendataStockDailySnapshotError("opendata_contract_invalid")
    for row in records:
        if not isinstance(row, Mapping) or set(row) != _ROW_FIELDS:
            raise OpendataStockDailySnapshotError("opendata_record_identity_invalid")
        payload = row.get("payload")
        business_date = row.get("business_date")
        publication_sequence = row.get("publication_sequence")
        row_publication_id = row.get("publication_id")
        if (
            row.get("dataset_id") != _DATASET_ID
            or type(row.get("revision")) is not int
            or row["revision"] < 1
            or type(publication_sequence) is not int
            or publication_sequence != snapshot["sequence"]
            or row_publication_id != snapshot["publication_id"]
            or not isinstance(business_date, str)
            or _DATE.fullmatch(business_date) is None
            or not isinstance(payload, Mapping)
            or set(payload) != _PAYLOAD_FIELDS
            or payload.get("market") != "cn"
            or payload.get("symbol") != request.provider_symbol
            or payload.get("trade_date") != business_date
            or _HEX_64.fullmatch(str(row.get("record_hash", ""))) is None
        ):
            raise OpendataStockDailySnapshotError("opendata_record_identity_invalid")
        try:
            parsed_date = date.fromisoformat(business_date)
        except ValueError as exc:
            raise OpendataStockDailySnapshotError("opendata_record_date_invalid") from exc
        expected_business_key = json.dumps(
            ["cn", request.provider_symbol, business_date],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if (
            parsed_date.isoformat() != business_date
            or not start <= parsed_date < end
            or business_date in seen_dates
            or (previous_date is not None and business_date <= previous_date)
            or row["business_key"] != expected_business_key
        ):
            raise OpendataStockDailySnapshotError("opendata_record_date_invalid")
        for field_name in ("event_at", "observed_at", "source_published_at", "available_at"):
            value = row.get(field_name)
            if value is not None and not _aware_timestamp(value):
                raise OpendataStockDailySnapshotError("opendata_record_timestamp_invalid")
        if row.get("event_at") is not None or row.get("source_published_at") is not None:
            raise OpendataStockDailySnapshotError("opendata_record_timestamp_invalid")
        numbers: dict[str, float] = {}
        for field_name in ("open", "high", "low", "close", "volume", "amount"):
            value = payload.get(field_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise OpendataStockDailySnapshotError("opendata_record_value_invalid")
            try:
                number = float(value)
            except (OverflowError, TypeError, ValueError) as exc:
                raise OpendataStockDailySnapshotError("opendata_record_value_invalid") from exc
            if not math.isfinite(number) or number < 0:
                raise OpendataStockDailySnapshotError("opendata_record_value_invalid")
            if field_name in {"open", "high", "low", "close"} and number == 0:
                raise OpendataStockDailySnapshotError("opendata_record_value_invalid")
            numbers[field_name] = number
        if numbers["high"] < max(numbers["open"], numbers["close"], numbers["low"]) or numbers[
            "low"
        ] > min(numbers["open"], numbers["close"], numbers["high"]):
            raise OpendataStockDailySnapshotError("opendata_record_ohlc_invalid")
        seen_dates.add(business_date)
        previous_date = business_date


def _aware_timestamp(value: object) -> bool:
    """Check an ISO datetime without accepting naive or malformed values."""
    try:
        _aware_timestamp_value(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return True


def _aware_timestamp_value(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return parsed.astimezone(_UTC)


def _provider_error_code(code: str) -> str:
    """Map provider failures to stable reader-visible codes."""
    return {
        "OPENDATA_CREDENTIAL_MISSING": "opendata_credentials_missing",
        "OPENDATA_UNAUTHORIZED": "opendata_credentials_rejected",
        "OPENDATA_FORBIDDEN": "opendata_dataset_grant_denied",
        "OPENDATA_SNAPSHOT_EXPIRED": "opendata_snapshot_expired",
        "OPENDATA_RESPONSE_TOO_LARGE": "opendata_snapshot_limit_exceeded",
        "OPENDATA_STOCK_DAILY_SNAPSHOT_INCOMPLETE": "opendata_snapshot_incomplete",
        "OPENDATA_STOCK_DAILY_SNAPSHOT_LIMIT_EXCEEDED": "opendata_snapshot_limit_exceeded",
        "OPENDATA_STOCK_DAILY_SNAPSHOT_CURSOR_INVALID": "opendata_snapshot_cursor_invalid",
        "OPENDATA_STOCK_DAILY_SNAPSHOT_PAGE_INVALID": "opendata_snapshot_page_invalid",
    }.get(code, "opendata_fetch_failed")


__all__ = [
    "OpendataStockDailySnapshotError",
    "OpendataStockDailySnapshotReader",
]
