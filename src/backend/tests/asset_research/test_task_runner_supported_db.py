"""Opt-in lease acceptance against this iteration's isolated MySQL or PostgreSQL DB."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  # Register the complete model metadata for this DB contract.
from app.db.database import Base
from app.models.asset_research import (
    AssetAnalysisTask,
    AssetDataSourceRegistry,
    AssetInstrument,
)
from app.models.user import User
from app.schemas.asset_research import (
    AssetAnalysisCreateRequest,
    FuturesIdentityDetails,
    InstrumentIdentity,
    RawAssetSnapshot,
)
from app.services.asset_research import orchestrator as orchestrator_module
from app.services.asset_research import task_runner as task_runner_module
from app.services.asset_research.data import DEFAULT_ASSET_RESEARCH_SOURCE_ID
from app.services.asset_research.orchestrator import AssetResearchOrchestrator
from app.services.asset_research.task_runner import AssetResearchTaskRunner


def _test_database_url() -> URL:
    """Read only the opt-in test URL and confine DDL to this round's loopback DB."""
    raw_url = os.environ.get("TEST_DB_URL")
    if not raw_url:
        pytest.skip("set TEST_DB_URL to the isolated iter202_lease[_pg] database for acceptance")

    parsed = make_url(raw_url)
    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    allowed_databases = {"iter202_lease", "iter202_lease_pg"}
    if parsed.host not in allowed_hosts or parsed.database not in allowed_databases:
        pytest.fail("TEST_DB_URL must target a loopback iteration-202 lease database")

    if parsed.get_backend_name() == "mysql":
        return parsed.set(drivername="mysql+aiomysql")
    if parsed.get_backend_name() == "postgresql":
        return parsed.set(drivername="postgresql+asyncpg")
    pytest.fail("TEST_DB_URL must use a supported MySQL or PostgreSQL driver")
    raise AssertionError("unreachable")


def _identity(tag: str) -> InstrumentIdentity:
    return InstrumentIdentity(
        asset_type="futures",
        identity_level="CONTRACT",
        canonical_id=f"futures:CFFEX:IF2609:CNY-{tag}",
        display_symbol="IF2609",
        name="沪深300期货2609",
        venue="CFFEX",
        currency="CNY",
        timezone="Asia/Shanghai",
        identifier_type="CONTRACT_CODE",
        identifier_value="IF2609",
        product_type="FUTURE",
        metadata_version=f"iter202-{tag}",
        details=FuturesIdentityDetails(
            product_code="IF",
            contract_month="2609",
            expiry_at="2026-09-18T07:15:00+00:00",
            contract_multiplier="300",
            trading_calendar_id="CFFEX",
        ),
    )


def _request(canonical_id: str) -> AssetAnalysisCreateRequest:
    return AssetAnalysisCreateRequest(asset_type="futures", canonical_id=canonical_id)


