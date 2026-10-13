"""Canonical local persistence for the Iteration 197 market-data path.

The store is intentionally provider-neutral and append-only.  It writes only
the normalized ``md_*`` evidence tables, never a legacy AkShare warehouse
table, and it makes every local read explicit about its point-in-time cutoff.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from types import MappingProxyType

from sqlalchemy import Select, and_, func, select, tuple_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.asset_research import AssetDataSourceRegistry
from app.models.data_governance import DgProvider
from app.models.market_data_platform import (
    CALENDAR_SOURCE_GOVERNANCE_STATE_VERIFIED,
    SOURCE_AUTHORIZATION_STATE_UNVERIFIED_COMPATIBILITY,
    SOURCE_AUTHORIZATION_STATE_VERIFIED,
    MdB2CompletenessManifestEntry,
    MdB2CompletenessReceipt,
    MdCalendarEvent,
    MdCalendarSnapshot,
    MdDataSeries,
    MdObservationRevision,
    MdPublication,
    MdPublicationReleaseHold,
    MdSourcePayload,
    MdSourceSnapshot,
    MdSourceSnapshotPayloadRef,
    calendar_coverage_descriptor,
    calendar_coverage_event_key,
)
from app.services.market_data import store_calendar as _store_calendar
from app.services.market_data import store_calendar_grid as _store_calendar_grid
from app.services.market_data import store_evidence as _store_evidence
from app.services.market_data import store_evidence_receipts as _store_evidence_receipts
from app.services.market_data import store_persistence as _store_persistence
from app.services.market_data import store_projection as _store_projection
from app.services.market_data.access import MarketDataSourceAuthorization
from app.services.market_data.coverage import (
    CalendarSnapshot,
    CalendarStatus,
    EventKey,
    Observation,
    ObservationQuality,
    TimeWindow,
)
from app.services.market_data.fetch_lease import (
    MarketDataFetchLeaseError,
    MarketDataFetchLeaseHandle,
    MarketDataFetchLeaseManager,
    assert_fetch_lease_held_in_transaction,
)
from app.services.market_data.field_quality import (
    FIELD_QUALITY_POLICY_VERSION,
    is_usable_field_value,
    normalize_provider_fields,
)
from app.services.market_data.multi_record import (
    SINGLE_RECORD_SEMANTIC_KEY_CANONICAL_JSON,
    SINGLE_RECORD_SEMANTIC_KEY_SHA256,
    B2ReportSelector,
    B2SliceSelector,
    SemanticRecordKey,
    normalize_semantic_record_key,
    single_record_semantic_key,
)
from app.services.market_data.multi_record_contracts import (
    B2FamilyContractError,
    normalize_b2_record_dimensions,
)
from app.services.market_data.multi_record_evidence import (
    B2CompletenessEvidenceError,
    DurableB2CompletenessEvidence,
    assert_b2_source_event_manifest_integrity,
    durable_b2_completeness_evidence_from_receipt,
)
from app.services.market_data.providers import (
    ProviderFetchResult,
    ProviderMarketObservation,
    SharedSourcePayloadSegment,
)
from app.services.market_data.publication import (
    PUBLICATION_B2_COMPLETENESS_RECEIPT,
    PUBLICATION_CALENDAR_SNAPSHOT,
    PUBLICATION_RELEASE_HOLD_STATE_DEFERRED,
    PUBLICATION_RELEASE_HOLD_STATE_PROMOTED,
    PUBLICATION_RELEASE_HOLD_WORKFLOW_LEGACY_STOCK_DAILY_IMPORT,
    PUBLICATION_SOURCE_SNAPSHOT,
    MarketDataDeferredPublicationIntent,
    MarketDataDeferredPublicationPromotion,
    MarketDataPublicationError,
    MarketDataPublicationManager,
    MarketDataVisibilityAnchor,
)
from app.services.market_data.query_resolution import ResolvedMarketDataQueryContext
from app.services.market_data.store_calendar import (
    _calendar_coverage_window as _calendar_coverage_window,
)
from app.services.market_data.store_calendar import (
    _compose_calendar_segments as _compose_calendar_segments,
)
from app.services.market_data.store_calendar import (
    _composed_calendar_version as _composed_calendar_version,
)
from app.services.market_data.store_calendar import (
    _parse_timestamp as _parse_timestamp,
)
from app.services.market_data.store_calendar import (
    _require_aware_utc as _require_aware_utc,
)
from app.services.market_data.store_calendar import (
    _require_calendar_governance_tokens as _require_calendar_governance_tokens,
)
from app.services.market_data.store_calendar import (
    _stored_utc as _stored_utc,
)
from app.services.market_data.store_calendar import (
    _unknown_calendar_trading_day_events as _unknown_calendar_trading_day_events,
)
from app.services.market_data.store_calendar import (
    _unknown_timezone as _unknown_timezone,
)
from app.services.market_data.store_calendar import (
    _verified_calendar_source_registry_id as _verified_calendar_source_registry_id,
)
from app.services.market_data.store_calendar import (
    _window_covers as _window_covers,
)
from app.services.market_data.store_calendar import (
    _window_intersection as _window_intersection,
)
from app.services.market_data.store_evidence import (
    _assert_source_authorization_matches_registry as _assert_source_authorization_matches_registry,
)
from app.services.market_data.store_evidence import (
    _normalize_unverified_compatibility_reason as _normalize_unverified_compatibility_reason,
)
from app.services.market_data.store_evidence import (
    _normalized_registry_authorization_token as _normalized_registry_authorization_token,
)
from app.services.market_data.store_evidence import (
    _normalized_source_authorization_provenance as _normalized_source_authorization_provenance,
)
from app.services.market_data.store_evidence import (
    _parse_authorization_timestamp as _parse_authorization_timestamp,
)
from app.services.market_data.store_evidence import (
    _parse_optional_authorization_timestamp as _parse_optional_authorization_timestamp,
)
from app.services.market_data.store_evidence import (
    _registry_authorization_fields as _registry_authorization_fields,
)
from app.services.market_data.store_evidence import (
    _registry_authorization_tokens as _registry_authorization_tokens,
)
from app.services.market_data.store_evidence import (
    _require_authorization_lower as _require_authorization_lower,
)
from app.services.market_data.store_evidence import (
    _require_authorization_tokens as _require_authorization_tokens,
)
from app.services.market_data.store_evidence import (
    _require_authorization_upper as _require_authorization_upper,
)
from app.services.market_data.store_evidence import (
    _require_optional_utc_authorization_timestamp as _require_optional_utc_authorization_timestamp,
)
from app.services.market_data.store_evidence import (
    _require_persisted_authorization_tokens as _require_persisted_authorization_tokens,
)
from app.services.market_data.store_evidence import (
    _require_utc_authorization_timestamp as _require_utc_authorization_timestamp,
)
from app.services.market_data.store_evidence import (
    _source_authorization_jurisdiction_allows as _source_authorization_jurisdiction_allows,
)
from app.services.market_data.store_evidence import (
    _source_authorization_receipt_purpose_allows_read as _source_authorization_receipt_purpose_allows_read,
)
from app.services.market_data.store_evidence import (
    _verified_source_authorization_registry_id as _verified_source_authorization_registry_id,
)
from app.services.market_data.store_evidence_receipts import (
    _promoted_legacy_import_publication_receipt as _promoted_legacy_import_publication_receipt,
)
from app.services.market_data.store_evidence_receipts import (
    _provider_request_matches_context as _provider_request_matches_context,
)
from app.services.market_data.store_evidence_receipts import (
    _require_provider_request_id as _require_provider_request_id,
)
from app.services.market_data.store_evidence_receipts import (
    _reread_deferred_legacy_import_observation as _reread_deferred_legacy_import_observation,
)
from app.services.market_data.store_evidence_receipts import (
    _reread_legacy_stock_daily_persisted_evidence as _reread_legacy_stock_daily_persisted_evidence,
)
from app.services.market_data.store_evidence_receipts import (
    _validated_provider_request_evidence as _validated_provider_request_evidence,
)
from app.services.market_data.store_persistence import (
    _coordinate_chunks as _coordinate_chunks,
)
from app.services.market_data.store_persistence import (
    _revision_number_current_read_statement as _revision_number_current_read_statement,
)
from app.services.market_data.store_persistence import (
    _series_lookup_statement as _series_lookup_statement,
)
from app.services.market_data.store_persistence_validation import (
    _assert_shared_source_payload_matches as _assert_shared_source_payload_matches,
)
from app.services.market_data.store_persistence_validation import (
    _provider_observation_semantic_record_key as _provider_observation_semantic_record_key,
)
from app.services.market_data.store_persistence_validation import (
    _validate_provider_fetch as _validate_provider_fetch,
)
from app.services.market_data.store_persistence_validation import (
    _validate_shared_source_payload as _validate_shared_source_payload,
)
from app.services.market_data.store_projection import (
    _decode_local_revision as _decode_local_revision,
)
from app.services.market_data.store_projection import (
    _observation_revision_identity_sha256 as _observation_revision_identity_sha256,
)
from app.services.market_data.store_projection import (
    _persisted_semantic_record_key as _persisted_semantic_record_key,
)
from app.services.market_data.store_projection import (
    _publication_is_visible_at_anchor as _publication_is_visible_at_anchor,
)
from app.services.market_data.store_projection import (
    _record_revision_output_sort_key as _record_revision_output_sort_key,
)
from app.services.market_data.store_projection import (
    _revision_is_usable_for_fields as _revision_is_usable_for_fields,
)
from app.services.market_data.store_projection import (
    _revision_sort_key as _revision_sort_key,
)
from app.services.market_data.store_projection import (
    _revision_source_available_at as _revision_source_available_at,
)
from app.services.market_data.store_projection import (
    _verified_revision_source_available_at as _verified_revision_source_available_at,
)

__all__ = (
    "AssetDataSourceRegistry",
    "AsyncSession",
    "Awaitable",
    "B2CompletenessEvidenceError",
    "B2FamilyContractError",
    "B2ReportSelector",
    "B2SliceSelector",
    "CALENDAR_SOURCE_GOVERNANCE_STATE_VERIFIED",
    "CalendarSnapshot",
    "CalendarStatus",
    "CalendarTradingDayEvent",
    "CalendarTradingDayEvents",
    "Callable",
    "Decimal",
    "DeferredProviderFetch",
    "DgProvider",
    "DurableB2CompletenessEvidence",
    "EventKey",
    "FIELD_QUALITY_POLICY_VERSION",
    "IntegrityError",
    "LocalObservationRevision",
    "MAX_SOURCE_PAYLOAD_BYTES",
    "Mapping",
    "MappingProxyType",
    "MarketDataDeferredPublicationIntent",
    "MarketDataDeferredPublicationPromotion",
    "MarketDataFetchLeaseError",
    "MarketDataFetchLeaseHandle",
    "MarketDataFetchLeaseManager",
    "MarketDataPublicationError",
    "MarketDataPublicationManager",
    "MarketDataSourceAuthorization",
    "MarketDataStore",
    "MarketDataStoreError",
    "MarketDataVisibilityAnchor",
    "MdB2CompletenessManifestEntry",
    "MdB2CompletenessReceipt",
    "MdCalendarEvent",
    "MdCalendarSnapshot",
    "MdDataSeries",
    "MdObservationRevision",
    "MdPublication",
    "MdPublicationReleaseHold",
    "MdSourcePayload",
    "MdSourceSnapshot",
    "MdSourceSnapshotPayloadRef",
    "NORMALIZATION_VERSION",
    "Observation",
    "ObservationQuality",
    "OperationalError",
    "PUBLICATION_B2_COMPLETENESS_RECEIPT",
    "PUBLICATION_CALENDAR_SNAPSHOT",
    "PUBLICATION_RELEASE_HOLD_STATE_DEFERRED",
    "PUBLICATION_RELEASE_HOLD_STATE_PROMOTED",
    "PUBLICATION_RELEASE_HOLD_WORKFLOW_LEGACY_STOCK_DAILY_IMPORT",
    "PUBLICATION_SOURCE_SNAPSHOT",
    "PersistedProviderFetch",
    "ProviderFetchResult",
    "ProviderMarketObservation",
    "QUALITY_POLICY_VERSION",
    "ResolvedMarketDataQueryContext",
    "SERIES_SEMANTIC_VERSION",
    "SINGLE_RECORD_SEMANTIC_KEY_CANONICAL_JSON",
    "SINGLE_RECORD_SEMANTIC_KEY_SHA256",
    "SOURCE_AUTHORIZATION_STATE_UNVERIFIED_COMPATIBILITY",
    "SOURCE_AUTHORIZATION_STATE_VERIFIED",
    "Select",
    "SemanticRecordKey",
    "Sequence",
    "SeriesIdentity",
    "SharedSourcePayloadSegment",
    "TimeWindow",
    "UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT",
    "UNVERIFIED_COMPATIBILITY_REASON_OPERATOR_RECOVERY",
    "UTC",
    "aliased",
    "and_",
    "assert_b2_source_event_manifest_integrity",
    "assert_fetch_lease_held_in_transaction",
    "calendar_coverage_descriptor",
    "calendar_coverage_event_key",
    "dataclass",
    "date",
    "datetime",
    "durable_b2_completeness_evidence_from_receipt",
    "func",
    "hashlib",
    "is_usable_field_value",
    "json",
    "math",
    "normalize_b2_record_dimensions",
    "normalize_provider_fields",
    "normalize_semantic_record_key",
    "select",
    "single_record_semantic_key",
    "timezone",
    "tuple_",
)

UTC = timezone.utc
SERIES_SEMANTIC_VERSION = "market-data-series-v1"
QUALITY_POLICY_VERSION = FIELD_QUALITY_POLICY_VERSION
NORMALIZATION_VERSION = "market-data-store-v1"
_OBSERVATION_REVISION_CONTRACT_V1 = "market-data-observation-revision-v1"
_OBSERVATION_REVISION_CONTRACT_V2 = "market-data-observation-revision-v2"
_OBSERVATION_REVISION_CONTRACT_V3 = "market-data-observation-revision-v3"
_MAX_PROVIDER_OBSERVATIONS = 50_000
_REVISION_COORDINATE_QUERY_CHUNK_SIZE = 400
_MAX_CURRENT_REVISION_ROWS_PER_CHUNK = 10_000
MAX_SOURCE_PAYLOAD_BYTES = 10 * 1024 * 1024
_MAX_NORMALIZED_FIELDS_BYTES = 10 * 1024 * 1024
_MAX_NORMALIZED_RECORD_IDENTITIES_BYTES = 10 * 1024 * 1024
_SOURCE_AUTHORIZATION_VERSION = "market-data-source-authorization-v1"
_SOURCE_AUTHORIZATION_APPROVED_LICENSES = frozenset(
    {
        "APPROVED",
        "LICENSED",
        "MARKET_DATA_APPROVED",
        "PUBLIC",
        "RESEARCH_APPROVED",
    }
)
_SOURCE_AUTHORIZATION_ALLOWED_USES: Mapping[str, frozenset[str]] = {
    "display": frozenset({"DISPLAY", "MARKET_DATA_DISPLAY", "MARKET_DATA_READ"}),
    "research": frozenset({"RESEARCH", "RESEARCH_ONLY", "DERIVED_RESEARCH"}),
    "research_cache_fill": frozenset({"RESEARCH", "RESEARCH_ONLY", "DERIVED_RESEARCH"}),
    "backtest": frozenset({"BACKTEST", "BACKTEST_ONLY"}),
}
# A cache-fill receipt records the narrowly scoped authorization that allowed
# collection.  It may subsequently satisfy a strict research *read* only when
# the caller has independently passed current research authorization.  It is
# deliberately not reusable for display, backtest, or binding purposes.
_SOURCE_AUTHORIZATION_RECEIPT_PURPOSES_BY_QUERY_PURPOSE: Mapping[str, frozenset[str]] = {
    "display": frozenset({"display"}),
    "research": frozenset({"research", "research_cache_fill"}),
    "research_cache_fill": frozenset({"research_cache_fill"}),
    "backtest": frozenset({"backtest"}),
}
_SOURCE_AUTHORIZATION_READABLE_REDISTRIBUTION_POLICIES = frozenset(
    {"ALLOWED", "INTERNAL_ONLY", "NO_REDISTRIBUTION"}
)
_SOURCE_AUTHORIZATION_PROHIBITED_RETENTION_POLICIES = frozenset(
    {"", "DENIED", "EXPIRED", "PROHIBITED", "UNKNOWN"}
)
_SOURCE_AUTHORIZATION_PROVENANCE_FIELDS = frozenset(
    {
        "source_registry_id",
        "registry_updated_at",
        "asset_type",
        "market",
        "purpose",
        "license_status",
        "allowed_uses",
        "jurisdictions",
        "effective_from",
        "effective_to",
        "retention_policy",
        "retention_expires_at",
        "redistribution_policy",
        "principal_scope",
        "tenant_scope",
        "entitlement_revision",
        "decision",
        "descriptor_hash",
    }
)
UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT = "legacy_import"
UNVERIFIED_COMPATIBILITY_REASON_OPERATOR_RECOVERY = "operator_recovery"
_UNVERIFIED_COMPATIBILITY_REASONS = frozenset(
    {
        UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
        UNVERIFIED_COMPATIBILITY_REASON_OPERATOR_RECOVERY,
    }
)
_UNVERIFIED_COMPATIBILITY_PROVENANCE_VERSION = "market-data-unverified-source-write-v1"
_CALENDAR_SOURCE_GOVERNANCE_VERSION = "market-data-calendar-source-governance-v1"
# These contracts remain unconfigured at every public/API/provider boundary.
# The lower-level Store nevertheless knows that a future approved writer for
# one of them must carry a record dimension set; silently persisting a
# singleton would make an incomplete B2 receipt look like a complete fact.
_MULTI_RECORD_FAMILY_IDS = frozenset(
    {
        "futures.inventory",
        "option.derivative",
        "option.risk_surface",
        "crypto.cme_position",
    }
)


def _utc_now() -> datetime:
    """Return the trusted local receipt clock used for point-in-time evidence."""
    return datetime.now(UTC)


class MarketDataStoreError(ValueError):
    """Stable failure code for canonical local market-data persistence."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SeriesIdentity:
    """Server-derived content identity of a generic normalized data series."""

    semantic_key_sha256: str
    semantic_identity: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PersistedProviderFetch:
    """Identifiers and quality counts created for one immutable provider receipt."""

    series_id: str
    source_snapshot_id: str
    observation_revision_ids: tuple[str, ...]
    passing_observation_count: int
    failed_observation_count: int
    received_at: datetime


