"""Persist provider facts and enforce the two-transaction publication handoff."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.market_data.store import (
        Awaitable,
        Callable,
        DeferredProviderFetch,
        DgProvider,
        MarketDataDeferredPublicationIntent,
        MarketDataFetchLeaseHandle,
        MarketDataSourceAuthorization,
        MarketDataStore,
        MdDataSeries,
        MdObservationRevision,
        MdSourcePayload,
        MdSourceSnapshot,
        PersistedProviderFetch,
        ProviderFetchResult,
        ResolvedMarketDataQueryContext,
        Select,
        Sequence,
        SeriesIdentity,
        _ValidatedProviderFetch,
        _ValidatedProviderObservation,
        _ValidatedSharedSourcePayload,
        _ValidatedSourceAuthorization,
        datetime,
    )


async def persist_provider_result(
    self: MarketDataStore,
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
    from app.services.market_data.store import (
        PUBLICATION_SOURCE_SNAPSHOT,
        DeferredProviderFetch,
        IntegrityError,
        MarketDataDeferredPublicationIntent,
        MarketDataFetchLeaseError,
        MarketDataFetchLeaseHandle,
        MarketDataPublicationError,
        MarketDataStoreError,
        MdSourceSnapshotPayloadRef,
        ObservationQuality,
        OperationalError,
        PersistedProviderFetch,
        _assert_writable_context,
        _require_aware_utc,
        _validate_provider_fetch,
        assert_fetch_lease_held_in_transaction,
    )

    _assert_writable_context(context)
    if fetch_lease is not None and not isinstance(fetch_lease, MarketDataFetchLeaseHandle):
        raise TypeError("fetch_lease must be a MarketDataFetchLeaseHandle")
    if deferred_intent is not None and not isinstance(
        deferred_intent, MarketDataDeferredPublicationIntent
    ):
        raise TypeError("deferred_intent must be a MarketDataDeferredPublicationIntent")
    local_received_at = _require_aware_utc(
        received_at or self._clock(),
        field_name="local receipt timestamp",
    )
    validated = _validate_provider_fetch(
        context,
        result,
        local_received_at=local_received_at,
    )
    provider = await self._require_active_provider(result.provider_id)
    authorization = await self._validate_source_authorization(
        context,
        result,
        source_authorization,
        local_received_at=local_received_at,
        unverified_compatibility_reason=unverified_compatibility_reason,
    )

    try:
        # Renew the owner row before staging facts, but within the same
        # short outer transaction that will commit them. This makes a
        # stale owner fail before it can even flush a pending receipt, and
        # the conditional row update prevents a takeover until the fact
        # transaction commits or rolls back.
        if fetch_lease is not None:
            await assert_fetch_lease_held_in_transaction(
                self._db,
                fetch_lease,
                clock=self._clock if self._clock_is_test_override else None,
            )
        async with self._db.begin_nested():
            series = await self.get_or_create_series(context)
            series = await self._lock_series_for_revision(series, context)
            validated_payload = validated.shared_source_payload
            shared_source_payload = (
                await self._get_or_create_shared_source_payload(validated_payload)
                if validated_payload is not None
                else None
            )
            source_snapshot = self._make_source_snapshot(
                context,
                provider,
                result,
                validated,
                source_authorization=authorization,
                local_received_at=local_received_at,
                fetch_lease=fetch_lease,
                shared_source_payload=shared_source_payload,
            )
            self._db.add(source_snapshot)
            await self._db.flush()
            if shared_source_payload is not None and validated_payload is not None:
                self._db.add(
                    MdSourceSnapshotPayloadRef(
                        source_snapshot_id=source_snapshot.id,
                        content_sha256=shared_source_payload.content_sha256,
                        payload_role=validated_payload.payload_role,
                    )
                )
                await self._db.flush()
            publication = await self._publications.stage(
                entity_type=PUBLICATION_SOURCE_SNAPSHOT,
                entity_id=source_snapshot.id,
                entity_sha256=source_snapshot.payload_sha256,
            )

            revision_numbers = await self._next_revision_numbers(
                series_id=series.id,
                record_coordinates=tuple(
                    (item.event_at, item.semantic_record_key.sha256)
                    for item in validated.observations
                ),
            )
            revisions = [
                self._make_observation_revision(
                    series=series,
                    source_snapshot=source_snapshot,
                    result=result,
                    observation=observation,
                    revision_number=revision_numbers[
                        (observation.event_at, observation.semantic_record_key.sha256)
                    ],
                    local_received_at=local_received_at,
                )
                for observation in validated.observations
            ]
            self._db.add_all(revisions)
            await self._db.flush()
            if deferred_intent is not None:
                await self._publications.hold_staged_source_snapshot(
                    publication=publication,
                    source_snapshot_id=source_snapshot.id,
                    intent=deferred_intent,
                )
    except MarketDataFetchLeaseError as exc:
        if self._db.in_transaction():
            await self._db.rollback()
        raise MarketDataStoreError(exc.code) from exc
    except IntegrityError as exc:
        if self._db.in_transaction():
            await self._db.rollback()
        raise MarketDataStoreError("OBSERVATION_WRITE_FAILED") from exc
    except OperationalError as exc:
        if self._db.in_transaction():
            await self._db.rollback()
        raise MarketDataStoreError("OBSERVATION_WRITE_CONFLICT") from exc

    try:
        # The actual data transaction must finish before a trusted local
        # visibility instant is sampled.  Query-service callers never mix
        # unrelated writes into this session; a separate API transaction
        # remains the boundary for any future mixed workflow.
        await self._db.commit()
    except MarketDataFetchLeaseError as exc:
        if self._db.in_transaction():
            await self._db.rollback()
        raise MarketDataStoreError(exc.code) from exc
    except OperationalError as exc:
        if self._db.in_transaction():
            await self._db.rollback()
        raise MarketDataStoreError("OBSERVATION_PUBLICATION_FAILED") from exc

    if deferred_intent is not None:
        return DeferredProviderFetch(
            series_id=series.id,
            source_snapshot_id=source_snapshot.id,
            publication_id=publication.id,
            observation_revision_ids=tuple(revision.id for revision in revisions),
            passing_observation_count=sum(
                item.quality is ObservationQuality.PASS for item in validated.observations
            ),
            failed_observation_count=sum(
                item.quality is ObservationQuality.FAILED for item in validated.observations
            ),
            local_received_at=local_received_at,
            intent=deferred_intent,
        )

    async def assert_publish_fence() -> None:
        if fetch_lease is not None:
            await assert_fetch_lease_held_in_transaction(
                self._db,
                fetch_lease,
                clock=self._clock if self._clock_is_test_override else None,
            )

    try:
        published_at = await self._publications.publish_staged(
            (publication.id,),
            not_before=local_received_at,
            pre_publish_guard=assert_publish_fence if fetch_lease is not None else None,
            fetch_lease=fetch_lease,
        )
    except MarketDataFetchLeaseError as exc:
        if self._db.in_transaction():
            await self._db.rollback()
        raise MarketDataStoreError(exc.code) from exc
    except (MarketDataPublicationError, OperationalError) as exc:
        if self._db.in_transaction():
            await self._db.rollback()
        raise MarketDataStoreError("OBSERVATION_PUBLICATION_FAILED") from exc

    return PersistedProviderFetch(
        series_id=series.id,
        source_snapshot_id=source_snapshot.id,
        observation_revision_ids=tuple(revision.id for revision in revisions),
        passing_observation_count=sum(
            item.quality is ObservationQuality.PASS for item in validated.observations
        ),
        failed_observation_count=sum(
            item.quality is ObservationQuality.FAILED for item in validated.observations
        ),
        received_at=published_at,
    )


async def stage_provider_result_for_deferred_release(
    self: MarketDataStore,
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
    from app.services.market_data.store import (
        DeferredProviderFetch,
    )

    staged = await self.persist_provider_result(
        context,
        result,
        received_at=received_at,
        source_authorization=source_authorization,
        unverified_compatibility_reason=unverified_compatibility_reason,
        fetch_lease=fetch_lease,
        deferred_intent=deferred_intent,
    )
    if not isinstance(staged, DeferredProviderFetch):
        raise AssertionError("deferred provider write returned a visible receipt")
    return staged


async def promote_deferred_provider_result(
    self: MarketDataStore,
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
    from app.services.market_data.store import (
        DeferredProviderFetch,
        MarketDataDeferredPublicationPromotion,
        MarketDataFetchLeaseError,
        MarketDataPublicationError,
        MarketDataStoreError,
        OperationalError,
        PersistedProviderFetch,
    )

    if not isinstance(staged, DeferredProviderFetch):
        raise TypeError("staged must be a DeferredProviderFetch")
    if not callable(pre_publish_guard):
        raise TypeError("pre_publish_guard must be callable")
    promotion = MarketDataDeferredPublicationPromotion(
        publication_id=staged.publication_id,
        source_snapshot_id=staged.source_snapshot_id,
        workflow_kind=staged.intent.workflow_kind,
        intent_sha256=staged.intent.intent_sha256,
        promotion_evidence_sha256=promotion_evidence_sha256,
    )
    try:
        published_at = await self._publications.promote_deferred_after_attestation(
            (promotion,),
            not_before=staged.local_received_at,
            pre_publish_guard=pre_publish_guard,
            fetch_lease=fetch_lease,
        )
    except MarketDataFetchLeaseError as exc:
        if self._db.in_transaction():
            await self._db.rollback()
        raise MarketDataStoreError(exc.code) from exc
    except (MarketDataPublicationError, OperationalError) as exc:
        if self._db.in_transaction():
            await self._db.rollback()
        code = (
            exc.code
            if isinstance(exc, MarketDataPublicationError)
            else "OBSERVATION_PUBLICATION_FAILED"
        )
        raise MarketDataStoreError(code) from exc
    return PersistedProviderFetch(
        series_id=staged.series_id,
        source_snapshot_id=staged.source_snapshot_id,
        observation_revision_ids=staged.observation_revision_ids,
        passing_observation_count=staged.passing_observation_count,
        failed_observation_count=staged.failed_observation_count,
        received_at=published_at,
    )


async def quarantine_deferred_provider_result(
    self: MarketDataStore,
    staged: DeferredProviderFetch,
    *,
    quarantine_code: str,
) -> None:
    """Record that a staged candidate failed verification without exposing it."""
    from app.services.market_data.store import (
        DeferredProviderFetch,
        MarketDataPublicationError,
        MarketDataStoreError,
    )

    if not isinstance(staged, DeferredProviderFetch):
        raise TypeError("staged must be a DeferredProviderFetch")
    try:
        await self._publications.quarantine_deferred(
            publication_id=staged.publication_id,
            source_snapshot_id=staged.source_snapshot_id,
            intent=staged.intent,
            quarantine_code=quarantine_code,
        )
    except MarketDataPublicationError as exc:
        if self._db.in_transaction():
            await self._db.rollback()
        raise MarketDataStoreError(exc.code) from exc


async def _find_series(
    self: MarketDataStore,
    identity: SeriesIdentity,
    context: ResolvedMarketDataQueryContext,
    *,
    for_update: bool = False,
) -> MdDataSeries | None:
    from app.services.market_data.store import (
        MarketDataStoreError,
        _assert_series_matches_context,
        _series_lookup_statement,
    )

    statement = _series_lookup_statement(
        semantic_key_sha256=identity.semantic_key_sha256,
        for_update=for_update,
    )
    rows = list((await self._db.execute(statement)).scalars().all())
    if len(rows) > 1:
        raise MarketDataStoreError("SERIES_INTEGRITY")
    if not rows:
        return None
    series = rows[0]
    _assert_series_matches_context(series, identity, context)
    return series


async def _get_or_create_shared_source_payload(
    self: MarketDataStore,
    validated: _ValidatedSharedSourcePayload | None,
) -> MdSourcePayload | None:
    """Persist one validated raw response once within the fact transaction.

    The payload cannot be published or queried independently.  It becomes
    reachable only through the source snapshots created in the same outer
    transaction.  A matching content address is revalidated before reuse
    so an unexpected manual/database corruption cannot be hidden by its
    natural-key lookup.
    """
    from app.services.market_data.store import (
        IntegrityError,
        MarketDataStoreError,
        MdSourcePayload,
        _assert_shared_source_payload_matches,
    )

    if validated is None:
        return None

    existing = await self._load_shared_source_payload(validated.content_sha256)
    if existing is not None:
        _assert_shared_source_payload_matches(existing, validated)
        return existing

    payload = MdSourcePayload(
        content_sha256=validated.content_sha256,
        payload_format=validated.payload_format,
        payload_bytes=validated.payload_bytes,
        canonical_payload_bytes=validated.canonical_payload_bytes,
    )
    try:
        # The nested savepoint lets a concurrent identical content write
        # resolve to the committed payload without rolling back the
        # enclosing source-snapshot transaction.  An operational lock is
        # deliberately surfaced as a normal write conflict for a retry.
        async with self._db.begin_nested():
            self._db.add(payload)
            await self._db.flush()
    except IntegrityError:
        existing = await self._load_shared_source_payload(validated.content_sha256)
        if existing is None:
            raise MarketDataStoreError("SHARED_SOURCE_PAYLOAD_WRITE_CONFLICT") from None
        _assert_shared_source_payload_matches(existing, validated)
        return existing
    return payload


async def _load_shared_source_payload(
    self: MarketDataStore, content_sha256: str
) -> MdSourcePayload | None:
    """Re-read a shared blob instead of trusting a long-lived identity map."""
    from app.services.market_data.store import (
        MdSourcePayload,
        select,
    )

    return await self._db.scalar(
        select(MdSourcePayload)
        .where(MdSourcePayload.content_sha256 == content_sha256)
        .execution_options(populate_existing=True)
    )


def _make_source_snapshot(
    self: MarketDataStore,
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
    from app.services.market_data.store import (
        NORMALIZATION_VERSION,
        SOURCE_AUTHORIZATION_STATE_UNVERIFIED_COMPATIBILITY,
        SOURCE_AUTHORIZATION_STATE_VERIFIED,
        MarketDataStoreError,
        MdSourceSnapshot,
        _json_safe_mapping,
        _require_text,
    )

    provider_id = _require_text(result.provider_id, field_name="provider_id", maximum=255)
    platform = _require_text(
        provider_id.split(":", maxsplit=1)[0],
        field_name="provider platform",
        maximum=64,
    )
    source_revision = _require_text(
        result.source_revision,
        field_name="source_revision",
        maximum=128,
    )
    adapter_id = _require_text(f"{platform}.market-data", field_name="adapter_id", maximum=128)
    request_json = _json_safe_mapping(
        {
            "provider_request": result.request.dto_payload,
            "resolved_query": context.query.semantic_payload(),
        },
        field_name="source request",
    )
    payload_manifest: dict[str, object] = {
        "format": "inline-json",
        "raw_payload": dict(validated.raw_payload),
        "observation_count": len(validated.observations),
    }
    if shared_source_payload is not None:
        shared = validated.shared_source_payload
        if shared is None:
            raise MarketDataStoreError("SHARED_SOURCE_PAYLOAD_INTEGRITY_CONFLICT")
        payload_manifest["format"] = "content-addressed-source-batch-v1"
        payload_manifest["receipt_payload"] = dict(shared.receipt_payload)
        payload_manifest.pop("raw_payload")
        payload_manifest["shared_source_payload"] = {
            "content_sha256": shared_source_payload.content_sha256,
            "payload_format": shared_source_payload.payload_format,
            "payload_bytes": shared_source_payload.payload_bytes,
            "payload_role": shared.payload_role,
        }
    provenance: dict[str, object] = {
        "provider_id": provider.provider_id,
        "source_revision": source_revision,
        "provider_retrieved_at": result.retrieved_at.isoformat(),
        "local_received_at": local_received_at.isoformat(),
        "warnings": list(result.warnings),
        "normalization_version": NORMALIZATION_VERSION,
    }
    if source_authorization.state == SOURCE_AUTHORIZATION_STATE_VERIFIED:
        # The mapping originates from the registry-checked normalizer above,
        # rather than from a caller-controlled free-form provenance field.
        provenance["source_authorization"] = dict(source_authorization.provenance)
    elif source_authorization.state == SOURCE_AUTHORIZATION_STATE_UNVERIFIED_COMPATIBILITY:
        provenance["unverified_compatibility"] = dict(source_authorization.provenance)
    else:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_INVALID")
    return MdSourceSnapshot(
        provider_id=provider.id,
        platform=platform,
        source_id=provider_id,
        adapter_id=adapter_id,
        endpoint_version=source_revision,
        request_fingerprint_sha256=context.query.query_fingerprint,
        provider_request_id=validated.provider_request_id,
        provider_request_fingerprint_sha256=(validated.provider_request_fingerprint_sha256),
        query_fingerprint_sha256=validated.query_fingerprint_sha256,
        source_authorization_state=source_authorization.state,
        source_authorization_descriptor_sha256=source_authorization.descriptor_sha256,
        fetch_lease_key_sha256=(fetch_lease.lease_key_sha256 if fetch_lease is not None else None),
        fetch_lease_fence_token=(fetch_lease.fence_token if fetch_lease is not None else None),
        payload_sha256=validated.payload_sha256,
        request_json=request_json,
        payload_manifest_json=_json_safe_mapping(payload_manifest, field_name="payload manifest"),
        provenance_json=_json_safe_mapping(provenance, field_name="source provenance"),
        source_observed_at=result.retrieved_at,
        retrieved_at=local_received_at,
    )


async def _next_revision_numbers(
    self: MarketDataStore,
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
    from app.services.market_data.store import (
        _MAX_CURRENT_REVISION_ROWS_PER_CHUNK,
        _REVISION_COORDINATE_QUERY_CHUNK_SIZE,
        MarketDataStoreError,
        _coordinate_chunks,
        _require_sha256_digest,
        _revision_number_current_read_statement,
        _stored_utc,
    )

    if not record_coordinates:
        return {}
    requested = frozenset(record_coordinates)
    if len(requested) != len(record_coordinates):
        raise MarketDataStoreError("DUPLICATE_PROVIDER_RECORD")
    requested_coordinates = tuple(sorted(requested))
    existing_maximums: dict[tuple[datetime, str], int] = {}
    for coordinate_chunk in _coordinate_chunks(
        requested_coordinates,
        _REVISION_COORDINATE_QUERY_CHUNK_SIZE,
    ):
        # Use a locking/current read after the series lock. Under MySQL's
        # default REPEATABLE READ, the earlier ordinary series lookup may
        # have established an older consistent snapshot; a later plain
        # aggregate could therefore miss a revision committed by the prior
        # holder while this writer waited for the series lock. MySQL does
        # not support a portable aggregate locking read, so read the rows
        # under FOR UPDATE and calculate the bounded maxima in-process.
        rows = (
            await self._db.execute(
                _revision_number_current_read_statement(
                    series_id=series_id,
                    record_coordinates=coordinate_chunk,
                )
            )
        ).all()
        if len(rows) > _MAX_CURRENT_REVISION_ROWS_PER_CHUNK:
            raise MarketDataStoreError("CURRENT_REVISION_READ_LIMIT_EXCEEDED")
        for event_time, semantic_record_key_sha256, revision_number in rows:
            stored_event_at = _stored_utc(event_time, field_name="revision event_time")
            stored_key_sha256 = _require_sha256_digest(
                semantic_record_key_sha256,
                code="LOCAL_OBSERVATION_INTEGRITY",
            )
            coordinate = (stored_event_at, stored_key_sha256)
            if coordinate in requested:
                current_maximum = existing_maximums.get(coordinate, 0)
                existing_maximums[coordinate] = max(current_maximum, int(revision_number))
    return {
        coordinate: existing_maximums.get(coordinate, 0) + 1 for coordinate in record_coordinates
    }


async def _lock_series_for_revision(
    self: MarketDataStore,
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
    from app.services.market_data.store import (
        MarketDataStoreError,
        MdDataSeries,
        _assert_series_matches_context,
        select,
    )

    locked = await self._db.scalar(
        select(MdDataSeries).where(MdDataSeries.id == series.id).with_for_update()
    )
    if locked is None:
        raise MarketDataStoreError("SERIES_WRITE_CONFLICT")
    _assert_series_matches_context(
        locked,
        self.series_identity(context),
        context,
    )
    return locked


def _make_observation_revision(
    *,
    series: MdDataSeries,
    source_snapshot: MdSourceSnapshot,
    result: ProviderFetchResult,
    observation: _ValidatedProviderObservation,
    revision_number: int,
    local_received_at: datetime,
) -> MdObservationRevision:
    from app.services.market_data.store import (
        _OBSERVATION_REVISION_CONTRACT_V3,
        NORMALIZATION_VERSION,
        QUALITY_POLICY_VERSION,
        MdObservationRevision,
        _json_safe_mapping,
        _observation_revision_identity_sha256,
    )

    provenance = {
        "provider_id": result.provider_id,
        "source_revision": result.source_revision,
        "source_snapshot_id": source_snapshot.id,
        "provider_available_at": observation.source_available_at.isoformat(),
        "local_received_at": local_received_at.isoformat(),
    }
    return MdObservationRevision(
        series_id=series.id,
        event_time=observation.event_at,
        available_at=observation.available_at,
        source_snapshot_id=source_snapshot.id,
        quality_status=observation.quality.value,
        quality_policy_version=QUALITY_POLICY_VERSION,
        quality_details_json=dict(observation.quality_details),
        fields_json=dict(observation.fields),
        fields_sha256=observation.fields_sha256,
        revision_number=revision_number,
        revision_key_sha256=_observation_revision_identity_sha256(
            contract_version=_OBSERVATION_REVISION_CONTRACT_V3,
            series_semantic_key_sha256=series.semantic_key_sha256,
            source_snapshot_id=source_snapshot.id,
            event_at=observation.event_at,
            available_at=observation.available_at,
            fields_sha256=observation.fields_sha256,
            quality=observation.quality,
            revision_number=revision_number,
            source_available_at=observation.source_available_at,
            semantic_record_key_sha256=observation.semantic_record_key.sha256,
        ),
        normalization_version=NORMALIZATION_VERSION,
        semantic_record_key=observation.semantic_record_key.canonical_json,
        semantic_record_key_sha256=observation.semantic_record_key.sha256,
        provenance_json=_json_safe_mapping(provenance, field_name="revision provenance"),
        committed_at=local_received_at,
    )


def _coordinate_chunks(
    values: Sequence[tuple[datetime, str]],
    size: int,
) -> tuple[tuple[tuple[datetime, str], ...], ...]:
    """Split exact event/key coordinate pairs below SQLite's bind-value budget."""
    return tuple(tuple(values[index : index + size]) for index in range(0, len(values), size))


