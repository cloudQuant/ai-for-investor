"""Persist immutable owner-bound offline analytics facts datasets.

Revision ID: 20261016_portfolio_analytics_datasets_v1
Revises: 20261016_approved_target_http_operations
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261016_portfolio_analytics_datasets_v1"
down_revision = "20261016_approved_target_http_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_analytics_datasets_v1",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_ref", sa.String(length=128), nullable=False),
        sa.Column("owner_subject", sa.String(length=256), nullable=False),
        sa.Column("portfolio_ref", sa.String(length=128), nullable=False),
        sa.Column("membership_version", sa.Integer(), nullable=False),
        sa.Column("membership_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_trust", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=128), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=False),
        sa.Column("source_generation", sa.String(length=128), nullable=False),
        sa.Column("facts_snapshot_ref", sa.String(length=128), nullable=False),
        sa.Column("facts_sha256", sa.String(length=64), nullable=False),
        sa.Column("facts_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "membership_version > 0",
            name="ck_portfolio_analytics_dataset_v1_membership_version",
        ),
        sa.CheckConstraint(
            "source_type IN ('research', 'imported', 'paper')",
            name="ck_portfolio_analytics_dataset_v1_source_type",
        ),
        sa.CheckConstraint(
            "source_trust = 'USER_SUPPLIED_OFFLINE'",
            name="ck_portfolio_analytics_dataset_v1_source_trust",
        ),
        sa.CheckConstraint(
            "length(membership_sha256) = 64",
            name="ck_portfolio_analytics_dataset_v1_membership_sha",
        ),
        sa.CheckConstraint(
            "length(facts_sha256) = 64",
            name="ck_portfolio_analytics_dataset_v1_facts_sha",
        ),
        sa.CheckConstraint(
            "length(idempotency_key_sha256) = 64",
            name="ck_portfolio_analytics_dataset_v1_idempotency_sha",
        ),
        sa.ForeignKeyConstraint(
            ["owner_subject", "portfolio_ref", "membership_version"],
            [
                "portfolio_composition_versions.owner_subject",
                "portfolio_composition_versions.portfolio_ref",
                "portfolio_composition_versions.membership_version",
            ],
            ondelete="RESTRICT",
            name="fk_portfolio_analytics_dataset_v1_membership",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_ref", name="uq_portfolio_analytics_dataset_v1_ref"),
        sa.UniqueConstraint(
            "owner_subject",
            "portfolio_ref",
            "membership_version",
            "idempotency_key_sha256",
            name="uq_portfolio_analytics_dataset_v1_idempotency",
        ),
    )
    op.create_index(
        "ix_portfolio_analytics_datasets_v1_owner_subject",
        "portfolio_analytics_datasets_v1",
        ["owner_subject"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_portfolio_analytics_datasets_v1_owner_subject",
        table_name="portfolio_analytics_datasets_v1",
    )
    op.drop_table("portfolio_analytics_datasets_v1")
