"""Add versioned AFI approval policy and serialized freshness sources.

Revision ID: 20261016_strategy_approval_authority_sources
Revises: 20261016_strategy_target_approvals
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261016_strategy_approval_authority_sources"
down_revision = "20261016_strategy_target_approvals"
branch_labels = None
depends_on = None


def _validate_existing_branch_heads(bind) -> None:
    duplicate = bind.execute(
        sa.text(
            "SELECT strategy_id, branch_name, COUNT(*) AS row_count "
            "FROM strategy_branches GROUP BY strategy_id, branch_name "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError("strategy branch uniqueness migration found duplicate branch rows")

    invalid_head = bind.execute(
        sa.text(
            "SELECT b.id FROM strategy_branches AS b "
            "LEFT JOIN strategy_versions AS v ON v.id = b.last_version_id "
            "WHERE (b.last_version_id IS NULL AND (b.version_count > 0 OR EXISTS ("
            "SELECT 1 FROM strategy_versions AS branch_versions WHERE "
            "branch_versions.strategy_id = b.strategy_id AND "
            "branch_versions.branch = b.branch_name))) OR "
            "(b.last_version_id IS NOT NULL AND b.version_count = 0) OR "
            "(b.last_version_id IS NOT NULL AND (v.id IS NULL OR "
            "v.strategy_id != b.strategy_id OR v.branch IS NULL OR "
            "v.branch != b.branch_name OR EXISTS ("
            "SELECT 1 FROM strategy_versions AS newer WHERE "
            "newer.strategy_id = b.strategy_id AND newer.branch = b.branch_name AND "
            "newer.version_number > v.version_number))) LIMIT 1"
        )
    ).first()
    if invalid_head is not None:
        raise RuntimeError("strategy branch head migration found a missing or mismatched pointer")


def upgrade() -> None:
    bind = op.get_bind()
    _validate_existing_branch_heads(bind)

    with op.batch_alter_table("strategy_branches") as batch:
        batch.create_unique_constraint(
            "uq_strategy_branch_strategy_name", ["strategy_id", "branch_name"]
        )

    with op.batch_alter_table("strategy_target_approvals") as batch:
        batch.add_column(sa.Column("strategy_version_source_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("strategy_version_branch", sa.String(50), nullable=True))
        batch.add_column(sa.Column("strategy_version_sha256", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_strategy_target_source_version",
            "strategy_versions",
            ["strategy_version_source_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_strategy_target_source_version_binding",
            "(strategy_version_source_id IS NULL AND strategy_version_branch IS NULL "
            "AND strategy_version_sha256 IS NULL) OR "
            "(strategy_version_source_id IS NOT NULL AND strategy_version_branch IS NOT NULL "
            "AND strategy_version_sha256 IS NOT NULL "
            "AND length(strategy_version_sha256) = 64)",
        )

    op.create_table(
        "strategy_order_approval_policy_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_subject", sa.String(256), nullable=False),
        sa.Column("policy_ref", sa.String(128), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("policy_sha256", sa.String(64), nullable=False),
        sa.Column("canonical_policy_json", sa.Text(), nullable=False),
        sa.Column("published_by_subject", sa.String(256), nullable=False),
        sa.Column("published_by_principal_ref", sa.String(128), nullable=False),
        sa.Column("published_by_actor_ref", sa.String(128), nullable=False),
        sa.Column("published_by_delegate_ref", sa.String(128), nullable=False),
        sa.Column("published_at_ns", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "owner_subject",
            "policy_ref",
            "policy_version",
            name="uq_strategy_order_approval_policy_version",
        ),
        sa.CheckConstraint("policy_version > 0", name="ck_strategy_order_policy_version_positive"),
        sa.CheckConstraint("length(policy_sha256) = 64", name="ck_strategy_order_policy_hash_length"),
    )
    op.create_index(
        "ix_strategy_order_approval_policy_owner",
        "strategy_order_approval_policy_versions",
        ["owner_subject"],
    )

    op.create_table(
        "strategy_order_approval_policy_heads",
        sa.Column("owner_subject", sa.String(256), primary_key=True),
        sa.Column("policy_ref", sa.String(128), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("policy_sha256", sa.String(64), nullable=False),
        sa.Column("head_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_subject", "policy_ref", "policy_version"],
            [
                "strategy_order_approval_policy_versions.owner_subject",
                "strategy_order_approval_policy_versions.policy_ref",
                "strategy_order_approval_policy_versions.policy_version",
            ],
            ondelete="RESTRICT",
            name="fk_strategy_order_policy_head_version",
        ),
        sa.CheckConstraint("head_version > 0", name="ck_strategy_order_policy_head_version_positive"),
        sa.CheckConstraint("length(policy_sha256) = 64", name="ck_strategy_order_policy_head_hash_length"),
    )

    op.create_table(
        "strategy_approval_authority_epochs",
        sa.Column("owner_subject", sa.String(256), primary_key=True),
        sa.Column("epoch", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("epoch >= 0", name="ck_strategy_approval_authority_epoch_nonnegative"),
    )
    bind.execute(
        sa.text(
            "INSERT INTO strategy_approval_authority_epochs (owner_subject, epoch, updated_at) "
            "SELECT id, 0, CURRENT_TIMESTAMP FROM users"
        )
    )


def downgrade() -> None:
    op.drop_table("strategy_approval_authority_epochs")
    op.drop_table("strategy_order_approval_policy_heads")
    op.drop_index(
        "ix_strategy_order_approval_policy_owner",
        table_name="strategy_order_approval_policy_versions",
    )
    op.drop_table("strategy_order_approval_policy_versions")

    with op.batch_alter_table("strategy_target_approvals") as batch:
        batch.drop_constraint("ck_strategy_target_source_version_binding", type_="check")
        batch.drop_constraint("fk_strategy_target_source_version", type_="foreignkey")
        batch.drop_column("strategy_version_sha256")
        batch.drop_column("strategy_version_branch")
        batch.drop_column("strategy_version_source_id")

    with op.batch_alter_table("strategy_branches") as batch:
        batch.drop_constraint("uq_strategy_branch_strategy_name", type_="unique")