def _series_lookup_statement(
    *,
    semantic_key_sha256: str,
    for_update: bool,
) -> Select[tuple[MdDataSeries]]:
    """Build an exact series lookup, using a current read when recovering a race."""
    from app.services.market_data.store import (
        MdDataSeries,
        select,
    )

    statement = select(MdDataSeries).where(MdDataSeries.semantic_key_sha256 == semantic_key_sha256)
    return statement.with_for_update() if for_update else statement


def _revision_number_current_read_statement(
    *,
    series_id: str,
    record_coordinates: Sequence[tuple[datetime, str]],
) -> Select[tuple[datetime, str, int]]:
    """Build the post-series-lock current read used for ordinal allocation.

    The series row is locked before this query, serializing writers for one
    semantic series. ``FOR UPDATE`` additionally makes MySQL/InnoDB evaluate
    this read against the latest committed state rather than an earlier
    REPEATABLE READ snapshot established by a harmless pre-lock lookup. The
    predicate contains each requested event/key coordinate, never every
    historical record for a matching event. A bounded response prevents one
    pathological correction history from turning ordinal allocation into an
    unbounded materialization; callers fail before writing a new receipt.
    """
    from app.services.market_data.store import (
        _MAX_CURRENT_REVISION_ROWS_PER_CHUNK,
        MdObservationRevision,
        select,
        tuple_,
    )

    return (
        select(
            MdObservationRevision.event_time,
            MdObservationRevision.semantic_record_key_sha256,
            MdObservationRevision.revision_number,
        )
        .where(
            MdObservationRevision.series_id == series_id,
            tuple_(
                MdObservationRevision.event_time,
                MdObservationRevision.semantic_record_key_sha256,
            ).in_(record_coordinates),
        )
        .order_by(
            MdObservationRevision.event_time,
            MdObservationRevision.semantic_record_key_sha256,
            MdObservationRevision.revision_number.desc(),
        )
        .limit(_MAX_CURRENT_REVISION_ROWS_PER_CHUNK + 1)
        .with_for_update()
    )
