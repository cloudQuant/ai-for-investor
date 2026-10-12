"""Reread held receipt evidence before guarded legacy promotion or visibility."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.market_data.store import (
        DeferredProviderFetch,
        Mapping,
        MarketDataStore,
        MdObservationRevision,
        MdPublication,
        MdPublicationReleaseHold,
        MdSourcePayload,
        MdSourceSnapshot,
        MdSourceSnapshotPayloadRef,
        ProviderFetchResult,
        ResolvedMarketDataQueryContext,
        _DeferredLegacyImportCandidate,
        _DeferredLegacyImportObservation,
        _LegacyStockDailyPersistedEvidence,
        _LegacyStockDailyReread,
        _PromotedLegacyImportCandidate,
        _PromotedLegacyImportPublicationReceipt,
    )


async def _read_deferred_legacy_import_candidate(
    self: MarketDataStore,
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
    from app.services.market_data.store import (
        PUBLICATION_RELEASE_HOLD_STATE_DEFERRED,
        MarketDataStoreError,
        _DeferredLegacyImportCandidate,
    )

    if not isinstance(lock_for_promotion, bool):
        raise TypeError("lock_for_promotion must be a bool")
    if lock_for_promotion and not self._db.in_transaction():
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_PROMOTION_TRANSACTION_REQUIRED")
    reread = await self._reread_legacy_stock_daily_harness_candidate(
        context,
        staged=staged,
        expected_hold_state=PUBLICATION_RELEASE_HOLD_STATE_DEFERRED,
        lock_for_promotion=lock_for_promotion,
    )
    if reread.publication is not None:
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_INTEGRITY")
    return _DeferredLegacyImportCandidate(
        staged=staged,
        observations=reread.observations,
        evidence=reread.evidence,
    )


async def _read_promoted_legacy_import_publication(
    self: MarketDataStore,
    context: ResolvedMarketDataQueryContext,
    *,
    staged: DeferredProviderFetch,
) -> _PromotedLegacyImportPublicationReceipt:
    """Load one promoted receipt after a persisted-evidence reread."""
    return (
        await self._read_promoted_legacy_import_candidate(
            context,
            staged=staged,
        )
    ).publication


async def _read_promoted_legacy_import_candidate(
    self: MarketDataStore,
    context: ResolvedMarketDataQueryContext,
    *,
    staged: DeferredProviderFetch,
) -> _PromotedLegacyImportCandidate:
    """Reread a promoted unverified fixture receipt without product visibility.

    The method deliberately accepts only the opaque staged handle and
    exact resolved context.  It is the harness's local-only reread seam;
    public Store reads, API routes, and coverage planners cannot use it.
    """
    from app.services.market_data.store import (
        PUBLICATION_RELEASE_HOLD_STATE_PROMOTED,
        MarketDataStoreError,
        _PromotedLegacyImportCandidate,
    )

    reread = await self._reread_legacy_stock_daily_harness_candidate(
        context,
        staged=staged,
        expected_hold_state=PUBLICATION_RELEASE_HOLD_STATE_PROMOTED,
    )
    if reread.publication is None:
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_PUBLICATION_INTEGRITY")
    return _PromotedLegacyImportCandidate(
        staged=staged,
        observations=reread.observations,
        evidence=reread.evidence,
        publication=reread.publication,
    )


async def _reread_legacy_stock_daily_harness_candidate(
    self: MarketDataStore,
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
    from app.services.market_data.store import (
        PUBLICATION_RELEASE_HOLD_STATE_DEFERRED,
        PUBLICATION_RELEASE_HOLD_STATE_PROMOTED,
        PUBLICATION_RELEASE_HOLD_WORKFLOW_LEGACY_STOCK_DAILY_IMPORT,
        PUBLICATION_SOURCE_SNAPSHOT,
        DeferredProviderFetch,
        MarketDataStoreError,
        MdObservationRevision,
        MdPublication,
        MdPublicationReleaseHold,
        MdSourcePayload,
        MdSourceSnapshot,
        MdSourceSnapshotPayloadRef,
        _assert_context_integrity,
        _LegacyStockDailyReread,
        _promoted_legacy_import_publication_receipt,
        _reread_deferred_legacy_import_observation,
        _reread_legacy_stock_daily_persisted_evidence,
        and_,
        select,
    )

    if not isinstance(staged, DeferredProviderFetch):
        raise TypeError("staged must be a DeferredProviderFetch")
    if expected_hold_state not in {
        PUBLICATION_RELEASE_HOLD_STATE_DEFERRED,
        PUBLICATION_RELEASE_HOLD_STATE_PROMOTED,
    }:
        raise TypeError("expected_hold_state must be a private legacy hold state")
    if not isinstance(lock_for_promotion, bool):
        raise TypeError("lock_for_promotion must be a bool")
    if lock_for_promotion and expected_hold_state != PUBLICATION_RELEASE_HOLD_STATE_DEFERRED:
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_PROMOTION_LOCK_INVALID")
    if staged.intent.workflow_kind != PUBLICATION_RELEASE_HOLD_WORKFLOW_LEGACY_STOCK_DAILY_IMPORT:
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_INTENT_INVALID")
    _assert_context_integrity(context)
    series = await self.get_series(context)
    if series is None or series.id != staged.series_id:
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_SERIES_MISMATCH")
    statement = (
        select(
            MdObservationRevision,
            MdSourceSnapshot,
            MdPublication,
            MdPublicationReleaseHold,
            MdSourceSnapshotPayloadRef,
            MdSourcePayload,
        )
        .join(
            MdSourceSnapshot,
            MdSourceSnapshot.id == MdObservationRevision.source_snapshot_id,
        )
        .join(
            MdPublication,
            and_(
                MdPublication.entity_type == PUBLICATION_SOURCE_SNAPSHOT,
                MdPublication.entity_id == MdSourceSnapshot.id,
            ),
        )
        .join(
            MdPublicationReleaseHold,
            MdPublicationReleaseHold.publication_id == MdPublication.id,
        )
        .join(
            MdSourceSnapshotPayloadRef,
            MdSourceSnapshotPayloadRef.source_snapshot_id == MdSourceSnapshot.id,
        )
        .join(
            MdSourcePayload,
            MdSourcePayload.content_sha256 == MdSourceSnapshotPayloadRef.content_sha256,
        )
        .where(
            MdObservationRevision.series_id == staged.series_id,
            MdObservationRevision.source_snapshot_id == staged.source_snapshot_id,
            MdObservationRevision.id.in_(staged.observation_revision_ids),
            MdPublication.id == staged.publication_id,
            MdPublication.entity_sha256 == MdSourceSnapshot.payload_sha256,
            MdPublicationReleaseHold.source_snapshot_id == staged.source_snapshot_id,
            MdPublicationReleaseHold.workflow_kind
            == PUBLICATION_RELEASE_HOLD_WORKFLOW_LEGACY_STOCK_DAILY_IMPORT,
            MdPublicationReleaseHold.state == expected_hold_state,
            MdPublicationReleaseHold.intent_sha256 == staged.intent.intent_sha256,
        )
        .order_by(MdObservationRevision.event_time, MdObservationRevision.id)
        .execution_options(populate_existing=True)
    )
    if lock_for_promotion:
        # The publication manager already owns the publication/hold locks
        # in Tx B.  Lock the remaining evidence rows in the same
        # transaction before the writer compares request/manifest/shared
        # bytes and permit/context bindings.  The caller must not release
        # this transaction before guarded promotion seals visibility.
        statement = statement.with_for_update()
    if expected_hold_state == PUBLICATION_RELEASE_HOLD_STATE_DEFERRED:
        statement = statement.where(
            MdPublication.published_at.is_(None),
            MdPublication.visibility_sequence.is_(None),
        )
    else:
        statement = statement.where(
            MdPublication.published_at.is_not(None),
            MdPublication.visibility_sequence.is_not(None),
        )
    rows = list((await self._db.execute(statement)).all())
    if len(rows) != len(staged.observation_revision_ids):
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_NOT_AVAILABLE")

    observations: list[_DeferredLegacyImportObservation] = []
    seen_revision_ids: set[str] = set()
    evidence: _LegacyStockDailyPersistedEvidence | None = None
    publication_receipt: _PromotedLegacyImportPublicationReceipt | None = None
    for revision, source_snapshot, publication, hold, payload_ref, source_payload in rows:
        if (
            revision.id in seen_revision_ids
            or source_snapshot.id != staged.source_snapshot_id
            or publication.id != staged.publication_id
            or hold.publication_id != staged.publication_id
            or hold.source_snapshot_id != staged.source_snapshot_id
            or payload_ref.source_snapshot_id != staged.source_snapshot_id
        ):
            raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_INTEGRITY")
        if evidence is None:
            evidence = _reread_legacy_stock_daily_persisted_evidence(
                context=context,
                source_snapshot=source_snapshot,
                payload_ref=payload_ref,
                source_payload=source_payload,
                observation_count=len(rows),
            )
            if expected_hold_state == PUBLICATION_RELEASE_HOLD_STATE_PROMOTED:
                publication_receipt = _promoted_legacy_import_publication_receipt(
                    publication=publication,
                    hold=hold,
                    staged=staged,
                )
        elif (
            source_snapshot.id != evidence.source_snapshot_id
            or payload_ref.content_sha256 != evidence.source_payload_content_sha256
            or source_payload.content_sha256 != evidence.source_payload_content_sha256
        ):
            raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_INTEGRITY")
        seen_revision_ids.add(revision.id)
        observations.append(
            _reread_deferred_legacy_import_observation(
                revision=revision,
                context=context,
                staged=staged,
            )
        )
    if (
        evidence is None
        or seen_revision_ids != set(staged.observation_revision_ids)
        or (
            expected_hold_state == PUBLICATION_RELEASE_HOLD_STATE_PROMOTED
            and publication_receipt is None
        )
    ):
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_INTEGRITY")
    return _LegacyStockDailyReread(
        observations=tuple(observations),
        evidence=evidence,
        publication=publication_receipt,
    )


def _reread_deferred_legacy_import_observation(
    *,
    revision: MdObservationRevision,
    context: ResolvedMarketDataQueryContext,
    staged: DeferredProviderFetch,
) -> _DeferredLegacyImportObservation:
    """Decode one persisted revision only after its private receipt is bound."""
    from app.services.market_data.store import (
        MappingProxyType,
        MarketDataStoreError,
        ObservationQuality,
        _canonical_json,
        _DeferredLegacyImportObservation,
        _json_safe_mapping,
        _persisted_semantic_record_key,
        _sha256,
        _stored_utc,
        _verified_revision_source_available_at,
    )

    try:
        event_at = _stored_utc(
            revision.event_time,
            field_name="deferred legacy observation event time",
        )
        available_at = _stored_utc(
            revision.available_at,
            field_name="deferred legacy observation available time",
        )
        quality = ObservationQuality(revision.quality_status)
        fields = _json_safe_mapping(
            revision.fields_json,
            field_name="deferred legacy observation fields",
        )
        fields_sha256 = _sha256(
            _canonical_json(fields, field_name="deferred legacy observation fields")
        )
        semantic_record_key = _persisted_semantic_record_key(revision)
        source_available_at = _verified_revision_source_available_at(
            revision,
            context=context,
            event_at=event_at,
            available_at=available_at,
            fields_sha256=fields_sha256,
            quality=quality,
            revision_number=revision.revision_number,
            semantic_record_key=semantic_record_key,
        )
    except (TypeError, ValueError) as exc:
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_INTEGRITY") from exc
    if (
        fields_sha256 != revision.fields_sha256
        or source_available_at is None
        or available_at != staged.local_received_at
    ):
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_INTEGRITY")
    return _DeferredLegacyImportObservation(
        revision_id=revision.id,
        source_snapshot_id=revision.source_snapshot_id,
        event_at=event_at,
        available_at=available_at,
        source_available_at=source_available_at,
        quality=quality,
        fields=MappingProxyType(fields),
    )


def _reread_legacy_stock_daily_persisted_evidence(
    *,
    context: ResolvedMarketDataQueryContext,
    source_snapshot: MdSourceSnapshot,
    payload_ref: MdSourceSnapshotPayloadRef,
    source_payload: MdSourcePayload,
    observation_count: int,
) -> _LegacyStockDailyPersistedEvidence:
    """Validate the persisted source snapshot and shared bytes for the harness.

    This function intentionally starts from database values, not from the
    writer's batch DTO.  The private writer compares the returned evidence to
    its issued permit and source receipt before promotion.  A malformed or
    substituted payload cannot therefore be made canonical by rebuilding a
    matching caller-side DTO.
    """
    from app.services.market_data.store import (
        _UNVERIFIED_COMPATIBILITY_PROVENANCE_VERSION,
        SOURCE_AUTHORIZATION_STATE_UNVERIFIED_COMPATIBILITY,
        UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
        MappingProxyType,
        MarketDataStoreError,
        _canonical_json,
        _json_safe_mapping,
        _LegacyStockDailyPersistedEvidence,
        _require_provider_request_id,
        _require_sha256_digest,
        _require_text,
        _sha256,
        _stored_utc,
        hashlib,
        json,
    )

    code = "DEFERRED_LEGACY_IMPORT_INTEGRITY"
    try:
        if (
            source_snapshot.source_authorization_state
            != SOURCE_AUTHORIZATION_STATE_UNVERIFIED_COMPATIBILITY
            or source_snapshot.source_authorization_descriptor_sha256 is not None
        ):
            raise MarketDataStoreError(code)
        source_id = _require_text(
            source_snapshot.source_id,
            field_name="deferred legacy source id",
            maximum=255,
        )
        endpoint_version = _require_text(
            source_snapshot.endpoint_version,
            field_name="deferred legacy endpoint version",
            maximum=128,
        )
        raw_source_observed_at = source_snapshot.source_observed_at
        if raw_source_observed_at is None:
            raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY")
        source_observed_at = _stored_utc(
            raw_source_observed_at,
            field_name="deferred legacy source observed time",
        )
        fetch_lease_key_sha256 = _require_sha256_digest(
            source_snapshot.fetch_lease_key_sha256,
            code=code,
        )
        fetch_lease_fence_token = source_snapshot.fetch_lease_fence_token
        if (
            not isinstance(fetch_lease_fence_token, int)
            or isinstance(fetch_lease_fence_token, bool)
            or fetch_lease_fence_token < 1
        ):
            raise MarketDataStoreError(code)
        provenance = _json_safe_mapping(
            source_snapshot.provenance_json,
            field_name="deferred legacy source provenance",
        )
        unverified_compatibility = _json_safe_mapping(
            provenance.get("unverified_compatibility"),
            field_name="deferred legacy unverified compatibility",
        )
        if unverified_compatibility != {
            "version": _UNVERIFIED_COMPATIBILITY_PROVENANCE_VERSION,
            "reason": UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
            "decision": "UNVERIFIED",
        }:
            raise MarketDataStoreError(code)

        request_json = _json_safe_mapping(
            source_snapshot.request_json,
            field_name="deferred legacy source request",
        )
        if set(request_json) != {"provider_request", "resolved_query"}:
            raise MarketDataStoreError(code)
        provider_request = _json_safe_mapping(
            request_json["provider_request"],
            field_name="deferred legacy provider request",
        )
        resolved_query = _json_safe_mapping(
            request_json["resolved_query"],
            field_name="deferred legacy resolved query",
        )
        expected_query = _json_safe_mapping(
            context.query.semantic_payload(),
            field_name="deferred legacy expected resolved query",
        )
        expected_query_fingerprint = _require_sha256_digest(
            context.query.query_fingerprint,
            code=code,
        )
        if (
            _canonical_json(resolved_query, field_name="deferred legacy resolved query")
            != _canonical_json(expected_query, field_name="deferred legacy expected resolved query")
            or source_snapshot.request_fingerprint_sha256 != expected_query_fingerprint
            or source_snapshot.query_fingerprint_sha256 != expected_query_fingerprint
            or provider_request.get("query_fingerprint") != expected_query_fingerprint
            or provider_request.get("request_id") != source_snapshot.provider_request_id
            or provider_request.get("provider") != source_id
            or _require_provider_request_id(source_snapshot.provider_request_id)
            != source_snapshot.provider_request_id
        ):
            raise MarketDataStoreError(code)
        provider_request_digest = _sha256(
            _canonical_json(provider_request, field_name="deferred legacy provider request")
        )
        if (
            provider_request_digest != source_snapshot.provider_request_fingerprint_sha256
            or source_snapshot.provider_request_fingerprint_sha256
            != _require_sha256_digest(
                source_snapshot.provider_request_fingerprint_sha256, code=code
            )
        ):
            raise MarketDataStoreError(code)

        payload_manifest = _json_safe_mapping(
            source_snapshot.payload_manifest_json,
            field_name="deferred legacy payload manifest",
        )
        if (
            set(payload_manifest)
            != {
                "format",
                "observation_count",
                "receipt_payload",
                "shared_source_payload",
            }
            or payload_manifest.get("format") != "content-addressed-source-batch-v1"
        ):
            raise MarketDataStoreError(code)
        if payload_manifest.get("observation_count") != observation_count:
            raise MarketDataStoreError(code)
        receipt_payload = _json_safe_mapping(
            payload_manifest["receipt_payload"],
            field_name="deferred legacy receipt payload",
        )
        shared_manifest = _json_safe_mapping(
            payload_manifest["shared_source_payload"],
            field_name="deferred legacy shared payload manifest",
        )
        if set(shared_manifest) != {
            "content_sha256",
            "payload_format",
            "payload_bytes",
            "payload_role",
        }:
            raise MarketDataStoreError(code)
        content_sha256 = _require_sha256_digest(shared_manifest.get("content_sha256"), code=code)
        payload_format = _require_text(
            shared_manifest.get("payload_format"),
            field_name="deferred legacy shared payload format",
            maximum=128,
        )
        payload_role = _require_text(
            shared_manifest.get("payload_role"),
            field_name="deferred legacy shared payload role",
            maximum=128,
        )
        payload_bytes = shared_manifest.get("payload_bytes")
        if (
            not isinstance(payload_bytes, int)
            or isinstance(payload_bytes, bool)
            or payload_bytes < 1
            or payload_role != "source_batch"
            or payload_ref.source_snapshot_id != source_snapshot.id
            or payload_ref.content_sha256 != content_sha256
            or payload_ref.payload_role != payload_role
            or source_payload.content_sha256 != content_sha256
            or source_payload.payload_format != payload_format
            or source_payload.payload_bytes != payload_bytes
        ):
            raise MarketDataStoreError(code)
        shared_bytes = bytes(source_payload.canonical_payload_bytes)
        if (
            len(shared_bytes) != payload_bytes
            or hashlib.sha256(shared_bytes).hexdigest() != content_sha256
        ):
            raise MarketDataStoreError(code)
        decoded_source_batch = json.loads(shared_bytes.decode("utf-8"))
        source_batch = _json_safe_mapping(
            decoded_source_batch,
            field_name="deferred legacy shared source batch",
        )
        if (
            _canonical_json(source_batch, field_name="deferred legacy shared source batch").encode(
                "utf-8"
            )
            != shared_bytes
        ):
            raise MarketDataStoreError(code)
        raw_payload = dict(receipt_payload)
        raw_payload["source_batch"] = source_batch
        if _sha256(_canonical_json(raw_payload, field_name="deferred legacy raw payload")) != (
            source_snapshot.payload_sha256
        ):
            raise MarketDataStoreError(code)
        legacy_import = _json_safe_mapping(
            receipt_payload.get("legacy_import"),
            field_name="deferred legacy import evidence",
        )
        source_batch_sha256 = _require_sha256_digest(
            legacy_import.get("source_batch_sha256"),
            code=code,
        )
        if source_batch_sha256 != hashlib.sha256(shared_bytes).hexdigest():
            raise MarketDataStoreError(code)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise MarketDataStoreError(code) from exc
    return _LegacyStockDailyPersistedEvidence(
        source_snapshot_id=source_snapshot.id,
        source_id=source_id,
        endpoint_version=endpoint_version,
        source_observed_at=source_observed_at,
        source_authorization_state=source_snapshot.source_authorization_state,
        unverified_compatibility=MappingProxyType(unverified_compatibility),
        request_json=MappingProxyType(request_json),
        provider_request=MappingProxyType(provider_request),
        resolved_query=MappingProxyType(resolved_query),
        payload_manifest=MappingProxyType(payload_manifest),
        receipt_payload=MappingProxyType(receipt_payload),
        source_batch=MappingProxyType(source_batch),
        legacy_import=MappingProxyType(legacy_import),
        source_payload_content_sha256=content_sha256,
        source_payload_format=payload_format,
        source_payload_bytes=payload_bytes,
        fetch_lease_key_sha256=fetch_lease_key_sha256,
        fetch_lease_fence_token=fetch_lease_fence_token,
    )


def _promoted_legacy_import_publication_receipt(
    *,
    publication: MdPublication,
    hold: MdPublicationReleaseHold,
    staged: DeferredProviderFetch,
) -> _PromotedLegacyImportPublicationReceipt:
    """Validate a promoted private receipt after its evidence has been reread."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        _is_visibility_sequence,
        _PromotedLegacyImportPublicationReceipt,
        _require_sha256_digest,
        _stored_utc,
    )

    if (
        publication.id != staged.publication_id
        or hold.publication_id != staged.publication_id
        or hold.source_snapshot_id != staged.source_snapshot_id
        or publication.published_at is None
        or not _is_visibility_sequence(publication.visibility_sequence)
        or hold.promoted_at is None
    ):
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_PUBLICATION_INTEGRITY")
    _require_sha256_digest(
        hold.promotion_evidence_sha256,
        code="DEFERRED_LEGACY_IMPORT_PUBLICATION_INTEGRITY",
    )
    visible_at = _stored_utc(
        publication.published_at,
        field_name="deferred legacy publication time",
    )
    if _stored_utc(hold.promoted_at, field_name="deferred legacy promotion time") != visible_at:
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_PUBLICATION_INTEGRITY")
    visibility_sequence = publication.visibility_sequence
    if visibility_sequence is None:
        raise MarketDataStoreError("DEFERRED_LEGACY_IMPORT_PUBLICATION_INTEGRITY")
    return _PromotedLegacyImportPublicationReceipt(
        publication_id=publication.id,
        source_snapshot_id=staged.source_snapshot_id,
        visible_at=visible_at,
        visibility_sequence=visibility_sequence,
    )


