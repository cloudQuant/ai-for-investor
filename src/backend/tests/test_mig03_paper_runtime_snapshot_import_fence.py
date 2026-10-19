"""AFI12 migration must fence old Paper snapshot producers by persisted identity."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db import database
from app.models.legacy_paper_import import LegacyPaperImportReceipt
from app.models.paper_runtime import PaperEquitySnapshot
from app.models.workspace import StrategyUnit, Workspace
from app.services.paper_runtime_scheduler import PaperRuntimeSnapshotScheduler
from app.services.paper_runtime_service import (
    PaperRuntimeService,
    PaperRuntimeSnapshotWriteDenied,
)
from tests import test_legacy_paper_import_migration as legacy


async def _seed_runtime(*, linked_account_id: str | None) -> str:
    workspace_id = str(uuid.UUID("af130000-0000-4000-8000-000000000001"))
    unit_id = str(uuid.UUID("af130000-0000-4000-8000-000000000002"))
    instance_id = str(uuid.UUID("af130000-0000-4000-8000-000000000003"))
    async with database.async_session_maker() as session:
        async with session.begin():
            session.add(
                Workspace(
                    id=workspace_id,
                    user_id=legacy._SOURCE_OWNER_ID,
                    name="Synthetic MIG03 paper runtime",
                    workspace_type="trading",
                    trading_config={},
                )
            )
            session.add(
                StrategyUnit(
                    id=unit_id,
                    workspace_id=workspace_id,
                    strategy_name="MIG03 synthetic runtime",
                    symbol="BTC/USDT",
                    trading_mode="paper",
                    trading_instance_id=instance_id,
                    run_status="running",
                    lock_running=False,
                    unit_settings={"initial_cash": 100.0},
                    metrics_snapshot={},
                    trading_snapshot={"positions": [], "cumulative_pnl": 0.0},
                )
            )
            if linked_account_id is not None:
                session.add(
                    PaperEquitySnapshot(
                        id=str(uuid.UUID("af130000-0000-4000-8000-000000000004")),
                        user_id=legacy._SOURCE_OWNER_ID,
                        workspace_id=workspace_id,
                        unit_id=unit_id,
                        instance_id=instance_id,
                        paper_account_id=linked_account_id,
                        observed_at=datetime.now(timezone.utc) - timedelta(seconds=5),
                        source="migration_seed",
                        total_equity=100.0,
                        cash=100.0,
                        position_value=0.0,
                        unrealized_pnl=0.0,
                        realized_pnl=0.0,
                        metadata_json={"source": "synthetic_history"},
                    )
                )
    return instance_id


async def _snapshot_rows(instance_id: str) -> list[PaperEquitySnapshot]:
    async with database.async_session_maker() as session:
        result = await session.execute(
            select(PaperEquitySnapshot)
            .where(PaperEquitySnapshot.instance_id == instance_id)
            .order_by(PaperEquitySnapshot.observed_at.asc(), PaperEquitySnapshot.id.asc())
        )
        return list(result.scalars().all())


class _SnapshotObserver:
    def __init__(self, service: PaperRuntimeService) -> None:
        self._service = service
        self.new_snapshots: asyncio.Queue[PaperEquitySnapshot] = asyncio.Queue()
        self._seen_ids: set[str] = set()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._service, name)

    async def capture_mark_to_market_snapshot(self, *args: Any, **kwargs: Any):
        snapshot = await self._service.capture_mark_to_market_snapshot(*args, **kwargs)
        if snapshot is not None and snapshot.id not in self._seen_ids:
            self._seen_ids.add(snapshot.id)
            await self.new_snapshots.put(snapshot)
        return snapshot

    async def wait_for_new_snapshot(self) -> PaperEquitySnapshot:
        return await asyncio.wait_for(self.new_snapshots.get(), timeout=5.0)


class _CountingWorker:
    def __init__(self, worker: Any) -> None:
        self._worker = worker
        self.calls = 0

    async def call_paper_legacy_import(
        self, legacy_account_id: str, operation: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls += 1
        return await self._worker.call_paper_legacy_import(
            legacy_account_id, operation, arguments
        )


@pytest.mark.asyncio
async def test_unbound_running_runtime_fails_import_before_target_and_remains_operational(
    tmp_path: Path,
) -> None:
    await legacy._install_source_migrations()
    await legacy._seed_account()
    instance_id = await _seed_runtime(linked_account_id=None)
    scheduler = PaperRuntimeSnapshotScheduler(interval_seconds=1)
    scheduler._last_cleanup_at = datetime.now(timezone.utc)
    observer = _SnapshotObserver(scheduler._service)
    scheduler._service = observer  # type: ignore[assignment]
    target_store, raw_worker, scope, domain = legacy._target(tmp_path)
    worker = _CountingWorker(raw_worker)
    try:
        async with database.async_session_maker() as session:
            assert await session.get(legacy.Account, legacy._SOURCE_ACCOUNT_ID) is not None
        assert await scheduler.start_existing() == 1
        async with database.async_session_maker() as session:
            assert await session.get(legacy.Account, legacy._SOURCE_ACCOUNT_ID) is not None
        first_snapshot = await observer.wait_for_new_snapshot()
        await scheduler.stop(instance_id)
        assert first_snapshot.paper_account_id is None
        async with database.async_session_maker() as session:
            assert await session.get(legacy.Account, legacy._SOURCE_ACCOUNT_ID) is not None

        with pytest.raises(legacy.LegacyPaperImportError) as denied:
            await legacy.migrate_nonempty_legacy_paper_account(
                legacy.PaperTradingService(),
                legacy._SOURCE_OWNER_ID,
                legacy._binding(domain),
                target_worker=worker,
                scope=scope,
                domain=domain,
                symbol_bindings=(
                    legacy.LegacyPaperSymbolBindingV1(
                        legacy._LEGACY_SYMBOL, legacy._INSTRUMENT
                    ),
                ),
            )
        assert denied.value.code == "LEGACY_RUNTIME_INSTANCE_RELATION_UNPROVEN"
        assert worker.calls == 0
        assert target_store.get_paper_legacy_import(scope) is None
        async with database.async_session_maker() as session:
            receipt = await session.scalar(
                select(LegacyPaperImportReceipt).where(
                    LegacyPaperImportReceipt.legacy_account_id == legacy._SOURCE_ACCOUNT_ID
                )
            )
            assert receipt is None

        # The failed import has not installed a receipt, so an ordinary old
        # scheduler restart can still write another unbound runtime point.
        assert await scheduler.start_existing() == 1
        second_snapshot = await observer.wait_for_new_snapshot()
        continued_rows = await _snapshot_rows(instance_id)
        assert len(continued_rows) >= 2
        assert second_snapshot.id != first_snapshot.id
        assert all(row.paper_account_id is None for row in continued_rows)
    finally:
        await scheduler.shutdown()
        target_store.close()


@pytest.mark.asyncio
async def test_bound_scheduler_is_stopped_by_active_import_receipt_and_write_fence(
    tmp_path: Path,
) -> None:
    await legacy._install_source_migrations()
    await legacy._seed_account()
    instance_id = await _seed_runtime(linked_account_id=legacy._SOURCE_ACCOUNT_ID)
    scheduler = PaperRuntimeSnapshotScheduler(interval_seconds=1)
    scheduler._last_cleanup_at = datetime.now(timezone.utc)
    observer = _SnapshotObserver(scheduler._service)
    scheduler._service = observer  # type: ignore[assignment]
    target_store, target_worker, scope, domain = legacy._target(tmp_path)
    try:
        assert await scheduler.start_existing() == 1
        seed_snapshot = (await _snapshot_rows(instance_id))[0]
        worker_snapshot = await observer.wait_for_new_snapshot()
        before_import = await _snapshot_rows(instance_id)
        await scheduler.stop(instance_id)
        assert len(before_import) >= 2
        assert worker_snapshot.id != seed_snapshot.id
        assert all(
            row.paper_account_id == legacy._SOURCE_ACCOUNT_ID for row in before_import
        )

        migrated = await legacy.migrate_nonempty_legacy_paper_account(
            legacy.PaperTradingService(),
            legacy._SOURCE_OWNER_ID,
            legacy._binding(domain),
            target_worker=target_worker,
            scope=scope,
            domain=domain,
            symbol_bindings=(
                legacy.LegacyPaperSymbolBindingV1(
                    legacy._LEGACY_SYMBOL, legacy._INSTRUMENT
                ),
            ),
        )
        assert migrated.receipt.state == "ACTIVE"
        async with database.async_session_maker() as session:
            source_receipt = await session.scalar(
                select(LegacyPaperImportReceipt)
                .where(
                    LegacyPaperImportReceipt.legacy_account_id
                    == legacy._SOURCE_ACCOUNT_ID
                )
                .order_by(LegacyPaperImportReceipt.generation.desc())
                .limit(1)
            )
            assert source_receipt is not None
            preserved_context = json.loads(source_receipt.preserved_context_json)
        assert preserved_context["schema"] == "afi.legacy-paper-preserved-context.v1"
        preserved_snapshots = {
            row["id"]: row
            for row in preserved_context["categories"]["paper_equity_snapshots"]
        }
        assert set(preserved_snapshots) == {row.id for row in before_import}
        for row in before_import:
            preserved = preserved_snapshots[row.id]
            assert (
                preserved["user_id"],
                preserved["workspace_id"],
                preserved["unit_id"],
                preserved["instance_id"],
                preserved["paper_account_id"],
            ) == (
                row.user_id,
                row.workspace_id,
                row.unit_id,
                row.instance_id,
                row.paper_account_id,
            )
        assert await scheduler.start_existing() == 0

        service = PaperRuntimeService()
        with pytest.raises(PaperRuntimeSnapshotWriteDenied) as denied:
            await service.record_snapshot(
                legacy._SOURCE_OWNER_ID,
                instance_id,
                {
                    "observed_at": datetime.now(timezone.utc) + timedelta(seconds=1),
                    "source": "post_import_probe",
                    "total_equity": 100.0,
                },
            )
        assert denied.value.code == "MANAGED_PAPER_LEGACY_ACCOUNT_FENCED"

        # Exercise an explicit old-worker restart as well as startup restore;
        # its pre-write receipt check exits without a row or provider-style work.
        scheduler.ensure_running(legacy._SOURCE_OWNER_ID, instance_id)
        task = scheduler._tasks[instance_id]
        await asyncio.wait_for(task, timeout=5.0)
        after_restart = await _snapshot_rows(instance_id)
        assert [row.id for row in after_restart] == [row.id for row in before_import]
        assert all(
            row.paper_account_id == legacy._SOURCE_ACCOUNT_ID for row in after_restart
        )
        async with database.async_session_maker() as session:
            active_receipt = await session.scalar(
                select(LegacyPaperImportReceipt).where(
                    LegacyPaperImportReceipt.legacy_account_id == legacy._SOURCE_ACCOUNT_ID,
                    LegacyPaperImportReceipt.state == "ACTIVE",
                )
            )
            snapshot_count = await session.scalar(
                select(func.count(PaperEquitySnapshot.id)).where(
                    PaperEquitySnapshot.instance_id == instance_id
                )
            )
        assert active_receipt is not None
        assert snapshot_count == len(before_import)
    finally:
        await scheduler.shutdown()
        target_store.close()
