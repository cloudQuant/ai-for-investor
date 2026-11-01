"""Behavioral tests for producing persisted stock-daily report evidence.

Every test uses an isolated file-backed SQLite database, synthetic grants, and
an in-process fake reader. No OpenData network call, credential, or real
publication is used.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
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
from app.models.ai_call_log import AICallLog
from app.models.permission import user_roles
from app.models.stock_analysis import StockAnalysisReportModel, StockAnalysisTaskModel
from app.schemas.stock_analysis import (
    StockAnalysisParams,
    StockAnalysisStockDailySnapshotSelection,
)
from app.services.market_data.opendata_provider import OpendataPublishedSnapshotResult
from app.services.market_data.opendata_stock_daily_snapshot import (
    OpendataStockDailySnapshotError,
)
from app.services.stock_analysis.data_collector import StockAnalysisDataCollector
from app.services.stock_analysis.opendata_snapshot_authorization import (
    RESEARCH_PURPOSE,
    StockAnalysisSnapshotAuthorizationReceipt,
    StockAnalysisSnapshotScope,
)
from app.services.stock_analysis.pipeline import StockAnalysisPipeline
from app.services.stock_analysis.report_evidence_producer import (
    StockDailyAuthorizedPublication,
    build_stock_daily_report_evidence_vector,
)
from app.services.stock_analysis.stock_daily_report_evidence import (
    DATASET_ID,
    SOURCE_ID,
    StockDailyReportEvidenceGate,
    StockDailyReportEvidenceVector,
)
from app.services.stock_analysis.stock_daily_snapshot_authorization_adapter import (
    StockDailySnapshotAuthorizationAdapter,
    StockDailySnapshotAuthorizationError,
    source_registry_revision,
)
from app.services.stock_analysis.tasks import StockAnalysisTaskService
from app.services.stock_signal.service import StockSignalService

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
    AICallLog.__table__,
)

SessionFactory = async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[SessionFactory]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'report-producer.db'}")

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


@pytest.fixture
def stub_run_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep task-service tests deterministic without any external I/O."""

    async def collect(_self: StockAnalysisDataCollector, **_kwargs: object) -> dict[str, Any]:
        return {
            "info": {"name": "贵州茅台"},
            "data_quality": {"status": "ok", "missing_fields": [], "degraded_reasons": []},
        }

    async def create_prediction(_self: StockSignalService, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            id="signal-prediction-1",
            signal_action="WATCH",
            confidence_score=0.5,
            risk_score=0.5,
            expected_excess_return=None,
            eligibility_status="eligible",
            quality_reasons_json=[],
            feature_version="feature-v1",
            decision_policy_version="policy-v1",
            model_version="model-v1",
            feature_snapshot_json={},
            data_freshness_json={},
        )

    async def attach_report(_self: StockSignalService, **_kwargs: object) -> None:
        return None

    async def run_pipeline(_self: StockAnalysisPipeline, **_kwargs: object) -> dict[str, Any]:
        return {
            "scores": {},
            "decision": {"label": "观望", "risk_score": 0.5},
            "final_trade_decision": "最终交易建议：观望。",
        }

    monkeypatch.setattr(StockAnalysisDataCollector, "collect", collect)
    monkeypatch.setattr(StockSignalService, "create_prediction", create_prediction)
    monkeypatch.setattr(StockSignalService, "attach_report", attach_report)
    monkeypatch.setattr(StockAnalysisPipeline, "run", run_pipeline)


