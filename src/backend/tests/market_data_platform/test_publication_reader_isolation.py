"""Cross-connection visibility contracts for the AC06 half-written-batch criterion.

AC06 requires that a reader never observes a partially published batch.  The
in-memory ``StaticPool`` fixture used by the rest of the suite shares one
connection across every session, so it cannot express a second reader at all.
These tests therefore use one ``tmp_path`` SQLite *file* with two independent
engines: the production writer seals a multi-receipt batch while a genuinely
separate connection reads the same file.  Nothing here replaces the database
with a stub; the only extra machinery is an out-of-band read taken while the
production publication transaction is open.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.database import Base
from app.db.persistence_boundaries import stored_utc
from app.models.market_data_platform import MdObservationRevision, MdPublication
from app.services.market_data.coverage import Observation
from app.services.market_data.publication import (
    MarketDataPublicationError,
    MarketDataPublicationManager,
)
from app.services.market_data.store import (
    UNVERIFIED_COMPATIBILITY_REASON_LEGACY_IMPORT,
    MarketDataStore,
    MarketDataStoreError,
)
from tests.market_data_platform.test_store import (
    _at,
    _context,
    _observation,
    _result,
    _seed_dataset_and_provider,
)

_BATCH_REVISIONS = (("half-written-batch-a", 10), ("half-written-batch-b", 11))


@dataclass(frozen=True, slots=True)
class _FileDatabase:
    """Two independent engine pools over one physical SQLite file."""

    path: Path
    writer_engine: object
    writer_maker: async_sessionmaker[AsyncSession]
    reader_maker: async_sessionmaker[AsyncSession]


@pytest.fixture
async def file_database(tmp_path: Path) -> AsyncIterator[_FileDatabase]:
    """Build a file-backed database so a second connection can really exist."""
    path = tmp_path / "ac06-publication.db"
    url = f"sqlite+aiosqlite:///{path}"
    admin_engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with admin_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await admin_engine.dispose()
    writer_engine = create_async_engine(url, poolclass=NullPool)
    reader_engine = create_async_engine(url, poolclass=NullPool)
    try:
        yield _FileDatabase(
            path=path,
            writer_engine=writer_engine,
            writer_maker=async_sessionmaker(
                writer_engine, class_=AsyncSession, expire_on_commit=False
            ),
            reader_maker=async_sessionmaker(
                reader_engine, class_=AsyncSession, expire_on_commit=False
            ),
        )
    finally:
        await writer_engine.dispose()
        await reader_engine.dispose()


def _external_visibility(path: Path) -> dict[str, tuple[bool, int | None]]:
    """Read seal state through a separate OS-level SQLite connection.

    A second ``sqlite3`` handle is a different database connection in the same
    sense as another worker process: it only ever observes the last committed
    content of the file.
    """
    connection = sqlite3.connect(str(path))
    try:
        return {
            str(row[0]): (row[1] is not None, row[2])
            for row in connection.execute(
                "SELECT id, published_at, visibility_sequence FROM md_publications"
            ).fetchall()
        }
    finally:
        connection.close()


async def _interrupted_publish(*_args: object, **_kwargs: object) -> datetime:
    """Stand in for the process dying after the fact commit, before sealing."""
    raise MarketDataPublicationError("PUBLICATION_TEST_INTERRUPTED")


async def _stage_committed_but_unsealed_batch(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, ...]:
    """Run the real persist path for batches whose sealing never completed."""
    await _seed_dataset_and_provider(db)
    context = _context()
    store = MarketDataStore(db, clock=lambda: _at(14))
    monkeypatch.setattr(store._publications, "publish_staged", _interrupted_publish)
    for source_revision, event_hour in _BATCH_REVISIONS:
        with pytest.raises(MarketDataStoreError) as interrupted:
            await store.persist_provider_result(
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
        assert interrupted.value.code == "OBSERVATION_PUBLICATION_FAILED"

    publication_ids = tuple(
        (await db.execute(select(MdPublication.id).order_by(MdPublication.id))).scalars()
    )
    await db.rollback()
    assert len(publication_ids) == len(_BATCH_REVISIONS)
    return publication_ids


async def _visible_rows(db: AsyncSession) -> tuple[Observation, ...]:
    """Ask the production reader what it can currently see."""
    return await MarketDataStore(db).read_observations(_context(), knowledge_cutoff=_at(20))


async def _sealed_event_at(db: AsyncSession, publication_id: str) -> datetime:
    """Return the business instant the facts behind one receipt carry."""
    value = await db.scalar(
        select(MdObservationRevision.event_time)
        .join(MdPublication, MdPublication.entity_id == MdObservationRevision.source_snapshot_id)
        .where(MdPublication.id == publication_id)
    )
    await db.rollback()
    assert value is not None
    return stored_utc(value)


@pytest.mark.asyncio
async def test_reader_connection_never_observes_a_partially_sealed_batch(
    file_database: _FileDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With one of two receipts already written, an outside reader still sees none."""
    mid_write_reads: list[tuple[tuple[int, int], dict[str, tuple[bool, int | None]]]] = []

    def record_visibility_while_half_written(
        conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _execution_context: object,
        _executemany: bool,
    ) -> None:
        if not statement.startswith("UPDATE md_publications"):
            return
        # ``conn`` is the writer's own connection, so this count is the true
        # in-transaction state of the batch. The dictionary is the independent
        # connection's view of the very same file at the very same instant.
        writer_view = conn.exec_driver_sql(  # type: ignore[attr-defined]
            "SELECT count(*) FROM md_publications WHERE published_at IS NOT NULL"
        ).fetchone()
        mid_write_reads.append((writer_view, _external_visibility(file_database.path)))

    async with file_database.writer_maker() as writer_db:
        publication_ids = await _stage_committed_but_unsealed_batch(writer_db, monkeypatch)

        async with file_database.reader_maker() as reader_db:
            sealed_before = await reader_db.scalar(
                select(func.count())
                .select_from(MdPublication)
                .where(MdPublication.published_at.is_not(None))
            )
            hidden_before = await _visible_rows(reader_db)
            await reader_db.rollback()

        sync_engine = file_database.writer_engine.sync_engine  # type: ignore[attr-defined]
        event.listen(sync_engine, "after_cursor_execute", record_visibility_while_half_written)
        try:
            sealed_ids = await MarketDataPublicationManager(
                writer_db, clock=lambda: _at(15)
            ).recover_pending()
        finally:
            event.remove(sync_engine, "after_cursor_execute", record_visibility_while_half_written)

        async with file_database.reader_maker() as reader_db:
            visible_after = await _visible_rows(reader_db)
            revision_count = await reader_db.scalar(
                select(func.count()).select_from(MdObservationRevision)
            )
            await reader_db.rollback()

    assert sealed_before == 0
    assert hidden_before == ()
    # One conditional UPDATE per receipt, so these reads bracket the exact
    # instants at which the batch is half written inside the open seal.
    assert sorted(sealed_ids) == sorted(publication_ids)
    assert len(mid_write_reads) == len(publication_ids)
    for index, (writer_view, snapshot) in enumerate(mid_write_reads, start=1):
        assert len(snapshot) == len(publication_ids)
        assert all(sealed is False and sequence is None for sealed, sequence in snapshot.values())
        # The writer itself has sealed exactly ``index`` receipts so far.
        assert writer_view[0] == index
    final = _external_visibility(file_database.path)
    assert all(sealed is True for sealed, _ in final.values())
    assert sorted(sequence for _, sequence in final.values()) == [1, 2]
    assert revision_count == len(publication_ids)
    assert sorted(row.event_key.event_at for row in visible_after) == [_at(10), _at(11)]