@dataclass(frozen=True, slots=True)
class DeferredProviderFetch:
    """A durable-but-hidden provider write awaiting explicit attestation.

    This DTO intentionally does not expose a publication/visibility time.  A
    future legacy adapter must validate the staged candidate and ask the
    publication manager for a guarded promotion before it can obtain a normal
    ``PersistedProviderFetch`` usable by any local-first query path.
    """

    series_id: str
    source_snapshot_id: str
    publication_id: str
    observation_revision_ids: tuple[str, ...]
    passing_observation_count: int
    failed_observation_count: int
    local_received_at: datetime
    intent: MarketDataDeferredPublicationIntent


@dataclass(frozen=True, slots=True)
class _DeferredLegacyImportObservation:
    """An exact, unpublished revision visible only to the legacy writer.

    This is intentionally private to :class:`MarketDataStore`.  It is not a
    query result and cannot be selected by public local reads: the enclosing
    receipt still has an active ``DEFERRED`` release hold.
    """

    revision_id: str
    source_snapshot_id: str
    event_at: datetime
    available_at: datetime
    source_available_at: datetime
    quality: ObservationQuality
    fields: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _LegacyStockDailyPersistedEvidence:
    """Persisted-only legacy receipt evidence for the isolated harness.

    This type is intentionally private.  It is populated only after Store has
    reread the exact held/promoted source snapshot, its content-addressed
    source batch, and its release hold.  It is not a product local-read DTO.
    """

    source_snapshot_id: str
    source_id: str
    endpoint_version: str
    source_observed_at: datetime
    source_authorization_state: str
    unverified_compatibility: Mapping[str, object]
    request_json: Mapping[str, object]
    provider_request: Mapping[str, object]
    resolved_query: Mapping[str, object]
    payload_manifest: Mapping[str, object]
    receipt_payload: Mapping[str, object]
    source_batch: Mapping[str, object]
    legacy_import: Mapping[str, object]
    source_payload_content_sha256: str
    source_payload_format: str
    source_payload_bytes: int
    fetch_lease_key_sha256: str
    fetch_lease_fence_token: int


