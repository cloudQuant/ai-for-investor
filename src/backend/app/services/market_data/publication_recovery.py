"""Fenced pending-publication recovery filtering."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.persistence_boundaries import stored_utc
from app.models.market_data_platform import MdFetchLease, MdPublication
from app.services.market_data.fetch_lease import MarketDataFetchLeaseManager


async def exclude_active_fenced_receipts(
    db: AsyncSession,
    rows: Iterable[MdPublication],
    generations: tuple[tuple[str, str, int], ...],
    *,
    fetch_lease_clock: Callable[[], datetime] | None,
) -> tuple[MdPublication, ...]:
    from app.services.market_data.publication import MarketDataPublicationError

    materialized = tuple(rows)
    if not generations:
        return materialized
    lease_keys = tuple(sorted({key for _, key, _ in generations}))
    leases = {
        row.lease_key_sha256: row
        for row in (
            await db.scalars(
                select(MdFetchLease)
                .where(MdFetchLease.lease_key_sha256.in_(lease_keys))
                .with_for_update()
            )
        ).all()
    }
    if set(leases) != set(lease_keys):
        raise MarketDataPublicationError("PUBLICATION_FETCH_LEASE_BINDING_INTEGRITY")
    now = await MarketDataFetchLeaseManager(db, clock=fetch_lease_clock)._now()
    active_keys: set[str] = set()
    for key, lease in leases.items():
        if lease.owner_token is None and lease.expires_at is None:
            continue
        if lease.owner_token is None or lease.expires_at is None:
            raise MarketDataPublicationError("PUBLICATION_FETCH_LEASE_BINDING_INTEGRITY")
        if stored_utc(lease.expires_at) > now:
            active_keys.add(key)
    excluded_receipts = {
        publication_id for publication_id, key, _fence in generations if key in active_keys
    }
    return tuple(row for row in materialized if row.id not in excluded_receipts)