@pytest.mark.asyncio
async def test_open_publication_transaction_is_invisible_to_a_second_session(
    file_database: _FileDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reader on another connection sees the batch only when the seal commits."""
    reads_during_publication: list[tuple[int, tuple[Observation, ...]]] = []

    async with file_database.writer_maker() as writer_db:
        publication_ids = await _stage_committed_but_unsealed_batch(writer_db, monkeypatch)
        first_publication_id = publication_ids[0]
        first_event_at = await _sealed_event_at(writer_db, first_publication_id)

        async def read_while_publish_transaction_is_open() -> None:
            assert writer_db.in_transaction()
            async with file_database.reader_maker() as reader_db:
                sealed = await reader_db.scalar(
                    select(func.count())
                    .select_from(MdPublication)
                    .where(MdPublication.published_at.is_not(None))
                )
                rows = await _visible_rows(reader_db)
                await reader_db.rollback()
            reads_during_publication.append((sealed, rows))

        published_at = await MarketDataPublicationManager(
            writer_db, clock=lambda: _at(15)
        ).publish_staged(
            (first_publication_id,),
            pre_publish_guard=read_while_publish_transaction_is_open,
        )

        async with file_database.reader_maker() as reader_db:
            visible_after = await _visible_rows(reader_db)
            sealed_after = await reader_db.scalar(
                select(func.count())
                .select_from(MdPublication)
                .where(MdPublication.published_at.is_not(None))
            )
            await reader_db.rollback()

    assert published_at is not None
    assert len(reads_during_publication) == 1
    assert reads_during_publication[0] == (0, ())
    external = _external_visibility(file_database.path)
    assert external[first_publication_id][0] is True
    assert external[publication_ids[1]][0] is False
    assert sealed_after == 1
    assert len(visible_after) == 1
    assert visible_after[0].event_key.event_at == first_event_at


@pytest.mark.asyncio
async def test_rejected_seal_leaves_no_part_of_the_batch_visible(
    file_database: _FileDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guard that rejects after the seal opened still hides every row."""

    async def reject_publish_transaction() -> None:
        raise RuntimeError("publication rejected after the transaction opened")

    async with file_database.writer_maker() as writer_db:
        publication_ids = await _stage_committed_but_unsealed_batch(writer_db, monkeypatch)

        with pytest.raises(RuntimeError, match="publication rejected"):
            await MarketDataPublicationManager(writer_db, clock=lambda: _at(15)).publish_staged(
                publication_ids,
                pre_publish_guard=reject_publish_transaction,
            )

        async with file_database.reader_maker() as reader_db:
            sealed = await reader_db.scalar(
                select(func.count())
                .select_from(MdPublication)
                .where(MdPublication.published_at.is_not(None))
            )
            rows = await _visible_rows(reader_db)
            await reader_db.rollback()

    assert sealed == 0
    assert rows == ()
    assert len(_external_visibility(file_database.path)) == len(publication_ids)
    assert all(
        sealed_row is False for sealed_row, _ in _external_visibility(file_database.path).values()
    )
