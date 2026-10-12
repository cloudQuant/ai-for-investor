"""Queued task lifecycle keeps UI polling separate from the research computation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db.database import async_session_maker
from app.models.asset_research import AssetDataSourceRegistry, AssetInstrument
from app.models.user import User
from app.schemas.asset_research import (
    AssetAnalysisCreateRequest,
    FuturesIdentityDetails,
    InstrumentIdentity,
    RawAssetSnapshot,
)
from app.services.asset_research import orchestrator as orchestrator_module
from app.services.asset_research.data import DEFAULT_ASSET_RESEARCH_SOURCE_ID
from app.services.asset_research.orchestrator import (
    AssetResearchOrchestrationError,
    AssetResearchOrchestrator,
)


class _Data:
    async def collect(
        self, identity: InstrumentIdentity, *, cutoff_at: datetime
    ) -> RawAssetSnapshot:
        return RawAssetSnapshot(
            identity=identity,
            cutoff_at=cutoff_at,
            retrieved_at=cutoff_at,
            raw_schema_version="fixture-v1",
            raw_fields={"snapshot": {"price": 101}},
            history_rows=[{"date": "2026-08-01", "close": 101}],
            source_manifest={
                "license_status": "APPROVED",
                "capabilities": ["price", "contract_calendar"],
            },
            license_tags=["APPROVED"],
            content_hash="c" * 64,
        )


def _identity() -> InstrumentIdentity:
    return InstrumentIdentity(
        asset_type="futures",
        identity_level="CONTRACT",
        canonical_id="futures:CFFEX:IF2609:CNY",
        display_symbol="IF2609",
        name="沪深300期货2609",
        venue="CFFEX",
        currency="CNY",
        timezone="Asia/Shanghai",
        identifier_type="CONTRACT_CODE",
        identifier_value="IF2609",
        product_type="FUTURE",
        metadata_version="fixture-v1",
        details=FuturesIdentityDetails(
            product_code="IF",
            contract_month="2609",
            expiry_at="2026-09-18T07:15:00+00:00",
            contract_multiplier="300",
            trading_calendar_id="CFFEX",
        ),
    )


def _approved_futures_source(
    *, source_id: str = "task-lifecycle-fixture"
) -> AssetDataSourceRegistry:
    """Return a registry entry that permits this lifecycle fixture to queue work."""
    return AssetDataSourceRegistry(
        source_id=source_id,
        asset_types=["futures"],
        jurisdictions=["GLOBAL"],
        license_status="RESEARCH_APPROVED",
        allowed_uses=["RESEARCH_ONLY"],
        redistribution_policy="NO_REDISTRIBUTION",
        derived_data_policy="ALLOWED",
        retention_policy="research-v1",
        effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        freshness_sla={},
        enabled=True,
    )


@pytest.mark.asyncio
async def test_create_pending_keeps_a_task_queued_until_the_worker_claims_it() -> None:
    async with async_session_maker() as db:
        user = User(
            username="queued_asset_user", email="queued@example.test", hashed_password="hash"
        )
        db.add(user)
        db.add(_approved_futures_source())
        await db.flush()
        service = AssetResearchOrchestrator(db, data_adapter=_Data())
        await service.persist_identity(_identity())
        task = await service.create_pending(
            user_id=user.id,
            request=AssetAnalysisCreateRequest(
                asset_type="futures", canonical_id="futures:CFFEX:IF2609:CNY"
            ),
        )

        assert task.status == "QUEUED"
        assert task.progress == 0
        assert task.completed_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lifecycle_status", "valid_to"),
    [
        ("DELISTED", None),
        ("ACTIVE", datetime(2020, 1, 2, tzinfo=timezone.utc)),
    ],
)
async def test_create_pending_rejects_a_noncurrent_instrument_version(
    lifecycle_status: str, valid_to: datetime | None
) -> None:
    """New research must not start from a delisted or expired identity version."""
    async with async_session_maker() as db:
        user = User(
            username=f"asset_task_noncurrent_{lifecycle_status.lower()}",
            email=f"asset-task-noncurrent-{lifecycle_status.lower()}@example.test",
            hashed_password="hash",
        )
        db.add_all([user, _approved_futures_source()])
        await db.flush()
        service = AssetResearchOrchestrator(db, data_adapter=_Data())
        instrument = await service.persist_identity(_identity())
        instrument.lifecycle_status = lifecycle_status
        instrument.valid_to = valid_to
        await db.flush()

        with pytest.raises(AssetResearchOrchestrationError, match="INSTRUMENT_VERSION_STALE"):
            await service.create_pending(
                user_id=user.id,
                request=AssetAnalysisCreateRequest(
                    asset_type="futures", canonical_id="futures:CFFEX:IF2609:CNY"
                ),
            )


@pytest.mark.asyncio
async def test_create_pending_rejects_an_ambiguous_current_instrument_version() -> None:
    """A direct task path must not bypass the catalog's version-tie rejection."""
    effective_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
    first_identity = _identity()
    second_identity = first_identity.model_copy(update={"metadata_version": "fixture-v2"})
    async with async_session_maker() as db:
        user = User(
            username="asset_task_ambiguous_version",
            email="asset-task-ambiguous-version@example.test",
            hashed_password="hash",
        )
        db.add_all([user, _approved_futures_source()])
        await db.flush()
        service = AssetResearchOrchestrator(db, data_adapter=_Data())
        first = await service.persist_identity(first_identity)
        first.valid_from = effective_at
        db.add(
            AssetInstrument(
                canonical_id=second_identity.canonical_id,
                asset_type=second_identity.asset_type,
                identity_level=second_identity.identity_level,
                venue=second_identity.venue,
                currency=second_identity.currency,
                product_type=second_identity.product_type,
                identity_json=second_identity.model_dump(mode="json"),
                metadata_version=second_identity.metadata_version,
                lifecycle_status="ACTIVE",
                valid_from=effective_at,
            )
        )
        await db.flush()

        with pytest.raises(AssetResearchOrchestrationError, match="INSTRUMENT_VERSION_STALE"):
            await service.create_pending(
                user_id=user.id,
                request=AssetAnalysisCreateRequest(
                    asset_type="futures", canonical_id=first_identity.canonical_id
                ),
            )


