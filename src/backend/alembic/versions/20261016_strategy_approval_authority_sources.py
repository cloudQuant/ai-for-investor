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

_APPROVAL_TABLE = "strategy_target_approvals"
_SOURCE_VERSION_COLUMNS = frozenset(
    {
        "strategy_version_source_id",
        "strategy_version_branch",
        "strategy_version_sha256",
    }
)
_SOURCE_VERSION_FK = "fk_strategy_target_source_version"
_SOURCE_VERSION_CHECK = "ck_strategy_target_source_version_binding"
_POLICY_VERSION_TABLE = "strategy_order_approval_policy_versions"
_POLICY_VERSION_COLUMNS = frozenset(
    {
        "id",
        "owner_subject",
        "policy_ref",
        "policy_version",
        "policy_sha256",
        "canonical_policy_json",
        "published_by_subject",
        "published_by_principal_ref",
        "published_by_actor_ref",
        "published_by_delegate_ref",
        "published_at_ns",
        "created_at",
    }
)
_POLICY_HEAD_TABLE = "strategy_order_approval_policy_heads"
_POLICY_HEAD_COLUMNS = frozenset(
    {
        "owner_subject",
        "policy_ref",
        "policy_version",
        "policy_sha256",
        "head_version",
        "updated_at",
    }
)
_AUTHORITY_EPOCH_TABLE = "strategy_approval_authority_epochs"
_AUTHORITY_EPOCH_COLUMNS = frozenset({"owner_subject", "epoch", "updated_at"})


def _existing_columns(inspector: sa.Inspector, table_name: str) -> set[str]:
    """Return the reflected column names for an existing table."""
    return {column["name"] for column in inspector.get_columns(table_name)}


def _has_source_version_binding(inspector: sa.Inspector) -> bool:
    """Return whether a complete startup-created source-version binding exists."""
    if not _SOURCE_VERSION_COLUMNS.issubset(_existing_columns(inspector, _APPROVAL_TABLE)):
        return False
    checks = {check["name"] for check in inspector.get_check_constraints(_APPROVAL_TABLE)}
    if _SOURCE_VERSION_CHECK not in checks:
        return False
    return any(
        foreign_key.get("constrained_columns") == ["strategy_version_source_id"]
        and foreign_key.get("referred_table") == "strategy_versions"
        for foreign_key in inspector.get_foreign_keys(_APPROVAL_TABLE)
    )


def _validate_startup_table(
    inspector: sa.Inspector, table_name: str, required_columns: frozenset[str]
) -> None:
    """Accept only a complete startup-created table, never a partial same-named one."""
    if not required_columns.issubset(_existing_columns(inspector, table_name)):
        raise RuntimeError("STRATEGY_APPROVAL_AUTHORITY_SCHEMA_CONFLICT")


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

    inspector = sa.inspect(bind)
    branch_uniques = {
        constraint["name"] for constraint in inspector.get_unique_constraints("strategy_branches")
    }
    if "uq_strategy_branch_strategy_name" not in branch_uniques:
        with op.batch_alter_table("strategy_branches") as batch:
            batch.create_unique_constraint(
                "uq_strategy_branch_strategy_name", ["strategy_id", "branch_name"]
            )

    inspector = sa.inspect(bind)
    present_columns = _existing_columns(inspector, _APPROVAL_TABLE)
    if present_columns & _SOURCE_VERSION_COLUMNS:
        # A startup-created current schema already carries the Iteration 202
        # binding.  Accept it only when the columns, check, and foreign key are
        # all present; re-adding an existing column makes Alembic's SQLite
        # batch copy build a cyclic column ordering.
        if not _has_source_version_binding(inspector):
            raise RuntimeError("STRATEGY_TARGET_APPROVAL_SOURCE_VERSION_SCHEMA_CONFLICT")
    else:
        with op.batch_alter_table(_APPROVAL_TABLE) as batch:
            batch.add_column(sa.Column("strategy_version_source_id", sa.String(36), nullable=True))
            batch.add_column(sa.Column("strategy_version_branch", sa.String(50), nullable=True))
            batch.add_column(sa.Column("strategy_version_sha256", sa.String(64), nullable=True))
            batch.create_foreign_key(
                _SOURCE_VERSION_FK,
                "strategy_versions",
                ["strategy_version_source_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_check_constraint(
                _SOURCE_VERSION_CHECK,
                "(strategy_version_source_id IS NULL AND strategy_version_branch IS NULL "
                "AND strategy_version_sha256 IS NULL) OR "
                "(strategy_version_source_id IS NOT NULL AND strategy_version_branch IS NOT NULL "
                "AND strategy_version_sha256 IS NOT NULL "
                "AND length(strategy_version_sha256) = 64)",
            )

    inspector = sa.inspect(bind)
    if inspector.has_table(_POLICY_VERSION_TABLE):
        _validate_startup_table(inspector, _POLICY_VERSION_TABLE, _POLICY_VERSION_COLUMNS)
    else:
        _create_policy_version_table()

    inspector = sa.inspect(bind)
    if inspector.has_table(_POLICY_HEAD_TABLE):
        _validate_startup_table(inspector, _POLICY_HEAD_TABLE, _POLICY_HEAD_COLUMNS)
    else:
        _create_policy_head_table()

    inspector = sa.inspect(bind)
    if inspector.has_table(_AUTHORITY_EPOCH_TABLE):
        _validate_startup_table(inspector, _AUTHORITY_EPOCH_TABLE, _AUTHORITY_EPOCH_COLUMNS)
    else:
        op.create_table(
            _AUTHORITY_EPOCH_TABLE,
            sa.Column("owner_subject", sa.String(256), primary_key=True),
            sa.Column("epoch", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "epoch >= 0", name="ck_strategy_approval_authority_epoch_nonnegative"
            ),
        )
    bind.execute(
        sa.text(
            "INSERT INTO strategy_approval_authority_epochs (owner_subject, epoch, updated_at) "
            "SELECT id, 0, CURRENT_TIMESTAMP FROM users AS u WHERE NOT EXISTS ("
            "SELECT 1 FROM strategy_approval_authority_epochs AS e "
            "WHERE e.owner_subject = u.id)"
        )
    )


def _create_policy_version_table() -> None:
    op.create_table(
        _POLICY_VERSION_TABLE,
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
        sa.CheckConstraint(
            "length(policy_sha256) = 64", name="ck_strategy_order_policy_hash_length"
        ),
    )
    op.create_index(
        "ix_strategy_order_approval_policy_owner",
        _POLICY_VERSION_TABLE,
        ["owner_subject"],
    )


def _create_policy_head_table() -> None:
    op.create_table(
        _POLICY_HEAD_TABLE,
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
        sa.CheckConstraint(
            "head_version > 0", name="ck_strategy_order_policy_head_version_positive"
        ),
        sa.CheckConstraint(
            "length(policy_sha256) = 64", name="ck_strategy_order_policy_head_hash_length"
        ),
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
        # Dropping the column also drops its (possibly unnamed) FK; a
        # startup-created ORM schema does not carry this migration's FK name.
        batch.drop_column("strategy_version_sha256")
        batch.drop_column("strategy_version_branch")
        batch.drop_column("strategy_version_source_id")

    with op.batch_alter_table("strategy_branches") as batch:
        batch.drop_constraint("uq_strategy_branch_strategy_name", type_="unique")
