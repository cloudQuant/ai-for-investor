"""Persist AFI manual-operation identity before forwarding to Execution.

Revision ID: 20261016_service_order_operations
Revises: 20261015_portfolio_import_source_material
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261016_service_order_operations"
down_revision = "20261015_portfolio_import_source_material"
branch_labels = None
depends_on = None

_TABLE = "service_order_operations"
_LENGTHS = {
    "id": 36,
    "owner_subject": 256,
    "principal_ref": 128,
    "actor_ref": 128,
    "delegate_ref": 128,
    "operation_kind": 32,
    "operation_key_sha256": 64,
    "request_sha256": 64,
    "intent_id": 128,
    "scope_ref": 128,
    "account_ref": 128,
    "manual_book_ref": 128,
    "last_service_code": 64,
    "last_record_state": 32,
}
_REQUIRED_COLUMNS = set(_LENGTHS) | {"created_at", "updated_at"}


def _validate_existing_table() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"]: column for column in inspector.get_columns(_TABLE)}
    if not _REQUIRED_COLUMNS.issubset(columns):
        raise RuntimeError("SERVICE_ORDER_OPERATION_SCHEMA_CONFLICT")
    if inspector.get_pk_constraint(_TABLE).get("constrained_columns") != ["id"]:
        raise RuntimeError("SERVICE_ORDER_OPERATION_SCHEMA_CONFLICT")
    for name, length in _LENGTHS.items():
        column = columns[name]
        if not isinstance(column["type"], sa.String) or column["type"].length != length:
            raise RuntimeError("SERVICE_ORDER_OPERATION_SCHEMA_CONFLICT")
        if name not in {"last_service_code", "last_record_state"} and column["nullable"]:
            raise RuntimeError("SERVICE_ORDER_OPERATION_SCHEMA_CONFLICT")
    for name in ("created_at", "updated_at"):
        if not isinstance(columns[name]["type"], sa.DateTime) or columns[name]["nullable"]:
            raise RuntimeError("SERVICE_ORDER_OPERATION_SCHEMA_CONFLICT")
    uniques = inspector.get_unique_constraints(_TABLE)
    if not any(
        constraint.get("column_names")
        == [
            "owner_subject",
            "principal_ref",
            "actor_ref",
            "delegate_ref",
            "operation_key_sha256",
        ]
        for constraint in uniques
    ) or not any(constraint.get("column_names") == ["intent_id"] for constraint in uniques):
        raise RuntimeError("SERVICE_ORDER_OPERATION_SCHEMA_CONFLICT")
    checks = inspector.get_check_constraints(_TABLE)
    check_text = " ".join(check.get("sqltext") or "" for check in checks)
    if "length(operation_key_sha256) = 64" not in check_text or "length(request_sha256) = 64" not in check_text:
        raise RuntimeError("SERVICE_ORDER_OPERATION_SCHEMA_CONFLICT")
    if not any(
        index.get("name") == "ix_service_order_operations_owner_subject"
        and index.get("column_names") == ["owner_subject"]
        for index in inspector.get_indexes(_TABLE)
    ):
        raise RuntimeError("SERVICE_ORDER_OPERATION_SCHEMA_CONFLICT")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_TABLE):
        _validate_existing_table()
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_subject", sa.String(length=256), nullable=False),
        sa.Column("principal_ref", sa.String(length=128), nullable=False),
        sa.Column("actor_ref", sa.String(length=128), nullable=False),
        sa.Column("delegate_ref", sa.String(length=128), nullable=False),
        sa.Column("operation_kind", sa.String(length=32), nullable=False),
        sa.Column("operation_key_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("intent_id", sa.String(length=128), nullable=False),
        sa.Column("scope_ref", sa.String(length=128), nullable=False),
        sa.Column("account_ref", sa.String(length=128), nullable=False),
        sa.Column("manual_book_ref", sa.String(length=128), nullable=False),
        sa.Column("last_service_code", sa.String(length=64), nullable=True),
        sa.Column("last_record_state", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(operation_key_sha256) = 64", name="ck_service_order_key_hash"
        ),
        sa.CheckConstraint("length(request_sha256) = 64", name="ck_service_order_request_hash"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_subject",
            "principal_ref",
            "actor_ref",
            "delegate_ref",
            "operation_key_sha256",
            name="uq_service_order_operation_authority_key",
        ),
        sa.UniqueConstraint("intent_id", name="uq_service_order_operation_intent"),
    )
    op.create_index(
        "ix_service_order_operations_owner_subject", _TABLE, ["owner_subject"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_service_order_operations_owner_subject", table_name=_TABLE)
    op.drop_table(_TABLE)
