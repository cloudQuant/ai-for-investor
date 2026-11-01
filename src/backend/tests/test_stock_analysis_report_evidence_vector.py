"""Behavioral tests for persisted OpenData stock-daily report evidence.

Every test uses an isolated file-backed SQLite database and synthetic grants,
publications, and timestamps. No OpenData network call is made and no real
publication is read.
"""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.database import Base
from app.models import (
    AssetDataSourceRegistry,
    StockSnapshotGrantAudit,
    StockSnapshotSourceResearchGrant,
    StockSnapshotUserReadGrant,
    User,
)
from app.models.permission import user_roles
from app.models.stock_analysis import StockAnalysisReportModel, StockAnalysisTaskModel
from app.schemas.stock_analysis import (
    StockAnalysisParams,
    StockAnalysisStockDailySnapshotSelection,
)
from app.services.stock_analysis.opendata_snapshot_authorization import (
    RESEARCH_PURPOSE,
    StockAnalysisSnapshotAuthorizationReceipt,
    StockAnalysisSnapshotScope,
)
from app.services.stock_analysis.stock_daily_report_evidence import (
    DATASET_ID,
    SOURCE_ID,
    StockDailyReportEvidence,
    StockDailyReportEvidenceError,
    StockDailyReportEvidenceExpectation,
    StockDailyReportEvidenceGate,
    StockDailyReportEvidenceVector,
)
from app.services.stock_analysis.stock_daily_snapshot_authorization_adapter import (
    StockDailySnapshotAuthorizationAdapter,
    source_registry_revision,
)
from app.services.stock_analysis.tasks import StockAnalysisTaskService

UTC = timezone.utc
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
VALID_FROM = NOW - timedelta(minutes=5)
EXPIRES_AT = NOW + timedelta(hours=1)
CONTENT_SHA256 = "f" * 64
CONTRACT_SHA256 = "d" * 64
PUBLICATION_ID = "a" * 32
PUBLICATION_SEQUENCE = 7
CAPTURED_AT = datetime(2026, 10, 30, 0, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 10, 30, 0, 0, tzinfo=UTC)
USER_ID = "4a5a77a0-8db9-4e20-b8a3-070aef54e417"
USER_GRANT_ID = "88919c8f-6bd3-44ca-a96b-26c5b0551960"
SOURCE_GRANT_ID = "63fb60bb-23ef-4a96-9ea0-f814f78018d9"
INSTRUMENT_ID = "600519.SH"

_TABLES = (
    User.__table__,
    user_roles,
    AssetDataSourceRegistry.__table__,
    StockSnapshotUserReadGrant.__table__,
    StockSnapshotSourceResearchGrant.__table__,
    StockSnapshotGrantAudit.__table__,
    StockAnalysisTaskModel.__table__,
    StockAnalysisReportModel.__table__,
)

SessionFactory = async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[SessionFactory]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'report-evidence.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=list(_TABLES))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _scope() -> StockAnalysisSnapshotScope:
    return StockAnalysisSnapshotScope(
        user_id=USER_ID,
        dataset_id=DATASET_ID,
        source_id=SOURCE_ID,
        instrument_id=INSTRUMENT_ID,
        market="SH",
        publication_id=PUBLICATION_ID,
        capture_id=CONTENT_SHA256,
    )


def _selector(
    *,
    content_sha256: str = CONTENT_SHA256,
    contract_sha256: str = CONTRACT_SHA256,
) -> StockAnalysisStockDailySnapshotSelection:
    return StockAnalysisStockDailySnapshotSelection(
        instrument_id=INSTRUMENT_ID,
        publication_id=PUBLICATION_ID,
        publication_sequence=PUBLICATION_SEQUENCE,
        content_sha256=content_sha256,
        contract_sha256=contract_sha256,
    )


def _params(
    selector: StockAnalysisStockDailySnapshotSelection | None = None,
) -> StockAnalysisParams:
    return StockAnalysisParams(symbol=INSTRUMENT_ID, opendata_stock_daily_snapshot=selector)


def _user() -> User:
    return User(
        id=USER_ID,
        username="report-evidence-user",
        email="report-evidence@example.test",
        hashed_password="test-only-hash",
        is_active=True,
    )


def _registry() -> AssetDataSourceRegistry:
    return AssetDataSourceRegistry(
        source_id=SOURCE_ID,
        asset_types=["stock"],
        jurisdictions=["GLOBAL"],
        license_status="APPROVED",
        allowed_uses=["RESEARCH"],
        redistribution_policy="INTERNAL_ONLY",
        retention_policy="research-v1",
        effective_from=NOW - timedelta(days=1),
        enabled=True,
        updated_at=NOW,
    )