@dataclass(frozen=True, slots=True)
class _DeferredLegacyImportCandidate:
    """A bounded reread of exactly one deferred legacy-import receipt."""

    staged: DeferredProviderFetch
    observations: tuple[_DeferredLegacyImportObservation, ...]
    evidence: _LegacyStockDailyPersistedEvidence


@dataclass(frozen=True, slots=True)
class _PromotedLegacyImportPublicationReceipt:
    """The sealed receipt a private writer needs to construct audit evidence."""

    publication_id: str
    source_snapshot_id: str
    visible_at: datetime
    visibility_sequence: int


@dataclass(frozen=True, slots=True)
class _PromotedLegacyImportCandidate:
    """Private reread of one promoted, still-unverified fixture receipt."""

    staged: DeferredProviderFetch
    observations: tuple[_DeferredLegacyImportObservation, ...]
    evidence: _LegacyStockDailyPersistedEvidence
    publication: _PromotedLegacyImportPublicationReceipt


@dataclass(frozen=True, slots=True)
class _LegacyStockDailyReread:
    """Internal common result for deferred and promoted harness rereads."""

    observations: tuple[_DeferredLegacyImportObservation, ...]
    evidence: _LegacyStockDailyPersistedEvidence
    publication: _PromotedLegacyImportPublicationReceipt | None