@pytest.mark.asyncio
async def test_create_pending_rejects_a_malformed_current_instrument_version() -> None:
    """A direct task path must apply the same master-record integrity checks as search."""
    async with async_session_maker() as db:
        user = User(
            username="asset_task_malformed_identity",
            email="asset-task-malformed-identity@example.test",
            hashed_password="hash",
        )
        db.add_all([user, _approved_futures_source()])
        await db.flush()
        service = AssetResearchOrchestrator(db, data_adapter=_Data())
        instrument = await service.persist_identity(_identity())
        instrument.identity_json = {"asset_type": "futures"}
        await db.flush()

        with pytest.raises(AssetResearchOrchestrationError, match="INSTRUMENT_VERSION_STALE"):
            await service.create_pending(
                user_id=user.id,
                request=AssetAnalysisCreateRequest(
                    asset_type="futures", canonical_id=instrument.canonical_id
                ),
            )


@pytest.mark.asyncio
async def test_task_creation_reuses_the_same_idempotency_key_and_rejects_conflicts() -> None:
    async with async_session_maker() as db:
        user = User(
            username="asset_task_idempotency",
            email="asset-task-idempotency@example.test",
            hashed_password="hash",
        )
        db.add(user)
        db.add(_approved_futures_source())
        await db.flush()
        service = AssetResearchOrchestrator(db, data_adapter=_Data())
        await service.persist_identity(_identity())
        request = AssetAnalysisCreateRequest(
            asset_type="futures", canonical_id="futures:CFFEX:IF2609:CNY"
        )

        first = await service.create_pending(
            user_id=user.id, request=request, idempotency_key="asset-task-1"
        )
        repeated = await service.create_pending(
            user_id=user.id, request=request, idempotency_key="asset-task-1"
        )

        assert first.id == repeated.id
        with pytest.raises(AssetResearchOrchestrationError, match="IDEMPOTENCY_CONFLICT"):
            await service.create_pending(
                user_id=user.id,
                request=AssetAnalysisCreateRequest(
                    asset_type="futures",
                    canonical_id="futures:CFFEX:IF2609:CNY",
                    horizon_code="short",
                ),
                idempotency_key="asset-task-1",
            )


@pytest.mark.asyncio
async def test_cancelling_an_unfinished_task_is_idempotent() -> None:
    """Repeated cancellation returns the same terminal fact without a new task."""
    async with async_session_maker() as db:
        user = User(
            username="asset_task_cancel_idempotent",
            email="asset-task-cancel-idempotent@example.test",
            hashed_password="hash",
        )
        db.add_all([user, _approved_futures_source()])
        await db.flush()
        service = AssetResearchOrchestrator(db, data_adapter=_Data())
        await service.persist_identity(_identity())
        task = await service.create_pending(
            user_id=user.id,
            request=AssetAnalysisCreateRequest(
                asset_type="futures", canonical_id="futures:CFFEX:IF2609:CNY"
            ),
        )

        first = await service.cancel_task(user_id=user.id, task_id=task.id)
        assert first is not None
        first_completed_at = first.completed_at
        second = await service.cancel_task(user_id=user.id, task_id=task.id)

    assert first.status == "CANCELLED"
    assert second is not None
    assert second.task_id == task.id
    assert second.status == "CANCELLED"
    assert second.completed_at == first_completed_at


