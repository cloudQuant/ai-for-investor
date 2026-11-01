"""Behavioral tests for the current-evidence stock-daily authorization adapter.

Everything runs against isolated in-memory/file SQLite databases. No OpenData
network call is made; provider behavior is an ``httpx.MockTransport`` fixture.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models import (
    AssetDataSourceRegistry,
    StockSnapshotGrantAudit,
    StockSnapshotSourceResearchGrant,
    StockSnapshotUserReadGrant,
    User,
)
from app.models.permission import user_roles
from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.market_data.opendata_provider import OpendataProvider
from app.services.market_data.opendata_stock_daily_snapshot import (
    OpendataStockDailySnapshotError,
    OpendataStockDailySnapshotReader,
)
from app.services.stock_analysis.opendata_snapshot_authorization import (
    StockAnalysisSnapshotScope,
)
from app.services.stock_analysis.stock_daily_snapshot_authorization_adapter import (
    StockDailySnapshotAuthorizationAdapter,
    StockDailySnapshotAuthorizationError,
    source_registry_revision,
)
from tests.test_opendata_stock_daily_snapshot import (
    PUBLICATION_ID,
    _page,
    _request,
    _response,
    _row,
    _snapshot,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
VALID_FROM = NOW - timedelta(minutes=5)
EXPIRES_AT = NOW + timedelta(hours=1)
CONTENT_SHA256 = "f" * 64
USER_ID = "4a5a77a0-8db9-4e20-b8a3-070aef54e417"
OTHER_USER_ID = "7ec9aefe-f57a-47cc-955b-8b94e0105578"
USER_GRANT_ID = "88919c8f-6bd3-44ca-a96b-26c5b0551960"
SOURCE_GRANT_ID = "63fb60bb-23ef-4a96-9ea0-f814f78018d9"

_TABLES = (
    User.__table__,
    user_roles,
    AssetDataSourceRegistry.__table__,
    StockSnapshotUserReadGrant.__table__,
    StockSnapshotSourceResearchGrant.__table__,
    StockSnapshotGrantAudit.__table__,
)


def _scope(
    *,
    user_id: str = USER_ID,
    instrument_id: str = "600519.SH",
    market: str = "SH",
    publication_id: str = PUBLICATION_ID,
    capture_id: str = CONTENT_SHA256,
) -> StockAnalysisSnapshotScope:
    return StockAnalysisSnapshotScope(
        user_id=user_id,
        dataset_id="cn-equity-stock-daily",
        source_id="akshare.daily",
        instrument_id=instrument_id,
        market=market,
        publication_id=publication_id,
        capture_id=capture_id,
    )


async def _make_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=list(_TABLES))
    return engine


def _user(user_id: str = USER_ID, *, active: bool = True) -> User:
    suffix = user_id[:8]
    return User(
        id=user_id,
        username=f"stock-daily-{suffix}",
        email=f"stock-daily-{suffix}@example.test",
        hashed_password="test-only-hash",
        is_active=active,
    )


def _registry(
    *,
    enabled: bool = True,
    license_status: str = "APPROVED",
) -> AssetDataSourceRegistry:
    return AssetDataSourceRegistry(
        source_id="akshare.daily",
        asset_types=["stock"],
        jurisdictions=["GLOBAL"],
        license_status=license_status,
        allowed_uses=["RESEARCH"],
        redistribution_policy="INTERNAL_ONLY",
        retention_policy="research-v1",
        effective_from=NOW - timedelta(days=1),
        enabled=enabled,
        updated_at=NOW,
    )


def _user_grant(
    *,
    publication_id: str = PUBLICATION_ID,
    capture_id: str = CONTENT_SHA256,
    user_id: str = USER_ID,
) -> StockSnapshotUserReadGrant:
    return StockSnapshotUserReadGrant(
        id=USER_GRANT_ID,
        user_id=user_id,
        permission="data:read",
        dataset_id="cn-equity-stock-daily",
        instrument_id="600519.SH",
        market="SH",
        publication_id=publication_id,
        capture_id=capture_id,
        purpose="RESEARCH",
        revision=1,
        valid_from=VALID_FROM,
        expires_at=EXPIRES_AT,
    )


def _source_grant(
    *,
    registry_revision: str,
    publication_id: str = PUBLICATION_ID,
    capture_id: str = CONTENT_SHA256,
    user_id: str = USER_ID,
) -> StockSnapshotSourceResearchGrant:
    return StockSnapshotSourceResearchGrant(
        id=SOURCE_GRANT_ID,
        user_id=user_id,
        source_id="akshare.daily",
        dataset_id="cn-equity-stock-daily",
        instrument_id="600519.SH",
        market="SH",
        publication_id=publication_id,
        capture_id=capture_id,
        purpose="RESEARCH",
        source_registry_revision=registry_revision,
        revision=1,
        valid_from=VALID_FROM,
        expires_at=EXPIRES_AT,
    )


def _audit(
    *,
    event_type: str,
    idempotency_hash: str,
    occurred_at: datetime = NOW,
    user_grant_id: str | None = USER_GRANT_ID,
    source_grant_id: str | None = None,
    subject_user_id: str = USER_ID,
) -> StockSnapshotGrantAudit:
    return StockSnapshotGrantAudit(
        user_grant_id=user_grant_id,
        source_grant_id=source_grant_id,
        subject_user_id=subject_user_id,
        actor_user_id=USER_ID,
        event_type=event_type,
        grant_revision=1,
        revocation_revision=1 if event_type == "ISSUED" else 2,
        policy_version="stock-analysis-opendata-access-v1",
        occurred_at=occurred_at,
        reason_code=f"test_{event_type.lower()}",
        idempotency_key_sha256=idempotency_hash,
    )


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    registry: bool = True,
    registry_enabled: bool = True,
    license_status: str = "APPROVED",
    user_grant: bool = True,
    source_grant: bool = True,
    user_audit: bool = True,
    source_audit: bool = True,
    active: bool = True,
    grant_publication_id: str = PUBLICATION_ID,
    grant_capture_id: str = CONTENT_SHA256,
) -> None:
    async with session_factory() as session:
        session.add(_user(active=active))
        await session.flush()
        await session.execute(user_roles.insert().values(user_id=USER_ID, role="user"))
        revision = "asset-source-registry-v1:" + "0" * 64
        if registry:
            row = _registry(enabled=registry_enabled, license_status=license_status)
            session.add(row)
            await session.flush()
            revision = source_registry_revision(row)
        if user_grant:
            session.add(
                _user_grant(
                    publication_id=grant_publication_id,
                    capture_id=grant_capture_id,
                )
            )
        if source_grant:
            session.add(
                _source_grant(
                    registry_revision=revision,
                    publication_id=grant_publication_id,
                    capture_id=grant_capture_id,
                )
            )
        await session.flush()
        if user_grant and user_audit:
            session.add(
                _audit(event_type="ISSUED", idempotency_hash="1" * 64, user_grant_id=USER_GRANT_ID)
            )
        if source_grant and source_audit:
            session.add(
                _audit(
                    event_type="ISSUED",
                    idempotency_hash="2" * 64,
                    user_grant_id=None,
                    source_grant_id=SOURCE_GRANT_ID,
                )
            )
        await session.commit()


def _provider(handler: Any) -> tuple[OpendataProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpendataProvider(
        client=client,
        credentials=OpendataCredentials("synthetic-key", base_url="http://opendata.test"),
        max_retries=0,
        retry_backoff_seconds=0,
    )
    return provider, client


def _adapter() -> StockDailySnapshotAuthorizationAdapter:
    return StockDailySnapshotAuthorizationAdapter(clock=lambda: NOW)


@pytest.mark.asyncio
async def test_allowed_scope_returns_receipt_with_utc_restored_datetimes() -> None:
    engine = await _make_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        await _seed(session_factory)
        async with session_factory() as session:
            raw = (
                await session.execute(
                    select(StockSnapshotUserReadGrant)
                    .where(StockSnapshotUserReadGrant.id == USER_GRANT_ID)
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
            assert raw.valid_from.tzinfo is None  # SQLite drops timezone metadata

            receipt = await _adapter().authorize(
                session=session,
                user_id=USER_ID,
                scope=_scope(),
            )

        assert receipt.user_grant_id == USER_GRANT_ID
        assert receipt.source_grant_id == SOURCE_GRANT_ID
        assert receipt.user_grant_valid_from == VALID_FROM
        assert receipt.user_grant_expires_at == EXPIRES_AT
        assert receipt.user_grant_valid_from.utcoffset() == timedelta(0)
        assert receipt.authorized_at == NOW
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_missing_user_grant_denies_before_any_provider_call() -> None:
    engine = await _make_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _response({})

    provider, client = _provider(handler)
    reader = OpendataStockDailySnapshotReader(provider, authorization_adapter=_adapter())
    try:
        await _seed(session_factory, user_grant=False)
        async with session_factory() as session:
            with pytest.raises(OpendataStockDailySnapshotError) as failure:
                await reader.read_authorized(
                    _request(),
                    publication_id=PUBLICATION_ID,
                    content_sha256=CONTENT_SHA256,
                    user_id=USER_ID,
                    session=session,
                )
        assert failure.value.code == "stock_daily_user_grant_missing"
        assert calls == []
    finally:
        await client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_allowed_reader_fetches_once_and_returns_validated_rows() -> None:
    engine = await _make_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _response(_page([_row("2026-10-27"), _row("2026-10-28")]))

    provider, client = _provider(handler)
    reader = OpendataStockDailySnapshotReader(provider, authorization_adapter=_adapter())
    try:
        await _seed(session_factory)
        async with session_factory() as session:
            result = await reader.read_authorized(
                _request(),
                publication_id=PUBLICATION_ID,
                content_sha256=CONTENT_SHA256,
                user_id=USER_ID,
                session=session,
            )
        assert len(calls) == 1
        assert [row["business_date"] for row in result.records] == [
            "2026-10-27",
            "2026-10-28",
        ]
        assert result.snapshot["content_sha256"] == CONTENT_SHA256
    finally:
        await client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_revoked_between_authorization_and_revalidation_fails_second_check() -> None:
    engine = await _make_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        await _seed(session_factory)
        adapter = _adapter()
        async with session_factory() as session:
            receipt = await adapter.authorize(
                session=session,
                user_id=USER_ID,
                scope=_scope(),
            )

            async with session_factory() as revocation_session:
                revocation_session.add(
                    _audit(
                        event_type="REVOKED",
                        idempotency_hash="9" * 64,
                        occurred_at=NOW + timedelta(seconds=30),
                        user_grant_id=USER_GRANT_ID,
                    )
                )
                await revocation_session.commit()

            with pytest.raises(StockDailySnapshotAuthorizationError) as failure:
                await adapter.revalidate(
                    session=session,
                    user_id=USER_ID,
                    scope=_scope(),
                    receipt=receipt,
                )
        assert failure.value.code == "user_grant_revoked"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_missing_registry_row_denies() -> None:
    engine = await _make_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        await _seed(session_factory, registry=False)
        async with session_factory() as session:
            with pytest.raises(StockDailySnapshotAuthorizationError) as failure:
                await _adapter().authorize(
                    session=session,
                    user_id=USER_ID,
                    scope=_scope(),
                )
        assert failure.value.code == "stock_daily_source_registry_unregistered"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("registry_enabled", "license_status"),
    [(False, "APPROVED"), (True, "UNKNOWN")],
)
async def test_registry_not_allowed_denies(registry_enabled: bool, license_status: str) -> None:
    engine = await _make_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        await _seed(
            session_factory,
            registry_enabled=registry_enabled,
            license_status=license_status,
        )
        async with session_factory() as session:
            with pytest.raises(StockDailySnapshotAuthorizationError) as failure:
                await _adapter().authorize(
                    session=session,
                    user_id=USER_ID,
                    scope=_scope(),
                )
        assert failure.value.code == "stock_daily_source_registry_denied"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["user_audit", "source_audit"])
async def test_missing_issue_audit_denies(missing: str) -> None:
    engine = await _make_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        await _seed(session_factory, **{missing: False})
        async with session_factory() as session:
            with pytest.raises(StockDailySnapshotAuthorizationError) as failure:
                await _adapter().authorize(
                    session=session,
                    user_id=USER_ID,
                    scope=_scope(),
                )
        assert failure.value.code == "stock_daily_grant_audit_invalid"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_issue_audit_cannot_be_persisted() -> None:
    engine = await _make_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        await _seed(session_factory)
        async with session_factory() as session:
            session.add(
                _audit(
                    event_type="ISSUED",
                    idempotency_hash="3" * 64,
                    user_grant_id=USER_GRANT_ID,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_fallback_to_another_publication_or_registry_only_grant() -> None:
    engine = await _make_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _response({})

    provider, client = _provider(handler)
    reader = OpendataStockDailySnapshotReader(provider, authorization_adapter=_adapter())
    try:
        await _seed(session_factory, grant_publication_id="9" * 32)
        async with session_factory() as session:
            with pytest.raises(OpendataStockDailySnapshotError) as failure:
                await reader.read_authorized(
                    _request(),
                    publication_id=PUBLICATION_ID,
                    content_sha256=CONTENT_SHA256,
                    user_id=USER_ID,
                    session=session,
                )
        assert failure.value.code == "stock_daily_user_grant_missing"
        assert calls == []
    finally:
        await client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_inactive_principal_denies_without_registry_or_provider_read() -> None:
    engine = await _make_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        await _seed(session_factory, active=False)
        async with session_factory() as session:
            with pytest.raises(StockDailySnapshotAuthorizationError) as failure:
                await _adapter().authorize(
                    session=session,
                    user_id=USER_ID,
                    scope=_scope(),
                )
        assert failure.value.code == "stock_daily_principal_denied"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_response_content_hash_drift_fails_closed_after_fetch() -> None:
    engine = await _make_engine()
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        changed = _snapshot()
        changed["content_sha256"] = "c" * 64
        return _response(_page([_row("2026-10-27"), _row("2026-10-28")], snapshot=changed))

    provider, client = _provider(handler)
    reader = OpendataStockDailySnapshotReader(provider, authorization_adapter=_adapter())
    try:
        await _seed(session_factory)
        async with session_factory() as session:
            with pytest.raises(OpendataStockDailySnapshotError) as failure:
                await reader.read_authorized(
                    _request(),
                    publication_id=PUBLICATION_ID,
                    content_sha256=CONTENT_SHA256,
                    user_id=USER_ID,
                    session=session,
                )
        assert failure.value.code == "opendata_snapshot_content_changed"
        assert len(calls) == 1
    finally:
        await client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_authorized_reader_is_unavailable_without_injected_adapter() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response({})

    provider, client = _provider(handler)
    reader = OpendataStockDailySnapshotReader(provider)
    try:
        with pytest.raises(OpendataStockDailySnapshotError) as failure:
            await reader.read_authorized(
                _request(),
                publication_id=PUBLICATION_ID,
                content_sha256=CONTENT_SHA256,
                user_id=USER_ID,
                session=None,  # type: ignore[arg-type]
            )
        assert failure.value.code == "stock_daily_authorization_unavailable"
        assert calls == 0
    finally:
        await client.aclose()