def _approved_source() -> AssetDataSourceRegistry:
    return AssetDataSourceRegistry(
        source_id=DEFAULT_ASSET_RESEARCH_SOURCE_ID,
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
@pytest.mark.integration
async def test_supported_db_task_leases_do_not_expire_while_waiting_for_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the cross-runner lease and zero-provider-I/O contract on a real DB."""
    engine = create_async_engine(_test_database_url(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    run_tag = uuid4().hex[:12]
    user_id = str(uuid4())
    username = f"iter202_lease_{run_tag}"
    canonical_id = f"futures:CFFEX:IF2609:CNY-{run_tag}"
    first_task_id: str | None = None
    second_task_id: str | None = None
    cancel_cas_task_id: str | None = None
    fresh_cancel_task_id: str | None = None
    tasks_for_rejection: dict[str, str] = {}
    base_time = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    clock = [base_time]
    schema_ready = False
    monkeypatch.setattr(task_runner_module, "_now", lambda: clock[0])
    monkeypatch.setattr(orchestrator_module, "_now", lambda: clock[0])

    class _BlockingService:
        def __init__(self, db: AsyncSession) -> None:
            self.db = db

        async def run_claimed_task(self, *, task_id: str, lease_token: str) -> None:
            task = await self.db.get(AssetAnalysisTask, task_id)
            assert task is not None and task.lease_token == lease_token
            first_started.set()
            await release_first.wait()
            task.status = "SUCCEEDED"
            task.progress = 100
            task.completed_at = clock[0]

    class _FinishingService:
        def __init__(self, db: AsyncSession) -> None:
            self.db = db

        async def run_claimed_task(self, *, task_id: str, lease_token: str) -> None:
            task = await self.db.get(AssetAnalysisTask, task_id)
            assert task is not None
            assert task.status == "RUNNING" and task.lease_token == lease_token
            assert task.lease_expires_at is not None
            assert task.lease_expires_at.replace(tzinfo=timezone.utc) > clock[0]
            task.status = "SUCCEEDED"
            task.progress = 100
            task.completed_at = clock[0]

    class _NoProviderCall:
        def __init__(self) -> None:
            self.collect_calls = 0

        async def collect(
            self, identity: InstrumentIdentity, *, cutoff_at: datetime
        ) -> RawAssetSnapshot:
            self.collect_calls += 1
            return RawAssetSnapshot(
                identity=identity,
                cutoff_at=cutoff_at,
                retrieved_at=cutoff_at,
                raw_schema_version="iter202-lease-test-v1",
                raw_fields={"snapshot": {"price": 101}},
                history_rows=[],
                source_manifest={"source_id": DEFAULT_ASSET_RESEARCH_SOURCE_ID},
                license_tags=["APPROVED"],
                content_hash="c" * 64,
            )

    first_started = asyncio.Event()
    release_first = asyncio.Event()
    first_run: asyncio.Task[int] | None = None
    cancel_started = asyncio.Event()
    release_cancel = asyncio.Event()
    cancel_run: asyncio.Task[int] | None = None
    provider = _NoProviderCall()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            schema_ready = True
            version = str((await connection.execute(text("SELECT version()"))).scalar_one())
        backend = engine.url.get_backend_name()
        if backend == "mysql":
            assert re.search(r"\b8\.0\.\d+", version), f"expected MySQL 8.0, got {version}"
        else:
            assert re.search(r"\bPostgreSQL 16\.", version), (
                f"expected PostgreSQL 16, got {version}"
            )

        async with sessions() as db:
            user = User(
                id=user_id,
                username=username,
                email=f"{username}@example.test",
                hashed_password="hash",
            )
            db.add_all([user, _approved_source()])
            await db.flush()
            service = AssetResearchOrchestrator(db)
            await service.persist_identity(_identity(run_tag))
            first = await service.create_pending(user_id=user_id, request=_request(canonical_id))
            second = await service.create_pending(user_id=user_id, request=_request(canonical_id))
            first.created_at = base_time - timedelta(seconds=2)
            second.created_at = base_time - timedelta(seconds=1)
            first_task_id = first.id
            second_task_id = second.id
            await db.commit()

        first_runner = AssetResearchTaskRunner(
            session_maker=sessions,
            orchestrator_factory=_BlockingService,
            lease_seconds=5,
            max_batch=2,
            max_concurrency=1,
        )

        async def hold_without_renewing(
            claim: task_runner_module.ClaimedAnalysisTask, stop: asyncio.Event
        ) -> None:
            await stop.wait()

        monkeypatch.setattr(first_runner, "_maintain_lease_heartbeat", hold_without_renewing)
        second_runner = AssetResearchTaskRunner(
            session_maker=sessions,
            orchestrator_factory=_FinishingService,
            lease_seconds=5,
            max_batch=2,
            max_concurrency=1,
        )
        first_run = asyncio.create_task(first_runner.run_due(now=base_time))
        await asyncio.wait_for(first_started.wait(), timeout=5)

        async with sessions() as db:
            first_task = await db.get(AssetAnalysisTask, first_task_id)
            second_task = await db.get(AssetAnalysisTask, second_task_id)
            assert first_task is not None and first_task.status == "RUNNING"
            assert second_task is not None and second_task.status == "QUEUED"

        clock[0] = base_time + timedelta(seconds=6)
        assert await asyncio.wait_for(second_runner.run_due(now=clock[0]), timeout=5) == 1
        release_first.set()
        assert await asyncio.wait_for(first_run, timeout=5) == 1
        first_run = None

        async with sessions() as db:
            first_task = await db.get(AssetAnalysisTask, first_task_id)
            second_task = await db.get(AssetAnalysisTask, second_task_id)
            assert first_task is not None and first_task.error_code == "TASK_LEASE_EXPIRED"
            assert first_task.status == "FAILED"
            assert second_task is not None and second_task.status == "SUCCEEDED"

            lifecycle = AssetResearchOrchestrator(db)
            cancel_cas_task = await lifecycle.create_pending(
                user_id=user_id,
                request=_request(canonical_id),
            )
            cancel_cas_task_id = cancel_cas_task.id
            await db.commit()

        class _LateCompletionService:
            def __init__(self, db: AsyncSession) -> None:
                self.db = db

            async def run_claimed_task(self, *, task_id: str, lease_token: str) -> None:
                task = await self.db.get(AssetAnalysisTask, task_id)
                assert task is not None and task.lease_token == lease_token
                cancel_started.set()
                await release_cancel.wait()
                task.status = "SUCCEEDED"
                task.progress = 100
                task.completed_at = clock[0]

        cancel_runner = AssetResearchTaskRunner(
            session_maker=sessions,
            orchestrator_factory=_LateCompletionService,
            lease_seconds=60,
            max_batch=2,
            max_concurrency=1,
        )
        cancel_run = asyncio.create_task(cancel_runner.run_due(now=clock[0]))
        await asyncio.wait_for(cancel_started.wait(), timeout=5)
        async with sessions() as db:
            response = await AssetResearchOrchestrator(db).cancel_task(
                user_id=user_id,
                task_id=cancel_cas_task_id,
            )
            assert response is not None and response.status == "CANCELLED"
            await db.commit()
        release_cancel.set()
        assert await asyncio.wait_for(cancel_run, timeout=5) == 1
        cancel_run = None

        async with sessions() as db:
            cancelled = await db.get(AssetAnalysisTask, cancel_cas_task_id)
            assert cancelled is not None and cancelled.status == "CANCELLED"
            assert cancelled.lease_token is None
            assert cancelled.lease_expires_at is None
            assert cancelled.lease_heartbeat_at is None

        async with sessions() as db:
            fresh_cancel_task = await AssetResearchOrchestrator(db).create_pending(
                user_id=user_id,
                request=_request(canonical_id),
            )
            fresh_cancel_task.status = "RUNNING"
            fresh_cancel_token = f"fresh-cancel-{run_tag}"
            fresh_cancel_task.lease_token = fresh_cancel_token
            fresh_cancel_task.lease_heartbeat_at = clock[0]
            fresh_cancel_task.lease_expires_at = clock[0] + timedelta(minutes=1)
            fresh_cancel_task_id = fresh_cancel_task.id
            await db.commit()

        normalization_started = asyncio.Event()
        allow_lease_recheck = asyncio.Event()
        async with sessions() as db:
            service = AssetResearchOrchestrator(db, data_adapter=provider)

            async def pause_before_lease_recheck(**_: object) -> bool:
                normalization_started.set()
                await allow_lease_recheck.wait()
                return False

            monkeypatch.setattr(
                service,
                "_normalize_task_position_context_for_cutoff",
                pause_before_lease_recheck,
            )
            stale_session_run = asyncio.create_task(
                service.run_claimed_task(
                    task_id=fresh_cancel_task_id,
                    lease_token=fresh_cancel_token,
                )
            )
            try:
                await asyncio.wait_for(normalization_started.wait(), timeout=5)
                async with sessions() as cancel_db:
                    response = await AssetResearchOrchestrator(cancel_db).cancel_task(
                        user_id=user_id,
                        task_id=fresh_cancel_task_id,
                    )
                    assert response is not None and response.status == "CANCELLED"
                    await cancel_db.commit()
            finally:
                allow_lease_recheck.set()
            result = await asyncio.wait_for(stale_session_run, timeout=5)
            assert result is not None and result.error_code == "TASK_LEASE_LOST"
            await db.rollback()

        async with sessions() as db:
            fresh_cancel_task = await db.get(AssetAnalysisTask, fresh_cancel_task_id)
            assert fresh_cancel_task is not None and fresh_cancel_task.status == "CANCELLED"

        async with sessions() as db:
            lifecycle = AssetResearchOrchestrator(db)
            for label in ("old-token", "expired", "cancelled"):
                task = await lifecycle.create_pending(
                    user_id=user_id,
                    request=_request(canonical_id),
                )
                task.status = "RUNNING"
                task.lease_token = f"{label}-{run_tag}"
                task.lease_heartbeat_at = clock[0]
                task.lease_expires_at = (
                    clock[0] - timedelta(seconds=1)
                    if label == "expired"
                    else clock[0] + timedelta(minutes=1)
                )
                tasks_for_rejection[label] = task.id
            await db.commit()

        async with sessions() as db:
            response = await AssetResearchOrchestrator(db).cancel_task(
                user_id=user_id,
                task_id=tasks_for_rejection["cancelled"],
            )
            assert response is not None and response.status == "CANCELLED"
            await db.commit()

        for label, token in (
            ("old-token", "stale-token"),
            ("expired", f"expired-{run_tag}"),
            ("cancelled", f"cancelled-{run_tag}"),
        ):
            async with sessions() as db:
                result = await AssetResearchOrchestrator(
                    db, data_adapter=provider
                ).run_claimed_task(
                    task_id=tasks_for_rejection[label],
                    lease_token=token,
                )
                if label == "expired":
                    assert result is not None and result.error_code == "TASK_LEASE_EXPIRED"
                    await db.commit()
                else:
                    assert result is None

        assert provider.collect_calls == 0
    finally:
        release_first.set()
        release_cancel.set()
        if first_run is not None and not first_run.done():
            await first_run
        if cancel_run is not None and not cancel_run.done():
            await cancel_run
        if user_id and schema_ready:
            async with sessions() as db:
                await db.execute(
                    delete(AssetAnalysisTask).where(AssetAnalysisTask.user_id == user_id)
                )
                await db.execute(
                    delete(AssetDataSourceRegistry).where(
                        AssetDataSourceRegistry.source_id == DEFAULT_ASSET_RESEARCH_SOURCE_ID
                    )
                )
                await db.execute(
                    delete(AssetInstrument).where(AssetInstrument.canonical_id == canonical_id)
                )
                await db.execute(delete(User).where(User.id == user_id))
                await db.commit()
        await engine.dispose()