@dataclass(frozen=True, slots=True)
class LocalObservationRevision:
    """One selected local observation revision with source provenance.

    ``source_available_at`` is the upstream provider's declared availability,
    distinct from ``available_at``: the latter is the locally trusted receipt
    time used for PIT eligibility.  Store reads populate and validate the
    former only when a V2 or V3 revision identity seals it. Historical V1 rows and
    older synthetic DTO callers expose ``None`` instead; provenance-sensitive
    consumers must reject that value rather than infer it from local receipt
    time.
    """

    revision_id: str
    source_snapshot_id: str
    event_at: datetime
    available_at: datetime
    committed_at: datetime
    visible_at: datetime
    visibility_sequence: int
    revision_number: int
    quality: ObservationQuality
    fields: Mapping[str, object]
    source_available_at: datetime | None = None
    # Synthetic legacy test callers and pre-B2 compatibility adapters retain
    # the fixed singleton unless an actual Store read supplies a validated key.
    semantic_record_key: str = SINGLE_RECORD_SEMANTIC_KEY_CANONICAL_JSON
    semantic_record_key_sha256: str = SINGLE_RECORD_SEMANTIC_KEY_SHA256

    def as_coverage_observation(self, context: ResolvedMarketDataQueryContext) -> Observation:
        """Convert the persisted row to the pure DTO consumed by coverage planning."""
        return Observation(
            identity=context.coverage_identity,
            event_key=EventKey(self.event_at),
            fields=self.fields,
            quality=self.quality,
            available_at=self.available_at,
        )


@dataclass(frozen=True, slots=True)
class CalendarTradingDayEvent:
    """One exact published daily-grid EventKey with its source trading date."""

    trading_date: date
    event_key: EventKey

    def __post_init__(self) -> None:
        if not isinstance(self.trading_date, date) or isinstance(self.trading_date, datetime):
            raise TypeError("trading_date must be a date")
        if not isinstance(self.event_key, EventKey):
            raise TypeError("event_key must be an EventKey")


@dataclass(frozen=True, slots=True)
class CalendarTradingDayEvents:
    """A source-authorized, PIT-frozen date-to-EventKey calendar projection.

    A legacy importer may use ``trading_date`` only as a label.  The exact
    EventKey, snapshot identity, visibility anchor, and coverage evidence stay
    attached so a later writer cannot replace calendar semantics by a local
    date/time conversion.
    """

    calendar_code: str
    calendar_version: str
    data_kind: str
    frequency: str
    calendar_snapshot_id: str | None
    timezone_name: str
    coverage_window: TimeWindow | None
    visibility_anchor: MarketDataVisibilityAnchor
    status: CalendarStatus
    reason: str | None
    events: tuple[CalendarTradingDayEvent, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.calendar_code, field_name="calendar_code", maximum=128)
        _require_text(self.calendar_version, field_name="calendar_version", maximum=128)
        _require_text(self.data_kind, field_name="data_kind", maximum=64)
        _require_text(self.frequency, field_name="frequency", maximum=16)
        _require_text(self.timezone_name, field_name="timezone_name", maximum=128)
        if not isinstance(self.visibility_anchor, MarketDataVisibilityAnchor):
            raise TypeError("visibility_anchor must be a MarketDataVisibilityAnchor")
        status = CalendarStatus(self.status)
        if self.coverage_window is not None and not isinstance(self.coverage_window, TimeWindow):
            raise TypeError("coverage_window must be a TimeWindow")
        if self.calendar_snapshot_id is not None:
            _require_text(
                self.calendar_snapshot_id,
                field_name="calendar_snapshot_id",
                maximum=36,
            )
        if self.reason is not None:
            _require_text(self.reason, field_name="reason", maximum=128)
        events = tuple(self.events)
        if any(not isinstance(item, CalendarTradingDayEvent) for item in events):
            raise TypeError("events must contain CalendarTradingDayEvent values")
        ordered_events = tuple(sorted(events, key=lambda item: item.trading_date))
        if len({item.trading_date for item in ordered_events}) != len(ordered_events):
            raise ValueError("trading dates must map one-to-one to EventKeys")
        if len({item.event_key for item in ordered_events}) != len(ordered_events):
            raise ValueError("EventKeys must map one-to-one to trading dates")
        if status is CalendarStatus.KNOWN:
            if (
                self.calendar_snapshot_id is None
                or self.coverage_window is None
                or self.reason is not None
            ):
                raise ValueError("known trading-day evidence requires snapshot and coverage")
        elif (
            ordered_events
            or self.calendar_snapshot_id is not None
            or self.coverage_window is not None
        ):
            raise ValueError("unknown trading-day evidence cannot expose partial calendar data")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "events", ordered_events)


@dataclass(frozen=True, slots=True)
class _ValidatedProviderObservation:
    """Validated, JSON-safe provider record prepared before any database write."""

    event_at: datetime
    available_at: datetime
    source_available_at: datetime
    fields: Mapping[str, object]
    fields_sha256: str
    quality: ObservationQuality
    quality_details: Mapping[str, object]
    semantic_record_key: SemanticRecordKey


@dataclass(frozen=True, slots=True)
class _ValidatedProviderFetch:
    """Validated source receipt data prepared before opening a write savepoint."""

    raw_payload: Mapping[str, object]
    payload_sha256: str
    observations: tuple[_ValidatedProviderObservation, ...]
    provider_request_id: str
    provider_request_fingerprint_sha256: str
    query_fingerprint_sha256: str
    shared_source_payload: _ValidatedSharedSourcePayload | None


@dataclass(frozen=True, slots=True)
class _ValidatedSharedSourcePayload:
    """An integrity-checked content-addressed wide-provider response."""

    content_sha256: str
    payload_format: str
    payload_role: str
    payload_bytes: int
    canonical_payload_bytes: bytes
    receipt_payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _ValidatedSourceAuthorization:
    """Persistence-ready source trust state detached from caller prose."""

    state: str
    descriptor_sha256: str | None
    provenance: Mapping[str, object]


