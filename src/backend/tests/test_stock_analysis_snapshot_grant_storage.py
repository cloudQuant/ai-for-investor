"""Behavioral storage contract for exact OpenData snapshot grants.

These tests use only isolated in-memory or temporary-file SQLite databases.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.db.database import Base
from app.models import (
    ImmutableStockSnapshotGrantError,
    InvalidStockSnapshotGrantRecord,
    StockSnapshotGrantAudit,
    StockSnapshotSourceResearchGrant,
    StockSnapshotUserReadGrant,
    User,
)

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20261030_stock_analysis_snapshot_grants.py"
)
_STOCK_DAILY_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20261031_stock_daily_snapshot_grants.py"
)
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_PRE_GRANT_REVISION = "20261017_legacy_paper_import_cutover"
_STOCK_DAILY_REVISION = "20261031_stock_daily_snapshot_grants"
_STOCK_DAILY_DATASET = "cn-equity-stock-daily"
_STOCK_DAILY_SOURCE = "akshare.daily"
_TABLES = (
    StockSnapshotUserReadGrant.__table__,
    StockSnapshotSourceResearchGrant.__table__,
    StockSnapshotGrantAudit.__table__,
)
_TABLES_BY_NAME = tuple(table.name for table in _TABLES)
_USER_ID = "4a5a77a0-8db9-4e20-b8a3-070aef54e417"
_OTHER_USER_ID = "7ec9aefe-f57a-47cc-955b-8b94e0105578"
_USER_GRANT_ID = "88919c8f-6bd3-44ca-a96b-26c5b0551960"
_SOURCE_GRANT_ID = "63fb60bb-23ef-4a96-9ea0-f814f78018d9"
_NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
_VALID_FROM = _NOW - timedelta(minutes=5)
_EXPIRES_AT = _NOW + timedelta(hours=1)


def _engine() -> Engine:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _create_model_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine, tables=[User.__table__, *_TABLES])


def _add_user(session: Session, user_id: str = _USER_ID) -> None:
    """Persist a user fixture before creating rows with user foreign keys."""
    suffix = user_id[:8]
    session.add(
        User(
            id=user_id,
            username=f"grant-owner-{suffix}",
            email=f"grant-owner-{suffix}@example.test",
            hashed_password="test-only-hash",
        )
    )
    session.flush()


def _user_grant(**overrides: Any) -> StockSnapshotUserReadGrant:
    values: dict[str, Any] = {
        "id": _USER_GRANT_ID,
        "user_id": _USER_ID,
        "permission": "data:read",
        "dataset_id": "sina_lrb_report_observations",
        "instrument_id": "600000.SH",
        "market": "SH",
        "publication_id": "d0a7b2f3302346249e6e37b026ab1961",
        "capture_id": "a" * 64,
        "purpose": "RESEARCH",
        "revision": 1,
        "valid_from": _VALID_FROM,
        "expires_at": _EXPIRES_AT,
    }
    values.update(overrides)
    return StockSnapshotUserReadGrant(**values)


def _source_grant(**overrides: Any) -> StockSnapshotSourceResearchGrant:
    values: dict[str, Any] = {
        "id": _SOURCE_GRANT_ID,
        "user_id": _USER_ID,
        "source_id": "sina-lrb",
        "dataset_id": "sina_lrb_report_observations",
        "instrument_id": "600000.SH",
        "market": "SH",
        "publication_id": "d0a7b2f3302346249e6e37b026ab1961",
        "capture_id": "a" * 64,
        "purpose": "RESEARCH",
        "source_registry_revision": "source-policy-r17",
        "revision": 1,
        "valid_from": _VALID_FROM,
        "expires_at": _EXPIRES_AT,
    }
    values.update(overrides)
    return StockSnapshotSourceResearchGrant(**values)


def _audit(
    *,
    event_type: str,
    idempotency_hash: str,
    user_grant_id: str | None = None,
    source_grant_id: str | None = None,
    subject_user_id: str = _USER_ID,
    actor_user_id: str = _USER_ID,
    grant_revision: int = 1,
    revocation_revision: int = 1,
) -> StockSnapshotGrantAudit:
    return StockSnapshotGrantAudit(
        user_grant_id=user_grant_id,
        source_grant_id=source_grant_id,
        subject_user_id=subject_user_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        grant_revision=grant_revision,
        revocation_revision=revocation_revision,
        policy_version="stock-analysis-opendata-access-v1",
        occurred_at=_NOW,
        reason_code=f"test_{event_type.lower()}",
        idempotency_key_sha256=idempotency_hash,
    )


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "stock_analysis_snapshot_grants_migration", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_stock_daily_migration():
    spec = importlib.util.spec_from_file_location(
        "stock_daily_snapshot_grants_migration", _STOCK_DAILY_MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration(engine: Engine, migration: Any, operation: str) -> None:
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, operation)()


def _run_alembic(database_url: str, action: str, target: str) -> None:
    """Run one Alembic command against an isolated SQLite file."""
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            getattr(command, action)(config, target)
    finally:
        engine.dispose()


_USER_CHECK_NAMES = {
    "ck_stock_snapshot_user_permission",
    "ck_stock_snapshot_user_dataset",
    "ck_stock_snapshot_user_market",
    "ck_stock_snapshot_user_snapshot_ids",
    "ck_stock_snapshot_user_purpose",
    "ck_stock_snapshot_user_revision",
    "ck_stock_snapshot_user_validity",
}
_SOURCE_CHECK_NAMES = {
    "ck_stock_snapshot_source_dataset",
    "ck_stock_snapshot_source_market",
    "ck_stock_snapshot_source_snapshot_ids",
    "ck_stock_snapshot_source_purpose",
    "ck_stock_snapshot_source_revision",
    "ck_stock_snapshot_source_registry_revision",
    "ck_stock_snapshot_source_validity",
}
_RAW_TIMESTAMP = "2026-10-30 09:00:00.000000"
_RAW_EXPIRES_AT = "2026-10-30 10:00:00.000000"


def _insert_user_row(connection: Connection) -> None:
    connection.execute(
        text(
            "INSERT INTO users (id, username, email, hashed_password) "
            "VALUES (:id, :username, :email, :hashed_password)"
        ),
        {
            "id": _USER_ID,
            "username": "migration-grant-owner",
            "email": "migration-grant-owner@example.test",
            "hashed_password": "test-only-hash",
        },
    )


def _insert_user_grant_row(
    connection: Connection,
    *,
    grant_id: str = _USER_GRANT_ID,
    dataset_id: str = _STOCK_DAILY_DATASET,
) -> None:
    """Insert via raw SQL so the database CHECK, not the ORM, decides validity."""
    connection.execute(
        text(
            "INSERT INTO stock_snapshot_user_read_grants ("
            "id, user_id, permission, dataset_id, instrument_id, market, "
            "publication_id, capture_id, purpose, revision, valid_from, expires_at, created_at"
            ") VALUES ("
            ":id, :user_id, 'data:read', :dataset_id, '600000.SH', 'SH', "
            ":publication_id, :capture_id, 'RESEARCH', 1, :valid_from, :expires_at, :created_at"
            ")"
        ),
        {
            "id": grant_id,
            "user_id": _USER_ID,
            "dataset_id": dataset_id,
            "publication_id": "e" * 32,
            "capture_id": "f" * 64,
            "valid_from": _RAW_TIMESTAMP,
            "expires_at": _RAW_EXPIRES_AT,
            "created_at": _RAW_TIMESTAMP,
        },
    )


def _insert_source_grant_row(
    connection: Connection,
    *,
    dataset_id: str = _STOCK_DAILY_DATASET,
    source_id: str = _STOCK_DAILY_SOURCE,
) -> None:
    connection.execute(
        text(
            "INSERT INTO stock_snapshot_source_research_grants ("
            "id, user_id, source_id, dataset_id, instrument_id, market, "
            "publication_id, capture_id, purpose, source_registry_revision, revision, "
            "valid_from, expires_at, created_at"
            ") VALUES ("
            ":id, :user_id, :source_id, :dataset_id, '600000.SH', 'SH', "
            ":publication_id, :capture_id, 'RESEARCH', 'source-policy-r17', 1, "
            ":valid_from, :expires_at, :created_at"
            ")"
        ),
        {
            "id": _SOURCE_GRANT_ID,
            "user_id": _USER_ID,
            "source_id": source_id,
            "dataset_id": dataset_id,
            "publication_id": "e" * 32,
            "capture_id": "f" * 64,
            "valid_from": _RAW_TIMESTAMP,
            "expires_at": _RAW_EXPIRES_AT,
            "created_at": _RAW_TIMESTAMP,
        },
    )


def _check_constraint_names(engine: Engine, table_name: str) -> list[str]:
    return [item["name"] for item in inspect(engine).get_check_constraints(table_name)]


def _check_constraint_sql(engine: Engine, table_name: str) -> dict[str, str]:
    return {
        item["name"]: item["sqltext"] for item in inspect(engine).get_check_constraints(table_name)
    }


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive representation of UTC timestamps."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def test_model_schema_starts_with_no_user_or_source_grants() -> None:
    engine = _engine()
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(StockSnapshotUserReadGrant)) == 0
            assert (
                session.scalar(select(func.count()).select_from(StockSnapshotSourceResearchGrant))
                == 0
            )
            assert session.scalar(select(func.count()).select_from(StockSnapshotGrantAudit)) == 0
    finally:
        engine.dispose()


def test_exact_user_and_source_grants_round_trip_with_issue_and_revoke_audits() -> None:
    engine = _engine()
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session)
            created_at_window_start = datetime.now(timezone.utc)
            user_grant = _user_grant()
            source_grant = _source_grant()
            session.add_all([user_grant, source_grant])
            session.flush()
            session.add_all(
                [
                    _audit(
                        event_type="ISSUED",
                        idempotency_hash="1" * 64,
                        user_grant_id=_USER_GRANT_ID,
                    ),
                    _audit(
                        event_type="ISSUED",
                        idempotency_hash="2" * 64,
                        source_grant_id=_SOURCE_GRANT_ID,
                    ),
                    _audit(
                        event_type="REVOKED",
                        idempotency_hash="3" * 64,
                        source_grant_id=_SOURCE_GRANT_ID,
                        revocation_revision=2,
                    ),
                ]
            )
            session.flush()
            session.commit()
            created_at_window_end = datetime.now(timezone.utc)

            loaded_user = session.get(StockSnapshotUserReadGrant, _USER_GRANT_ID)
            loaded_source = session.get(StockSnapshotSourceResearchGrant, _SOURCE_GRANT_ID)
            assert loaded_user is not None
            assert loaded_source is not None
            assert isinstance(loaded_user.created_at, datetime)
            assert isinstance(loaded_source.created_at, datetime)
            assert (
                created_at_window_start <= _as_utc(loaded_user.created_at) <= created_at_window_end
            )
            assert (
                created_at_window_start
                <= _as_utc(loaded_source.created_at)
                <= created_at_window_end
            )
            assert (
                loaded_user.user_id,
                loaded_user.permission,
                loaded_user.dataset_id,
                loaded_user.instrument_id,
                loaded_user.market,
                loaded_user.publication_id,
                loaded_user.capture_id,
                loaded_user.purpose,
                loaded_user.revision,
                _as_utc(loaded_user.valid_from),
                _as_utc(loaded_user.expires_at),
            ) == (
                _USER_ID,
                "data:read",
                "sina_lrb_report_observations",
                "600000.SH",
                "SH",
                "d0a7b2f3302346249e6e37b026ab1961",
                "a" * 64,
                "RESEARCH",
                1,
                _VALID_FROM,
                _EXPIRES_AT,
            )
            assert loaded_source.source_registry_revision == "source-policy-r17"
            assert loaded_source.revision == 1
            source_events = session.scalars(
                select(StockSnapshotGrantAudit)
                .where(StockSnapshotGrantAudit.source_grant_id == _SOURCE_GRANT_ID)
                .order_by(StockSnapshotGrantAudit.revocation_revision)
            ).all()
            assert [(row.event_type, row.revocation_revision) for row in source_events] == [
                ("ISSUED", 1),
                ("REVOKED", 2),
            ]
    finally:
        engine.dispose()


def test_failed_issue_audit_rolls_back_the_flushed_grant() -> None:
    """A failed audit insert must not leave its already-flushed grant behind."""
    engine = _engine()
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session)
            _add_user(session, _OTHER_USER_ID)
            session.commit()

            session.add(_user_grant())
            session.flush()
            session.add(
                _audit(
                    event_type="ISSUED",
                    idempotency_hash="d" * 64,
                    user_grant_id=_USER_GRANT_ID,
                    subject_user_id=_OTHER_USER_ID,
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()

            assert session.scalar(select(func.count()).select_from(StockSnapshotUserReadGrant)) == 0
            assert session.scalar(select(func.count()).select_from(StockSnapshotGrantAudit)) == 0
    finally:
        engine.dispose()


def test_user_references_preserve_non_uuid_ids_supported_by_existing_contract() -> None:
    engine = _engine()
    user_id = "research-service"
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session, user_id)
            grant = _user_grant(user_id=user_id)
            session.add(grant)
            session.flush()
            session.add(
                _audit(
                    event_type="ISSUED",
                    idempotency_hash="c" * 64,
                    user_grant_id=_USER_GRANT_ID,
                    subject_user_id=user_id,
                    actor_user_id=user_id,
                )
            )
            session.flush()
            session.commit()
            stored_grant = session.get(StockSnapshotUserReadGrant, _USER_GRANT_ID)
            assert stored_grant is not None
            assert stored_grant.user_id == user_id
    finally:
        engine.dispose()


def test_scope_constraints_reject_wildcards_bse_and_invalid_validity() -> None:
    engine = _engine()
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session)
            session.commit()

            invalid_grants = (
                _user_grant(id="00000000-0000-0000-0000-000000000001", dataset_id="*"),
                _user_grant(
                    id="00000000-0000-0000-0000-000000000002",
                    instrument_id="600000.BJ",
                    market="BJ",
                ),
                _user_grant(
                    id="00000000-0000-0000-0000-000000000003",
                    expires_at=_VALID_FROM,
                ),
                _user_grant(
                    id="00000000-0000-0000-0000-000000000004",
                    instrument_id="A00000.SH",
                ),
                _user_grant(
                    id="00000000-0000-0000-0000-000000000005",
                    instrument_id="٦٠٠٠٠٠.SH",
                ),
                _user_grant(
                    id="00000000-0000-0000-0000-000000000006",
                    publication_id="D0A7B2F3302346249E6E37B026AB1961",
                ),
                _user_grant(
                    id="00000000-0000-0000-0000-000000000007",
                    capture_id="g" * 64,
                ),
                _user_grant(
                    id="00000000-0000-0000-0000-000000000008",
                    instrument_id="600000.sh",
                    market="sh",
                ),
                _user_grant(
                    id="00000000-0000-0000-0000-000000000009",
                    permission="DATA:READ",
                ),
            )
            for grant in invalid_grants:
                session.add(grant)
                with pytest.raises(InvalidStockSnapshotGrantRecord):
                    session.flush()
                session.rollback()
    finally:
        engine.dispose()


def test_audit_binds_the_subject_and_requires_exactly_one_grant() -> None:
    engine = _engine()
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session)
            _add_user(session, _OTHER_USER_ID)
            session.add(_user_grant())
            session.flush()
            session.commit()

            wrong_subject = _audit(
                event_type="ISSUED",
                idempotency_hash="4" * 64,
                user_grant_id=_USER_GRANT_ID,
                subject_user_id=_OTHER_USER_ID,
            )
            session.add(wrong_subject)
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()

            ambiguous_audit = _audit(
                event_type="ISSUED",
                idempotency_hash="5" * 64,
                user_grant_id=_USER_GRANT_ID,
                source_grant_id=_SOURCE_GRANT_ID,
            )
            session.add(ambiguous_audit)
            with pytest.raises(InvalidStockSnapshotGrantRecord):
                session.flush()
    finally:
        engine.dispose()


def test_source_grant_rejects_invalid_source_revision_and_snapshot_symbols() -> None:
    engine = _engine()
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session)
            session.flush()
            invalid_grants = (
                _source_grant(source_registry_revision=" revision with spaces "),
                _source_grant(source_registry_revision="_starts-with-punctuation"),
                _source_grant(capture_id="G" * 64),
                _source_grant(publication_id="z" * 32),
            )
            for grant in invalid_grants:
                session.add(grant)
                with pytest.raises(InvalidStockSnapshotGrantRecord):
                    session.flush()
                session.rollback()
                _add_user(session)
                session.flush()
    finally:
        engine.dispose()


def test_audit_rejects_non_hex_idempotency_digest_at_orm_boundary() -> None:
    engine = _engine()
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session)
            session.flush()
            session.add(
                _audit(
                    event_type="ISSUED",
                    idempotency_hash="g" * 64,
                    user_grant_id=_USER_GRANT_ID,
                )
            )
            with pytest.raises(InvalidStockSnapshotGrantRecord, match="idempotency_hash_invalid"):
                session.flush()
    finally:
        engine.dispose()


def test_each_audit_revision_must_match_its_immutable_grant_revision() -> None:
    engine = _engine()
    second_grant_id = "00000000-0000-0000-0000-000000000002"
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session)
            session.add_all([_user_grant(), _user_grant(id=second_grant_id, revision=2)])
            session.flush()
            session.add_all(
                [
                    _audit(
                        event_type="ISSUED",
                        idempotency_hash="7" * 64,
                        user_grant_id=_USER_GRANT_ID,
                        grant_revision=1,
                    ),
                    _audit(
                        event_type="ISSUED",
                        idempotency_hash="8" * 64,
                        user_grant_id=second_grant_id,
                        grant_revision=2,
                    ),
                ]
            )
            session.flush()
            session.commit()

            wrong_revision_event = _audit(
                event_type="REVOKED",
                idempotency_hash="9" * 64,
                user_grant_id=second_grant_id,
                grant_revision=1,
                revocation_revision=2,
            )
            session.add(wrong_revision_event)
            with pytest.raises(IntegrityError):
                session.flush()
    finally:
        engine.dispose()


def test_orm_rejects_grant_scope_and_audit_mutation() -> None:
    engine = _engine()
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session)
            session.add(_user_grant())
            session.flush()
            audit = _audit(
                event_type="ISSUED",
                idempotency_hash="6" * 64,
                user_grant_id=_USER_GRANT_ID,
            )
            session.add(audit)
            session.flush()
            session.commit()

            grant = session.get(StockSnapshotUserReadGrant, _USER_GRANT_ID)
            assert grant is not None
            grant.instrument_id = "000001.SZ"
            with pytest.raises(ImmutableStockSnapshotGrantError):
                session.flush()
            session.rollback()

            immutable_audit = session.scalar(select(StockSnapshotGrantAudit))
            assert immutable_audit is not None
            immutable_audit.reason_code = "rewritten"
            with pytest.raises(ImmutableStockSnapshotGrantError):
                session.flush()
            session.rollback()

            persisted_grant = session.get(StockSnapshotUserReadGrant, _USER_GRANT_ID)
            assert persisted_grant is not None
            session.delete(persisted_grant)
            with pytest.raises(ImmutableStockSnapshotGrantError):
                session.flush()
    finally:
        engine.dispose()


def test_orm_normalizes_aware_timestamps_to_utc_before_persistence() -> None:
    engine = _engine()
    plus_eight = timezone(timedelta(hours=8))
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session)
            grant = _user_grant(
                valid_from=_VALID_FROM.astimezone(plus_eight),
                expires_at=_EXPIRES_AT.astimezone(plus_eight),
                created_at=_NOW.astimezone(plus_eight),
            )
            source_grant = _source_grant(created_at=_NOW.astimezone(plus_eight))
            audit = _audit(
                event_type="ISSUED",
                idempotency_hash="a" * 64,
                user_grant_id=_USER_GRANT_ID,
            )
            audit.occurred_at = _NOW.astimezone(plus_eight)
            session.add_all([grant, source_grant])
            session.flush()
            session.add(audit)
            session.flush()
            session.commit()

            stored_grant = session.get(StockSnapshotUserReadGrant, _USER_GRANT_ID)
            stored_source_grant = session.get(StockSnapshotSourceResearchGrant, _SOURCE_GRANT_ID)
            stored_audit = session.scalar(select(StockSnapshotGrantAudit))
            assert stored_grant is not None
            assert stored_source_grant is not None
            assert stored_audit is not None
            assert _as_utc(stored_grant.valid_from) == _VALID_FROM
            assert _as_utc(stored_grant.expires_at) == _EXPIRES_AT
            assert _as_utc(stored_grant.created_at) == _NOW
            assert _as_utc(stored_source_grant.created_at) == _NOW
            assert _as_utc(stored_audit.occurred_at) == _NOW
    finally:
        engine.dispose()


def test_orm_rejects_naive_grant_and_audit_timestamps() -> None:
    engine = _engine()
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session)
            session.flush()
            session.add(_user_grant(valid_from=_VALID_FROM.replace(tzinfo=None)))
            with pytest.raises(InvalidStockSnapshotGrantRecord, match="must_be_timezone_aware"):
                session.flush()
            session.rollback()

            _add_user(session)
            session.flush()
            session.add(_source_grant(created_at=_NOW.replace(tzinfo=None)))
            with pytest.raises(InvalidStockSnapshotGrantRecord, match="must_be_timezone_aware"):
                session.flush()
            session.rollback()

            _add_user(session)
            session.flush()
            audit = _audit(
                event_type="ISSUED",
                idempotency_hash="b" * 64,
                user_grant_id=_USER_GRANT_ID,
            )
            audit.occurred_at = _NOW.replace(tzinfo=None)
            session.add(audit)
            with pytest.raises(InvalidStockSnapshotGrantRecord, match="must_be_timezone_aware"):
                session.flush()
    finally:
        engine.dispose()


def test_migration_creates_empty_tables_and_empty_downgrade_succeeds() -> None:
    engine = _engine()
    migration = _load_migration()
    try:
        with engine.begin() as connection:
            User.__table__.create(connection)
        _run_migration(engine, migration, "upgrade")
        assert set(migration._TABLES).issubset(set(inspect(engine).get_table_names()))
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(StockSnapshotGrantAudit)) == 0

        _run_migration(engine, migration, "downgrade")
        remaining = set(inspect(engine).get_table_names())
        assert set(migration._TABLES).isdisjoint(remaining)
        assert User.__tablename__ in remaining
        with engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []

        _run_migration(engine, migration, "upgrade")
        assert set(migration._TABLES).issubset(set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()


def test_migration_downgrade_refuses_to_delete_user_grant_evidence() -> None:
    engine = _engine()
    migration = _load_migration()
    try:
        with engine.begin() as connection:
            User.__table__.create(connection)
        _run_migration(engine, migration, "upgrade")
        with Session(engine) as session:
            _add_user(session)
            session.add(_user_grant())
            session.commit()
        with pytest.raises(RuntimeError, match="STOCK_SNAPSHOT_GRANT_DOWNGRADE_UNSUPPORTED"):
            _run_migration(engine, migration, "downgrade")
        assert set(migration._TABLES).issubset(set(inspect(engine).get_table_names()))
        with Session(engine) as session:
            assert session.get(StockSnapshotUserReadGrant, _USER_GRANT_ID) is not None
    finally:
        engine.dispose()


def test_migration_downgrade_refuses_to_delete_source_grant_evidence() -> None:
    engine = _engine()
    migration = _load_migration()
    try:
        with engine.begin() as connection:
            User.__table__.create(connection)
        _run_migration(engine, migration, "upgrade")
        with Session(engine) as session:
            _add_user(session)
            session.add(_source_grant())
            session.commit()
        with pytest.raises(RuntimeError, match="STOCK_SNAPSHOT_GRANT_DOWNGRADE_UNSUPPORTED"):
            _run_migration(engine, migration, "downgrade")
        assert set(migration._TABLES).issubset(set(inspect(engine).get_table_names()))
        with Session(engine) as session:
            assert session.get(StockSnapshotSourceResearchGrant, _SOURCE_GRANT_ID) is not None
    finally:
        engine.dispose()


def test_migration_downgrade_refuses_to_delete_audit_evidence() -> None:
    """Probe the audit table independently, even with grant foreign keys unenforced."""
    engine = create_engine("sqlite://")
    migration = _load_migration()
    try:
        with engine.begin() as connection:
            User.__table__.create(connection)
        _run_migration(engine, migration, "upgrade")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, username, email, hashed_password) "
                    "VALUES (:id, 'audit-owner', 'audit-owner@example.test', 'test-only-hash')"
                ),
                {"id": _USER_ID},
            )
            connection.execute(
                text(
                    "INSERT INTO stock_snapshot_grant_audits ("
                    "id, user_grant_id, subject_user_id, actor_user_id, event_type, "
                    "grant_revision, revocation_revision, policy_version, occurred_at, "
                    "reason_code, idempotency_key_sha256"
                    ") VALUES ("
                    "'00000000-0000-0000-0000-0000000000ff', :grant_id, :user_id, :user_id, "
                    "'ISSUED', 1, 1, 'stock-analysis-opendata-access-v1', :occurred_at, "
                    "'audit_only_probe', :idempotency_hash"
                    ")"
                ),
                {
                    "grant_id": _USER_GRANT_ID,
                    "user_id": _USER_ID,
                    "occurred_at": _RAW_TIMESTAMP,
                    "idempotency_hash": "9" * 64,
                },
            )
        with pytest.raises(RuntimeError, match="STOCK_SNAPSHOT_GRANT_DOWNGRADE_UNSUPPORTED"):
            _run_migration(engine, migration, "downgrade")
        assert set(migration._TABLES).issubset(set(inspect(engine).get_table_names()))
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM stock_snapshot_grant_audits")
                ).scalar()
                == 1
            )
    finally:
        engine.dispose()


def test_offline_migration_downgrade_emits_precheck_and_drops() -> None:
    migration = _load_migration()
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="sqlite",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        migration.downgrade()
    sql = output.getvalue()
    assert "STOCK_SNAPSHOT_GRANT_DOWNGRADE_UNSUPPORTED" in sql
    for probe in migration._DOWNGRADE_PROBES:
        assert str(probe) in sql
    for table_name in migration._DROP_ORDER:
        assert f"DROP TABLE {table_name}" in sql
    drop_position = sql.index(f"DROP TABLE {migration._DROP_ORDER[0]}")
    for probe in migration._DOWNGRADE_PROBES:
        assert sql.index(str(probe)) < drop_position


def test_stock_daily_dataset_and_source_grants_round_trip() -> None:
    engine = _engine()
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session)
            user_grant = _user_grant(
                dataset_id=_STOCK_DAILY_DATASET,
                publication_id="e" * 32,
                capture_id="f" * 64,
            )
            source_grant = _source_grant(
                dataset_id=_STOCK_DAILY_DATASET,
                source_id=_STOCK_DAILY_SOURCE,
                publication_id="e" * 32,
                capture_id="f" * 64,
            )
            session.add_all([user_grant, source_grant])
            session.flush()
            session.add_all(
                [
                    _audit(
                        event_type="ISSUED",
                        idempotency_hash="e" * 64,
                        user_grant_id=_USER_GRANT_ID,
                    ),
                    _audit(
                        event_type="ISSUED",
                        idempotency_hash="f" * 64,
                        source_grant_id=_SOURCE_GRANT_ID,
                    ),
                ]
            )
            session.commit()

            loaded_user = session.get(StockSnapshotUserReadGrant, _USER_GRANT_ID)
            loaded_source = session.get(StockSnapshotSourceResearchGrant, _SOURCE_GRANT_ID)
            assert loaded_user is not None
            assert loaded_source is not None
            assert loaded_user.dataset_id == _STOCK_DAILY_DATASET
            assert (loaded_source.dataset_id, loaded_source.source_id) == (
                _STOCK_DAILY_DATASET,
                _STOCK_DAILY_SOURCE,
            )
            assert loaded_user.capture_id == "f" * 64
            assert loaded_source.capture_id == "f" * 64
    finally:
        engine.dispose()


def test_stock_daily_source_grant_rejects_a_mismatched_dataset_source_pair() -> None:
    engine = _engine()
    try:
        _create_model_schema(engine)
        with Session(engine) as session:
            _add_user(session)
            session.flush()
            invalid_pairs = (
                {
                    "dataset_id": _STOCK_DAILY_DATASET,
                    "source_id": "sina-lrb",
                },
                {
                    "dataset_id": "sina_lrb_report_observations",
                    "source_id": _STOCK_DAILY_SOURCE,
                },
            )
            for index, pair in enumerate(invalid_pairs):
                session.add(
                    _source_grant(
                        id=f"00000000-0000-0000-0000-00000000001{index}",
                        **pair,
                    )
                )
                with pytest.raises(
                    InvalidStockSnapshotGrantRecord, match="source_grant_scope_invalid"
                ):
                    session.flush()
                session.rollback()
                _add_user(session)
                session.flush()
    finally:
        engine.dispose()


def test_stock_daily_migration_widens_checks_and_preserves_constraints() -> None:
    engine = _engine()
    baseline = _load_migration()
    migration = _load_stock_daily_migration()
    try:
        with engine.begin() as connection:
            User.__table__.create(connection)
        _run_migration(engine, baseline, "upgrade")
        _run_migration(engine, migration, "upgrade")

        inspector = inspect(engine)
        user_checks = _check_constraint_sql(engine, StockSnapshotUserReadGrant.__tablename__)
        source_checks = _check_constraint_sql(
            engine, StockSnapshotSourceResearchGrant.__tablename__
        )
        assert _STOCK_DAILY_DATASET in user_checks["ck_stock_snapshot_user_dataset"]
        assert _STOCK_DAILY_DATASET in source_checks["ck_stock_snapshot_source_dataset"]
        assert _STOCK_DAILY_SOURCE in source_checks["ck_stock_snapshot_source_dataset"]
        audit_foreign_keys = {
            item["name"]
            for item in inspector.get_foreign_keys(StockSnapshotGrantAudit.__tablename__)
        }
        assert {
            "fk_stock_snapshot_audit_user_scope",
            "fk_stock_snapshot_audit_source_scope",
            "fk_stock_snapshot_audit_subject",
            "fk_stock_snapshot_audit_actor",
        }.issubset(audit_foreign_keys)
        assert {
            item["name"] for item in inspector.get_indexes(StockSnapshotUserReadGrant.__tablename__)
        } == {"ix_stock_snapshot_user_lookup"}
        assert {
            item["name"]
            for item in inspector.get_indexes(StockSnapshotSourceResearchGrant.__tablename__)
        } == {"ix_stock_snapshot_source_lookup"}

        # A clean schema downgrades: both CHECKs narrow and nothing is duplicated.
        _run_migration(engine, migration, "downgrade")
        assert sorted(
            _check_constraint_names(engine, StockSnapshotUserReadGrant.__tablename__)
        ) == sorted(_USER_CHECK_NAMES)
        assert sorted(
            _check_constraint_names(engine, StockSnapshotSourceResearchGrant.__tablename__)
        ) == sorted(_SOURCE_CHECK_NAMES)
        narrowed_user = _check_constraint_sql(engine, StockSnapshotUserReadGrant.__tablename__)
        narrowed_source = _check_constraint_sql(
            engine, StockSnapshotSourceResearchGrant.__tablename__
        )
        assert _STOCK_DAILY_DATASET not in narrowed_user["ck_stock_snapshot_user_dataset"]
        assert _STOCK_DAILY_DATASET not in narrowed_source["ck_stock_snapshot_source_dataset"]
        assert _STOCK_DAILY_SOURCE not in narrowed_source["ck_stock_snapshot_source_dataset"]
        assert {
            item["name"]
            for item in inspect(engine).get_indexes(StockSnapshotUserReadGrant.__tablename__)
        } == {"ix_stock_snapshot_user_lookup"}

        with engine.begin() as connection:
            _insert_user_row(connection)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                _insert_user_grant_row(connection)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                _insert_source_grant_row(connection)

        # Re-upgrade restores exactly one widened CHECK per table and accepts pairs.
        _run_migration(engine, migration, "upgrade")
        assert len(
            _check_constraint_names(engine, StockSnapshotUserReadGrant.__tablename__)
        ) == len(_USER_CHECK_NAMES)
        assert len(
            _check_constraint_names(engine, StockSnapshotSourceResearchGrant.__tablename__)
        ) == len(_SOURCE_CHECK_NAMES)
        with engine.begin() as connection:
            _insert_user_grant_row(connection)
            _insert_source_grant_row(connection)
        with Session(engine) as session:
            stored_user = session.get(StockSnapshotUserReadGrant, _USER_GRANT_ID)
            stored_source = session.get(StockSnapshotSourceResearchGrant, _SOURCE_GRANT_ID)
            assert stored_user is not None and stored_user.dataset_id == _STOCK_DAILY_DATASET
            assert stored_source is not None
            assert (stored_source.dataset_id, stored_source.source_id) == (
                _STOCK_DAILY_DATASET,
                _STOCK_DAILY_SOURCE,
            )
    finally:
        engine.dispose()


def test_stock_daily_migration_refuses_an_unreviewed_schema() -> None:
    engine = _engine()
    migration = _load_stock_daily_migration()
    try:
        with pytest.raises(RuntimeError, match="STOCK_DAILY_GRANT_SCHEMA_CONFLICT"):
            _run_migration(engine, migration, "upgrade")
    finally:
        engine.dispose()


def test_stock_daily_downgrade_refuses_persisted_stock_daily_user_grant() -> None:
    engine = _engine()
    baseline = _load_migration()
    migration = _load_stock_daily_migration()
    try:
        with engine.begin() as connection:
            User.__table__.create(connection)
        _run_migration(engine, baseline, "upgrade")
        _run_migration(engine, migration, "upgrade")
        with engine.begin() as connection:
            _insert_user_row(connection)
            _insert_user_grant_row(connection)

        with pytest.raises(RuntimeError, match="STOCK_DAILY_GRANT_DOWNGRADE_UNSUPPORTED"):
            _run_migration(engine, migration, "downgrade")

        # Schema is still widened, the row survives, and one CHECK remains per table.
        assert (
            _STOCK_DAILY_DATASET
            in _check_constraint_sql(engine, StockSnapshotUserReadGrant.__tablename__)[
                "ck_stock_snapshot_user_dataset"
            ]
        )
        assert sorted(
            _check_constraint_names(engine, StockSnapshotUserReadGrant.__tablename__)
        ) == sorted(_USER_CHECK_NAMES)
        with Session(engine) as session:
            stored = session.get(StockSnapshotUserReadGrant, _USER_GRANT_ID)
            assert stored is not None and stored.dataset_id == _STOCK_DAILY_DATASET
    finally:
        engine.dispose()


def test_stock_daily_downgrade_refuses_persisted_stock_daily_source_grant() -> None:
    engine = _engine()
    baseline = _load_migration()
    migration = _load_stock_daily_migration()
    try:
        with engine.begin() as connection:
            User.__table__.create(connection)
        _run_migration(engine, baseline, "upgrade")
        _run_migration(engine, migration, "upgrade")
        with engine.begin() as connection:
            _insert_user_row(connection)
            _insert_source_grant_row(connection)

        with pytest.raises(RuntimeError, match="STOCK_DAILY_GRANT_DOWNGRADE_UNSUPPORTED"):
            _run_migration(engine, migration, "downgrade")

        assert (
            _STOCK_DAILY_SOURCE
            in _check_constraint_sql(engine, StockSnapshotSourceResearchGrant.__tablename__)[
                "ck_stock_snapshot_source_dataset"
            ]
        )
        with Session(engine) as session:
            stored = session.get(StockSnapshotSourceResearchGrant, _SOURCE_GRANT_ID)
            assert stored is not None and stored.source_id == _STOCK_DAILY_SOURCE
    finally:
        engine.dispose()


def test_stock_daily_downgrade_narrows_clean_sqlite_schema_one_revision() -> None:
    """Fresh upgrade to head, one-revision downgrade, then upgrade again on SQLite."""
    engine = _engine()
    baseline = _load_migration()
    migration = _load_stock_daily_migration()
    try:
        with engine.begin() as connection:
            User.__table__.create(connection)
        _run_migration(engine, baseline, "upgrade")
        _run_migration(engine, migration, "upgrade")
        with engine.begin() as connection:
            _insert_user_row(connection)
            _insert_user_grant_row(
                connection,
                grant_id="00000000-0000-0000-0000-0000000000aa",
                dataset_id="sina_lrb_report_observations",
            )

        _run_migration(engine, migration, "downgrade")
        with Session(engine) as session:
            preserved = session.get(
                StockSnapshotUserReadGrant, "00000000-0000-0000-0000-0000000000aa"
            )
            assert preserved is not None
            assert preserved.dataset_id == "sina_lrb_report_observations"
        _run_migration(engine, migration, "upgrade")

        with engine.begin() as connection:
            _insert_user_grant_row(connection)
        with Session(engine) as session:
            assert session.get(StockSnapshotUserReadGrant, _USER_GRANT_ID) is not None
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("dialect_name", "drop_fragment", "add_fragment"),
    [
        ("mysql", "DROP CHECK", "ADD CONSTRAINT ck_stock_snapshot_user_dataset"),
        ("postgresql", "DROP CONSTRAINT", "ADD CONSTRAINT ck_stock_snapshot_user_dataset"),
    ],
)
def test_stock_daily_offline_downgrade_compiles_narrowing_ddl(
    dialect_name: str, drop_fragment: str, add_fragment: str
) -> None:
    """Compile the downgrade DDL for MySQL/PostgreSQL without a live database."""
    migration = _load_stock_daily_migration()
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name=dialect_name,
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        migration.downgrade()
    sql = output.getvalue()
    assert "STOCK_DAILY_GRANT_DOWNGRADE_UNSUPPORTED" in sql
    assert str(migration._USER_GRANT_DOWNGRADE_PROBE) in sql
    assert str(migration._SOURCE_GRANT_DOWNGRADE_PROBE) in sql
    assert f"ALTER TABLE stock_snapshot_user_read_grants {drop_fragment}" in sql
    assert f"ALTER TABLE stock_snapshot_source_research_grants {drop_fragment}" in sql
    assert add_fragment in sql
    user_add = sql.split(add_fragment, 1)[1].split(";", 1)[0]
    assert "sina_fzb_report_observations" in user_add
    assert "sina_lrb_report_observations" in user_add
    assert _STOCK_DAILY_DATASET not in user_add
    assert "akshare.daily" not in user_add


@pytest.mark.parametrize("dialect_name", ["mysql", "postgresql"])
def test_offline_grant_downgrade_compiles_drops_after_precheck(dialect_name: str) -> None:
    migration = _load_migration()
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name=dialect_name,
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        migration.downgrade()
    sql = output.getvalue()
    assert "STOCK_SNAPSHOT_GRANT_DOWNGRADE_UNSUPPORTED" in sql
    positions = [sql.index(f"DROP TABLE {table}") for table in migration._DROP_ORDER]
    assert positions == sorted(positions)
    for probe in migration._DOWNGRADE_PROBES:
        assert sql.index(str(probe)) < positions[0]


def test_grant_revision_chain_round_trips_on_empty_sqlite_database(tmp_path) -> None:
    """Stamp the pre-grant revision, upgrade head, downgrade both grants, re-upgrade."""
    database_url = f"sqlite:///{tmp_path / 'grant-chain.db'}"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)")
    finally:
        engine.dispose()

    _run_alembic(database_url, "stamp", _PRE_GRANT_REVISION)
    _run_alembic(database_url, "upgrade", _STOCK_DAILY_REVISION)
    engine = create_engine(database_url)
    try:
        assert set(_TABLES_BY_NAME).issubset(set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()

    _run_alembic(database_url, "downgrade", _PRE_GRANT_REVISION)
    engine = create_engine(database_url)
    try:
        remaining = set(inspect(engine).get_table_names())
        assert set(_TABLES_BY_NAME).isdisjoint(remaining)
        assert {"users", "alembic_version"}.issubset(remaining)
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == _PRE_GRANT_REVISION
            )
    finally:
        engine.dispose()

    _run_alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    try:
        assert set(_TABLES_BY_NAME).issubset(set(inspect(engine).get_table_names()))
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == _STOCK_DAILY_REVISION
            )
    finally:
        engine.dispose()