@pytest.mark.asyncio
@pytest.mark.parametrize("lease_state", ["old_token", "expired", "cancelled"])
async def test_claimed_task_rejects_stale_leases_before_provider_io(lease_state: str) -> None:
    """Old tokens, expired claims, and cancelled tasks never reach collection."""

    class _CountingData(_Data):
        def __init__(self) -> None:
            self.collect_calls = 0

        async def collect(
            self, identity: InstrumentIdentity, *, cutoff_at: datetime
        ) -> RawAssetSnapshot:
            self.collect_calls += 1
            return await super().collect(identity, cutoff_at=cutoff_at)

    now = datetime.now(timezone.utc)
    token = "current-lease-token"
    data = _CountingData()
    async with async_session_maker() as db:
        user = User(
            username="asset_task_lease_dispatch",
            email="asset-task-lease-dispatch@example.test",
            hashed_password="hash",
        )
        db.add_all([user, _approved_futures_source()])
        await db.flush()
        service = AssetResearchOrchestrator(db, data_adapter=data)
        await service.persist_identity(_identity())
        task = await service.create_pending(
            user_id=user.id,
            request=AssetAnalysisCreateRequest(
                asset_type="futures", canonical_id="futures:CFFEX:IF2609:CNY"
            ),
        )
        task.status = "RUNNING"
        task.lease_token = token
        task.lease_expires_at = (
            now - timedelta(seconds=1) if lease_state == "expired" else now + timedelta(minutes=1)
        )
        task.lease_heartbeat_at = now
        task_id = task.id
        user_id = user.id
        await db.commit()

        if lease_state == "cancelled":
            async with async_session_maker() as cancel_db:
                response = await AssetResearchOrchestrator(cancel_db).cancel_task(
                    user_id=user_id,
                    task_id=task_id,
                )
                assert response is not None
                await cancel_db.commit()

        supplied_token = "stale-lease-token" if lease_state == "old_token" else token
        result = await service.run_claimed_task(
            task_id=task_id,
            lease_token=supplied_token,
        )

        assert data.collect_calls == 0
        if lease_state == "expired":
            assert result is task
            assert result.status == "FAILED"
            assert result.error_code == "TASK_LEASE_EXPIRED"
        else:
            assert result is None


@pytest.mark.asyncio
async def test_claimed_task_rechecks_expiry_immediately_before_provider_dispatch(
    monkeypatch,
) -> None:
    """A lease that expires during preparation is rejected before collection."""

    class _CountingData(_Data):
        def __init__(self) -> None:
            self.collect_calls = 0

        async def collect(
            self, identity: InstrumentIdentity, *, cutoff_at: datetime
        ) -> RawAssetSnapshot:
            self.collect_calls += 1
            return await super().collect(identity, cutoff_at=cutoff_at)

    initial_time = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    expiry = initial_time + timedelta(seconds=5)
    clock = [initial_time]
    monkeypatch.setattr(orchestrator_module, "_now", lambda: clock[0])
    data = _CountingData()

    async with async_session_maker() as db:
        user = User(
            username="asset_task_lease_dispatch_expiry",
            email="asset-task-lease-dispatch-expiry@example.test",
            hashed_password="hash",
        )
        db.add_all([user, _approved_futures_source()])
        await db.flush()
        service = AssetResearchOrchestrator(db, data_adapter=data)
        await service.persist_identity(_identity())
        task = await service.create_pending(
            user_id=user.id,
            request=AssetAnalysisCreateRequest(
                asset_type="futures", canonical_id="futures:CFFEX:IF2609:CNY"
            ),
        )
        task.status = "RUNNING"
        task.lease_token = "current-lease-token"
        task.lease_expires_at = expiry
        task.lease_heartbeat_at = initial_time
        await db.commit()

        async def expire_during_preparation(**_: object) -> bool:
            clock[0] = expiry + timedelta(microseconds=1)
            return False

        monkeypatch.setattr(
            service,
            "_normalize_task_position_context_for_cutoff",
            expire_during_preparation,
        )
        result = await service.run_claimed_task(
            task_id=task.id,
            lease_token="current-lease-token",
        )

    assert result is not None
    assert result.status == "FAILED"
    assert result.error_code == "TASK_LEASE_EXPIRED"
    assert data.collect_calls == 0


