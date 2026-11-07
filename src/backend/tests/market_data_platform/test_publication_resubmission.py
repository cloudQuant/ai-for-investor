"""Duplicate-resubmission contracts for the Iteration 204 AC06 publication plane.

AC06 states that resubmitting one already-submitted batch must not duplicate a
fact.  The production publication layer keys a batch on
``(entity_type, entity_id)`` (``uq_md_publication_entity``) and binds its
payload with ``entity_sha256``; ``MdVisibilitySequenceAllocator`` is the single
global counter that a seal may consume.  These tests replay that exact key
through the real manager, the real provider-persist path and the real calendar
batch importer, and they assert the counter is not advanced a second time.

Every helper below returns plain scalars rather than ORM instances, because a
publication call requires the caller session to hold no open transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy import ScalarResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session_maker
from app.db.persistence_boundaries import optional_stored_utc
from app.models.asset_research import AssetDataSourceRegistry
from app.models.market_data_platform import (
    MdCalendarEvent,
    MdCalendarSnapshot,
    MdObservationRevision,
    MdPublication,
    MdSourceSnapshot,
    MdVisibilitySequenceAllocator,
)
from app.services.market_data.calendar_importer import MarketDataCalendarImporter
from app.services.market_data.publication import (
    PUBLICATION_CALENDAR_SNAPSHOT,
    PUBLICATION_SOURCE_SNAPSHOT,
    MarketDataPublicationError,
    MarketDataPublicationManager,
)
from app.services.market_data.store import (
    UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
    MarketDataStore,
    PersistedProviderFetch,
)
from tests.market_data_platform.test_calendar_importer import _manifest
from tests.market_data_platform.test_store import (
    _at,
    _context,
    _observation,
    _result,
    _seed_dataset_and_provider,
    _sha,
)

UTC = timezone.utc
CALENDAR_SOURCE_ID = "akshare"


@pytest.fixture(autouse=True)
async def seed_calendar_source_registry() -> None:
    """The reviewed calendar batch path names an explicit governed source."""
    async with async_session_maker() as session:
        session.add(
            AssetDataSourceRegistry(
                source_id=CALENDAR_SOURCE_ID,
                asset_types=["stock"],
                jurisdictions=["CN"],
                license_status="APPROVED",
                allowed_uses=["DISPLAY"],
                redistribution_policy="NO_REDISTRIBUTION",
                derived_data_policy="ALLOWED",
                retention_policy="market-data-v1",
                effective_from=datetime(2020, 1, 1, tzinfo=UTC),
                effective_to=None,
                retention_expires_at=None,
                enabled=True,
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()


@dataclass(frozen=True, slots=True)
class _ReceiptState:
    """The scalars that identify one receipt and its visibility seal."""

    publication_id: str
    entity_id: str
    entity_sha256: str
    published_at: datetime | None
    visibility_sequence: int | None


async def _read_scalar(db: AsyncSession, statement) -> object:
    """Run one aggregate read and leave no transaction behind for a publisher."""
    value = await db.scalar(statement)
    await db.rollback()
    return value


async def _receipt_state(db: AsyncSession, publication_id: str) -> _ReceiptState:
    """Re-read a receipt from the database rather than from a cached ORM object."""
    row = (
        await db.execute(
            select(
                MdPublication.entity_id,
                MdPublication.entity_sha256,
                MdPublication.published_at,
                MdPublication.visibility_sequence,
            ).where(MdPublication.id == publication_id)
        )
    ).one()
    await db.rollback()
    return _ReceiptState(
        publication_id=publication_id,
        entity_id=row[0],
        entity_sha256=row[1],
        published_at=optional_stored_utc(row[2]),
        visibility_sequence=row[3],
    )


async def _allocator_next_sequence(db: AsyncSession) -> int | None:
    """Read the single global visibility counter as it is durably stored."""
    return await _read_scalar(
        db,
        select(MdVisibilitySequenceAllocator.next_visibility_sequence).where(
            MdVisibilitySequenceAllocator.singleton_id == 1
        ),
    )


async def _persist_one_batch(
    db: AsyncSession,
    *,
    source_revision: str,
    event_hour: int,
) -> tuple[MarketDataStore, PersistedProviderFetch, _ReceiptState]:
    """Run the real provider-persist path for one sealed single-record batch."""
    context = _context()
    store = MarketDataStore(db, clock=lambda: _at(14))
    persisted = await store.persist_provider_result(
        context,
        _result(
            retrieved_at=_at(13),
            source_revision=source_revision,
            context=context,
            observations=(
                _observation(
                    event_at=_at(event_hour),
                    available_at=_at(12),
                    fields={"close": "10.50"},
                ),
            ),
        ),
        received_at=_at(14),
        unverified_compatibility_reason=UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
    )
    publication_id: str = await db.scalar(
        select(MdPublication.id).where(
            MdPublication.entity_type == PUBLICATION_SOURCE_SNAPSHOT,
            MdPublication.entity_id == persisted.source_snapshot_id,
        )
    )
    assert publication_id is not None
    await db.rollback()
    return store, persisted, await _receipt_state(db, publication_id)


@pytest.mark.asyncio
async def test_republishing_a_sealed_batch_identity_creates_no_second_fact_or_sequence() -> None:
    """A retried publish for one batch identity returns the original seal unchanged."""
    context = _context()

    async with async_session_maker() as db:
        await _seed_dataset_and_provider(db)
        store, persisted, sealed = await _persist_one_batch(
            db, source_revision="resubmit-once-v1", event_hour=10
        )
        original_next_sequence = await _allocator_next_sequence(db)
        assert sealed.published_at is not None
        assert sealed.visibility_sequence is not None
        assert original_next_sequence == sealed.visibility_sequence + 1

        replayed_at = await MarketDataPublicationManager(
            db, clock=lambda: _at(23, day=20)
        ).publish_staged((sealed.publication_id,))

        after = await _receipt_state(db, sealed.publication_id)
        publication_count = await _read_scalar(db, select(func.count()).select_from(MdPublication))
        snapshot_count = await _read_scalar(db, select(func.count()).select_from(MdSourceSnapshot))
        revision_count = await _read_scalar(
            db, select(func.count()).select_from(MdObservationRevision)
        )
        next_sequence = await _allocator_next_sequence(db)
        visible = await store.read_observations(context, knowledge_cutoff=_at(20))

    assert persisted.source_snapshot_id == sealed.entity_id
    assert after == sealed
    assert replayed_at == sealed.published_at
    assert publication_count == 1
    assert snapshot_count == 1
    assert revision_count == 1
    # The replay must consume no visibility ordinal at all.
    assert next_sequence == original_next_sequence
    assert len(visible) == 1
    assert visible[0].event_key.event_at == _at(10)


@pytest.mark.asyncio
async def test_restaging_the_same_entity_identity_reuses_the_existing_receipt() -> None:
    """Staging one entity identity twice returns the receipt the first call made."""
    async with async_session_maker() as db:
        await _seed_dataset_and_provider(db)
        _, _, sealed = await _persist_one_batch(
            db, source_revision="restage-same-v1", event_hour=10
        )

        restaged = await MarketDataPublicationManager(db).stage(
            entity_type=PUBLICATION_SOURCE_SNAPSHOT,
            entity_id=sealed.entity_id,
            entity_sha256=sealed.entity_sha256,
        )
        restaged_id = restaged.id
        await db.rollback()

        publication_count = await _read_scalar(
            db,
            select(func.count())
            .select_from(MdPublication)
            .where(MdPublication.entity_type == PUBLICATION_SOURCE_SNAPSHOT),
        )
        after = await _receipt_state(db, sealed.publication_id)

    assert restaged_id == sealed.publication_id
    assert publication_count == 1
    assert after == sealed


@pytest.mark.asyncio
async def test_restaging_one_entity_identity_with_a_different_payload_fails_closed() -> None:
    """A resubmission that renames the payload is rejected, never silently rewritten."""
    async with async_session_maker() as db:
        await _seed_dataset_and_provider(db)
        _, _, sealed = await _persist_one_batch(
            db, source_revision="restage-conflict-v1", event_hour=10
        )

        with pytest.raises(MarketDataPublicationError) as conflict:
            await MarketDataPublicationManager(db).stage(
                entity_type=PUBLICATION_SOURCE_SNAPSHOT,
                entity_id=sealed.entity_id,
                entity_sha256=_sha("a different payload for the same identity"),
            )
        await db.rollback()

        publication_count = await _read_scalar(db, select(func.count()).select_from(MdPublication))
        after = await _receipt_state(db, sealed.publication_id)

    assert conflict.value.code == "PUBLICATION_ENTITY_CONFLICT"
    assert after == sealed
    assert publication_count == 1


@pytest.mark.asyncio
async def test_republishing_a_receipt_whose_entity_digest_drifted_fails_closed() -> None:
    """The publish path refuses to reseal a key whose entity no longer matches."""
    async with async_session_maker() as db:
        await _seed_dataset_and_provider(db)
        _, _, sealed = await _persist_one_batch(
            db, source_revision="entity-drift-v1", event_hour=10
        )
        original_next_sequence = await _allocator_next_sequence(db)

        # Simulate a resubmitted batch that overwrote the immutable entity body
        # while keeping the identity the receipt is keyed on.
        await db.execute(
            update(MdSourceSnapshot)
            .where(MdSourceSnapshot.id == sealed.entity_id)
            .values(payload_sha256=_sha("overwritten payload"))
        )
        await db.commit()

        with pytest.raises(MarketDataPublicationError) as rejected:
            await MarketDataPublicationManager(db, clock=lambda: _at(23, day=20)).publish_staged(
                (sealed.publication_id,)
            )
        await db.rollback()

        after = await _receipt_state(db, sealed.publication_id)
        next_sequence = await _allocator_next_sequence(db)

    assert rejected.value.code == "PUBLICATION_ENTITY_INTEGRITY"
    assert after == sealed
    assert next_sequence == original_next_sequence


@pytest.mark.asyncio
async def test_resubmitting_the_identical_provider_batch_keeps_one_visible_fact_per_record() -> (
    None
):
    """An identical provider receipt replayed twice still reads back as one fact.

    The provider-persist path deliberately has no request-level dedupe: each
    submission is a distinct fetch event and therefore a new immutable source
    snapshot plus the next revision ordinal for the same business record.  The
    AC06 requirement is that no *fact* is duplicated for a reader, so this test
    pins the append-only lineage and the single visible row together.
    """
    context = _context()

    def fetched() -> object:
        return _result(
            retrieved_at=_at(13),
            source_revision="identical-replay-v1",
            context=context,
            observations=(
                _observation(
                    event_at=_at(10),
                    available_at=_at(12),
                    fields={"close": "10.50"},
                ),
            ),
        )

    async with async_session_maker() as db:
        await _seed_dataset_and_provider(db)
        first = await MarketDataStore(db, clock=lambda: _at(14)).persist_provider_result(
            context,
            fetched(),
            received_at=_at(14),
            unverified_compatibility_reason=UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
        )
        second = await MarketDataStore(db, clock=lambda: _at(15)).persist_provider_result(
            context,
            fetched(),
            received_at=_at(15),
            unverified_compatibility_reason=UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
        )

        revision_numbers: ScalarResult = await db.scalars(
            select(MdObservationRevision.revision_number).order_by(
                MdObservationRevision.revision_number
            )
        )
        seen_numbers = tuple(revision_numbers.all())
        publication_count = await _read_scalar(db, select(func.count()).select_from(MdPublication))
        next_sequence = await _allocator_next_sequence(db)
        visible = await MarketDataStore(db).read_observations(context, knowledge_cutoff=_at(20))

    assert first.source_snapshot_id != second.source_snapshot_id
    assert seen_numbers == (1, 2)
    assert publication_count == 2
    assert next_sequence == 3
    assert len(visible) == 1
    assert visible[0].fields["close"] == "10.50"


@pytest.mark.asyncio
async def test_importing_the_same_calendar_batch_twice_seals_one_visibility_receipt() -> None:
    """A replayed reviewed calendar batch reuses its receipt and allocates nothing more."""
    payload = _manifest()

    async with async_session_maker() as db:
        importer = MarketDataCalendarImporter(db, clock=lambda: _at(15))
        first = await importer.import_payload(payload=payload, dry_run=False)
        second = await importer.import_payload(payload=payload, dry_run=False)

        publication_count: int = await _read_scalar(
            db,
            select(func.count())
            .select_from(MdPublication)
            .where(MdPublication.entity_type == PUBLICATION_CALENDAR_SNAPSHOT),
        )
        sequences = list(
            (
                await db.execute(
                    select(MdPublication.visibility_sequence).where(
                        MdPublication.entity_type == PUBLICATION_CALENDAR_SNAPSHOT
                    )
                )
            ).scalars()
        )
        await db.rollback()
        snapshot_count = await _read_scalar(
            db, select(func.count()).select_from(MdCalendarSnapshot)
        )
        event_count = await _read_scalar(db, select(func.count()).select_from(MdCalendarEvent))
        next_sequence = await _allocator_next_sequence(db)

    assert first.action == "created"
    assert second.action == "reused"
    assert second.snapshot_id == first.snapshot_id
    assert second.publication_id == first.publication_id
    assert publication_count == 1
    assert snapshot_count == 1
    assert event_count == 2
    assert sequences == [1]
    # The replayed batch sealed no second receipt, so the global counter stayed put.
    assert next_sequence == 2
