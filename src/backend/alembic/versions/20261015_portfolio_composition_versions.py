"""Add append-only portfolio membership versions.

Revision ID: 20261015_portfolio_composition_versions
Revises: 20261012_optimization_objective_direction
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261015_portfolio_composition_versions"
down_revision = "20261012_optimization_objective_direction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("portfolio_composition_versions"):
        columns = {
            column["name"]: column
            for column in inspector.get_columns("portfolio_composition_versions")
        }
        required = {
            "id",
            "owner_subject",
            "portfolio_ref",
            "membership_version",
            "source_type",
            "base_currency",
            "members",
            "membership_sha256",
            "created_at",
        }
        if not required.issubset(columns):
            raise RuntimeError("PORTFOLIO_COMPOSITION_SCHEMA_CONFLICT")
        if inspector.get_pk_constraint("portfolio_composition_versions").get(
            "constrained_columns"
        ) != ["id"]:
            raise RuntimeError("PORTFOLIO_COMPOSITION_SCHEMA_CONFLICT")
        expected_lengths = {
            "id": 36,
            "owner_subject": 256,
            "portfolio_ref": 128,
            "source_type": 16,
            "base_currency": 16,
            "membership_sha256": 64,
        }
        for name, length in expected_lengths.items():
            column = columns[name]
            if not isinstance(column["type"], sa.String) or column["type"].length != length:
                raise RuntimeError("PORTFOLIO_COMPOSITION_SCHEMA_CONFLICT")
        if (
            not isinstance(columns["membership_version"]["type"], sa.Integer)
            or not isinstance(columns["members"]["type"], sa.JSON)
            or not isinstance(columns["created_at"]["type"], sa.DateTime)
            or any(columns[name]["nullable"] for name in required)
        ):
            raise RuntimeError("PORTFOLIO_COMPOSITION_SCHEMA_CONFLICT")
        unique_constraints = inspector.get_unique_constraints("portfolio_composition_versions")
        if not any(
            constraint.get("column_names")
            == ["owner_subject", "portfolio_ref", "membership_version"]
            for constraint in unique_constraints
        ):
            raise RuntimeError("PORTFOLIO_COMPOSITION_SCHEMA_CONFLICT")
        checks = inspector.get_check_constraints("portfolio_composition_versions")
        if not any("membership_version > 0" in (check.get("sqltext") or "") for check in checks):
            raise RuntimeError("PORTFOLIO_COMPOSITION_SCHEMA_CONFLICT")
        if not any(
            index.get("name") == "ix_portfolio_composition_versions_owner_subject"
            for index in inspector.get_indexes("portfolio_composition_versions")
        ):
            raise RuntimeError("PORTFOLIO_COMPOSITION_SCHEMA_CONFLICT")
        return

    op.create_table(
        "portfolio_composition_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_subject", sa.String(length=256), nullable=False),
        sa.Column("portfolio_ref", sa.String(length=128), nullable=False),
        sa.Column("membership_version", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("base_currency", sa.String(length=16), nullable=False),
        sa.Column("members", sa.JSON(), nullable=False),
        sa.Column("membership_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "membership_version > 0",
            name="ck_portfolio_composition_version_positive",
        ),
        sa.UniqueConstraint(
            "owner_subject",
            "portfolio_ref",
            "membership_version",
            name="uq_portfolio_composition_owner_ref_version",
        ),
    )
    op.create_index(
        "ix_portfolio_composition_versions_owner_subject",
        "portfolio_composition_versions",
        ["owner_subject"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_portfolio_composition_versions_owner_subject",
        table_name="portfolio_composition_versions",
    )
    op.drop_table("portfolio_composition_versions")