class MarketDataStore:
    """Write and read normalized market observations through one async session.

    Read-only methods use the request session normally. A provider receipt is
    different: it owns a two-transaction visibility protocol so a strict
    cutoff can never treat a pre-commit flush timestamp as durable evidence.
    The receipt and its pending publication are committed first, then a
    separate transaction publishes their post-commit visibility instant.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._clock = clock or _utc_now
        self._clock_is_test_override = clock is not None
        self._publications = MarketDataPublicationManager(
            db,
            clock=self._clock,
            fetch_lease_clock=self._clock if self._clock_is_test_override else None,
        )

    def fetch_lease_manager(self) -> MarketDataFetchLeaseManager:
        """Return a request-session lease manager for real local-first fills."""
        return MarketDataFetchLeaseManager(
            self._db,
            # Lease takeover must use a shared database clock in production;
            # deterministic store clocks remain an explicit test seam.
            clock=self._clock if self._clock_is_test_override else None,
        )

    async def close_transaction_before_provider_io(self) -> None:
        """End request-local database work before an adapter can use the network.

        Local reads and post-fetch authorization checks auto-begin SQLAlchemy
        transactions, including ``FOR UPDATE`` source-registry checks.  The
        query service owns this session and its persistence protocol commits
        every supported write itself, so an outstanding transaction here is
        only a read/authorization boundary that must be released before a
        fallback provider call.  Refuse to discard caller-staged ORM changes
        rather than silently rolling them back.
        """
        if not self._db.in_transaction():
            return
        if self._db.new or self._db.dirty or self._db.deleted:
            raise MarketDataStoreError("PROVIDER_IO_TRANSACTION_DIRTY")
        try:
            await self._db.rollback()
        except OperationalError as exc:
            raise MarketDataStoreError("PROVIDER_IO_TRANSACTION_RESET_FAILED") from exc

    @staticmethod
    def series_identity(context: ResolvedMarketDataQueryContext) -> SeriesIdentity:
        """Derive the stable identity shared by every window of one series.

        Request bounds, pagination, projection fields, consistency mode and
        knowledge cutoff are deliberately excluded.  Those describe one read
        or fetch operation, not the economic content of the resulting series.
        """
        _assert_context_integrity(context)
        coverage = context.coverage_identity
        semantic_identity: dict[str, object] = {
            "series_contract_version": SERIES_SEMANTIC_VERSION,
            "dataset_id": context.storage.dataset_id,
            "dataset_code": coverage.dataset_code,
            "canonical_id": coverage.canonical_id,
            "asset_type": coverage.asset_type,
            "instrument_metadata_version": coverage.instrument_metadata_version,
            "data_kind": coverage.data_kind,
            "frequency": coverage.frequency,
            "market": coverage.market,
            "source_policy_id": coverage.source_policy_id,
            "adjustment": coverage.adjustment,
            "price_basis": coverage.price_basis,
            "currency": coverage.currency,
            "unit": coverage.unit,
            "family_id": coverage.family_id,
            "family_contract_version": coverage.family_contract_version,
        }
        canonical_identity = _canonical_json(semantic_identity, field_name="series identity")
        return SeriesIdentity(
            semantic_key_sha256=_sha256(canonical_identity),
            semantic_identity=MappingProxyType(semantic_identity),
        )

    async def get_series(self, context: ResolvedMarketDataQueryContext) -> MdDataSeries | None:
        """Return an existing exact series, failing closed on a hash collision."""
        identity = self.series_identity(context)
        return await self._find_series(identity, context)

    async def get_or_create_series(self, context: ResolvedMarketDataQueryContext) -> MdDataSeries:
        """Find or create an exact series without trusting a hash by itself."""
        _assert_writable_context(context)
        identity = self.series_identity(context)
        existing = await self._find_series(identity, context)
        if existing is not None:
            return existing

        candidate = MdDataSeries(
            dataset_id=context.storage.dataset_id,
            canonical_id=context.query.canonical_id,
            data_kind=context.query.data_kind,
            frequency=context.query.frequency,
            semantic_key_sha256=identity.semantic_key_sha256,
            semantic_identity_json=dict(identity.semantic_identity),
        )
        try:
            async with self._db.begin_nested():
                self._db.add(candidate)
                await self._db.flush()
        except IntegrityError as exc:
            # A competing writer may have committed while this session waited
            # on the unique index. The first ordinary lookup can be frozen at
            # an older MySQL REPEATABLE READ snapshot, so recovery must use a
            # locking/current read rather than repeat that stale lookup.
            existing = await self._find_series(identity, context, for_update=True)
            if existing is None:
                raise MarketDataStoreError("SERIES_WRITE_FAILED") from exc
            return existing
        except OperationalError as exc:
            # SQLite has no row-level FOR UPDATE.  Its write lock can reject a
            # concurrent insert rather than wait, so expose a retryable typed
            # conflict instead of leaking a driver-specific exception.
            raise MarketDataStoreError("SERIES_WRITE_CONFLICT") from exc
        return candidate

    async def persist_provider_result(
        self,
        context: ResolvedMarketDataQueryContext,
        result: ProviderFetchResult,
        *,
        received_at: datetime | None = None,
        source_authorization: MarketDataSourceAuthorization | None = None,
        unverified_compatibility_reason: str | None = None,
        fetch_lease: MarketDataFetchLeaseHandle | None = None,
        deferred_intent: MarketDataDeferredPublicationIntent | None = None,
    ) -> PersistedProviderFetch | DeferredProviderFetch:
        """Append one provider receipt and its normalized observation revisions.

        Input validation completes before any evidence row is added. The
        source snapshot, revisions and a pending publication receipt share a
        savepoint. After that transaction commits, a second transaction records
        a trusted visibility instant; an interrupted publication stays hidden.

        V2 provider writes require a registry-validated structured source
        authorization.  Controlled historical import/recovery callers may
        instead provide one of the explicit compatibility reasons; their
        receipt is durably tagged as unverified and is excluded from every
        current-authorized local read.

        When a cross-worker fetch lease is supplied, the owner/fence predicate
        is renewed in both the immutable-fact transaction and the separate
        publication transaction.  The provider call has already completed by
        this point, so neither short database transaction spans external I/O.

        ``deferred_intent`` is a deliberately narrow legacy-import seam.  It
        stores the facts and a durable release hold in transaction A, then
        returns without creating a visibility receipt.  Generic recovery and
        generic publishing reject the held receipt; callers must use the
        explicit guarded promotion API after their private verification.
        """
        return await _store_persistence.persist_provider_result(
            self,
            context,
            result,
            received_at=received_at,
            source_authorization=source_authorization,
            unverified_compatibility_reason=unverified_compatibility_reason,
            fetch_lease=fetch_lease,
            deferred_intent=deferred_intent,
        )

    async def stage_provider_result_for_deferred_release(
        self,
        context: ResolvedMarketDataQueryContext,
        result: ProviderFetchResult,
        *,
        deferred_intent: MarketDataDeferredPublicationIntent,
        received_at: datetime | None = None,
        source_authorization: MarketDataSourceAuthorization | None = None,
        unverified_compatibility_reason: str | None = None,
        fetch_lease: MarketDataFetchLeaseHandle | None = None,
    ) -> DeferredProviderFetch:
        """Persist one legacy-import candidate without making it query-visible."""
        return await _store_persistence.stage_provider_result_for_deferred_release(
            self,
            context,
            result,
            deferred_intent=deferred_intent,
            received_at=received_at,
            source_authorization=source_authorization,
            unverified_compatibility_reason=unverified_compatibility_reason,
            fetch_lease=fetch_lease,
        )

    async def promote_deferred_provider_result(
        self,
        staged: DeferredProviderFetch,
        *,
        promotion_evidence_sha256: str,
        pre_publish_guard: Callable[[], Awaitable[None]],
        fetch_lease: MarketDataFetchLeaseHandle | None = None,
    ) -> PersistedProviderFetch:
        """Turn one verified staged candidate into an ordinary sealed receipt.

        The caller must provide the private verification/reauthorization guard.
        This Store method deliberately has no default guard and never offers a
        route-level shortcut for promotion.
        """
        return await _store_persistence.promote_deferred_provider_result(
            self,
            staged,
            promotion_evidence_sha256=promotion_evidence_sha256,
            pre_publish_guard=pre_publish_guard,
            fetch_lease=fetch_lease,
        )

    async def quarantine_deferred_provider_result(
        self,
        staged: DeferredProviderFetch,
        *,
        quarantine_code: str,
    ) -> None:
        """Record that a staged candidate failed verification without exposing it."""
        return await _store_persistence.quarantine_deferred_provider_result(
            self,
            staged,
            quarantine_code=quarantine_code,
        )

    async def _read_deferred_legacy_import_candidate(
        self,
        context: ResolvedMarketDataQueryContext,
        *,
        staged: DeferredProviderFetch,
        lock_for_promotion: bool = False,
    ) -> _DeferredLegacyImportCandidate:
        """Reread one exact held receipt before it is eligible for promotion.

        The method is deliberately private and narrower than
        :meth:`read_observation_revisions`: it only accepts the opaque staged
        handle returned by ``stage_provider_result_for_deferred_release`` and
        requires the active legacy-import hold.  No API, coverage, cursor, or
        ordinary local reader can use this path to see unpublished facts.

        ``lock_for_promotion`` is a private Tx-B-only seam for the canonical
        writer.  When true, the exact source snapshot, payload reference,
        shared payload, observation revisions, publication and release hold
        are reread with ``FOR UPDATE`` in the caller's existing promotion
        transaction.  It prevents a second writer from changing persisted
        evidence between verification and the visibility seal.
        """
        return await _store_evidence_receipts._read_deferred_legacy_import_candidate(
            self,
            context,
            staged=staged,
            lock_for_promotion=lock_for_promotion,
        )

    async def _read_promoted_legacy_import_publication(
        self,
        context: ResolvedMarketDataQueryContext,
        *,
        staged: DeferredProviderFetch,
    ) -> _PromotedLegacyImportPublicationReceipt:
        """Load one promoted receipt after a persisted-evidence reread."""
        return await _store_evidence_receipts._read_promoted_legacy_import_publication(
            self,
            context,
            staged=staged,
        )

    async def _read_promoted_legacy_import_candidate(
        self,
        context: ResolvedMarketDataQueryContext,
        *,
        staged: DeferredProviderFetch,
    ) -> _PromotedLegacyImportCandidate:
        """Reread a promoted unverified fixture receipt without product visibility.

        The method deliberately accepts only the opaque staged handle and
        exact resolved context.  It is the harness's local-only reread seam;
        public Store reads, API routes, and coverage planners cannot use it.
        """
        return await _store_evidence_receipts._read_promoted_legacy_import_candidate(
            self,
            context,
            staged=staged,
        )

    async def _reread_legacy_stock_daily_harness_candidate(
        self,
        context: ResolvedMarketDataQueryContext,
        *,
        staged: DeferredProviderFetch,
        expected_hold_state: str,
        lock_for_promotion: bool = False,
    ) -> _LegacyStockDailyReread:
        """Reload one private legacy receipt and all of its persisted evidence.

        This is intentionally the only Store path that may inspect a promoted
        ``UNVERIFIED_COMPATIBILITY`` legacy fixture.  It rechecks the source
        snapshot request, content-addressed shared bytes/hash, manifest, and
        release-hold binding before returning anything to the private writer.
        """
        return await _store_evidence_receipts._reread_legacy_stock_daily_harness_candidate(
            self,
            context,
            staged=staged,
            expected_hold_state=expected_hold_state,
            lock_for_promotion=lock_for_promotion,
        )

    async def resolve_visibility_anchor(
        self,
        *,
        knowledge_cutoff: datetime,
    ) -> MarketDataVisibilityAnchor:
        """Freeze the complete sealed-receipt boundary at one UTC cutoff.

        The maximum sequence is sampled before identity, calendar, coverage, or
        observation reads.  A later receipt with the same visible timestamp is
        therefore excluded from a continuation even on engines that retain only
        microsecond timestamp precision.
        """
        return await _store_projection.resolve_visibility_anchor(
            self,
            knowledge_cutoff=knowledge_cutoff,
        )

    async def read_b2_completeness_evidence(
        self,
        context: ResolvedMarketDataQueryContext,
        *,
        selector: B2SliceSelector | B2ReportSelector,
        event_at: datetime,
        knowledge_cutoff: datetime,
        visibility_anchor: MarketDataVisibilityAnchor | None = None,
        allowed_source_registry_ids: frozenset[str] | None,
    ) -> DurableB2CompletenessEvidence | None:
        """Resolve one published B2 manifest bound to its exact source receipt.

        ``selector`` is only an untrusted lookup coordinate.  The returned
        selector is always reconstructed from the immutable receipt and child
        manifest after both the B2 receipt and its source snapshot prove
        visibility at the same frozen anchor.  Absent, pending, or currently
        unauthorized evidence remains unavailable rather than becoming a
        caller-declared completeness manifest.
        """
        return await _store_projection.read_b2_completeness_evidence(
            self,
            context,
            selector=selector,
            event_at=event_at,
            knowledge_cutoff=knowledge_cutoff,
            visibility_anchor=visibility_anchor,
            allowed_source_registry_ids=allowed_source_registry_ids,
        )

    async def read_observation_revisions(
        self,
        context: ResolvedMarketDataQueryContext,
        *,
        knowledge_cutoff: datetime,
        visibility_anchor: MarketDataVisibilityAnchor | None = None,
        include_unusable_for_coverage: bool = False,
        allowed_source_registry_ids: frozenset[str] | None = None,
        exact_event_at: datetime | None = None,
        exact_source_snapshot_id: str | None = None,
    ) -> tuple[LocalObservationRevision, ...]:
        """Select the newest response-safe revision per event/record at PIT cutoff.

        A series deliberately does not include a field projection. A later,
        narrower request can therefore append a revision that has fewer fields
        than an older revision for the same event. Selecting that row
        unconditionally would hide a complete local fact and make a broader
        follow-up request fetch the network again. Prefer the newest revision
        that is PASS and satisfies this request's required fields. By default,
        unusable revisions are excluded because this method feeds product
        responses. Coverage planning may explicitly request the newest
        unusable fallback so it can report a deterministic rejection; that
        diagnostics-only result must never be rendered as market data.
        """
        return await _store_projection.read_observation_revisions(
            self,
            context,
            knowledge_cutoff=knowledge_cutoff,
            visibility_anchor=visibility_anchor,
            include_unusable_for_coverage=include_unusable_for_coverage,
            allowed_source_registry_ids=allowed_source_registry_ids,
            exact_event_at=exact_event_at,
            exact_source_snapshot_id=exact_source_snapshot_id,
        )

    async def _resolve_visibility_anchor(
        self,
        *,
        knowledge_cutoff: datetime,
        visibility_anchor: MarketDataVisibilityAnchor | None,
    ) -> MarketDataVisibilityAnchor:
        """Use a cursor's signed anchor or resolve one exactly once for a read."""
        return await _store_projection._resolve_visibility_anchor(
            self,
            knowledge_cutoff=knowledge_cutoff,
            visibility_anchor=visibility_anchor,
        )

    async def read_observations(
        self,
        context: ResolvedMarketDataQueryContext,
        *,
        knowledge_cutoff: datetime,
        visibility_anchor: MarketDataVisibilityAnchor | None = None,
        allowed_source_registry_ids: frozenset[str] | None = None,
    ) -> tuple[Observation, ...]:
        """Return local observations in the pure shape expected by coverage planning."""
        return await _store_projection.read_observations(
            self,
            context,
            knowledge_cutoff=knowledge_cutoff,
            visibility_anchor=visibility_anchor,
            allowed_source_registry_ids=allowed_source_registry_ids,
        )

    async def read_calendar(
        self,
        *,
        calendar_code: str,
        window: TimeWindow,
        calendar_version: str | None = None,
        knowledge_cutoff: datetime | None = None,
        visibility_anchor: MarketDataVisibilityAnchor | None = None,
        data_kind: str = "bars",
        frequency: str = "1d",
        allowed_source_registry_ids: frozenset[str] | None = None,
    ) -> CalendarSnapshot:
        """Return one explicit calendar version or a typed unknown result.

        A calendar becomes ``KNOWN`` only when its persisted definition carries
        an explicit ``coverage_start_at``/``coverage_end_at`` pair (or the
        equivalent nested ``coverage_window`` mapping).  Weekdays, holidays,
        and missing sessions are never inferred by this reader.
        """
        return await _store_calendar.read_calendar(
            self,
            calendar_code=calendar_code,
            window=window,
            calendar_version=calendar_version,
            knowledge_cutoff=knowledge_cutoff,
            visibility_anchor=visibility_anchor,
            data_kind=data_kind,
            frequency=frequency,
            allowed_source_registry_ids=allowed_source_registry_ids,
        )

    async def read_calendar_for_context(
        self,
        context: ResolvedMarketDataQueryContext,
        *,
        calendar_version: str | None = None,
        knowledge_cutoff: datetime | None = None,
        visibility_anchor: MarketDataVisibilityAnchor | None = None,
        allowed_source_registry_ids: frozenset[str] | None = None,
    ) -> CalendarSnapshot:
        """Load calendar evidence for a resolved query's exact market and window."""
        return await _store_calendar.read_calendar_for_context(
            self,
            context,
            calendar_version=calendar_version,
            knowledge_cutoff=knowledge_cutoff,
            visibility_anchor=visibility_anchor,
            allowed_source_registry_ids=allowed_source_registry_ids,
        )

    async def read_calendar_trading_day_events_for_context(
        self,
        context: ResolvedMarketDataQueryContext,
        *,
        knowledge_cutoff: datetime,
        visibility_anchor: MarketDataVisibilityAnchor | None = None,
        allowed_source_registry_ids: frozenset[str] | None = None,
    ) -> CalendarTradingDayEvents:
        """Return a one-to-one daily source-date map from one governed snapshot.

        This is deliberately narrower than :meth:`read_calendar_for_context`.
        It is for controlled legacy imports that must preserve the source table's
        ``DATE`` label while using the exact published EventKey.  It reuses the
        regular calendar read first, then requires that its proof comes from one
        visible snapshot; composed rolling segments remain unavailable here
        because no importer may erase their snapshot boundary.
        """
        return await _store_calendar.read_calendar_trading_day_events_for_context(
            self,
            context,
            knowledge_cutoff=knowledge_cutoff,
            visibility_anchor=visibility_anchor,
            allowed_source_registry_ids=allowed_source_registry_ids,
        )

    async def _read_visible_calendar_snapshot_for_trading_days(
        self,
        *,
        calendar_code: str,
        calendar_version: str,
        visibility_anchor: MarketDataVisibilityAnchor,
        allowed_source_registry_ids: frozenset[str] | None,
    ) -> tuple[MdCalendarSnapshot | None, str | None]:
        """Revalidate the single snapshot boundary retained by a known calendar."""
        return await _store_calendar._read_visible_calendar_snapshot_for_trading_days(
            self,
            calendar_code=calendar_code,
            calendar_version=calendar_version,
            visibility_anchor=visibility_anchor,
            allowed_source_registry_ids=allowed_source_registry_ids,
        )

    async def _read_calendar_trading_day_events(
        self,
        *,
        snapshot: MdCalendarSnapshot,
        window: TimeWindow,
        data_kind: str,
        frequency: str,
        expected_event_keys: Sequence[EventKey],
    ) -> tuple[CalendarTradingDayEvent, ...]:
        """Bind each selected daily EventKey to exactly one persisted date label."""
        return await _store_calendar._read_calendar_trading_day_events(
            self,
            snapshot=snapshot,
            window=window,
            data_kind=data_kind,
            frequency=frequency,
            expected_event_keys=expected_event_keys,
        )

    async def _find_series(
        self,
        identity: SeriesIdentity,
        context: ResolvedMarketDataQueryContext,
        *,
        for_update: bool = False,
    ) -> MdDataSeries | None:
        return await _store_persistence._find_series(
            self,
            identity,
            context,
            for_update=for_update,
        )

    async def _require_active_provider(self, provider_id: str) -> DgProvider:
        return await _store_evidence._require_active_provider(
            self,
            provider_id,
        )

    async def ensure_provider_active(self, provider_id: str) -> None:
        """Authorize an expected receipt provider before a route invokes it.

        ``persist_provider_result`` repeats this check for the actual receipt,
        but performing it here prevents a revoked or unregistered paid source
        from receiving an outbound request merely to be rejected afterwards.
        """
        return await _store_evidence.ensure_provider_active(
            self,
            provider_id,
        )

    async def ensure_source_authorization_before_provider_io(
        self,
        context: ResolvedMarketDataQueryContext,
        source_authorization: MarketDataSourceAuthorization,
        *,
        provider_id: str,
        checked_at: datetime | None = None,
    ) -> None:
        """Revalidate one exact source grant before an external request starts.

        ``persist_provider_result`` repeats this validation after the provider
        responds, which closes the race between outbound I/O and durable
        receipt creation.  Scheduled collectors also need this preflight so a
        revoked, expired, or stale grant cannot trigger a paid/broad source
        request merely because its provider remains active.
        """
        return await _store_evidence.ensure_source_authorization_before_provider_io(
            self,
            context,
            source_authorization,
            provider_id=provider_id,
            checked_at=checked_at,
        )

    async def _validate_source_authorization(
        self,
        context: ResolvedMarketDataQueryContext,
        result: ProviderFetchResult,
        source_authorization: MarketDataSourceAuthorization | None,
        *,
        local_received_at: datetime,
        unverified_compatibility_reason: str | None,
    ) -> _ValidatedSourceAuthorization:
        """Validate a frozen source grant against the live registry before persistence.

        A normal v2 write must supply the grant.  The only bypass is a bounded,
        explicit compatibility reason, which produces a permanently
        unverified receipt that v2 local reads reject.  Once a grant is
        supplied this method accepts neither an arbitrary mapping nor a
        caller-computed descriptor alone: it verifies the typed evidence, its
        canonical digest, request context, and the current registry row before
        the source snapshot can be staged.
        """
        return await _store_evidence._validate_source_authorization(
            self,
            context,
            result,
            source_authorization,
            local_received_at=local_received_at,
            unverified_compatibility_reason=unverified_compatibility_reason,
        )

    async def _validate_source_authorization_for_provider(
        self,
        context: ResolvedMarketDataQueryContext,
        *,
        provider_id: str,
        source_authorization: MarketDataSourceAuthorization | None,
        local_received_at: datetime,
        unverified_compatibility_reason: str | None,
    ) -> _ValidatedSourceAuthorization:
        """Validate one source grant using its explicit provider identity."""
        return await _store_evidence._validate_source_authorization_for_provider(
            self,
            context,
            provider_id=provider_id,
            source_authorization=source_authorization,
            local_received_at=local_received_at,
            unverified_compatibility_reason=unverified_compatibility_reason,
        )

    async def _get_or_create_shared_source_payload(
        self,
        validated: _ValidatedSharedSourcePayload | None,
    ) -> MdSourcePayload | None:
        """Persist one validated raw response once within the fact transaction.

        The payload cannot be published or queried independently.  It becomes
        reachable only through the source snapshots created in the same outer
        transaction.  A matching content address is revalidated before reuse
        so an unexpected manual/database corruption cannot be hidden by its
        natural-key lookup.
        """
        return await _store_persistence._get_or_create_shared_source_payload(
            self,
            validated,
        )

    async def _load_shared_source_payload(self, content_sha256: str) -> MdSourcePayload | None:
        """Re-read a shared blob instead of trusting a long-lived identity map."""
        return await _store_persistence._load_shared_source_payload(
            self,
            content_sha256,
        )

    def _make_source_snapshot(
        self,
        context: ResolvedMarketDataQueryContext,
        provider: DgProvider,
        result: ProviderFetchResult,
        validated: _ValidatedProviderFetch,
        *,
        source_authorization: _ValidatedSourceAuthorization,
        local_received_at: datetime,
        fetch_lease: MarketDataFetchLeaseHandle | None,
        shared_source_payload: MdSourcePayload | None,
    ) -> MdSourceSnapshot:
        return _store_persistence._make_source_snapshot(
            self,
            context,
            provider,
            result,
            validated,
            source_authorization=source_authorization,
            local_received_at=local_received_at,
            fetch_lease=fetch_lease,
            shared_source_payload=shared_source_payload,
        )

    async def _next_revision_numbers(
        self,
        *,
        series_id: str,
        record_coordinates: Sequence[tuple[datetime, str]],
    ) -> dict[tuple[datetime, str], int]:
        """Allocate revision ordinals independently for each business record.

        A B2 receipt may carry multiple valid facts at an identical event
        timestamp.  The timestamp still scopes the database lookup, while the
        server-derived semantic-key digest controls which fact receives the
        next revision ordinal.
        """
        return await _store_persistence._next_revision_numbers(
            self,
            series_id=series_id,
            record_coordinates=record_coordinates,
        )

    async def _lock_series_for_revision(
        self,
        series: MdDataSeries,
        context: ResolvedMarketDataQueryContext,
    ) -> MdDataSeries:
        """Serialize per-series revision-number allocation on engines with row locks.

        PostgreSQL and MySQL honour ``FOR UPDATE`` here, so concurrent source
        receipts cannot both allocate the same next revision number for an
        event/semantic-record coordinate. SQLite serializes writes at database
        level; the explicit lock remains a harmless no-op there while keeping
        the service contract uniform across the supported engines.
        """
        return await _store_persistence._lock_series_for_revision(
            self,
            series,
            context,
        )

    @staticmethod
    def _make_observation_revision(
        *,
        series: MdDataSeries,
        source_snapshot: MdSourceSnapshot,
        result: ProviderFetchResult,
        observation: _ValidatedProviderObservation,
        revision_number: int,
        local_received_at: datetime,
    ) -> MdObservationRevision:
        return _store_persistence._make_observation_revision(
            series=series,
            source_snapshot=source_snapshot,
            result=result,
            observation=observation,
            revision_number=revision_number,
            local_received_at=local_received_at,
        )

    async def _calendar_event_keys(
        self,
        snapshot: MdCalendarSnapshot,
        coverage_window: TimeWindow,
        *,
        requested_window: TimeWindow,
        data_kind: str,
        frequency: str,
    ) -> tuple[EventKey, ...]:
        return await _store_calendar_grid._calendar_event_keys(
            self,
            snapshot,
            coverage_window,
            requested_window=requested_window,
            data_kind=data_kind,
            frequency=frequency,
        )

    async def _assert_calendar_grid_declared(
        self,
        snapshot: MdCalendarSnapshot,
        coverage_window: TimeWindow,
        *,
        data_kind: str,
        frequency: str,
    ) -> None:
        """Prove a frequency grid exists without loading the whole snapshot.

        A holiday or weekend request can legitimately contain no expected
        event.  It is still known only if the snapshot declares the requested
        grid elsewhere.  The materialized coverage key gives that proof in one
        indexed, bounded witness query rather than scanning every event in a
        long-lived calendar segment.
        """
        return await _store_calendar_grid._assert_calendar_grid_declared(
            self,
            snapshot,
            coverage_window,
            data_kind=data_kind,
            frequency=frequency,
        )


