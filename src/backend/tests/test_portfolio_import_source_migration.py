"""Additive, conflict-aware migration coverage for imported source payloads."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20261015_portfolio_import_source_material.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "portfolio_import_source_migration", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_legacy_imports_table(engine, *, primary_key: bool = True) -> None:
    metadata = MetaData()
    id_column = Column("id", String(36), primary_key=primary_key, nullable=False)
    Table(
        "portfolio_ledger_imports",
        metadata,
        id_column,
        Column("portfolio_id", String(36), nullable=False),
        Column("import_format", String(20), nullable=False),
        Column("idempotency_key", String(128), nullable=False),
        Column("imported_count", Integer, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine)


def _upgrade(engine) -> None:
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            _migration_module().upgrade()


def test_migration_adds_nullable_source_columns_preserving_legacy_rows() -> None:
    engine = create_engine("sqlite://")
    _create_legacy_imports_table(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO portfolio_ledger_imports "
                "(id, portfolio_id, import_format, idempotency_key, imported_count, created_at) "
                "VALUES ('legacy-1', 'portfolio-1', 'json', 'key-1', 2, '2026-10-15T00:00:00')"
            )
        )

    try:
        _upgrade(engine)
        _upgrade(engine)
        inspector = sa.inspect(engine)
        columns = {
            column["name"]: column for column in inspector.get_columns("portfolio_ledger_imports")
        }
        assert {
            "source_schema_version",
            "source_document",
            "source_sha256",
            "source_as_of",
            "source_currency",
        }.issubset(columns)
        assert all(
            columns[name]["nullable"]
            for name in (
                "source_schema_version",
                "source_document",
                "source_sha256",
                "source_as_of",
                "source_currency",
            )
        )
        with engine.connect() as connection:
            legacy = connection.execute(
                sa.text(
                    "SELECT id, imported_count, source_document, source_sha256 "
                    "FROM portfolio_ledger_imports WHERE id='legacy-1'"
                )
            ).one()
        assert legacy.id == "legacy-1"
        assert legacy.imported_count == 2
        assert legacy.source_document is None
        assert legacy.source_sha256 is None
    finally:
        engine.dispose()


def test_migration_rejects_partial_source_schema_before_writing_more_columns() -> None:
    engine = create_engine("sqlite://")
    _create_legacy_imports_table(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.text("ALTER TABLE portfolio_ledger_imports ADD COLUMN source_sha256 VARCHAR(63)")
        )

    try:
        with pytest.raises(RuntimeError, match="PORTFOLIO_IMPORT_SOURCE_SCHEMA_CONFLICT"):
            _upgrade(engine)
        columns = {
            column["name"] for column in sa.inspect(engine).get_columns("portfolio_ledger_imports")
        }
        assert "source_document" not in columns
        assert "source_as_of" not in columns
    finally:
        engine.dispose()


def test_migration_rejects_import_table_without_exact_id_primary_key() -> None:
    engine = create_engine("sqlite://")
    _create_legacy_imports_table(engine, primary_key=False)
    try:
        with pytest.raises(RuntimeError, match="PORTFOLIO_IMPORT_SOURCE_SCHEMA_CONFLICT"):
            _upgrade(engine)
        columns = {
            column["name"] for column in sa.inspect(engine).get_columns("portfolio_ledger_imports")
        }
        assert "source_document" not in columns
    finally:
        engine.dispose()