def _validated_provider_request_evidence(
    context: ResolvedMarketDataQueryContext,
    result: ProviderFetchResult,
) -> Mapping[str, str]:
    """Bind a persisted source receipt to the exact one-time provider DTO.

    ``MarketDataProviderRequest`` already validates its own construction.  The
    store recomputes the DTO digest nevertheless, because this is the last
    boundary before immutable evidence is written and it must not silently
    equate the public query identity with a provider-call identity.
    """
    from app.services.market_data.store import (
        MappingProxyType,
        MarketDataStoreError,
        _canonical_json,
        _json_safe_mapping,
        _require_provider_request_id,
        _require_sha256_digest,
        _sha256,
    )

    request = result.request
    request_id = _require_provider_request_id(request.request_id)
    query_fingerprint = _require_sha256_digest(
        context.query.query_fingerprint,
        code="QUERY_FINGERPRINT_INVALID",
    )
    dto_payload = _json_safe_mapping(request.dto_payload, field_name="provider request DTO")
    if dto_payload.get("request_id") != request_id:
        raise MarketDataStoreError("PROVIDER_REQUEST_EVIDENCE_INVALID")
    if dto_payload.get("query_fingerprint") != query_fingerprint:
        raise MarketDataStoreError("PROVIDER_REQUEST_EVIDENCE_INVALID")
    computed_fingerprint = _sha256(_canonical_json(dto_payload, field_name="provider request DTO"))
    declared_fingerprint = _require_sha256_digest(
        request.provider_request_fingerprint_sha256,
        code="PROVIDER_REQUEST_EVIDENCE_INVALID",
    )
    if declared_fingerprint != computed_fingerprint:
        raise MarketDataStoreError("PROVIDER_REQUEST_EVIDENCE_INVALID")
    return MappingProxyType(
        {
            "provider_request_id": request_id,
            "provider_request_fingerprint_sha256": declared_fingerprint,
            "query_fingerprint_sha256": query_fingerprint,
        }
    )


