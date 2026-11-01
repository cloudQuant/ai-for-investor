"""Schema-conflict checks for the portfolio composition migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
)

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20261015_portfolio_composition_versions.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "portfolio_composition_migration", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_composition_table_without_id_primary_key_is_rejected() -> None:
    engine = create_engine("sqlite://")
    metadata = MetaData()
    Table(
        "portfolio_composition_versions",
        metadata,
        Column("id", String(36), nullable=False),
        Column("owner_subject", String(256), nullable=False),
        Column("portfolio_ref", String(128), nullable=False),
        Column("membership_version", Integer, nullable=False),
        Column("source_type", String(16), nullable=False),
        Column("base_currency", String(16), nullable=False),
        Column("members", JSON, nullable=False),
        Column("membership_sha256", String(64), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        CheckConstraint(
            "membership_version > 0",
            name="ck_portfolio_composition_version_positive",
        ),
        UniqueConstraint(
            "owner_subject",
            "portfolio_ref",
            "membership_version",
            name="uq_portfolio_composition_owner_ref_version",
        ),
    )
    Index(
        "ix_portfolio_composition_versions_owner_subject",
        "portfolio_composition_versions",
        "owner_subject",
    )
    metadata.create_all(engine)

    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(
                    RuntimeError,
                    match="PORTFOLIO_COMPOSITION_SCHEMA_CONFLICT",
                ):
                    _migration_module().upgrade()
    finally:
        engine.dispose()
