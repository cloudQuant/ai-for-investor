from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.db.database import async_session_maker
from app.models.market_data_platform import MdObservationRevision, MdSourceSnapshot
from app.services.market_data.query_persistence import ProviderPersistenceTasks
from app.services.market_data.store import (
    UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
    MarketDataStore,
    PersistedProviderFetch,
    _ValidatedSourceAuthorization,
)
from tests.market_data_platform.test_store import (
    _at,
    _context,
    _observation,
    _result,
    _seed_dataset_and_provider,
)


async def _count(db, model) -> int:
    return int(await db.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.asyncio
async def test_identical_receipt_retry_reuses_source_and_revision() -> None:
    context = _context()

    async with async_session_maker() as db:
        await _seed_dataset_and_provider(db)
        store = MarketDataStore(db, clock=lambda: _at(14))
        first = await store.persist_provider_result(
            context,
            _result(
                context=context,
                retrieved_at=_at(13),
                observations=(
                    _observation(event_at=_at(10), available_at=_at(12), fields={"close": "10.50"}),
                ),
            ),
            received_at=_at(14),
            unverified_compatibility_reason=UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
        )
        repeated = await store.persist_provider_result(
            context,
            _result(
                context=context,
                retrieved_at=_at(13),
                observations=(
                    _observation(event_at=_at(10), available_at=_at(12), fields={"close": "10.50"}),
                ),
            ),
            received_at=_at(15),
            unverified_compatibility_reason=UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
        )

        assert repeated.source_snapshot_id == first.source_snapshot_id
        assert repeated.observation_revision_ids == first.observation_revision_ids
        assert repeated.received_at == first.received_at
        assert await _count(db, MdSourceSnapshot) == 1
        assert await _count(db, MdObservationRevision) == 1


@pytest.mark.asyncio
async def test_changed_fields_for_same_business_coordinate_append_one_revision() -> None:
    context = _context()

    async with async_session_maker() as db:
        await _seed_dataset_and_provider(db)
        store = MarketDataStore(db, clock=lambda: _at(14))
        first = await store.persist_provider_result(
            context,
            _result(
                context=context,
                retrieved_at=_at(13),
                observations=(
                    _observation(event_at=_at(10), available_at=_at(12), fields={"close": "10.50"}),
                ),
            ),
            received_at=_at(14),
            unverified_compatibility_reason=UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
        )
        changed = await store.persist_provider_result(
            context,
            _result(
                context=context,
                retrieved_at=_at(13),
                observations=(
                    _observation(event_at=_at(10), available_at=_at(12), fields={"close": "11.50"}),
                ),
            ),
            received_at=_at(15),
            unverified_compatibility_reason=UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
        )
        repeated = await store.persist_provider_result(
            context,
            _result(
                context=context,
                retrieved_at=_at(13),
                observations=(
                    _observation(event_at=_at(10), available_at=_at(12), fields={"close": "11.50"}),
                ),
            ),
            received_at=_at(16),
            unverified_compatibility_reason=UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
        )
        revisions = list(
            (
                await db.scalars(
                    select(MdObservationRevision)
                    .where(MdObservationRevision.series_id == first.series_id)
                    .order_by(MdObservationRevision.revision_number)
                )
            ).all()
        )

        assert changed.source_snapshot_id != first.source_snapshot_id
        assert repeated.source_snapshot_id == changed.source_snapshot_id
        assert [revision.revision_number for revision in revisions] == [1, 2]
        assert await _count(db, MdSourceSnapshot) == 2
        assert await _count(db, MdObservationRevision) == 2


@pytest.mark.asyncio
async def test_query_persistence_finishes_before_cancellation_propagates() -> None:
    started = asyncio.Event()
    finish = asyncio.Event()
    completed = asyncio.Event()
    receipt = PersistedProviderFetch(
        series_id="series",
        source_snapshot_id="snapshot",
        observation_revision_ids=("revision",),
        passing_observation_count=1,
        failed_observation_count=0,
        received_at=_at(14),
    )

    async def persist(*_args: object, **_kwargs: object):
        started.set()
        await finish.wait()
        completed.set()
        return receipt

    store = SimpleNamespace(persist_provider_result=persist)
    persistence = ProviderPersistenceTasks()
    task = asyncio.create_task(
        persistence.persist(
            store,
            SimpleNamespace(),
            SimpleNamespace(),
            received_at=_at(14),
            source_authorization=SimpleNamespace(),
            fetch_lease=None,
        )
    )
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert task.done() is False
    assert completed.is_set() is False

    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert completed.is_set()
    assert persistence._tasks == set()


@pytest.mark.asyncio
async def test_cancellation_after_fact_commit_still_publishes_visible_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    publication_started = asyncio.Event()
    finish_publication = asyncio.Event()

    async with async_session_maker() as db:
        await _seed_dataset_and_provider(db)
        store = MarketDataStore(db, clock=lambda: _at(14))
        monkeypatch.setattr(
            store,
            "_validate_source_authorization",
            AsyncMock(
                return_value=_ValidatedSourceAuthorization(
                    state="UNVERIFIED_COMPATIBILITY",
                    descriptor_sha256=None,
                    provenance={"reason": UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT},
                )
            ),
        )
        original_publish = store._publications.publish_staged

        async def blocked_publish(*args: object, **kwargs: object):
            publication_started.set()
            await finish_publication.wait()
            return await original_publish(*args, **kwargs)

        monkeypatch.setattr(store._publications, "publish_staged", blocked_publish)
        persistence = ProviderPersistenceTasks()
        task = asyncio.create_task(
            persistence.persist(
                store,
                context,
                _result(
                    context=context,
                    retrieved_at=_at(13),
                    observations=(
                        _observation(
                            event_at=_at(10), available_at=_at(12), fields={"close": "10.50"}
                        ),
                    ),
                ),
                received_at=_at(14),
                source_authorization=SimpleNamespace(),
                fetch_lease=None,
            )
        )
        await publication_started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert task.done() is False
        finish_publication.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        visible = await store.read_observations(context, knowledge_cutoff=_at(20))

    assert len(visible) == 1
    assert visible[0].fields["close"] == "10.50"
