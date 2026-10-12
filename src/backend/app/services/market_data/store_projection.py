"""Select authorized point-in-time revisions and shape query-safe projections."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.market_data.store import (
        B2ReportSelector,
        B2SliceSelector,
        DurableB2CompletenessEvidence,
        LocalObservationRevision,
        MarketDataStore,
        MarketDataVisibilityAnchor,
        MdObservationRevision,
        Observation,
        ObservationQuality,
        ResolvedMarketDataQueryContext,
        SemanticRecordKey,
        Sequence,
        datetime,
    )


async def resolve_visibility_anchor(
    self: MarketDataStore,
    *,
    knowledge_cutoff: datetime,
) -> MarketDataVisibilityAnchor:
    """Freeze the complete sealed-receipt boundary at one UTC cutoff.

    The maximum sequence is sampled before identity, calendar, coverage, or
    observation reads.  A later receipt with the same visible timestamp is
    therefore excluded from a continuation even on engines that retain only
    microsecond timestamp precision.
    """
    from app.services.market_data.store import (
        MarketDataStoreError,
        MarketDataVisibilityAnchor,
        MdPublication,
        _require_aware_utc,
        func,
        select,
    )

    cutoff = _require_aware_utc(knowledge_cutoff, field_name="knowledge_cutoff")
    missing_sequence = await self._db.scalar(
        select(MdPublication.id)
        .where(
            MdPublication.published_at.is_not(None),
            MdPublication.published_at <= cutoff,
            MdPublication.visibility_sequence.is_(None),
        )
        .limit(1)
    )
    if missing_sequence is not None:
        raise MarketDataStoreError("PUBLICATION_VISIBILITY_INTEGRITY")
    max_sequence = await self._db.scalar(
        select(func.max(MdPublication.visibility_sequence)).where(
            MdPublication.published_at.is_not(None),
            MdPublication.published_at <= cutoff,
            MdPublication.visibility_sequence.is_not(None),
        )
    )
    if max_sequence is None:
        return MarketDataVisibilityAnchor(
            visible_at=cutoff,
            max_visibility_sequence=0,
        )
    if not isinstance(max_sequence, int) or isinstance(max_sequence, bool) or max_sequence < 1:
        raise MarketDataStoreError("PUBLICATION_VISIBILITY_INTEGRITY")
    return MarketDataVisibilityAnchor(
        visible_at=cutoff,
        max_visibility_sequence=max_sequence,
    )


async def read_b2_completeness_evidence(
    self: MarketDataStore,
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
    from app.services.market_data.store import (
        PUBLICATION_B2_COMPLETENESS_RECEIPT,
        PUBLICATION_SOURCE_SNAPSHOT,
        SOURCE_AUTHORIZATION_STATE_VERIFIED,
        B2CompletenessEvidenceError,
        B2ReportSelector,
        B2SliceSelector,
        MarketDataStoreError,
        MdB2CompletenessManifestEntry,
        MdB2CompletenessReceipt,
        MdPublication,
        MdSourceSnapshot,
        _assert_context_integrity,
        _normalize_allowed_source_registry_ids,
        _require_aware_utc,
        _verified_source_authorization_registry_id,
        aliased,
        and_,
        assert_b2_source_event_manifest_integrity,
        durable_b2_completeness_evidence_from_receipt,
        select,
    )

    _assert_context_integrity(context)
    if not isinstance(selector, (B2SliceSelector, B2ReportSelector)):
        raise TypeError("selector must be a B2SliceSelector or B2ReportSelector")
    requested_event_at = _require_aware_utc(
        event_at,
        field_name="exact B2 completeness event time",
    )
    allowed_source_ids = _normalize_allowed_source_registry_ids(allowed_source_registry_ids)
    if not allowed_source_ids:
        return None
    if (
        context.query.family_id != selector.family_id
        or context.query.family_contract_version != selector.family_contract_version
    ):
        raise MarketDataStoreError("B2_COMPLETENESS_SELECTOR_CONTEXT_MISMATCH")
    if not context.query.start <= requested_event_at < context.query.end:
        raise MarketDataStoreError("B2_COMPLETENESS_EVENT_OUT_OF_WINDOW")
    anchor = await self._resolve_visibility_anchor(
        knowledge_cutoff=knowledge_cutoff,
        visibility_anchor=visibility_anchor,
    )
    series = await self.get_series(context)
    if series is None:
        return None

    b2_publication = aliased(MdPublication)
    source_publication = aliased(MdPublication)
    rows = list(
        (
            await self._db.execute(
                select(MdB2CompletenessReceipt, MdSourceSnapshot)
                .join(
                    MdSourceSnapshot,
                    MdSourceSnapshot.id == MdB2CompletenessReceipt.source_snapshot_id,
                )
                .join(
                    b2_publication,
                    and_(
                        b2_publication.entity_type == PUBLICATION_B2_COMPLETENESS_RECEIPT,
                        b2_publication.entity_id == MdB2CompletenessReceipt.id,
                        b2_publication.entity_sha256 == MdB2CompletenessReceipt.receipt_sha256,
                    ),
                )
                .join(
                    source_publication,
                    and_(
                        source_publication.entity_type == PUBLICATION_SOURCE_SNAPSHOT,
                        source_publication.entity_id == MdSourceSnapshot.id,
                        source_publication.entity_sha256 == MdSourceSnapshot.payload_sha256,
                    ),
                )
                .where(
                    MdB2CompletenessReceipt.series_id == series.id,
                    MdB2CompletenessReceipt.family_id == selector.family_id,
                    MdB2CompletenessReceipt.family_contract_version
                    == selector.family_contract_version,
                    MdB2CompletenessReceipt.event_at == requested_event_at,
                    MdB2CompletenessReceipt.selector_digest == selector.selector_digest,
                    MdSourceSnapshot.source_id.in_(sorted(allowed_source_ids)),
                    MdSourceSnapshot.source_authorization_state
                    == SOURCE_AUTHORIZATION_STATE_VERIFIED,
                    b2_publication.published_at.is_not(None),
                    b2_publication.visibility_sequence.is_not(None),
                    b2_publication.published_at <= anchor.visible_at,
                    b2_publication.visibility_sequence <= anchor.max_visibility_sequence,
                    source_publication.published_at.is_not(None),
                    source_publication.visibility_sequence.is_not(None),
                    source_publication.published_at <= anchor.visible_at,
                    source_publication.visibility_sequence <= anchor.max_visibility_sequence,
                )
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).all()
    )
    if not rows:
        return None
    if len(rows) != 1:
        raise MarketDataStoreError("B2_COMPLETENESS_EVIDENCE_INTEGRITY")
    receipt, source_snapshot = rows[0]
    try:
        source_registry_id = _verified_source_authorization_registry_id(
            source_snapshot,
            context=context,
        )
    except MarketDataStoreError:
        return None
    if source_registry_id not in allowed_source_ids:
        return None

    entry_hashes = tuple(
        (
            await self._db.execute(
                select(MdB2CompletenessManifestEntry.semantic_record_key_sha256)
                .where(MdB2CompletenessManifestEntry.receipt_id == receipt.id)
                .order_by(MdB2CompletenessManifestEntry.semantic_record_key_sha256)
                .with_for_update()
            )
        ).scalars()
    )
    try:
        evidence = durable_b2_completeness_evidence_from_receipt(receipt, entry_hashes)
        if (
            type(evidence.selector) is not type(selector)
            or evidence.selector.selector_digest != selector.selector_digest
        ):
            raise B2CompletenessEvidenceError("B2_COMPLETENESS_RECEIPT_INVALID")
        expected_hashes = evidence.selector.expected_record_key_sha256s
        if expected_hashes is None:
            raise B2CompletenessEvidenceError("B2_COMPLETENESS_RECEIPT_INVALID")
        await assert_b2_source_event_manifest_integrity(
            self._db,
            series_id=receipt.series_id,
            source_snapshot_id=receipt.source_snapshot_id,
            event_at=evidence.event_at,
            expected_hashes=expected_hashes,
        )
    except (B2CompletenessEvidenceError, TypeError, ValueError) as exc:
        raise MarketDataStoreError("B2_COMPLETENESS_EVIDENCE_INTEGRITY") from exc
    return evidence


async def read_observation_revisions(
    self: MarketDataStore,
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
    from app.services.market_data.store import (
        PUBLICATION_SOURCE_SNAPSHOT,
        SOURCE_AUTHORIZATION_STATE_VERIFIED,
        MarketDataStoreError,
        MdObservationRevision,
        MdPublication,
        MdSourceSnapshot,
        _assert_context_integrity,
        _decode_local_revision,
        _is_visibility_sequence,
        _normalize_allowed_source_registry_ids,
        _publication_is_visible_at_anchor,
        _record_revision_output_sort_key,
        _require_aware_utc,
        _require_text,
        _revision_is_usable_for_fields,
        _revision_sort_key,
        _stored_utc,
        _verified_source_authorization_registry_id,
        and_,
        select,
    )

    _assert_context_integrity(context)
    allowed_source_ids = _normalize_allowed_source_registry_ids(allowed_source_registry_ids)
    if allowed_source_ids is not None and not allowed_source_ids:
        return ()
    requested_event_at = (
        _require_aware_utc(exact_event_at, field_name="exact local observation event time")
        if exact_event_at is not None
        else None
    )
    requested_source_snapshot_id = (
        _require_text(
            exact_source_snapshot_id,
            field_name="exact local observation source snapshot",
            maximum=36,
        )
        if exact_source_snapshot_id is not None
        else None
    )
    if requested_event_at is not None and not (
        context.query.start <= requested_event_at < context.query.end
    ):
        raise MarketDataStoreError("LOCAL_OBSERVATION_EVENT_OUT_OF_WINDOW")
    anchor = await self._resolve_visibility_anchor(
        knowledge_cutoff=knowledge_cutoff,
        visibility_anchor=visibility_anchor,
    )
    series = await self.get_series(context)
    if series is None:
        return ()

    query = context.query
    event_predicates = (
        (MdObservationRevision.event_time == requested_event_at,)
        if requested_event_at is not None
        else (
            MdObservationRevision.event_time >= query.start,
            MdObservationRevision.event_time < query.end,
        )
    )
    statement = (
        select(
            MdObservationRevision,
            MdSourceSnapshot,
            MdPublication.published_at,
            MdPublication.visibility_sequence,
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
        .where(
            MdObservationRevision.series_id == series.id,
            *event_predicates,
            MdPublication.entity_sha256 == MdSourceSnapshot.payload_sha256,
            MdPublication.published_at.is_not(None),
            MdPublication.visibility_sequence.is_not(None),
            _publication_is_visible_at_anchor(anchor),
        )
        .order_by(
            MdObservationRevision.event_time,
            MdObservationRevision.semantic_record_key,
            MdPublication.published_at,
            MdPublication.visibility_sequence,
            MdObservationRevision.revision_number,
            MdObservationRevision.id,
        )
    )
    if allowed_source_ids is not None:
        # A valid source ID alone is not enough: rows imported through an
        # explicit compatibility path and rows written before authorization
        # receipts existed cannot become v2 facts merely because a current
        # provider happens to use the same identifier.
        statement = statement.where(
            MdSourceSnapshot.source_id.in_(sorted(allowed_source_ids)),
            MdSourceSnapshot.source_authorization_state == SOURCE_AUTHORIZATION_STATE_VERIFIED,
        ).execution_options(populate_existing=True)
    if requested_source_snapshot_id is not None:
        statement = statement.where(
            MdObservationRevision.source_snapshot_id == requested_source_snapshot_id
        )
    rows = list((await self._db.execute(statement)).all())

    selected_usable: dict[tuple[datetime, str], LocalObservationRevision] = {}
    selected_fallback: dict[tuple[datetime, str], LocalObservationRevision] = {}
    verified_source_registry_ids: dict[str, str | None] = {}
    for row, source_snapshot, published_at, visibility_sequence in rows:
        if published_at is None or not _is_visibility_sequence(visibility_sequence):
            raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY")
        if allowed_source_ids is not None:
            source_registry_id = verified_source_registry_ids.get(source_snapshot.id)
            if source_snapshot.id not in verified_source_registry_ids:
                try:
                    source_registry_id = _verified_source_authorization_registry_id(
                        source_snapshot,
                        context=context,
                    )
                except MarketDataStoreError:
                    # A raw/internal write must not turn a syntactically
                    # populated state column into a v2 fact. Compatibility,
                    # legacy, and structurally forged receipts remain absent
                    # from the authorization-filtered local response.
                    source_registry_id = None
                verified_source_registry_ids[source_snapshot.id] = source_registry_id
            if source_registry_id not in allowed_source_ids:
                continue
        local = _decode_local_revision(
            row,
            context=context,
            visibility_anchor=anchor,
            published_at=_stored_utc(published_at, field_name="publication published_at"),
            visibility_sequence=visibility_sequence,
        )
        record_coordinate = (local.event_at, local.semantic_record_key_sha256)
        current_fallback = selected_fallback.get(record_coordinate)
        if current_fallback is None or _revision_sort_key(local) > _revision_sort_key(
            current_fallback
        ):
            selected_fallback[record_coordinate] = local
        if not _revision_is_usable_for_fields(local, context.query.required_fields):
            continue
        current_usable = selected_usable.get(record_coordinate)
        if current_usable is None or _revision_sort_key(local) > _revision_sort_key(current_usable):
            selected_usable[record_coordinate] = local
    if include_unusable_for_coverage:
        return tuple(
            sorted(
                (
                    selected_usable.get(coordinate, selected_fallback[coordinate])
                    for coordinate in selected_fallback
                ),
                key=_record_revision_output_sort_key,
            )
        )
    return tuple(sorted(selected_usable.values(), key=_record_revision_output_sort_key))


async def _resolve_visibility_anchor(
    self: MarketDataStore,
    *,
    knowledge_cutoff: datetime,
    visibility_anchor: MarketDataVisibilityAnchor | None,
) -> MarketDataVisibilityAnchor:
    """Use a cursor's signed anchor or resolve one exactly once for a read."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        MarketDataVisibilityAnchor,
        _require_aware_utc,
    )

    cutoff = _require_aware_utc(knowledge_cutoff, field_name="knowledge_cutoff")
    if visibility_anchor is None:
        return await self.resolve_visibility_anchor(knowledge_cutoff=cutoff)
    if not isinstance(visibility_anchor, MarketDataVisibilityAnchor):
        raise TypeError("visibility_anchor must be a MarketDataVisibilityAnchor")
    if visibility_anchor.visible_at != cutoff:
        raise MarketDataStoreError("VISIBILITY_ANCHOR_CUTOFF_MISMATCH")
    return visibility_anchor


