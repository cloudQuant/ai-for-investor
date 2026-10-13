"""Validate normalized provider records before persistence creates evidence rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.market_data.store import (
        Mapping,
        MdSourcePayload,
        ProviderFetchResult,
        ProviderMarketObservation,
        ResolvedMarketDataQueryContext,
        SemanticRecordKey,
        SharedSourcePayloadSegment,
        _ValidatedProviderFetch,
        _ValidatedSharedSourcePayload,
        datetime,
    )


def _validate_provider_fetch(
    context: ResolvedMarketDataQueryContext,
    result: ProviderFetchResult,
    *,
    local_received_at: datetime,
) -> _ValidatedProviderFetch:
    """Validate all provider facts before the store creates a source receipt."""
    from app.services.market_data.store import (
        _MAX_NORMALIZED_FIELDS_BYTES,
        _MAX_NORMALIZED_RECORD_IDENTITIES_BYTES,
        _MAX_PROVIDER_OBSERVATIONS,
        MAX_SOURCE_PAYLOAD_BYTES,
        MappingProxyType,
        MarketDataStoreError,
        ObservationQuality,
        ProviderFetchResult,
        ProviderMarketObservation,
        _assert_context_integrity,
        _canonical_json,
        _json_safe_mapping,
        _provider_observation_semantic_record_key,
        _provider_request_matches_context,
        _require_aware_utc,
        _sha256,
        _validate_shared_source_payload,
        _validated_provider_request_evidence,
        _ValidatedProviderFetch,
        _ValidatedProviderObservation,
        is_usable_field_value,
        normalize_provider_fields,
    )

    _assert_context_integrity(context)
    if not isinstance(result, ProviderFetchResult):
        raise TypeError("result must be a ProviderFetchResult")
    if not _provider_request_matches_context(context, result.request):
        raise MarketDataStoreError("PROVIDER_REQUEST_MISMATCH")
    provider_request_evidence = _validated_provider_request_evidence(context, result)
    received_at = _require_aware_utc(
        local_received_at,
        field_name="local receipt timestamp",
    )
    if result.retrieved_at > received_at:
        raise MarketDataStoreError("PROVIDER_RETRIEVED_AT_FUTURE")
    if len(result.observations) > _MAX_PROVIDER_OBSERVATIONS:
        raise MarketDataStoreError("PROVIDER_OBSERVATION_LIMIT_EXCEEDED")
    raw_payload = _json_safe_mapping(result.raw_payload, field_name="provider raw_payload")
    canonical_raw_payload = _canonical_json(raw_payload, field_name="provider raw_payload")
    if len(canonical_raw_payload.encode("utf-8")) > MAX_SOURCE_PAYLOAD_BYTES:
        raise MarketDataStoreError("PROVIDER_PAYLOAD_TOO_LARGE")
    shared_source_payload = _validate_shared_source_payload(
        raw_payload,
        result.shared_source_payload_segment,
    )
    observations: list[_ValidatedProviderObservation] = []
    seen_records: set[tuple[datetime, str]] = set()
    required_fields = frozenset(context.query.required_fields)
    normalized_fields_bytes = 0
    normalized_record_identity_bytes = 0
    for observation in result.observations:
        if not isinstance(observation, ProviderMarketObservation):
            raise TypeError("provider observations must be ProviderMarketObservation values")
        event_at = _require_aware_utc(observation.event_at, field_name="provider event_at")
        available_at = _require_aware_utc(
            observation.available_at,
            field_name="provider available_at",
        )
        if not context.query.start <= event_at < context.query.end:
            raise MarketDataStoreError("PROVIDER_EVENT_OUT_OF_WINDOW")
        semantic_record_key = _provider_observation_semantic_record_key(
            context,
            observation,
        )
        normalized_record_identity_bytes += len(semantic_record_key.canonical_json.encode("utf-8"))
        if normalized_record_identity_bytes > _MAX_NORMALIZED_RECORD_IDENTITIES_BYTES:
            raise MarketDataStoreError("PROVIDER_RECORD_IDENTITIES_TOO_LARGE")
        record_coordinate = (event_at, semantic_record_key.sha256)
        if record_coordinate in seen_records:
            # Retain the established single-record failure code so existing
            # callers do not need a semantic-key migration of their own.
            if semantic_record_key.is_singleton:
                raise MarketDataStoreError("DUPLICATE_PROVIDER_EVENT")
            raise MarketDataStoreError("DUPLICATE_PROVIDER_RECORD")
        if available_at > result.retrieved_at:
            raise MarketDataStoreError("PROVIDER_AVAILABILITY_AFTER_RETRIEVAL")
        seen_records.add(record_coordinate)
        fields = _json_safe_mapping(
            normalize_provider_fields(observation.fields),
            field_name="provider observation fields",
        )
        canonical_fields = _canonical_json(fields, field_name="provider observation fields")
        normalized_fields_bytes += len(canonical_fields.encode("utf-8"))
        if normalized_fields_bytes > _MAX_NORMALIZED_FIELDS_BYTES:
            raise MarketDataStoreError("PROVIDER_NORMALIZED_FIELDS_TOO_LARGE")
        missing_required_fields = tuple(
            field_name
            for field_name in sorted(required_fields)
            if not is_usable_field_value(field_name, fields.get(field_name))
        )
        quality = (
            ObservationQuality.PASS if not missing_required_fields else ObservationQuality.FAILED
        )
        quality_details: dict[str, object] = {
            "required_fields": sorted(required_fields),
            "missing_required_fields": list(missing_required_fields),
        }
        observations.append(
            _ValidatedProviderObservation(
                event_at=event_at,
                # A provider may state that a value was published earlier,
                # but an interactive collection only becomes locally knowable
                # once this process has received its receipt.  Persist the
                # trusted local timestamp for PIT eligibility and retain the
                # upstream claim in revision provenance below.
                available_at=received_at,
                source_available_at=available_at,
                fields=MappingProxyType(fields),
                fields_sha256=_sha256(canonical_fields),
                quality=quality,
                quality_details=MappingProxyType(quality_details),
                semantic_record_key=semantic_record_key,
            )
        )
    return _ValidatedProviderFetch(
        raw_payload=MappingProxyType(raw_payload),
        payload_sha256=_sha256(canonical_raw_payload),
        observations=tuple(observations),
        provider_request_id=provider_request_evidence["provider_request_id"],
        provider_request_fingerprint_sha256=provider_request_evidence[
            "provider_request_fingerprint_sha256"
        ],
        query_fingerprint_sha256=provider_request_evidence["query_fingerprint_sha256"],
        shared_source_payload=shared_source_payload,
    )


def _provider_observation_semantic_record_key(
    context: ResolvedMarketDataQueryContext,
    observation: ProviderMarketObservation,
) -> SemanticRecordKey:
    """Derive the record identity after binding a provider row to its family.

    Provider DTOs may carry business dimensions but never a canonical key or
    digest.  This prevents an adapter from selecting a storage identity that
    disagrees with the server-owned family contract.  The four B2 families are
    intentionally still unconfigured; the lower-level check merely ensures a
    future approved writer cannot accidentally collapse their rows into the
    singleton fact shape.
    """
    from app.services.market_data.store import (
        _MULTI_RECORD_FAMILY_IDS,
        B2FamilyContractError,
        MarketDataStoreError,
        normalize_b2_record_dimensions,
        normalize_semantic_record_key,
        single_record_semantic_key,
    )

    family_id = context.query.family_id
    dimensions = observation.record_dimensions
    if family_id in _MULTI_RECORD_FAMILY_IDS:
        if dimensions is None:
            raise MarketDataStoreError("PROVIDER_RECORD_DIMENSIONS_REQUIRED")
    elif dimensions is not None:
        raise MarketDataStoreError("UNEXPECTED_PROVIDER_RECORD_DIMENSIONS")

    if dimensions is None:
        return single_record_semantic_key()

    family_contract_version = context.query.family_contract_version
    if family_id is None or family_contract_version is None:
        raise MarketDataStoreError("PROVIDER_RECORD_FAMILY_BINDING_REQUIRED")
    try:
        normalized_dimensions = normalize_b2_record_dimensions(
            family_id=family_id,
            family_contract_version=family_contract_version,
            dimensions=dimensions,
        )
        return normalize_semantic_record_key(
            family_id=family_id,
            family_contract_version=family_contract_version,
            dimensions=normalized_dimensions,
        )
    except (B2FamilyContractError, TypeError, ValueError) as exc:
        raise MarketDataStoreError("PROVIDER_RECORD_DIMENSIONS_INVALID") from exc


def _validate_shared_source_payload(
    raw_payload: Mapping[str, object],
    segment: SharedSourcePayloadSegment | None,
) -> _ValidatedSharedSourcePayload | None:
    """Extract and content-address one fixed raw segment before any write."""
    from app.services.market_data.store import (
        MAX_SOURCE_PAYLOAD_BYTES,
        Mapping,
        MappingProxyType,
        MarketDataStoreError,
        SharedSourcePayloadSegment,
        _canonical_json,
        _json_safe_mapping,
        _ValidatedSharedSourcePayload,
        hashlib,
    )

    if segment is None:
        return None
    if not isinstance(segment, SharedSourcePayloadSegment):
        raise TypeError("shared_source_payload_segment must be SharedSourcePayloadSegment or None")
    if (
        segment.segment_key != "source_batch"
        or segment.payload_format != "canonical-json-utf8-v1"
        or segment.payload_role != "source_batch"
    ):
        raise MarketDataStoreError("SHARED_SOURCE_PAYLOAD_SEGMENT_INVALID")
    source_batch = raw_payload.get(segment.segment_key)
    if not isinstance(source_batch, Mapping):
        raise MarketDataStoreError("SHARED_SOURCE_PAYLOAD_SEGMENT_MISSING")
    payload_json = _json_safe_mapping(source_batch, field_name="shared source payload")
    canonical_payload_bytes = _canonical_json(
        payload_json,
        field_name="shared source payload",
    ).encode("utf-8")
    payload_bytes = len(canonical_payload_bytes)
    if payload_bytes > MAX_SOURCE_PAYLOAD_BYTES:
        raise MarketDataStoreError("SHARED_SOURCE_PAYLOAD_TOO_LARGE")
    receipt_payload = dict(raw_payload)
    del receipt_payload[segment.segment_key]
    return _ValidatedSharedSourcePayload(
        content_sha256=hashlib.sha256(canonical_payload_bytes).hexdigest(),
        payload_format=segment.payload_format,
        payload_role=segment.payload_role,
        payload_bytes=payload_bytes,
        canonical_payload_bytes=canonical_payload_bytes,
        receipt_payload=MappingProxyType(receipt_payload),
    )


def _assert_shared_source_payload_matches(
    stored: MdSourcePayload,
    expected: _ValidatedSharedSourcePayload,
) -> None:
    """Fail closed if a natural-key payload does not exactly match its address."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        hashlib,
    )

    try:
        stored_payload = bytes(stored.canonical_payload_bytes)
    except (TypeError, ValueError) as exc:
        raise MarketDataStoreError("SHARED_SOURCE_PAYLOAD_INTEGRITY_CONFLICT") from exc
    if (
        stored.content_sha256 != expected.content_sha256
        or stored.payload_format != expected.payload_format
        or stored.payload_bytes != expected.payload_bytes
        or len(stored_payload) != stored.payload_bytes
        or hashlib.sha256(stored_payload).hexdigest() != stored.content_sha256
        or stored_payload != expected.canonical_payload_bytes
    ):
        raise MarketDataStoreError("SHARED_SOURCE_PAYLOAD_INTEGRITY_CONFLICT")
