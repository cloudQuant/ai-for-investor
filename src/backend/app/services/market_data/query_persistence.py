"""Cancellation-safe provider persistence task ownership."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

from app.services.market_data.persisted_fetch_boundary import await_task_after_cancellation

if TYPE_CHECKING:
    from datetime import datetime

    from app.services.market_data.access import MarketDataSourceAuthorization
    from app.services.market_data.fetch_lease import MarketDataFetchLeaseHandle
    from app.services.market_data.providers import ProviderFetchResult
    from app.services.market_data.query_resolution import ResolvedMarketDataQueryContext
    from app.services.market_data.store import (
        DeferredProviderFetch,
        PersistedProviderFetch,
    )


class PersistenceStore(Protocol):
    async def persist_provider_result(
        self,
        context: ResolvedMarketDataQueryContext,
        result: ProviderFetchResult,
        *,
        received_at: datetime,
        source_authorization: MarketDataSourceAuthorization,
        fetch_lease: MarketDataFetchLeaseHandle | None,
    ) -> PersistedProviderFetch | DeferredProviderFetch: ...


class ProviderPersistenceTasks:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[PersistedProviderFetch | DeferredProviderFetch]] = set()

    async def persist(
        self,
        store: PersistenceStore,
        context: ResolvedMarketDataQueryContext,
        result: ProviderFetchResult,
        *,
        received_at: datetime,
        source_authorization: MarketDataSourceAuthorization,
        fetch_lease: MarketDataFetchLeaseHandle | None,
    ) -> PersistedProviderFetch | DeferredProviderFetch:
        task = asyncio.create_task(
            store.persist_provider_result(
                context,
                result,
                received_at=received_at,
                source_authorization=source_authorization,
                fetch_lease=fetch_lease,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancellation:
            try:
                await await_task_after_cancellation(task)
            except BaseException as persistence_error:
                raise cancellation from persistence_error
            raise