def _user_grant() -> StockSnapshotUserReadGrant:
    return StockSnapshotUserReadGrant(
        id=USER_GRANT_ID,
        user_id=USER_ID,
        permission="data:read",
        dataset_id=DATASET_ID,
        instrument_id=INSTRUMENT_ID,
        market="SH",
        publication_id=PUBLICATION_ID,
        capture_id=CONTENT_SHA256,
        purpose=RESEARCH_PURPOSE,
        revision=1,
        valid_from=VALID_FROM,
        expires_at=EXPIRES_AT,
    )


def _source_grant(*, registry_revision: str) -> StockSnapshotSourceResearchGrant:
    return StockSnapshotSourceResearchGrant(
        id=SOURCE_GRANT_ID,
        user_id=USER_ID,
        source_id=SOURCE_ID,
        dataset_id=DATASET_ID,
        instrument_id=INSTRUMENT_ID,
        market="SH",
        publication_id=PUBLICATION_ID,
        capture_id=CONTENT_SHA256,
        purpose=RESEARCH_PURPOSE,
        source_registry_revision=registry_revision,
        revision=1,
        valid_from=VALID_FROM,
        expires_at=EXPIRES_AT,
    )


def _issued_audit(
    *,
    user_grant_id: str | None = USER_GRANT_ID,
    source_grant_id: str | None = None,
    idempotency_hash: str,
) -> StockSnapshotGrantAudit:
    return StockSnapshotGrantAudit(
        user_grant_id=user_grant_id,
        source_grant_id=source_grant_id,
        subject_user_id=USER_ID,
        actor_user_id=USER_ID,
        event_type="ISSUED",
        grant_revision=1,
        revocation_revision=1,
        policy_version="stock-analysis-opendata-access-v1",
        occurred_at=NOW,
        reason_code="test_issued",
        idempotency_key_sha256=idempotency_hash,
    )