class _FakeReader:
    def __init__(
        self,
        *,
        publication: StockDailyAuthorizedPublication | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.publication = publication
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def read_authorized(
        self,
        *,
        selector: StockAnalysisStockDailySnapshotSelection,
        user_id: str,
        session: AsyncSession,
    ) -> StockDailyAuthorizedPublication:
        self.calls.append({"selector": selector, "user_id": user_id, "session": session})
        if self.error is not None:
            raise self.error
        assert self.publication is not None
        return self.publication


class _RecordingGate(StockDailyReportEvidenceGate):
    """Record that the real save-time gate consumed the produced vector."""

    def __init__(self, *, adapter: StockDailySnapshotAuthorizationAdapter) -> None:
        super().__init__(adapter=adapter)
        self.calls: list[tuple[StockDailyReportEvidenceVector | None, object]] = []

    async def revalidate_for_report(
        self,
        *,
        session: AsyncSession,
        user_id: str,
        vector: StockDailyReportEvidenceVector | None,
        expected: object,
    ) -> StockDailyReportEvidenceVector | None:
        self.calls.append(
            (vector, tuple(expected) if expected is not None else None)  # type: ignore[arg-type]
        )
        return await super().revalidate_for_report(
            session=session,
            user_id=user_id,
            vector=vector,
            expected=expected,  # type: ignore[arg-type]
        )


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
        username="report-producer-user",
        email="report-producer@example.test",
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


async def _seed_user(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        session.add(_user())
        await session.commit()


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


def _snapshot(
    *,
    publication_id: str = PUBLICATION_ID,
    publication_sequence: int = PUBLICATION_SEQUENCE,
    content_sha256: str = CONTENT_SHA256,
    contract_sha256: str = CONTRACT_SHA256,
    instrument_id: str = INSTRUMENT_ID,
) -> dict[str, Any]:
    symbol, exchange = instrument_id.split(".", 1)
    return {
        "dataset_id": DATASET_ID,
        "source": {"source_id": SOURCE_ID, "source": "akshare"},
        "publication_id": publication_id,
        "sequence": publication_sequence,
        "content_sha256": content_sha256,
        "contract_sha256": contract_sha256,
        "stock_selection": {
            "market": {"SH": "CN-SSE", "SZ": "CN-SZSE"}[exchange],
            "symbol": symbol,
        },
        "created_at": CAPTURED_AT.isoformat(),
        "as_of": CAPTURED_AT.isoformat(),
        "expires_at": (CAPTURED_AT + timedelta(hours=1)).isoformat(),
        "record_count": 2,
    }


def _publication(
    receipt: StockAnalysisSnapshotAuthorizationReceipt,
    *,
    publication_id: str = PUBLICATION_ID,
    publication_sequence: int = PUBLICATION_SEQUENCE,
    content_sha256: str = CONTENT_SHA256,
    contract_sha256: str = CONTRACT_SHA256,
    instrument_id: str = INSTRUMENT_ID,
    records: tuple[dict[str, Any], ...] | None = None,
) -> StockDailyAuthorizedPublication:
    return StockDailyAuthorizedPublication(
        result=OpendataPublishedSnapshotResult(
            snapshot=_snapshot(
                publication_id=publication_id,
                publication_sequence=publication_sequence,
                content_sha256=content_sha256,
                contract_sha256=contract_sha256,
                instrument_id=instrument_id,
            ),
            coverage={"status": "unknown"},
            records=(
                records if records is not None else ({"observed_at": OBSERVED_AT.isoformat()},) * 2
            ),
            page_count=1,
        ),
        receipt=receipt,
    )


def _service(
    session: AsyncSession,
    session_factory: SessionFactory,
    *,
    reader: _FakeReader | None,
    gate: StockDailyReportEvidenceGate | None = None,
) -> StockAnalysisTaskService:
    return StockAnalysisTaskService(
        session,
        report_evidence_gate=(
            gate
            or StockDailyReportEvidenceGate(
                adapter=StockDailySnapshotAuthorizationAdapter(clock=lambda: NOW)
            )
        ),
        report_evidence_session_factory=session_factory,
        stock_daily_snapshot_reader=reader,
    )


async def _stored_parameters(session_factory: SessionFactory, task_id: str) -> dict[str, Any]:
    async with session_factory() as session:
        task = await session.get(StockAnalysisTaskModel, task_id)
    assert task is not None
    assert task.parameters_json is not None
    return task.parameters_json


async def _report_count(session_factory: SessionFactory) -> int:
    async with session_factory() as session:
        return int(
            (
                await session.execute(select(func.count()).select_from(StockAnalysisReportModel))
            ).scalar_one()
        )


async def test_selector_produces_vector_and_gate_revalidates(
    session_factory: SessionFactory,
    stub_run_dependencies: None,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    publication = _publication(receipt)
    reader = _FakeReader(publication=publication)
    gate = _RecordingGate(adapter=StockDailySnapshotAuthorizationAdapter(clock=lambda: NOW))

    async with session_factory() as session:
        service = _service(session, session_factory, reader=reader, gate=gate)
        task, report = await service.create_and_run(
            user_id=USER_ID,
            params=_params(_selector()),
        )

    assert task.status == "completed"
    assert report is not None
    expected = build_stock_daily_report_evidence_vector(
        selector=_selector(),
        publication=publication,
    )
    assert report.evidence_vector_json == expected.to_json()
    assert (await _stored_parameters(session_factory, task.id))[
        "opendata_stock_daily_evidence"
    ] == expected.to_json()
    assert len(reader.calls) == 1
    assert reader.calls[0]["selector"] == _selector()
    assert reader.calls[0]["user_id"] == USER_ID
    assert len(gate.calls) == 1
    assert gate.calls[0][0] == expected
    assert await _report_count(session_factory) == 1


async def test_commit_progress_persists_the_vector_before_report_save(
    session_factory: SessionFactory,
    stub_run_dependencies: None,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    publication = _publication(receipt)
    reader = _FakeReader(publication=publication)

    async with session_factory() as session:
        service = _service(session, session_factory, reader=reader)
        task = await service.create_pending(
            user_id=USER_ID,
            params=_params(_selector()),
        )
        await session.commit()
        report = await service._run_task(
            task,
            StockAnalysisParams.model_validate(task.parameters_json or {}),
            date(2026, 10, 30),
            commit_progress=True,
        )
        await session.commit()

    expected = build_stock_daily_report_evidence_vector(
        selector=_selector(),
        publication=publication,
    )
    assert report.evidence_vector_json == expected.to_json()
    assert (await _stored_parameters(session_factory, task.id))[
        "opendata_stock_daily_evidence"
    ] == expected.to_json()
    assert len(reader.calls) == 1


async def test_selector_without_reader_fails_closed(
    session_factory: SessionFactory,
    stub_run_dependencies: None,
) -> None:
    await _seed_user(session_factory)

    async with session_factory() as session:
        service = _service(session, session_factory, reader=None)
        task, report = await service.create_and_run(
            user_id=USER_ID,
            params=_params(_selector()),
        )

    assert task.status == "failed"
    assert task.error_message == "stock_daily_report_evidence_reader_unavailable"
    assert report is None
    assert await _report_count(session_factory) == 0
    parameters = await _stored_parameters(session_factory, task.id)
    assert "opendata_stock_daily_evidence" not in parameters


@pytest.mark.parametrize(
    "error",
    [
        OpendataStockDailySnapshotError("stock_daily_user_grant_missing"),
        StockDailySnapshotAuthorizationError("authorization_expired"),
    ],
)
async def test_reader_authorization_failure_fails_closed(
    error: BaseException,
    session_factory: SessionFactory,
    stub_run_dependencies: None,
) -> None:
    await _seed_user(session_factory)
    reader = _FakeReader(error=error)

    async with session_factory() as session:
        service = _service(session, session_factory, reader=reader)
        task, report = await service.create_and_run(
            user_id=USER_ID,
            params=_params(_selector()),
        )

    assert task.status == "failed"
    assert task.error_message == error.code  # type: ignore[attr-defined]
    assert report is None
    assert await _report_count(session_factory) == 0


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        (
            {"publication_id": "b" * 32},
            "stock_daily_report_evidence_publication_mismatch",
        ),
        (
            {"publication_sequence": PUBLICATION_SEQUENCE + 1},
            "stock_daily_report_evidence_sequence_mismatch",
        ),
        (
            {"content_sha256": "e" * 64},
            "stock_daily_report_evidence_hash_mismatch",
        ),
        (
            {"instrument_id": "000001.SZ"},
            "stock_daily_report_evidence_expected_mismatch",
        ),
    ],
)
async def test_publication_mismatch_fails_without_report(
    overrides: dict[str, object],
    code: str,
    session_factory: SessionFactory,
    stub_run_dependencies: None,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    reader = _FakeReader(publication=_publication(receipt, **overrides))  # type: ignore[arg-type]

    async with session_factory() as session:
        service = _service(session, session_factory, reader=reader)
        task, report = await service.create_and_run(
            user_id=USER_ID,
            params=_params(_selector()),
        )

    assert task.status == "failed"
    assert task.error_message == code
    assert report is None
    assert await _report_count(session_factory) == 0
    parameters = await _stored_parameters(session_factory, task.id)
    assert "opendata_stock_daily_evidence" not in parameters


@pytest.mark.parametrize(
    "records",
    [
        ({"observed_at": None},),
        (
            {"observed_at": OBSERVED_AT.isoformat()},
            {"observed_at": (OBSERVED_AT + timedelta(seconds=1)).isoformat()},
        ),
    ],
)
async def test_unusable_observation_time_fails_closed(
    records: tuple[dict[str, Any], ...],
    session_factory: SessionFactory,
    stub_run_dependencies: None,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    reader = _FakeReader(publication=_publication(receipt, records=records))

    async with session_factory() as session:
        service = _service(session, session_factory, reader=reader)
        task, report = await service.create_and_run(
            user_id=USER_ID,
            params=_params(_selector()),
        )

    assert task.status == "failed"
    assert task.error_message == "stock_daily_report_evidence_invalid"
    assert report is None
    assert await _report_count(session_factory) == 0


async def test_no_selector_keeps_the_legacy_path_unchanged(
    session_factory: SessionFactory,
    stub_run_dependencies: None,
) -> None:
    await _seed_user(session_factory)
    reader = _FakeReader(error=AssertionError("reader must not be called"))

    async with session_factory() as session:
        service = _service(session, session_factory, reader=reader)
        task, report = await service.create_and_run(
            user_id=USER_ID,
            params=_params(),
        )

    assert task.status == "completed"
    assert report is not None
    assert report.evidence_vector_json is None
    assert reader.calls == []
    parameters = await _stored_parameters(session_factory, task.id)
    assert "opendata_stock_daily_evidence" not in parameters
    assert await _report_count(session_factory) == 1


async def test_preexisting_vector_is_revalidated_without_a_reader_call(
    session_factory: SessionFactory,
    stub_run_dependencies: None,
) -> None:
    await _seed_grants(session_factory)
    receipt = await _authorize(session_factory)
    publication = _publication(receipt)
    vector = build_stock_daily_report_evidence_vector(
        selector=_selector(),
        publication=publication,
    )
    reader = _FakeReader(error=AssertionError("reader must not be called"))

    async with session_factory() as session:
        service = _service(session, session_factory, reader=reader)
        task, report = await service.create_and_run(
            user_id=USER_ID,
            params=_params(_selector()),
            stock_daily_evidence=vector,
        )

    assert task.status == "completed"
    assert report is not None
    assert report.evidence_vector_json == vector.to_json()
    assert reader.calls == []
    assert (await _stored_parameters(session_factory, task.id))[
        "opendata_stock_daily_evidence"
    ] == vector.to_json()
