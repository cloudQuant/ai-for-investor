"""Preserve versioned imported portfolio source documents.

Revision ID: 20261015_portfolio_import_source_material
Revises: 20261015_portfolio_composition_versions
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261015_portfolio_import_source_material"
down_revision = "20261015_portfolio_composition_versions"
branch_labels = None
depends_on = None


_SOURCE_COLUMNS = {
    "source_schema_version": sa.Integer(),
    "source_document": sa.JSON(),
    "source_sha256": sa.String(length=64),
    "source_as_of": sa.String(length=20),
    "source_currency": sa.String(length=16),
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "portfolio_ledger_imports"
    if not inspector.has_table(table_name):
        raise RuntimeError("PORTFOLIO_IMPORT_SOURCE_SCHEMA_CONFLICT")

    columns = {column["name"]: column for column in inspector.get_columns(table_name)}
    required = {
        "id": (sa.String, 36),
        "portfolio_id": (sa.String, 36),
        "import_format": (sa.String, 20),
        "idempotency_key": (sa.String, 128),
        "imported_count": (sa.Integer, None),
        "created_at": (sa.DateTime, None),
    }
    if not set(required).issubset(columns):
        raise RuntimeError("PORTFOLIO_IMPORT_SOURCE_SCHEMA_CONFLICT")
    if inspector.get_pk_constraint(table_name).get("constrained_columns") != ["id"]:
        raise RuntimeError("PORTFOLIO_IMPORT_SOURCE_SCHEMA_CONFLICT")
    for name, (expected_type, expected_length) in required.items():
        column_type = columns[name]["type"]
        if not isinstance(column_type, expected_type):
            raise RuntimeError("PORTFOLIO_IMPORT_SOURCE_SCHEMA_CONFLICT")
        if expected_length is not None and column_type.length != expected_length:
            raise RuntimeError("PORTFOLIO_IMPORT_SOURCE_SCHEMA_CONFLICT")
    present_source_columns = set(columns).intersection(_SOURCE_COLUMNS)
    if present_source_columns and present_source_columns != set(_SOURCE_COLUMNS):
        raise RuntimeError("PORTFOLIO_IMPORT_SOURCE_SCHEMA_CONFLICT")

    if not present_source_columns:
        for name, column_type in _SOURCE_COLUMNS.items():
            op.add_column(table_name, sa.Column(name, column_type, nullable=True))
        return

    for name, expected_type in _SOURCE_COLUMNS.items():
        column = columns[name]
        actual_type = column["type"]
        type_matches = (
            (
                isinstance(actual_type, sa.String)
                and isinstance(expected_type, sa.String)
                and actual_type.length == expected_type.length
            )
            or (isinstance(actual_type, sa.Integer) and isinstance(expected_type, sa.Integer))
            or (isinstance(actual_type, sa.JSON) and isinstance(expected_type, sa.JSON))
        )
        if not type_matches or column["nullable"] is not True:
            raise RuntimeError("PORTFOLIO_IMPORT_SOURCE_SCHEMA_CONFLICT")


def downgrade() -> None:
    for name in reversed(tuple(_SOURCE_COLUMNS)):
        op.drop_column("portfolio_ledger_imports", name)