def _provider_request_matches_context(
    context: ResolvedMarketDataQueryContext,
    request: object,
) -> bool:
    """Bind a receipt's immutable request to every resolved query dimension.

    The query service also compares a receipt to the exact route request,
    including the provider adapter name.  This independent store check keeps
    direct writers from persisting a receipt for another identity, time window,
    semantic series, or source policy.
    """
    from app.services.market_data.providers import MarketDataProviderRequest

    if not isinstance(request, MarketDataProviderRequest):
        return False
    venue = context.identity.venue
    return (
        venue is not None
        and request.query_fingerprint == context.query.query_fingerprint
        and request.canonical_id == context.query.canonical_id
        and request.asset_type == context.identity.asset_type
        and request.provider_symbol == context.identity.identity.display_symbol
        and request.market == venue
        and request.data_kind == context.query.data_kind
        and request.frequency == (context.query.frequency or "snapshot")
        and request.start_at == context.query.start
        and request.end_at == context.query.end
        and request.required_fields == frozenset(context.query.required_fields)
        and request.adjustment == context.query.adjustment
        and request.price_basis == context.query.price_basis
        and request.currency == context.query.currency
        and request.unit == context.query.unit
        and request.source_policy_id == context.query.source_policy_id
        and request.family_id == context.query.family_id
        and request.family_contract_version == context.query.family_contract_version
    )


def _require_provider_request_id(value: object) -> str:
    """Validate the CSPRNG request ID shape before it becomes receipt evidence."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        _require_text,
    )

    normalized = _require_text(value, field_name="provider request_id", maximum=128)
    if len(normalized) < 32 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in normalized
    ):
        raise MarketDataStoreError("PROVIDER_REQUEST_EVIDENCE_INVALID")
    return normalized