async def read_observations(
    self: MarketDataStore,
    context: ResolvedMarketDataQueryContext,
    *,
    knowledge_cutoff: datetime,
    visibility_anchor: MarketDataVisibilityAnchor | None = None,
    allowed_source_registry_ids: frozenset[str] | None = None,
) -> tuple[Observation, ...]:
    """Return local observations in the pure shape expected by coverage planning."""
    revisions = await self.read_observation_revisions(
        context,
        knowledge_cutoff=knowledge_cutoff,
        visibility_anchor=visibility_anchor,
        include_unusable_for_coverage=True,
        allowed_source_registry_ids=allowed_source_registry_ids,
    )
    return tuple(item.as_coverage_observation(context) for item in revisions)


def _revision_source_available_at(
    row: MdObservationRevision,
    *,
    available_at: datetime,
) -> datetime:
    """Recover one upstream availability claim without weakening local PIT evidence."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        _json_safe_mapping,
        _parse_timestamp,
    )

    try:
        provenance = _json_safe_mapping(
            row.provenance_json,
            field_name="persisted observation provenance",
        )
        raw_source_available_at = provenance.get("provider_available_at")
        if not isinstance(raw_source_available_at, str):
            raise ValueError("provider_available_at must be an ISO-8601 string")
        source_available_at = _parse_timestamp(
            raw_source_available_at,
            field_name="provider_available_at",
        )
    except (MarketDataStoreError, TypeError, ValueError) as exc:
        raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY") from exc
    if source_available_at > available_at:
        raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY")
    return source_available_at


def _observation_revision_identity_sha256(
    *,
    contract_version: str,
    series_semantic_key_sha256: str,
    source_snapshot_id: str,
    event_at: datetime,
    available_at: datetime,
    fields_sha256: str,
    quality: ObservationQuality,
    revision_number: int,
    source_available_at: datetime | None,
    semantic_record_key_sha256: str | None = None,
) -> str:
    """Build the immutable identity for one normalized observation revision."""
    from app.services.market_data.store import (
        _OBSERVATION_REVISION_CONTRACT_V1,
        _OBSERVATION_REVISION_CONTRACT_V2,
        _OBSERVATION_REVISION_CONTRACT_V3,
        MarketDataStoreError,
        _canonical_json,
        _require_sha256_digest,
        _sha256,
    )

    revision_payload: dict[str, object] = {
        "revision_contract_version": contract_version,
        "series_semantic_key_sha256": series_semantic_key_sha256,
        "source_snapshot_id": source_snapshot_id,
        "event_at": event_at.isoformat(),
        "available_at": available_at.isoformat(),
        "fields_sha256": fields_sha256,
        "quality_status": quality.value,
        "revision_number": revision_number,
    }
    if contract_version in {
        _OBSERVATION_REVISION_CONTRACT_V2,
        _OBSERVATION_REVISION_CONTRACT_V3,
    }:
        if source_available_at is None:
            raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY")
        revision_payload["provider_available_at"] = source_available_at.isoformat()
    elif contract_version != _OBSERVATION_REVISION_CONTRACT_V1:
        raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY")
    if contract_version == _OBSERVATION_REVISION_CONTRACT_V3:
        revision_payload["semantic_record_key_sha256"] = _require_sha256_digest(
            semantic_record_key_sha256,
            code="LOCAL_OBSERVATION_INTEGRITY",
        )
    elif semantic_record_key_sha256 is not None:
        raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY")
    return _sha256(_canonical_json(revision_payload, field_name="revision identity"))


def _persisted_semantic_record_key(row: MdObservationRevision) -> SemanticRecordKey:
    """Recover and revalidate one immutable server-owned record identity."""
    from app.services.market_data.store import (
        SINGLE_RECORD_SEMANTIC_KEY_CANONICAL_JSON,
        Mapping,
        MarketDataStoreError,
        SemanticRecordKey,
        json,
    )

    raw_canonical_json = row.semantic_record_key
    raw_sha256 = row.semantic_record_key_sha256
    try:
        if not isinstance(raw_canonical_json, str):
            raise TypeError("semantic_record_key must be a string")
        payload = json.loads(raw_canonical_json)
        if not isinstance(payload, Mapping):
            raise ValueError("semantic_record_key must decode to an object")
        if raw_canonical_json == SINGLE_RECORD_SEMANTIC_KEY_CANONICAL_JSON:
            return SemanticRecordKey(
                canonical_json=raw_canonical_json,
                sha256=raw_sha256,
                dimensions={},
                is_singleton=True,
            )
        raw_dimensions = payload.get("dimensions")
        if not isinstance(raw_dimensions, Mapping):
            raise ValueError("semantic_record_key dimensions must decode to an object")
        return SemanticRecordKey(
            canonical_json=raw_canonical_json,
            sha256=raw_sha256,
            dimensions=raw_dimensions,
            is_singleton=False,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY") from exc


def _verified_revision_source_available_at(
    row: MdObservationRevision,
    *,
    context: ResolvedMarketDataQueryContext,
    event_at: datetime,
    available_at: datetime,
    fields_sha256: str,
    quality: ObservationQuality,
    revision_number: int,
    semantic_record_key: SemanticRecordKey,
) -> datetime | None:
    """Return a sealed source timestamp after validating the immutable identity.

    V1/V2 facts predate record-key sealing and remain valid only for the
    singleton identity supplied by the migration.  Every new V3 fact binds its
    semantic key digest, including new single-record writes.
    """
    from app.services.market_data.store import (
        _OBSERVATION_REVISION_CONTRACT_V1,
        _OBSERVATION_REVISION_CONTRACT_V2,
        _OBSERVATION_REVISION_CONTRACT_V3,
        MarketDataStore,
        MarketDataStoreError,
        _observation_revision_identity_sha256,
        _revision_source_available_at,
    )

    series_semantic_key_sha256 = MarketDataStore.series_identity(context).semantic_key_sha256
    if semantic_record_key.is_singleton:
        v1_identity = _observation_revision_identity_sha256(
            contract_version=_OBSERVATION_REVISION_CONTRACT_V1,
            series_semantic_key_sha256=series_semantic_key_sha256,
            source_snapshot_id=row.source_snapshot_id,
            event_at=event_at,
            available_at=available_at,
            fields_sha256=fields_sha256,
            quality=quality,
            revision_number=revision_number,
            source_available_at=None,
        )
        if row.revision_key_sha256 == v1_identity:
            # The v1 contract did not bind provider availability.  Even a
            # syntactically valid timestamp in its free-form provenance is not
            # a verified source fact and must stay unavailable to strict
            # consumers.
            return None

        source_available_at = _revision_source_available_at(row, available_at=available_at)
        v2_identity = _observation_revision_identity_sha256(
            contract_version=_OBSERVATION_REVISION_CONTRACT_V2,
            series_semantic_key_sha256=series_semantic_key_sha256,
            source_snapshot_id=row.source_snapshot_id,
            event_at=event_at,
            available_at=available_at,
            fields_sha256=fields_sha256,
            quality=quality,
            revision_number=revision_number,
            source_available_at=source_available_at,
        )
        if row.revision_key_sha256 == v2_identity:
            return source_available_at
    else:
        source_available_at = _revision_source_available_at(row, available_at=available_at)

    v3_identity = _observation_revision_identity_sha256(
        contract_version=_OBSERVATION_REVISION_CONTRACT_V3,
        series_semantic_key_sha256=series_semantic_key_sha256,
        source_snapshot_id=row.source_snapshot_id,
        event_at=event_at,
        available_at=available_at,
        fields_sha256=fields_sha256,
        quality=quality,
        revision_number=revision_number,
        source_available_at=source_available_at,
        semantic_record_key_sha256=semantic_record_key.sha256,
    )
    if row.revision_key_sha256 != v3_identity:
        raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY")
    return source_available_at


def _decode_local_revision(
    row: MdObservationRevision,
    *,
    context: ResolvedMarketDataQueryContext,
    visibility_anchor: MarketDataVisibilityAnchor,
    published_at: datetime,
    visibility_sequence: int,
) -> LocalObservationRevision:
    """Validate a persisted row before it can contribute local coverage."""
    from app.services.market_data.store import (
        LocalObservationRevision,
        MappingProxyType,
        MarketDataStoreError,
        ObservationQuality,
        _canonical_json,
        _is_visibility_sequence,
        _json_safe_mapping,
        _persisted_semantic_record_key,
        _sha256,
        _stored_utc,
        _verified_revision_source_available_at,
    )

    event_at = _stored_utc(row.event_time, field_name="observation event_time")
    available_at = _stored_utc(row.available_at, field_name="observation available_at")
    # ``row.committed_at`` records receipt processing time from the legacy
    # immutable evidence shape. The publication receipt is the only trusted
    # local visibility boundary for a strict replay.
    committed_at = _stored_utc(published_at, field_name="publication published_at")
    if not context.query.start <= event_at < context.query.end:
        raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY")
    if not _is_visibility_sequence(visibility_sequence) or not visibility_anchor.permits(
        visible_at=committed_at,
        visibility_sequence=visibility_sequence,
    ):
        raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY")
    try:
        quality = ObservationQuality(row.quality_status)
        fields = _json_safe_mapping(row.fields_json, field_name="persisted observation fields")
    except (MarketDataStoreError, ValueError) as exc:
        raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY") from exc
    if (
        _sha256(_canonical_json(fields, field_name="persisted observation fields"))
        != row.fields_sha256
    ):
        raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY")
    if not isinstance(row.revision_number, int) or row.revision_number < 1:
        raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY")
    semantic_record_key = _persisted_semantic_record_key(row)
    source_available_at = _verified_revision_source_available_at(
        row,
        context=context,
        event_at=event_at,
        available_at=available_at,
        fields_sha256=row.fields_sha256,
        quality=quality,
        revision_number=row.revision_number,
        semantic_record_key=semantic_record_key,
    )
    return LocalObservationRevision(
        revision_id=row.id,
        source_snapshot_id=row.source_snapshot_id,
        event_at=event_at,
        available_at=available_at,
        committed_at=committed_at,
        visible_at=committed_at,
        visibility_sequence=visibility_sequence,
        revision_number=row.revision_number,
        quality=quality,
        semantic_record_key=semantic_record_key.canonical_json,
        semantic_record_key_sha256=semantic_record_key.sha256,
        fields=MappingProxyType(fields),
        source_available_at=source_available_at,
    )


def _publication_is_visible_at_anchor(anchor: MarketDataVisibilityAnchor):
    """Build the portable complete-boundary predicate for one PIT anchor.

    The timestamp is a ceiling and the globally monotonic sequence is a
    separate ceiling.  Both are necessary: a client may ask for a future
    historical cutoff, and a subsequent receipt can retain an earlier
    timestamp while still receiving a later global sequence.
    """
    from app.services.market_data.store import (
        MdPublication,
        and_,
    )

    return and_(
        MdPublication.published_at <= anchor.visible_at,
        MdPublication.visibility_sequence <= anchor.max_visibility_sequence,
    )


def _revision_is_usable_for_fields(
    revision: LocalObservationRevision,
    required_fields: Sequence[str],
) -> bool:
    """Return whether a persisted revision can satisfy this field projection."""
    from app.services.market_data.store import (
        ObservationQuality,
        is_usable_field_value,
    )

    return revision.quality is ObservationQuality.PASS and all(
        is_usable_field_value(field_name, revision.fields.get(field_name))
        for field_name in required_fields
    )


def _revision_sort_key(revision: LocalObservationRevision) -> tuple[int, int, str]:
    """Order selected revisions by sealed receipt, ordinal, then immutable ID."""
    return (
        revision.visibility_sequence,
        revision.revision_number,
        revision.revision_id,
    )


def _record_revision_output_sort_key(
    revision: LocalObservationRevision,
) -> tuple[datetime, str, int, str]:
    """Keep B2/PIT output stable across equal-timestamp business records."""
    return (
        revision.event_at,
        revision.semantic_record_key,
        revision.revision_number,
        revision.revision_id,
    )