async def _seed_grants(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        session.add(_user())
        await session.flush()
        await session.execute(user_roles.insert().values(user_id=USER_ID, role="user"))
        registry = _registry()
        session.add(registry)
        await session.flush()
        session.add(_user_grant())
        session.add(_source_grant(registry_revision=source_registry_revision(registry)))
        await session.flush()
        session.add(_issued_audit(idempotency_hash="1" * 64))
        session.add(
            _issued_audit(
                user_grant_id=None,
                source_grant_id=SOURCE_GRANT_ID,
                idempotency_hash="2" * 64,
            )
        )
        await session.commit()


async def _seed_user(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        session.add(_user())
        await session.commit()


async def _revoke_user_grant(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        session.add(
            StockSnapshotGrantAudit(
                user_grant_id=USER_GRANT_ID,
                source_grant_id=None,
                subject_user_id=USER_ID,
                actor_user_id=USER_ID,
                event_type="REVOKED",
                grant_revision=1,
                revocation_revision=2,
                policy_version="stock-analysis-opendata-access-v1",
                occurred_at=NOW + timedelta(seconds=30),
                reason_code="test_revoked",
                idempotency_key_sha256="9" * 64,
            )
        )
        await session.commit()


async def _authorize(
    session_factory: SessionFactory,
    *,
    now: datetime = NOW,
) -> StockAnalysisSnapshotAuthorizationReceipt:
    adapter = StockDailySnapshotAuthorizationAdapter(clock=lambda: now)
    async with session_factory() as session:
        return await adapter.authorize(
            session=session,
            user_id=USER_ID,
            scope=_scope(),
        )


def _evidence(
    receipt: StockAnalysisSnapshotAuthorizationReceipt,
) -> StockDailyReportEvidence:
    return StockDailyReportEvidence(
        dataset_id=DATASET_ID,
        source_id=SOURCE_ID,
        instrument_id=INSTRUMENT_ID,
        market="SH",
        publication_id=PUBLICATION_ID,
        publication_sequence=PUBLICATION_SEQUENCE,
        content_sha256=CONTENT_SHA256,
        contract_sha256=CONTRACT_SHA256,
        captured_at=CAPTURED_AT,
        observed_at=OBSERVED_AT,
        principal_user_id=receipt.principal_user_id,
        entitlement_revision=receipt.entitlement_revision,
        user_grant_id=receipt.user_grant_id,
        user_grant_revision=receipt.user_grant_revision,
        user_grant_valid_from=receipt.user_grant_valid_from,
        user_grant_expires_at=receipt.user_grant_expires_at,
        source_grant_id=receipt.source_grant_id,
        source_grant_revision=receipt.source_grant_revision,
        source_grant_valid_from=receipt.source_grant_valid_from,
        source_grant_expires_at=receipt.source_grant_expires_at,
        authorized_at=receipt.authorized_at,
        expires_at=receipt.expires_at,
        purpose=RESEARCH_PURPOSE,
        authorization_receipt=receipt,
    )


def _service(
    session: AsyncSession,
    session_factory: SessionFactory,
    *,
    now: datetime = NOW,
) -> StockAnalysisTaskService:
    gate = StockDailyReportEvidenceGate(
        adapter=StockDailySnapshotAuthorizationAdapter(clock=lambda: now)
    )
    return StockAnalysisTaskService(
        session,
        report_evidence_gate=gate,
        report_evidence_session_factory=session_factory,
    )


async def _create_task(
    session_factory: SessionFactory,
    *,
    params: StockAnalysisParams,
    vector: StockDailyReportEvidenceVector | None = None,
) -> str:
    async with session_factory() as session:
        service = StockAnalysisTaskService(session)
        task = await service.create_pending(
            user_id=USER_ID,
            params=params,
            stock_daily_evidence=vector,
        )
        await session.commit()
        return task.id


async def _insert_task(
    session_factory: SessionFactory,
    *,
    parameters: dict[str, Any],
) -> str:
    async with session_factory() as session:
        task = StockAnalysisTaskModel(
            user_id=USER_ID,
            symbol=INSTRUMENT_ID,
            market_type="A股",
            analysis_date="2026-10-30",
            research_depth="标准",
            selected_modules=[],
            status="pending",
            progress=0,
            parameters_json=parameters,
            step_events_json=[],
        )
        session.add(task)
        await session.flush()
        task_id = task.id
        await session.commit()
        return task_id


async def _save_report(
    session_factory: SessionFactory,
    *,
    task_id: str,
    params: StockAnalysisParams,
    now: datetime = NOW,
) -> StockAnalysisReportModel:
    async with session_factory() as session:
        service = _service(session, session_factory, now=now)
        task = await service.get_task(user_id=USER_ID, task_id=task_id)
        assert task is not None
        report = await service._build_and_save_report(
            task=task,
            params=params,
            snapshot={"data_quality": {"status": "ok"}},
            pipeline_output={},
            payload={
                "executive_summary": "synthetic summary",
                "decision": {"label": "观望"},
            },
        )
        await session.commit()
        await session.refresh(report)
        return report


async def _report_count(session_factory: SessionFactory) -> int:
    async with session_factory() as session:
        return int(
            (
                await session.execute(select(func.count()).select_from(StockAnalysisReportModel))
            ).scalar_one()
        )


def _stored_vector_json(task_parameters: dict[str, Any]) -> dict[str, Any]:
    raw = copy.deepcopy(task_parameters["opendata_stock_daily_evidence"])
    assert isinstance(raw, dict)
    return raw


async def test_vector_round_trips_through_strict_json(
    session_factory: SessionFactory,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    vector = StockDailyReportEvidenceVector(entries=(_evidence(receipt),))

    payload = vector.to_json()
    parsed = StockDailyReportEvidenceVector.from_json(payload)

    assert parsed == vector
    assert parsed.to_json() == payload
    assert parsed.entries[0].captured_at.utcoffset() == timedelta(0)
    assert parsed.entries[0].observed_at.utcoffset() == timedelta(0)


async def test_allowed_evidence_is_revalidated_and_persisted(
    session_factory: SessionFactory,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    vector = StockDailyReportEvidenceVector(entries=(_evidence(receipt),))
    params = _params(_selector())
    task_id = await _create_task(session_factory, params=params, vector=vector)

    async with session_factory() as session:
        task = (
            await session.execute(
                select(StockAnalysisTaskModel).where(StockAnalysisTaskModel.id == task_id)
            )
        ).scalar_one()
        assert task.parameters_json is not None
        assert task.parameters_json["opendata_stock_daily_evidence"] == vector.to_json()

    report = await _save_report(session_factory, task_id=task_id, params=params)

    assert report.evidence_vector_json == vector.to_json()
    assert report.title == f"{INSTRUMENT_ID} 股票分析报告"
    assert report.summary == "synthetic summary"
    assert report.recommendation_label == "观望"
    assert report.report_json == {
        "executive_summary": "synthetic summary",
        "decision": {"label": "观望"},
    }
    assert StockDailyReportEvidenceVector.from_json(report.evidence_vector_json) == vector


async def test_missing_publication_id_fails_without_report(
    session_factory: SessionFactory,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    vector = StockDailyReportEvidenceVector(entries=(_evidence(receipt),))
    parameters = _params(_selector()).model_dump(mode="json")
    corrupted = copy.deepcopy(vector.to_json())
    entries = corrupted["entries"]
    assert isinstance(entries, list)
    del entries[0]["publication_id"]
    parameters["opendata_stock_daily_evidence"] = corrupted
    task_id = await _insert_task(session_factory, parameters=parameters)

    with pytest.raises(StockDailyReportEvidenceError) as failure:
        await _save_report(session_factory, task_id=task_id, params=_params(_selector()))

    assert failure.value.code == "stock_daily_report_evidence_publication_missing"
    assert await _report_count(session_factory) == 0


async def test_hash_mismatch_fails_without_report(
    session_factory: SessionFactory,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    vector = StockDailyReportEvidenceVector(entries=(_evidence(receipt),))
    params = _params(_selector())
    task_id = await _create_task(session_factory, params=params, vector=vector)
    mismatched = _params(_selector(content_sha256="e" * 64))

    with pytest.raises(StockDailyReportEvidenceError) as failure:
        await _save_report(session_factory, task_id=task_id, params=mismatched)

    assert failure.value.code == "stock_daily_report_evidence_hash_mismatch"
    assert await _report_count(session_factory) == 0


async def test_contract_hash_mismatch_fails_without_report(
    session_factory: SessionFactory,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    vector = StockDailyReportEvidenceVector(entries=(_evidence(receipt),))
    params = _params(_selector())
    task_id = await _create_task(session_factory, params=params, vector=vector)
    mismatched = _params(_selector(contract_sha256="e" * 64))

    with pytest.raises(StockDailyReportEvidenceError) as failure:
        await _save_report(session_factory, task_id=task_id, params=mismatched)

    assert failure.value.code == "stock_daily_report_evidence_hash_mismatch"
    assert await _report_count(session_factory) == 0


async def test_expired_grant_fails_without_report(
    session_factory: SessionFactory,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    vector = StockDailyReportEvidenceVector(entries=(_evidence(receipt),))
    params = _params(_selector())
    task_id = await _create_task(session_factory, params=params, vector=vector)

    with pytest.raises(StockDailyReportEvidenceError) as failure:
        await _save_report(
            session_factory,
            task_id=task_id,
            params=params,
            now=NOW + timedelta(hours=2),
        )

    assert failure.value.code == "authorization_expired"
    assert await _report_count(session_factory) == 0


async def test_revoked_grant_fails_without_report(
    session_factory: SessionFactory,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    vector = StockDailyReportEvidenceVector(entries=(_evidence(receipt),))
    params = _params(_selector())
    task_id = await _create_task(session_factory, params=params, vector=vector)
    await _revoke_user_grant(session_factory)

    with pytest.raises(StockDailyReportEvidenceError) as failure:
        await _save_report(
            session_factory,
            task_id=task_id,
            params=params,
            now=NOW + timedelta(minutes=1),
        )

    assert failure.value.code == "user_grant_revoked"
    assert await _report_count(session_factory) == 0


async def test_declared_selector_without_vector_fails_closed(
    session_factory: SessionFactory,
) -> None:
    await _seed_grants(session_factory)
    parameters = _params(_selector()).model_dump(mode="json")
    task_id = await _insert_task(session_factory, parameters=parameters)

    with pytest.raises(StockDailyReportEvidenceError) as failure:
        await _save_report(session_factory, task_id=task_id, params=_params(_selector()))

    assert failure.value.code == "stock_daily_report_evidence_missing"
    assert await _report_count(session_factory) == 0


async def test_vector_without_selector_fails_closed(
    session_factory: SessionFactory,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    vector = StockDailyReportEvidenceVector(entries=(_evidence(receipt),))
    parameters = _params().model_dump(mode="json")
    parameters["opendata_stock_daily_evidence"] = vector.to_json()
    task_id = await _insert_task(session_factory, parameters=parameters)

    with pytest.raises(StockDailyReportEvidenceError) as failure:
        await _save_report(session_factory, task_id=task_id, params=_params())

    assert failure.value.code == "stock_daily_report_evidence_scope_missing"
    assert await _report_count(session_factory) == 0


async def test_legacy_task_saves_report_unchanged(
    session_factory: SessionFactory,
) -> None:
    await _seed_user(session_factory)
    params = StockAnalysisParams(symbol=INSTRUMENT_ID)
    task_id = await _create_task(session_factory, params=params)

    report = await _save_report(session_factory, task_id=task_id, params=params)

    assert report.evidence_vector_json is None
    assert report.title == f"{INSTRUMENT_ID} 股票分析报告"
    assert report.summary == "synthetic summary"
    assert report.recommendation_label == "观望"
    assert report.source_snapshot_json == {"data_quality": {"status": "ok"}}
    assert await _report_count(session_factory) == 1


async def test_legacy_task_never_requires_grants(
    session_factory: SessionFactory,
) -> None:
    # No grant rows are seeded at all: the legacy path must not open the
    # authorization adapter or require a receipt.
    await _seed_user(session_factory)
    params = StockAnalysisParams(symbol=INSTRUMENT_ID)
    task_id = await _create_task(session_factory, params=params)

    report = await _save_report(
        session_factory,
        task_id=task_id,
        params=params,
        now=NOW + timedelta(days=30),
    )

    assert report.evidence_vector_json is None
    assert await _report_count(session_factory) == 1


def test_expectation_rejects_missing_publication_id() -> None:
    with pytest.raises(StockDailyReportEvidenceError) as failure:
        StockDailyReportEvidenceExpectation(
            dataset_id=DATASET_ID,
            source_id=SOURCE_ID,
            instrument_id=INSTRUMENT_ID,
            market="SH",
            publication_id="",
            publication_sequence=PUBLICATION_SEQUENCE,
            content_sha256=CONTENT_SHA256,
            contract_sha256=CONTRACT_SHA256,
        )
    assert failure.value.code == "stock_daily_report_evidence_publication_missing"


async def test_evidence_rejects_naive_timestamps_and_duplicate_identities(
    session_factory: SessionFactory,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    evidence = _evidence(receipt)

    with pytest.raises(StockDailyReportEvidenceError) as naive:
        replace(evidence, captured_at=datetime(2026, 10, 30, 0, 0))
    assert naive.value.code == "stock_daily_report_evidence_invalid"

    with pytest.raises(StockDailyReportEvidenceError) as duplicate:
        StockDailyReportEvidenceVector(entries=(evidence, evidence))
    assert duplicate.value.code == "stock_daily_report_evidence_invalid"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (("publication_sequence", 0), "stock_daily_report_evidence_invalid"),
        (("publication_sequence", True), "stock_daily_report_evidence_invalid"),
        (("content_sha256", "F" * 64), "stock_daily_report_evidence_invalid"),
        (("market", "SZ"), "stock_daily_report_evidence_invalid"),
        (("publication_id", "A" * 32), "stock_daily_report_evidence_invalid"),
        (("captured_at", "2026-10-30T00:00:00"), "stock_daily_report_evidence_invalid"),
        (("principal_user_id", "other-user"), "stock_daily_report_evidence_receipt_mismatch"),
        (("purpose", "PRODUCTION"), "stock_daily_report_evidence_invalid"),
    ],
)
async def test_evidence_json_rejects_mutated_fields(
    mutation: tuple[str, object],
    code: str,
    session_factory: SessionFactory,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    vector = StockDailyReportEvidenceVector(entries=(_evidence(receipt),))
    payload = copy.deepcopy(vector.to_json())
    entries = payload["entries"]
    assert isinstance(entries, list)
    entries[0][mutation[0]] = mutation[1]

    with pytest.raises(StockDailyReportEvidenceError) as failure:
        StockDailyReportEvidenceVector.from_json(payload)
    assert failure.value.code == code


async def test_vector_json_rejects_unknown_version_and_extra_keys(
    session_factory: SessionFactory,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    vector = StockDailyReportEvidenceVector(entries=(_evidence(receipt),))

    payload = copy.deepcopy(vector.to_json())
    payload["version"] = "stock-analysis-report-evidence-v2"
    with pytest.raises(StockDailyReportEvidenceError) as version_failure:
        StockDailyReportEvidenceVector.from_json(payload)
    assert version_failure.value.code == "stock_daily_report_evidence_invalid"

    payload = copy.deepcopy(vector.to_json())
    payload["extra"] = "not-allowed"
    with pytest.raises(StockDailyReportEvidenceError) as extra_failure:
        StockDailyReportEvidenceVector.from_json(payload)
    assert extra_failure.value.code == "stock_daily_report_evidence_invalid"