def _assert_context_integrity(context: ResolvedMarketDataQueryContext) -> None:
    """Ensure a manually assembled context cannot cross-wire series dimensions."""
    if not isinstance(context, ResolvedMarketDataQueryContext):
        raise TypeError("context must be a ResolvedMarketDataQueryContext")
    query = context.query
    identity = context.identity
    coverage = context.coverage_identity
    if (
        query.dataset_code != context.storage.dataset_code
        or query.dataset_code != coverage.dataset_code
        or query.canonical_id != identity.canonical_id
        or query.canonical_id != coverage.canonical_id
        or query.instrument_metadata_version != identity.metadata_version
        or query.instrument_metadata_version != coverage.instrument_metadata_version
        or identity.asset_type != coverage.asset_type
        or identity.venue != coverage.market
        or query.data_kind != coverage.data_kind
        or (query.frequency or "snapshot") != coverage.frequency
        or query.source_policy_id != coverage.source_policy_id
        or query.adjustment != coverage.adjustment
        or query.price_basis != coverage.price_basis
        or query.currency != coverage.currency
        or query.unit != coverage.unit
        or query.family_id != coverage.family_id
        or query.family_contract_version != coverage.family_contract_version
    ):
        raise MarketDataStoreError("QUERY_CONTEXT_INTEGRITY")
    _require_text(context.storage.dataset_id, field_name="dataset_id", maximum=36)


