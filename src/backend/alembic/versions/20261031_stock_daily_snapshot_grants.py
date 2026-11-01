"""Extend exact snapshot grants with the pinned stock-daily dataset.

Revision ID: 20261031_stock_daily_snapshot_grants
Revises: 20261030_stock_analysis_snapshot_grants
Create Date: 2026-10-31

This revision only widens the dataset/source CHECK constraints on the existing
user-read and source-research grant tables. It preserves every existing
constraint, unique key, index, and audit foreign key. No grant is seeded and no
issuer or API is added.

Downgrade narrows the two CHECK constraints back to the pre-migration form, but
only after proving that no persisted stock-daily grant row would become
unreadable. Any such row keeps the revision fail-closed with
``STOCK_DAILY_GRANT_DOWNGRADE_UNSUPPORTED`` and no schema or data changes. The
probe, DDL, and revision update share one connection/transaction where the
dialect supports transactional DDL; MySQL implicitly commits each DDL statement,
so a concurrent writer cannot be excluded there, which is why the pre-check
still runs before the first ALTER. Offline (``--sql``) generation cannot read
data and therefore emits a manual precheck query instead.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql, postgresql

from alembic import op

revision = "20261031_stock_daily_snapshot_grants"
down_revision = "20261030_stock_analysis_snapshot_grants"
branch_labels = None
depends_on = None

_USER_GRANT = "stock_snapshot_user_read_grants"
_SOURCE_GRANT = "stock_snapshot_source_research_grants"
_AUDIT = "stock_snapshot_grant_audits"
_USER_DATASET_CONSTRAINT = "ck_stock_snapshot_user_dataset"
_SOURCE_DATASET_CONSTRAINT = "ck_stock_snapshot_source_dataset"
_AUDIT_SCOPE_FOREIGN_KEYS = (
    "fk_stock_snapshot_audit_user_scope",
    "fk_stock_snapshot_audit_source_scope",
)
_USER_DATASET_CHECK = (
    "dataset_id IN ('sina_fzb_report_observations', "
    "'sina_lrb_report_observations', 'cn-equity-stock-daily')"
)
_SOURCE_DATASET_CHECK = (
    "(dataset_id = 'sina_fzb_report_observations' AND source_id = 'sina-fzb') OR "
    "(dataset_id = 'sina_lrb_report_observations' AND source_id = 'sina-lrb') OR "
    "(dataset_id = 'cn-equity-stock-daily' AND source_id = 'akshare.daily')"
)
_USER_DATASET_CHECK_PREVIOUS = (
    "dataset_id IN ('sina_fzb_report_observations', 'sina_lrb_report_observations')"
)
_SOURCE_DATASET_CHECK_PREVIOUS = (
    "(dataset_id = 'sina_fzb_report_observations' AND source_id = 'sina-fzb') OR "
    "(dataset_id = 'sina_lrb_report_observations' AND source_id = 'sina-lrb')"
)
_STOCK_DAILY_DATASET = "cn-equity-stock-daily"
_STOCK_DAILY_SOURCE = "akshare.daily"
_USER_GRANT_DOWNGRADE_PROBE = sa.text(
    f"SELECT 1 FROM {_USER_GRANT} WHERE dataset_id = '{_STOCK_DAILY_DATASET}' LIMIT 1"
)
_SOURCE_GRANT_DOWNGRADE_PROBE = sa.text(
    f"SELECT 1 FROM {_SOURCE_GRANT} "
    f"WHERE dataset_id = '{_STOCK_DAILY_DATASET}' "
    f"OR source_id = '{_STOCK_DAILY_SOURCE}' LIMIT 1"
)
_PIT_DATETIME = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def _exact_identifier_type(length: int) -> sa.types.TypeEngine[object]:
    return (
        sa.String(length, collation="BINARY")
        .with_variant(
            mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"),
            "mysql",
        )
        .with_variant(postgresql.VARCHAR(length, collation="C"), "postgresql")
    )


def _assert_expected_schema() -> None:
    """Require the reviewed constraint names before altering anything."""
    inspector = sa.inspect(op.get_bind())
    expected_checks = {
        _USER_GRANT: _USER_DATASET_CONSTRAINT,
        _SOURCE_GRANT: _SOURCE_DATASET_CONSTRAINT,
    }
    for table_name, constraint_name in expected_checks.items():
        if not inspector.has_table(table_name):
            raise RuntimeError("STOCK_DAILY_GRANT_SCHEMA_CONFLICT")
        names = {item["name"] for item in inspector.get_check_constraints(table_name)}
        if constraint_name not in names:
            raise RuntimeError("STOCK_DAILY_GRANT_SCHEMA_CONFLICT")
    audit_foreign_keys = {item["name"] for item in inspector.get_foreign_keys(_AUDIT)}
    if not set(_AUDIT_SCOPE_FOREIGN_KEYS).issubset(audit_foreign_keys):
        raise RuntimeError("STOCK_DAILY_GRANT_SCHEMA_CONFLICT")


def _user_grant_copy(dataset_check: str = _USER_DATASET_CHECK) -> sa.Table:
    """Offline copy source for the existing user-read grant table."""
    return sa.Table(
        _USER_GRANT,
        sa.MetaData(),
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
        sa.CheckConstraint(dataset_check, name=_USER_DATASET_CONSTRAINT),
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
        sa.Index(
            "ix_stock_snapshot_user_lookup",
            "user_id",
            "dataset_id",
            "instrument_id",
            "publication_id",
            "capture_id",
        ),
    )


def _source_grant_copy(dataset_check: str = _SOURCE_DATASET_CHECK) -> sa.Table:
    """Offline copy source for the existing source-research grant table."""
    return sa.Table(
        _SOURCE_GRANT,
        sa.MetaData(),
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
        sa.CheckConstraint(dataset_check, name=_SOURCE_DATASET_CONSTRAINT),
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
        sa.Index(
            "ix_stock_snapshot_source_lookup",
            "user_id",
            "source_id",
            "dataset_id",
            "instrument_id",
            "publication_id",
            "capture_id",
        ),
    )


def _replace_check(
    table_name: str,
    constraint_name: str,
    condition_sql: str,
    copy_table: sa.Table,
) -> None:
    """Drop and recreate one named CHECK without changing any other schema."""
    with op.batch_alter_table(
        table_name,
        recreate="always",
        copy_from=copy_table,
    ) as batch:
        batch.drop_constraint(constraint_name, type_="check")
        batch.create_check_constraint(constraint_name, condition_sql)


def _assert_no_stock_daily_grants() -> None:
    """Refuse downgrade while any stock-daily grant evidence would be stranded.

    Both probes run against the migration connection before the first DDL
    statement, so a blocked downgrade leaves schema and data untouched. A failed
    probe propagates and aborts the migration instead of being swallowed.
    """
    bind = op.get_bind()
    if op.get_context().as_sql:
        op.execute(
            "-- MANUAL PRECHECK: STOCK_DAILY_GRANT_DOWNGRADE_UNSUPPORTED; abort before "
            "applying this downgrade if either query returns a row."
        )
        op.execute(_USER_GRANT_DOWNGRADE_PROBE)
        op.execute(_SOURCE_GRANT_DOWNGRADE_PROBE)
        return
    if bind.execute(_USER_GRANT_DOWNGRADE_PROBE).first() is not None:
        raise RuntimeError("STOCK_DAILY_GRANT_DOWNGRADE_UNSUPPORTED")
    if bind.execute(_SOURCE_GRANT_DOWNGRADE_PROBE).first() is not None:
        raise RuntimeError("STOCK_DAILY_GRANT_DOWNGRADE_UNSUPPORTED")


def upgrade() -> None:
    """Widen only the dataset/source CHECK constraints for stock-daily grants."""
    if not op.get_context().as_sql:
        _assert_expected_schema()

    dialect = op.get_context().dialect.name
    if dialect == "sqlite":
        _replace_check(
            _USER_GRANT,
            _USER_DATASET_CONSTRAINT,
            _USER_DATASET_CHECK,
            _user_grant_copy(_USER_DATASET_CHECK_PREVIOUS),
        )
        _replace_check(
            _SOURCE_GRANT,
            _SOURCE_DATASET_CONSTRAINT,
            _SOURCE_DATASET_CHECK,
            _source_grant_copy(_SOURCE_DATASET_CHECK_PREVIOUS),
        )
        return

    op.drop_constraint(_USER_DATASET_CONSTRAINT, _USER_GRANT, type_="check")
    op.create_check_constraint(
        _USER_DATASET_CONSTRAINT,
        _USER_GRANT,
        _USER_DATASET_CHECK,
    )
    op.drop_constraint(_SOURCE_DATASET_CONSTRAINT, _SOURCE_GRANT, type_="check")
    op.create_check_constraint(
        _SOURCE_DATASET_CONSTRAINT,
        _SOURCE_GRANT,
        _SOURCE_DATASET_CHECK,
    )


def downgrade() -> None:
    """Narrow the CHECKs only when no stock-daily grant evidence would be lost."""
    if not op.get_context().as_sql:
        _assert_expected_schema()
    _assert_no_stock_daily_grants()

    dialect = op.get_context().dialect.name
    if dialect == "sqlite":
        _replace_check(
            _USER_GRANT,
            _USER_DATASET_CONSTRAINT,
            _USER_DATASET_CHECK_PREVIOUS,
            _user_grant_copy(_USER_DATASET_CHECK),
        )
        _replace_check(
            _SOURCE_GRANT,
            _SOURCE_DATASET_CONSTRAINT,
            _SOURCE_DATASET_CHECK_PREVIOUS,
            _source_grant_copy(_SOURCE_DATASET_CHECK),
        )
        return

    op.drop_constraint(_USER_DATASET_CONSTRAINT, _USER_GRANT, type_="check")
    op.create_check_constraint(
        _USER_DATASET_CONSTRAINT,
        _USER_GRANT,
        _USER_DATASET_CHECK_PREVIOUS,
    )
    op.drop_constraint(_SOURCE_DATASET_CONSTRAINT, _SOURCE_GRANT, type_="check")
    op.create_check_constraint(
        _SOURCE_DATASET_CONSTRAINT,
        _SOURCE_GRANT,
        _SOURCE_DATASET_CHECK_PREVIOUS,
    )