@pytest.mark.asyncio
async def test_worker_fails_a_queued_task_when_its_source_capability_is_removed() -> None:
    """A task queued before a registry change must not collect after it loses permission."""
    async with async_session_maker() as db:
        user = User(
            username="asset_task_capability_revoked",
            email="asset-task-capability-revoked@example.test",
            hashed_password="hash",
        )
        source = _approved_futures_source()
        db.add_all([user, source])
        await db.flush()
        service = AssetResearchOrchestrator(db, data_adapter=_Data())
        await service.persist_identity(_identity())
        task = await service.create_pending(
            user_id=user.id,
            request=AssetAnalysisCreateRequest(
                asset_type="futures", canonical_id="futures:CFFEX:IF2609:CNY"
            ),
        )
        task_id = task.id
        user_id = user.id
        await db.commit()

        await db.delete(source)
        await db.commit()

        await AssetResearchOrchestrator.run_pending_task(task_id=task_id, user_id=user_id)
        await db.refresh(task)

    assert task.status == "FAILED"
    assert task.error_code == "SOURCE_CAPABILITY_UNAVAILABLE"
    assert task.progress == 100


@pytest.mark.asyncio
async def test_worker_fails_a_queued_task_when_its_identity_is_delisted() -> None:
    """A task queued before a delisting must not reach collection or analysis."""
    async with async_session_maker() as db:
        user = User(
            username="asset_task_instrument_revoked",
            email="asset-task-instrument-revoked@example.test",
            hashed_password="hash",
        )
        db.add_all([user, _approved_futures_source(source_id=DEFAULT_ASSET_RESEARCH_SOURCE_ID)])
        await db.flush()
        service = AssetResearchOrchestrator(db, data_adapter=_Data())
        instrument = await service.persist_identity(_identity())
        task = await service.create_pending(
            user_id=user.id,
            request=AssetAnalysisCreateRequest(
                asset_type="futures", canonical_id="futures:CFFEX:IF2609:CNY"
            ),
        )
        task_id = task.id
        user_id = user.id
        instrument.lifecycle_status = "DELISTED"
        await db.commit()

        with patch.object(
            AssetResearchOrchestrator, "_run_task", new_callable=AsyncMock
        ) as run_task:
            await AssetResearchOrchestrator.run_pending_task(task_id=task_id, user_id=user_id)

        await db.refresh(task)

    assert task.status == "FAILED"
    assert task.error_code == "INSTRUMENT_VERSION_STALE"
    assert task.progress == 100
    run_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_fails_a_queued_task_when_a_newer_identity_version_supersedes_it() -> None:
    """A queued task cannot keep analyzing an older overlapping master version."""
    now = datetime.now(timezone.utc)
    first_identity = _identity()
    second_identity = first_identity.model_copy(update={"metadata_version": "fixture-v2"})
    async with async_session_maker() as db:
        user = User(
            username="asset_task_instrument_superseded",
            email="asset-task-instrument-superseded@example.test",
            hashed_password="hash",
        )
        db.add_all([user, _approved_futures_source(source_id=DEFAULT_ASSET_RESEARCH_SOURCE_ID)])
        await db.flush()
        service = AssetResearchOrchestrator(db, data_adapter=_Data())
        first = await service.persist_identity(first_identity)
        first.valid_from = now - timedelta(minutes=2)
        task = await service.create_pending(
            user_id=user.id,
            request=AssetAnalysisCreateRequest(
                asset_type="futures", canonical_id=first_identity.canonical_id
            ),
        )
        task_id = task.id
        user_id = user.id
        db.add(
            AssetInstrument(
                canonical_id=second_identity.canonical_id,
                asset_type=second_identity.asset_type,
                identity_level=second_identity.identity_level,
                venue=second_identity.venue,
                currency=second_identity.currency,
                product_type=second_identity.product_type,
                identity_json=second_identity.model_dump(mode="json"),
                metadata_version=second_identity.metadata_version,
                lifecycle_status="ACTIVE",
                valid_from=now - timedelta(minutes=1),
            )
        )
        await db.commit()

        with patch.object(
            AssetResearchOrchestrator, "_run_task", new_callable=AsyncMock
        ) as run_task:
            await AssetResearchOrchestrator.run_pending_task(task_id=task_id, user_id=user_id)

        await db.refresh(task)

    assert task.status == "FAILED"
    assert task.error_code == "INSTRUMENT_VERSION_STALE"
    assert task.progress == 100
    run_task.assert_not_awaited()