def _assert_writable_context(context: ResolvedMarketDataQueryContext) -> None:
    """Reject a catalog binding that has not opted into canonical writes."""
    _assert_context_integrity(context)
    if context.storage.write_mode not in {"canonical_read_write", "canonical_append_only"}:
        raise MarketDataStoreError("DATASET_STORAGE_NOT_WRITABLE")


def _assert_series_matches_context(
    series: MdDataSeries,
    identity: SeriesIdentity,
    context: ResolvedMarketDataQueryContext,
) -> None:
    """Detect a persisted structured-identity mismatch behind the same hash."""
    try:
        stored_identity = _json_safe_mapping(
            series.semantic_identity_json,
            field_name="persisted series identity",
        )
    except MarketDataStoreError as exc:
        raise MarketDataStoreError("SERIES_SEMANTIC_COLLISION") from exc
    if (
        series.semantic_key_sha256 != identity.semantic_key_sha256
        or _canonical_json(stored_identity, field_name="persisted series identity")
        != _canonical_json(identity.semantic_identity, field_name="series identity")
        or series.dataset_id != context.storage.dataset_id
        or series.canonical_id != context.query.canonical_id
        or series.data_kind != context.query.data_kind
        or series.frequency != context.query.frequency
    ):
        raise MarketDataStoreError("SERIES_SEMANTIC_COLLISION")


