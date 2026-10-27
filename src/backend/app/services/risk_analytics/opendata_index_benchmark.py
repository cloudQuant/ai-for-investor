"""Fail-closed reader for immutable OpenData v2 index benchmark snapshots."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.services.market_data.access import (
    MarketDataAccessGrant,
    MarketDataAuthorizationError,
    MarketDataQueryAccess,
)
from app.services.market_data.opendata_contracts import (
    OPENDATA_INDEX_BENCHMARK_DATASETS,
    OPENDATA_INDEX_BENCHMARK_FAMILY_ID,
    OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION,
    OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT,
    OPENDATA_INDEX_BENCHMARK_ROUTE_ID,
    has_complete_business_history_coverage,
)
from app.services.market_data.opendata_provider import (
    OpendataProviderError,
    OpendataPublishedSnapshotResult,
)
from app.services.market_data.provider_models import MarketDataProviderRequest
from app.services.market_data.query_cursor import _policy_descriptor_hash
from app.services.market_data.source_policy import (
    MarketDataProviderRoute,
    MarketDataSourcePolicy,
)

UTC = timezone.utc
OPENDATA_INDEX_DAILY_ROUTE_ID = OPENDATA_INDEX_BENCHMARK_ROUTE_ID
OPENDATA_INDEX_DAILY_SOURCE_ID = "opendata"
OPENDATA_INDEX_DAILY_POLICY_ID = "market-default-v1"
OPENDATA_INDEX_DAILY_SOURCE_REVISION = "opendata-published-snapshot-v2"
_SOURCE_ID = "ths.index_daily"
_SOURCE_NAME = "ths"
_SCHEMA_VERSION = "index-ohlcv-v1"
_SEMANTIC_VERSION = "ths-index-points-and-shares-v1"
_FIELD_NAMES = ("symbol", "trade_date", "open", "high", "low", "close", "volume")
_KEY_FIELDS = ["symbol", "trade_date"]
_ORDERING_FIELDS = ["trade_date", "symbol"]
_STORAGE_ORDER = [
    {"field": "business_date", "direction": "asc", "nulls": "last", "comparison": "native"},
    {"field": "business_key", "direction": "asc", "comparison": "binary_lexicographic"},
]
_TEMPORAL_FIELDS = {
    "business_date": "business-date bucket; null ordering last (route rejects null time values)",
    "observed_at": "source observation time",
    "source_published_at": "source publication time",
    "available_at": "platform availability time",
    "event_at": "source event time",
}
_IDENTITY_SEMANTICS = {
    "version": 1,
    "business_key_fields": _KEY_FIELDS,
    "identity_key_encoding": "canonical-json-array-v1",
    "revision": "latest non-deleted revision per business_key at the pinned publication sequence",
    "ordering_fields": _ORDERING_FIELDS,
    "storage_order": _STORAGE_ORDER,
    "temporal_semantics": "business_date",
    "time_field": "trade_date",
    "temporal_fields": _TEMPORAL_FIELDS,
}
_SCHEMA = [
    {"name": "symbol", "data_type": "string", "nullable": False},
    {"name": "trade_date", "data_type": "date", "nullable": False},
    {"name": "open", "data_type": "number", "nullable": False},
    {"name": "high", "data_type": "number", "nullable": False},
    {"name": "low", "data_type": "number", "nullable": False},
    {"name": "close", "data_type": "number", "nullable": False},
    {"name": "volume", "data_type": "number", "nullable": False},
]
_FIELD_UNITS = {
    "open": "index_points",
    "high": "index_points",
    "low": "index_points",
    "close": "index_points",
    "volume": "shares",
}
_FIELD_ADJUSTMENTS = {
    "open": "not_applicable",
    "high": "not_applicable",
    "low": "not_applicable",
    "close": "not_applicable",
    "volume": "not_applicable",
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
_PURPOSE_USES = {
    "display": frozenset({"DISPLAY", "MARKET_DATA_DISPLAY", "MARKET_DATA_READ"}),
    "backtest": frozenset({"BACKTEST", "BACKTEST_ONLY"}),
}
_HEX_32 = re.compile(r"[0-9a-f]{32}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")


class OpenDataIndexBenchmarkError(RuntimeError):
    """Safe, stable failure code for an OpenData benchmark read."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OpenDataIndexBenchmarkReader:
    """Read one allowlisted index only after current route/source authorization."""

    def __init__(
        self,
        *,
        access: MarketDataQueryAccess,
        policy: MarketDataSourcePolicy,
        route: MarketDataProviderRoute,
        grant: MarketDataAccessGrant,
    ) -> None:
        self._access = access
        self._policy = policy
        self._route = route
        self._grant = grant
        self._validate_authorized_context()

    async def fetch_prices(
        self,
        benchmark_id: str,
        risk_symbol: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Return ordered daily closes from one verified immutable snapshot."""
        identity = OPENDATA_INDEX_BENCHMARK_DATASETS.get(benchmark_id)
        if identity is None or risk_symbol != identity[0]:
            raise OpenDataIndexBenchmarkError("benchmark_identity_rejected")
        start, end_exclusive = _date_window(start_date, end_date)
        request = self._provider_request(
            benchmark_id=benchmark_id,
            provider_symbol=identity[0],
            start_at=start,
            end_at=end_exclusive,
        )
        fetch_snapshot = getattr(self._route.adapter, "fetch_published_index_snapshot", None)
        if not callable(fetch_snapshot):
            raise OpenDataIndexBenchmarkError("opendata_route_contract_invalid")
        try:
            result = await fetch_snapshot(request, dataset_id=identity[1])
        except OpendataProviderError as exc:
            mapped_code = {
                "OPENDATA_INDEX_COVERAGE_UNAVAILABLE": "opendata_coverage_unavailable",
                "OPENDATA_FORBIDDEN": "opendata_dataset_grant_denied",
                "OPENDATA_UNAUTHORIZED": "opendata_credentials_rejected",
                "OPENDATA_SNAPSHOT_EXPIRED": "opendata_snapshot_expired",
                "OPENDATA_INDEX_SNAPSHOT_METADATA_INVALID": "opendata_snapshot_metadata_invalid",
                "OPENDATA_INDEX_SNAPSHOT_INCOMPLETE": "opendata_snapshot_incomplete",
                "OPENDATA_INDEX_SNAPSHOT_LIMIT_EXCEEDED": "opendata_snapshot_limit_exceeded",
                "OPENDATA_INDEX_SNAPSHOT_CURSOR_INVALID": "opendata_snapshot_cursor_invalid",
                "OPENDATA_INDEX_SNAPSHOT_PAGE_INVALID": "opendata_snapshot_page_invalid",
            }.get(exc.code, "opendata_fetch_failed")
            raise OpenDataIndexBenchmarkError(mapped_code) from exc
        except Exception as exc:
            raise OpenDataIndexBenchmarkError("opendata_fetch_failed") from exc

        if not isinstance(result, OpendataPublishedSnapshotResult):
            raise OpenDataIndexBenchmarkError("opendata_snapshot_receipt_invalid")
        snapshot = result.snapshot
        _validate_snapshot_metadata(
            snapshot,
            dataset_id=identity[1],
            start=start.date(),
            end=end_exclusive.date(),
        )
        _validate_coverage(
            result.coverage,
            snapshot=snapshot,
            dataset_id=identity[1],
            start=start.date(),
            end=end_exclusive.date(),
        )
        if (
            type(result.page_count) is not int
            or not 1 <= result.page_count <= 100
            or len(result.records) != snapshot["record_count"]
        ):
            raise OpenDataIndexBenchmarkError("opendata_snapshot_incomplete")
        records = _records_from_snapshot(
            result.records,
            snapshot=snapshot,
            provider_symbol=identity[0],
            start=start.date(),
            end=end_exclusive.date(),
        )
        await self._reauthorize_after_fetch()
        return records

    def _validate_authorized_context(self) -> None:
        """Reject broad, stale, or purpose-incompatible authorization context."""
        route = self._route
        if (
            not isinstance(self._access, MarketDataQueryAccess)
            or not isinstance(self._policy, MarketDataSourcePolicy)
            or not isinstance(route, MarketDataProviderRoute)
            or not isinstance(self._grant, MarketDataAccessGrant)
        ):
            raise TypeError("OpenData benchmark reads require typed authorization context")
        if (
            self._policy.policy_id != OPENDATA_INDEX_DAILY_POLICY_ID
            or route not in self._policy.routes
            or route.route_id != OPENDATA_INDEX_DAILY_ROUTE_ID
            or route.request_provider != "opendata"
            or route.provider_endpoint != OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT
            or route.expected_result_provider_ids != frozenset({OPENDATA_INDEX_DAILY_SOURCE_ID})
            or route.asset_types != frozenset({"index"})
            or route.data_kinds != frozenset({"bars"})
            or route.frequencies != frozenset({"1d"})
            or route.markets != frozenset({"CN-SSE"})
            or route.adjustments != frozenset({"not_applicable"})
            or route.price_bases != frozenset({"close"})
            or route.currencies != frozenset({None})
            or route.units != frozenset({"point"})
            or route.family_id != OPENDATA_INDEX_BENCHMARK_FAMILY_ID
            or route.family_contract_version != OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION
            or not callable(getattr(route.adapter, "fetch_published_index_snapshot", None))
        ):
            raise OpenDataIndexBenchmarkError("opendata_route_contract_invalid")
        purpose = self._grant.purpose
        if (
            not self._access.principal.can_read_data
            or self._grant.principal != self._access.principal
            or self._grant.policy_id != self._policy.policy_id
            or purpose not in _PURPOSE_USES
            or not self._policy.allows_purpose(purpose)
            or self._grant.authorized_route_ids != frozenset({route.route_id})
            or self._grant.authorized_source_registry_ids
            != frozenset({OPENDATA_INDEX_DAILY_SOURCE_ID})
        ):
            raise MarketDataAuthorizationError("SOURCE_ROUTE_AUTHORIZATION_DENIED")
        source = self._grant.authorization_for_route(route.route_id)
        if (
            source.source_registry_id != OPENDATA_INDEX_DAILY_SOURCE_ID
            or source.asset_type != "index"
            or source.market != "CN-SSE"
            or source.purpose != purpose
            or source.decision != "ALLOW"
            or not (_PURPOSE_USES[purpose] & set(source.allowed_uses))
        ):
            raise MarketDataAuthorizationError("SOURCE_ROUTE_AUTHORIZATION_DENIED")

    def _provider_request(
        self,
        *,
        benchmark_id: str,
        provider_symbol: str,
        start_at: datetime,
        end_at: datetime,
    ) -> MarketDataProviderRequest:
        """Construct the exact provider DTO only after authorizations bind."""
        query_identity = {
            "version": "risk-opendata-index-benchmark-published-v2",
            "benchmark_id": benchmark_id,
            "provider_symbol": provider_symbol,
            "dataset_id": OPENDATA_INDEX_BENCHMARK_DATASETS[benchmark_id][1],
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "policy_id": self._policy.policy_id,
            "route_id": self._route.route_id,
            "family_id": OPENDATA_INDEX_BENCHMARK_FAMILY_ID,
            "family_contract_version": OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION,
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                query_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        return MarketDataProviderRequest(
            query_fingerprint=fingerprint,
            canonical_id=f"index:{benchmark_id}",
            asset_type="index",
            provider_symbol=provider_symbol,
            market="CN-SSE",
            data_kind="bars",
            frequency="1d",
            start_at=start_at,
            end_at=end_at,
            required_fields=frozenset({"close"}),
            provider="opendata",
            adjustment="not_applicable",
            price_basis="close",
            currency=None,
            unit="point",
            source_policy_id=self._policy.policy_id,
            route_id=self._route.route_id,
            family_id=OPENDATA_INDEX_BENCHMARK_FAMILY_ID,
            family_contract_version=OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION,
            provider_endpoint=self._route.provider_endpoint,
            policy_descriptor_hash=_policy_descriptor_hash(self._policy),
            access_grant_descriptor_hash=self._grant.policy_descriptor_hash,
        )

    async def _reauthorize_after_fetch(self) -> None:
        """Recheck current principal and source rights before exposing series."""
        current_principal = await self._access.authorizer.revalidate_principal(
            principal=self._grant.principal
        )
        current_grant = await self._access.authorizer.authorize_policy(
            principal=current_principal,
            policy=self._policy,
            routes=(self._route,),
            asset_type="index",
            market="CN-SSE",
            purpose=self._grant.purpose,
        )
        if current_grant.policy_descriptor_hash != self._grant.policy_descriptor_hash:
            raise MarketDataAuthorizationError("MARKET_DATA_ACCESS_CHANGED_DURING_FETCH")


def _date_window(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    """Parse the legacy inclusive API date window as v2's half-open range."""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (OverflowError, TypeError, ValueError) as exc:
        raise OpenDataIndexBenchmarkError("invalid_benchmark_date_window") from exc
    if start.isoformat() != start_date or end.isoformat() != end_date or end < start:
        raise OpenDataIndexBenchmarkError("invalid_benchmark_date_window")
    try:
        end_exclusive = end + timedelta(days=1)
    except OverflowError as exc:
        raise OpenDataIndexBenchmarkError("invalid_benchmark_date_window") from exc
    return (
        datetime.combine(start, time.min, tzinfo=UTC),
        datetime.combine(end_exclusive, time.min, tzinfo=UTC),
    )


def _validate_snapshot_metadata(
    snapshot: Mapping[str, Any],
    *,
    dataset_id: str,
    start: date,
    end: date,
) -> None:
    """Require the full v2 published index contract and exact dated scope."""
    window = snapshot.get("window")
    quality = snapshot.get("quality")
    if (
        snapshot.get("dataset_id") != dataset_id
        or _HEX_32.fullmatch(str(snapshot.get("publication_id", ""))) is None
        or type(snapshot.get("sequence")) is not int
        or snapshot["sequence"] < 1
        or snapshot.get("schema_version") != _SCHEMA_VERSION
        or snapshot.get("semantic_version") != _SEMANTIC_VERSION
        or _HEX_64.fullmatch(str(snapshot.get("contract_sha256", ""))) is None
        or snapshot.get("source") != {"source_id": _SOURCE_ID, "source": _SOURCE_NAME}
        or snapshot.get("schema") != _SCHEMA
        or not isinstance(quality, Mapping)
        or quality.get("status") != "passed"
        or type(quality.get("issue_count")) is not int
        or quality.get("issue_count") != 0
        or snapshot.get("field_units") != _FIELD_UNITS
        or snapshot.get("field_currencies") != {}
        or snapshot.get("field_adjustments") != _FIELD_ADJUSTMENTS
        or snapshot.get("currency") is not None
        or snapshot.get("adjustment_basis") != "not_applicable"
        or snapshot.get("asset_class") != "index"
        or snapshot.get("frequency") != "1d"
        or snapshot.get("record_kind") != "time_series"
        or snapshot.get("business_key_fields") != _KEY_FIELDS
        or snapshot.get("ordering_fields") != _ORDERING_FIELDS
        or snapshot.get("storage_order") != _STORAGE_ORDER
        or snapshot.get("identity_key_encoding") != "canonical-json-array-v1"
        or snapshot.get("filter_fields") != []
        or snapshot.get("time_field") != "trade_date"
        or snapshot.get("temporal_semantics") != "business_date"
        or snapshot.get("source_available_at_field") is not None
        or snapshot.get("calendar_id") is not None
        or snapshot.get("timezone") != "Asia/Shanghai"
        or snapshot.get("pit_policy") != "unsupported"
        or snapshot.get("identity_semantics") != _IDENTITY_SEMANTICS
        or not isinstance(window, Mapping)
        or window != {"start": start.isoformat(), "end": end.isoformat(), "end_exclusive": True}
        or snapshot.get("page_size") != 1000
        or isinstance(snapshot.get("page_size"), bool)
        or type(snapshot.get("record_count")) is not int
        or not 0 <= snapshot["record_count"] <= 50_000
        or _HEX_64.fullmatch(str(snapshot.get("selection_sha256", ""))) is None
        or _HEX_64.fullmatch(str(snapshot.get("content_sha256", ""))) is None
        or not _aware_timestamp(snapshot.get("as_of"))
        or not _aware_timestamp(snapshot.get("created_at"))
        or not _aware_timestamp(snapshot.get("expires_at"))
    ):
        raise OpenDataIndexBenchmarkError("opendata_snapshot_contract_mismatch")
    try:
        if _aware_timestamp_value(snapshot["expires_at"]) <= _aware_timestamp_value(
            snapshot["created_at"]
        ):
            raise OpenDataIndexBenchmarkError("opendata_snapshot_contract_mismatch")
    except (OverflowError, TypeError, ValueError) as exc:
        raise OpenDataIndexBenchmarkError("opendata_snapshot_contract_mismatch") from exc


def _validate_coverage(
    coverage_response: Mapping[str, Any],
    *,
    snapshot: Mapping[str, Any],
    dataset_id: str,
    start: date,
    end: date,
) -> None:
    """Require independent complete business-history evidence for this scope."""
    coverage = coverage_response.get("coverage")
    if (
        coverage_response.get("dataset_id") != dataset_id
        or coverage_response.get("publication_id") != snapshot.get("publication_id")
        or coverage_response.get("contract_sha256") != snapshot.get("contract_sha256")
        or not isinstance(coverage, Mapping)
        or not has_complete_business_history_coverage(
            coverage,
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
        )
    ):
        raise OpenDataIndexBenchmarkError("opendata_coverage_unavailable")


def _records_from_snapshot(
    records: tuple[Mapping[str, Any], ...],
    *,
    snapshot: Mapping[str, Any],
    provider_symbol: str,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Validate exact index identity, business keys, dates, and close values."""
    output: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    previous_date: str | None = None
    snapshot_sequence = snapshot["sequence"]
    snapshot_publication = snapshot["publication_id"]
    for row in records:
        if not isinstance(row, Mapping) or set(row) != _ROW_FIELDS:
            raise OpenDataIndexBenchmarkError("opendata_record_identity_invalid")
        business_date = row.get("business_date")
        payload = row.get("payload")
        if (
            row.get("dataset_id") != snapshot.get("dataset_id")
            or type(row.get("revision")) is not int
            or row["revision"] < 1
            or type(row.get("publication_sequence")) is not int
            or not 1 <= row["publication_sequence"] <= snapshot_sequence
            or _HEX_32.fullmatch(str(row.get("publication_id", ""))) is None
            or (
                row["publication_sequence"] == snapshot_sequence
                and row["publication_id"] != snapshot_publication
            )
            or not isinstance(row.get("business_key"), str)
            or not isinstance(business_date, str)
            or not isinstance(payload, Mapping)
            or set(payload) != set(_FIELD_NAMES)
            or payload.get("symbol") != provider_symbol
            or payload.get("trade_date") != business_date
            or _HEX_64.fullmatch(str(row.get("record_hash", ""))) is None
        ):
            raise OpenDataIndexBenchmarkError("opendata_record_identity_invalid")
        try:
            parsed_date = date.fromisoformat(business_date)
        except ValueError as exc:
            raise OpenDataIndexBenchmarkError("opendata_record_date_invalid") from exc
        if (
            parsed_date.isoformat() != business_date
            or not start <= parsed_date < end
            or business_date in seen_dates
            or (previous_date is not None and business_date <= previous_date)
            or row["business_key"]
            != json.dumps(
                [provider_symbol, business_date],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        ):
            raise OpenDataIndexBenchmarkError("opendata_record_date_invalid")
        for field_name in ("event_at", "observed_at", "source_published_at", "available_at"):
            value = row.get(field_name)
            if value is not None and not _aware_timestamp(value):
                raise OpenDataIndexBenchmarkError("opendata_record_timestamp_invalid")
        numeric_values: dict[str, float] = {}
        for field_name in ("open", "high", "low", "close", "volume"):
            value = payload.get(field_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise OpenDataIndexBenchmarkError("opendata_record_value_invalid")
            number = float(value)
            if not math.isfinite(number) or number < 0 or (field_name != "volume" and number == 0):
                raise OpenDataIndexBenchmarkError("opendata_record_value_invalid")
            numeric_values[field_name] = number
        if numeric_values["high"] < max(
            numeric_values["open"], numeric_values["close"], numeric_values["low"]
        ) or numeric_values["low"] > min(
            numeric_values["open"], numeric_values["close"], numeric_values["high"]
        ):
            raise OpenDataIndexBenchmarkError("opendata_record_ohlc_invalid")
        output.append({"date": business_date, "close": payload["close"]})
        seen_dates.add(business_date)
        previous_date = business_date
    return output


def _aware_timestamp(value: object) -> bool:
    """Check an ISO timestamp without accepting naive or malformed values."""
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
    return parsed.astimezone(UTC)


__all__ = [
    "OPENDATA_INDEX_DAILY_POLICY_ID",
    "OPENDATA_INDEX_DAILY_ROUTE_ID",
    "OpenDataIndexBenchmarkError",
    "OpenDataIndexBenchmarkReader",
]
