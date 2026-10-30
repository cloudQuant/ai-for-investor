"""Create empty-by-default exact OpenData stock-snapshot grant storage.

Revision ID: 20261030_stock_analysis_snapshot_grants
Revises: 20261017_legacy_paper_import_cutover
Create Date: 2026-10-30

This migration stores user-read grants, source-research grants, and their
issue/revocation audit events. It does not seed grants or add an issuer/API.
Database-level immutable-write guards are not installed in this revision.
Downgrade is intentionally unsupported on all dialects: an empty-check followed
by table drops cannot be proven free from concurrent writers across the three
supported databases, and grant/audit evidence must never be implicitly erased.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql, postgresql

from alembic import op

revision = "20261030_stock_analysis_snapshot_grants"
down_revision = "20261017_legacy_paper_import_cutover"
branch_labels = None
depends_on = None

_USER_GRANT = "stock_snapshot_user_read_grants"
_SOURCE_GRANT = "stock_snapshot_source_research_grants"
_AUDIT = "stock_snapshot_grant_audits"
_TABLES = (_USER_GRANT, _SOURCE_GRANT, _AUDIT)
_PIT_DATETIME = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def _exact_identifier_type(length: int) -> sa.types.TypeEngine[object]:
    """Use exact comparison semantics on every supported SQL dialect."""
    return (
        sa.String(length, collation="BINARY")
        .with_variant(
            mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"),
            "mysql",
        )
        .with_variant(postgresql.VARCHAR(length, collation="C"), "postgresql")
    )


def _assert_tables_absent() -> None:
    """Reject a partially or manually created schema instead of adopting it."""
    inspector = sa.inspect(op.get_bind())
    if any(inspector.has_table(table_name) for table_name in _TABLES):
        raise RuntimeError("STOCK_SNAPSHOT_GRANT_SCHEMA_CONFLICT")


def upgrade() -> None:
    """Create empty grant and audit tables with exact, narrow scope columns."""
    if not op.get_context().as_sql:
        _assert_tables_absent()

    op.create_table(
        _USER_GRANT,
        sa.Column("id", _exact_identifier_type(36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("permission", _exact_identifier_type(32), nullable=False),
        sa.Column("dataset_id", _exact_identifier_type(128), nullable=False),
        sa.Column("instrument_id", _exact_identifier_type(16), nullable=False),
        sa.Column("market", _exact_identifier_type(8), nullable=False),
        sa.Column("publication_id", _exact_identifier_type(32), nullable=False),
        sa.Column("capture_id", _exact_identifier_type(64), nullable=False),
        sa.Column("purpose", _exact_identifier_type(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("valid_from", _PIT_DATETIME, nullable=False),
        sa.Column("expires_at", _PIT_DATETIME, nullable=False),
        sa.Column("created_at", _PIT_DATETIME, nullable=False),
        sa.CheckConstraint(
            "permission = 'data:read'",
            name="ck_stock_snapshot_user_permission",
        ),
        sa.CheckConstraint(
            "dataset_id IN ('sina_fzb_report_observations', 'sina_lrb_report_observations')",
            name="ck_stock_snapshot_user_dataset",
        ),
        sa.CheckConstraint(
            "market IN ('SH', 'SZ') AND length(instrument_id) = 9 "
            "AND substr(instrument_id, 8, 2) = market",
            name="ck_stock_snapshot_user_market",
        ),
        sa.CheckConstraint(
            "length(publication_id) = 32 AND length(capture_id) = 64",
            name="ck_stock_snapshot_user_snapshot_ids",
        ),
        sa.CheckConstraint("purpose = 'RESEARCH'", name="ck_stock_snapshot_user_purpose"),
        sa.CheckConstraint("revision >= 1", name="ck_stock_snapshot_user_revision"),
        sa.CheckConstraint("expires_at > valid_from", name="ck_stock_snapshot_user_validity"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_stock_snapshot_user_grant_user",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "dataset_id",
            "instrument_id",
            "publication_id",
            "capture_id",
            "purpose",
            "revision",
            name="uq_stock_snapshot_user_scope_revision",
        ),
        sa.UniqueConstraint(
            "id", "user_id", "revision", name="uq_stock_snapshot_user_audit_revision"
        ),
    )
    op.create_index(
        "ix_stock_snapshot_user_lookup",
        _USER_GRANT,
        ["user_id", "dataset_id", "instrument_id", "publication_id", "capture_id"],
        unique=False,
    )

    op.create_table(
        _SOURCE_GRANT,
        sa.Column("id", _exact_identifier_type(36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", _exact_identifier_type(128), nullable=False),
        sa.Column("dataset_id", _exact_identifier_type(128), nullable=False),
        sa.Column("instrument_id", _exact_identifier_type(16), nullable=False),
        sa.Column("market", _exact_identifier_type(8), nullable=False),
        sa.Column("publication_id", _exact_identifier_type(32), nullable=False),
        sa.Column("capture_id", _exact_identifier_type(64), nullable=False),
        sa.Column("purpose", _exact_identifier_type(24), nullable=False),
        sa.Column("source_registry_revision", _exact_identifier_type(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("valid_from", _PIT_DATETIME, nullable=False),
        sa.Column("expires_at", _PIT_DATETIME, nullable=False),
        sa.Column("created_at", _PIT_DATETIME, nullable=False),
        sa.CheckConstraint(
            "(dataset_id = 'sina_fzb_report_observations' AND source_id = 'sina-fzb') OR "
            "(dataset_id = 'sina_lrb_report_observations' AND source_id = 'sina-lrb')",
            name="ck_stock_snapshot_source_dataset",
        ),
        sa.CheckConstraint(
            "market IN ('SH', 'SZ') AND length(instrument_id) = 9 "
            "AND substr(instrument_id, 8, 2) = market",
            name="ck_stock_snapshot_source_market",
        ),
        sa.CheckConstraint(
            "length(publication_id) = 32 AND length(capture_id) = 64",
            name="ck_stock_snapshot_source_snapshot_ids",
        ),
        sa.CheckConstraint("purpose = 'RESEARCH'", name="ck_stock_snapshot_source_purpose"),
        sa.CheckConstraint("revision >= 1", name="ck_stock_snapshot_source_revision"),
        sa.CheckConstraint(
            "length(source_registry_revision) BETWEEN 1 AND 128",
            name="ck_stock_snapshot_source_registry_revision",
        ),
        sa.CheckConstraint("expires_at > valid_from", name="ck_stock_snapshot_source_validity"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_stock_snapshot_source_grant_user",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_id",
            "dataset_id",
            "instrument_id",
            "publication_id",
            "capture_id",
            "purpose",
            "revision",
            name="uq_stock_snapshot_source_scope_revision",
        ),
        sa.UniqueConstraint(
            "id", "user_id", "revision", name="uq_stock_snapshot_source_audit_revision"
        ),
    )
    op.create_index(
        "ix_stock_snapshot_source_lookup",
        _SOURCE_GRANT,
        [
            "user_id",
            "source_id",
            "dataset_id",
            "instrument_id",
            "publication_id",
            "capture_id",
        ],
        unique=False,
    )

    op.create_table(
        _AUDIT,
        sa.Column("id", _exact_identifier_type(36), nullable=False),
        sa.Column("user_grant_id", _exact_identifier_type(36), nullable=True),
        sa.Column("source_grant_id", _exact_identifier_type(36), nullable=True),
        sa.Column("subject_user_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", _exact_identifier_type(16), nullable=False),
        sa.Column("grant_revision", sa.Integer(), nullable=False),
        sa.Column("revocation_revision", sa.Integer(), nullable=False),
        sa.Column("policy_version", _exact_identifier_type(64), nullable=False),
        sa.Column("occurred_at", _PIT_DATETIME, nullable=False),
        sa.Column("reason_code", _exact_identifier_type(128), nullable=False),
        sa.Column("idempotency_key_sha256", _exact_identifier_type(64), nullable=False),
        sa.CheckConstraint(
            "(user_grant_id IS NOT NULL AND source_grant_id IS NULL) OR "
            "(user_grant_id IS NULL AND source_grant_id IS NOT NULL)",
            name="ck_stock_snapshot_audit_one_grant",
        ),
        sa.CheckConstraint(
            "event_type IN ('ISSUED', 'REVOKED')",
            name="ck_stock_snapshot_audit_event",
        ),
        sa.CheckConstraint(
            "grant_revision >= 1 AND "
            "((event_type = 'ISSUED' AND revocation_revision = 1) OR "
            "(event_type = 'REVOKED' AND revocation_revision = 2))",
            name="ck_stock_snapshot_audit_revision",
        ),
        sa.CheckConstraint(
            "policy_version = 'stock-analysis-opendata-access-v1'",
            name="ck_stock_snapshot_audit_policy",
        ),
        sa.CheckConstraint(
            "length(reason_code) BETWEEN 1 AND 128",
            name="ck_stock_snapshot_audit_reason",
        ),
        sa.CheckConstraint(
            "length(idempotency_key_sha256) = 64",
            name="ck_stock_snapshot_audit_idempotency_hash",
        ),
        sa.ForeignKeyConstraint(
            ["user_grant_id", "subject_user_id", "grant_revision"],
            [
                f"{_USER_GRANT}.id",
                f"{_USER_GRANT}.user_id",
                f"{_USER_GRANT}.revision",
            ],
            name="fk_stock_snapshot_audit_user_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_grant_id", "subject_user_id", "grant_revision"],
            [
                f"{_SOURCE_GRANT}.id",
                f"{_SOURCE_GRANT}.user_id",
                f"{_SOURCE_GRANT}.revision",
            ],
            name="fk_stock_snapshot_audit_source_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_user_id"],
            ["users.id"],
            name="fk_stock_snapshot_audit_subject",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_stock_snapshot_audit_actor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_grant_id", "event_type", name="uq_stock_snapshot_audit_user_event"
        ),
        sa.UniqueConstraint(
            "source_grant_id", "event_type", name="uq_stock_snapshot_audit_source_event"
        ),
        sa.UniqueConstraint("idempotency_key_sha256", name="uq_stock_snapshot_audit_idempotency"),
    )
    op.create_index(
        "ix_stock_snapshot_audit_subject_time",
        _AUDIT,
        ["subject_user_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    """Refuse downgrade because no portable empty-check/drop lock is guaranteed."""
    raise RuntimeError("STOCK_SNAPSHOT_GRANT_DOWNGRADE_UNSUPPORTED")