def _is_visibility_sequence(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _normalize_allowed_source_registry_ids(
    value: frozenset[str] | None,
) -> frozenset[str] | None:
    """Validate the exact current-source allow-list used for a local read."""
    if value is None:
        return None
    if not isinstance(value, frozenset):
        raise TypeError("allowed_source_registry_ids must be a frozenset when supplied")
    return frozenset(
        _require_text(source_id, field_name="allowed source_registry_id", maximum=255)
        for source_id in value
    )


def _require_sha256_digest(value: object, *, code: str) -> str:
    """Return one canonical lowercase SHA-256 digest or a stable failure code."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise MarketDataStoreError(code)
    return value


def _require_text(value: object, *, field_name: str, maximum: int) -> str:
    """Require a bounded non-empty string before it reaches a relational column."""
    if not isinstance(value, str):
        raise MarketDataStoreError("TEXT_VALUE_INVALID")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise MarketDataStoreError("TEXT_VALUE_INVALID")
    return normalized


def _json_safe_mapping(value: object, *, field_name: str) -> dict[str, object]:
    """Return a recursively JSON-safe mapping with deterministic primitive values."""
    normalized = _json_safe(value, field_name=field_name)
    if not isinstance(normalized, dict):
        raise MarketDataStoreError("JSON_VALUE_UNSAFE")
    return normalized


def _json_safe(value: object, *, field_name: str) -> object:
    """Normalize only values that can be stored and hashed without Python repr fallbacks."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MarketDataStoreError("JSON_VALUE_UNSAFE")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise MarketDataStoreError("JSON_VALUE_UNSAFE")
        return format(value, "f")
    if isinstance(value, datetime):
        return _require_aware_utc(value, field_name=field_name).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized_mapping: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise MarketDataStoreError("JSON_VALUE_UNSAFE")
            normalized_mapping[key] = _json_safe(item, field_name=field_name)
        return normalized_mapping
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, field_name=field_name) for item in value]
    raise MarketDataStoreError("JSON_VALUE_UNSAFE")


def _canonical_json(value: object, *, field_name: str) -> str:
    """Serialize a JSON-safe value once, with stable ordering for SHA-256 identities."""
    try:
        return json.dumps(
            _json_safe(value, field_name=field_name),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise MarketDataStoreError("JSON_VALUE_UNSAFE") from exc


def _sha256(value: str) -> str:
    """Return a lowercase SHA-256 digest for a canonical JSON representation."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
