"""Persist approved-target HTTP idempotency-to-intent mappings.

Revision ID: 20261016_approved_target_http_operations
Revises: 20261016_strategy_approval_authority_sources
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261016_approved_target_http_operations"
down_revision = "20261016_strategy_approval_authority_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approved_target_http_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_subject", sa.String(length=256), nullable=False),
        sa.Column("principal_ref", sa.String(length=128), nullable=False),
        sa.Column("actor_ref", sa.String(length=128), nullable=False),
        sa.Column("delegate_ref", sa.String(length=128), nullable=False),
        sa.Column("operation_key_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("approval_ref", sa.String(length=128), nullable=False),
        sa.Column("approval_version", sa.Integer(), nullable=False),
        sa.Column("target_sha256", sa.String(length=64), nullable=False),
        sa.Column("intent_id", sa.String(length=128), nullable=False),
        sa.Column("selector_ref", sa.String(length=128), nullable=False),
        sa.Column("scope_ref", sa.String(length=128), nullable=False),
        sa.Column("account_ref", sa.String(length=128), nullable=False),
        sa.Column("strategy_ref", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(operation_key_sha256) = 64", name="ck_approved_target_http_key_hash"
        ),
        sa.CheckConstraint(
            "length(request_sha256) = 64", name="ck_approved_target_http_request_hash"
        ),
        sa.CheckConstraint(
            "length(target_sha256) = 64", name="ck_approved_target_http_target_hash"
        ),
        sa.CheckConstraint("approval_version > 0", name="ck_approved_target_http_version"),
        sa.ForeignKeyConstraint(
            ["approval_ref"],
            ["strategy_target_approvals.approval_ref"],
            ondelete="RESTRICT",
            name="fk_approved_target_http_approval",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_subject",
            "principal_ref",
            "actor_ref",
            "delegate_ref",
            "operation_key_sha256",
            name="uq_approved_target_http_authority_key",
        ),
        sa.UniqueConstraint("approval_ref", name="uq_approved_target_http_approval"),
        sa.UniqueConstraint("intent_id", name="uq_approved_target_http_intent"),
    )
    op.create_index(
        "ix_approved_target_http_operations_owner_subject",
        "approved_target_http_operations",
        ["owner_subject"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_approved_target_http_operations_owner_subject",
        table_name="approved_target_http_operations",
    )
    op.drop_table("approved_target_http_operations")
