"""Persist immutable approved order targets and one-use authority events.

Revision ID: 20261016_strategy_target_approvals
Revises: 20261016_service_order_operations
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261016_strategy_target_approvals"
down_revision = "20261016_service_order_operations"
branch_labels = None
depends_on = None

_APPROVALS = "strategy_target_approvals"
_EVENTS = "strategy_target_approval_events"
_APPROVAL_LENGTHS = {
    "approval_ref": 128,
    "state": 16,
    "owner_subject": 256,
    "principal_ref": 128,
    "actor_ref": 128,
    "delegate_ref": 128,
    "scope_ref": 128,
    "execution_domain_ref": 128,
    "account_ref": 128,
    "strategy_ref": 128,
    "membership_sha256": 64,
    "target_ref": 128,
    "target_sha256": 64,
    "policy_ref": 128,
    "policy_sha256": 64,
    "approved_by_subject": 256,
    "approved_by_principal_ref": 128,
    "approved_by_actor_ref": 128,
    "approved_by_delegate_ref": 128,
    "operation_key_sha256": 64,
    "operation_request_sha256": 64,
    "intent_id": 128,
    "revoked_by_subject": 256,
    "revoked_by_actor_ref": 128,
    "revocation_reason_code": 128,
    "consumption_ref": 128,
    "consumed_intent_sha256": 64,
}
_APPROVAL_REQUIRED = set(_APPROVAL_LENGTHS) | {
    "approval_version",
    "record_version",
    "strategy_version",
    "membership_version",
    "membership_sha256",
    "target_version",
    "canonical_target_json",
    "policy_version",
    "approved_at_ns",
    "expires_at_ns",
    "operation_reserved_at_ns",
    "revoked_at_ns",
    "consumed_at_ns",
    "consumed_record_version",
    "created_at",
    "updated_at",
}
_EVENT_LENGTHS = {
    "id": 36,
    "approval_ref": 128,
    "event_type": 24,
    "owner_subject": 256,
    "actor_subject": 256,
    "principal_ref": 128,
    "actor_ref": 128,
    "delegate_ref": 128,
    "target_sha256": 64,
    "reason_code": 128,
    "operation_key_sha256": 64,
    "intent_id": 128,
    "intent_sha256": 64,
    "consumption_ref": 128,
}
_EVENT_REQUIRED = set(_EVENT_LENGTHS) | {
    "approval_version",
    "record_version",
    "occurred_at_ns",
}


def _validate_columns(table: str, required: set[str], lengths: dict[str, int]) -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"]: column for column in inspector.get_columns(table)}
    if not required.issubset(columns):
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    for name, length in lengths.items():
        column = columns[name]
        if not isinstance(column["type"], sa.String) or column["type"].length != length:
            raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")


def _validate_approval_table() -> None:
    inspector = sa.inspect(op.get_bind())
    _validate_columns(_APPROVALS, _APPROVAL_REQUIRED, _APPROVAL_LENGTHS)
    columns = {column["name"]: column for column in inspector.get_columns(_APPROVALS)}
    if inspector.get_pk_constraint(_APPROVALS).get("constrained_columns") != ["approval_ref"]:
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    expected_types = {
        "approval_version": sa.Integer,
        "record_version": sa.Integer,
        "strategy_version": sa.Integer,
        "membership_version": sa.Integer,
        "target_version": sa.Integer,
        "policy_version": sa.Integer,
        "approved_at_ns": sa.BigInteger,
        "expires_at_ns": sa.BigInteger,
        "operation_reserved_at_ns": sa.BigInteger,
        "revoked_at_ns": sa.BigInteger,
        "consumed_at_ns": sa.BigInteger,
        "consumed_record_version": sa.Integer,
        "created_at": sa.DateTime,
        "updated_at": sa.DateTime,
    }
    if any(
        not isinstance(columns[name]["type"], expected_type)
        for name, expected_type in expected_types.items()
    ) or not isinstance(columns["canonical_target_json"]["type"], sa.Text):
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    nullable = {
        "membership_version",
        "membership_sha256",
        "operation_key_sha256",
        "operation_request_sha256",
        "intent_id",
        "operation_reserved_at_ns",
        "revoked_by_subject",
        "revoked_by_actor_ref",
        "revoked_at_ns",
        "revocation_reason_code",
        "consumption_ref",
        "consumed_intent_sha256",
        "consumed_at_ns",
        "consumed_record_version",
    }
    for name in _APPROVAL_REQUIRED:
        if columns[name]["nullable"] != (name in nullable):
            raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    if not any(
        item.get("column_names")
        == ["owner_subject", "target_ref", "target_version", "approval_version"]
        for item in inspector.get_unique_constraints(_APPROVALS)
    ):
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    if not any(
        item.get("column_names")
        == [
            "owner_subject",
            "principal_ref",
            "actor_ref",
            "delegate_ref",
            "operation_key_sha256",
        ]
        for item in inspector.get_unique_constraints(_APPROVALS)
    ) or not any(
        item.get("column_names") == ["intent_id"]
        for item in inspector.get_unique_constraints(_APPROVALS)
    ):
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    check_map = {
        item.get("name"): (item.get("sqltext") or "").lower()
        for item in inspector.get_check_constraints(_APPROVALS)
    }
    expected_checks = {
        "ck_strategy_target_approval_version": "approval_version > 0",
        "ck_strategy_target_record_version": "record_version > 0",
        "ck_strategy_target_approval_state": "state in ('approved', 'revoked', 'consumed')",
        "ck_strategy_target_hash_length": "length(target_sha256) = 64",
        "ck_strategy_target_operation_reservation_complete": "operation_key_sha256 is not null",
        "ck_strategy_target_revocation_state": "revoked_at_ns is not null",
        "ck_strategy_target_consumption_state": "consumption_ref is not null",
    }
    for name, fragment in expected_checks.items():
        if fragment not in check_map.get(name, ""):
            raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    index_columns = {
        item.get("name"): item.get("column_names") for item in inspector.get_indexes(_APPROVALS)
    }
    if index_columns.get("ix_strategy_target_approval_owner_state") != ["owner_subject", "state"]:
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    if index_columns.get("ix_strategy_target_approval_scope") != [
        "owner_subject",
        "execution_domain_ref",
        "account_ref",
        "strategy_ref",
    ]:
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")


def _validate_event_table() -> None:
    inspector = sa.inspect(op.get_bind())
    _validate_columns(_EVENTS, _EVENT_REQUIRED, _EVENT_LENGTHS)
    columns = {column["name"]: column for column in inspector.get_columns(_EVENTS)}
    if inspector.get_pk_constraint(_EVENTS).get("constrained_columns") != ["id"]:
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    expected_types = {
        "approval_version": sa.Integer,
        "record_version": sa.Integer,
        "occurred_at_ns": sa.BigInteger,
    }
    if any(
        not isinstance(columns[name]["type"], expected_type)
        for name, expected_type in expected_types.items()
    ):
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        restrictive_reference = any(
            row._mapping["table"] == _APPROVALS
            and row._mapping["from"] == "approval_ref"
            and row._mapping["to"] == "approval_ref"
            and str(row._mapping["on_delete"]).upper() in {"RESTRICT", "NO ACTION"}
            for row in bind.exec_driver_sql(f"PRAGMA foreign_key_list('{_EVENTS}')")
        )
    else:
        restrictive_reference = any(
            item.get("constrained_columns") == ["approval_ref"]
            and item.get("referred_table") == _APPROVALS
            and item.get("referred_columns") == ["approval_ref"]
            and str((item.get("options") or {}).get("ondelete") or "").upper()
            in {"RESTRICT", "NO ACTION"}
            for item in inspector.get_foreign_keys(_EVENTS)
        )
    if not restrictive_reference:
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    nullable = {"reason_code", "operation_key_sha256", "intent_id", "intent_sha256", "consumption_ref"}
    for name in _EVENT_REQUIRED:
        if columns[name]["nullable"] != (name in nullable):
            raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    if not any(
        item.get("column_names") == ["approval_ref", "approval_version", "record_version"]
        for item in inspector.get_unique_constraints(_EVENTS)
    ):
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    checks = {
        item.get("name"): (item.get("sqltext") or "").lower()
        for item in inspector.get_check_constraints(_EVENTS)
    }
    if "event_type in ('approved', 'operation_reserved', 'revoked', 'consumed')" not in checks.get(
        "ck_strategy_target_approval_event_type", ""
    ):
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")
    if not any(
        item.get("name") == "ix_strategy_target_approval_event_owner_time"
        and item.get("column_names") == ["owner_subject", "occurred_at_ns"]
        for item in inspector.get_indexes(_EVENTS)
    ):
        raise RuntimeError("STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT")


def _create_approval_table() -> None:
    op.create_table(
        _APPROVALS,
        sa.Column("approval_ref", sa.String(128), primary_key=True),
        sa.Column("approval_version", sa.Integer(), nullable=False),
        sa.Column("record_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("owner_subject", sa.String(256), nullable=False),
        sa.Column("principal_ref", sa.String(128), nullable=False),
        sa.Column("actor_ref", sa.String(128), nullable=False),
        sa.Column("delegate_ref", sa.String(128), nullable=False),
        sa.Column("scope_ref", sa.String(128), nullable=False),
        sa.Column("execution_domain_ref", sa.String(128), nullable=False),
        sa.Column("account_ref", sa.String(128), nullable=False),
        sa.Column("strategy_ref", sa.String(128), nullable=False),
        sa.Column("strategy_version", sa.Integer(), nullable=False),
        sa.Column("membership_version", sa.Integer(), nullable=True),
        sa.Column("membership_sha256", sa.String(64), nullable=True),
        sa.Column("target_ref", sa.String(128), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("target_sha256", sa.String(64), nullable=False),
        sa.Column("canonical_target_json", sa.Text(), nullable=False),
        sa.Column("policy_ref", sa.String(128), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("policy_sha256", sa.String(64), nullable=False),
        sa.Column("approved_by_subject", sa.String(256), nullable=False),
        sa.Column("approved_by_principal_ref", sa.String(128), nullable=False),
        sa.Column("approved_by_actor_ref", sa.String(128), nullable=False),
        sa.Column("approved_by_delegate_ref", sa.String(128), nullable=False),
        sa.Column("approved_at_ns", sa.BigInteger(), nullable=False),
        sa.Column("expires_at_ns", sa.BigInteger(), nullable=False),
        sa.Column("operation_key_sha256", sa.String(64), nullable=True),
        sa.Column("operation_request_sha256", sa.String(64), nullable=True),
        sa.Column("intent_id", sa.String(128), nullable=True),
        sa.Column("operation_reserved_at_ns", sa.BigInteger(), nullable=True),
        sa.Column("revoked_by_subject", sa.String(256), nullable=True),
        sa.Column("revoked_by_actor_ref", sa.String(128), nullable=True),
        sa.Column("revoked_at_ns", sa.BigInteger(), nullable=True),
        sa.Column("revocation_reason_code", sa.String(128), nullable=True),
        sa.Column("consumption_ref", sa.String(128), nullable=True),
        sa.Column("consumed_intent_sha256", sa.String(64), nullable=True),
        sa.Column("consumed_at_ns", sa.BigInteger(), nullable=True),
        sa.Column("consumed_record_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("approval_version > 0", name="ck_strategy_target_approval_version"),
        sa.CheckConstraint("record_version > 0", name="ck_strategy_target_record_version"),
        sa.CheckConstraint(
            "state IN ('APPROVED', 'REVOKED', 'CONSUMED')",
            name="ck_strategy_target_approval_state",
        ),
        sa.CheckConstraint("length(target_sha256) = 64", name="ck_strategy_target_hash_length"),
        sa.CheckConstraint(
            "(operation_key_sha256 IS NULL AND operation_request_sha256 IS NULL "
            "AND intent_id IS NULL AND operation_reserved_at_ns IS NULL) OR "
            "(operation_key_sha256 IS NOT NULL AND operation_request_sha256 IS NOT NULL "
            "AND intent_id IS NOT NULL AND operation_reserved_at_ns IS NOT NULL)",
            name="ck_strategy_target_operation_reservation_complete",
        ),
        sa.CheckConstraint(
            "(state = 'REVOKED' AND revoked_at_ns IS NOT NULL AND "
            "revoked_by_subject IS NOT NULL AND revoked_by_actor_ref IS NOT NULL "
            "AND revocation_reason_code IS NOT NULL) OR "
            "(state != 'REVOKED' AND revoked_at_ns IS NULL AND "
            "revoked_by_subject IS NULL AND revoked_by_actor_ref IS NULL "
            "AND revocation_reason_code IS NULL)",
            name="ck_strategy_target_revocation_state",
        ),
        sa.CheckConstraint(
            "(state = 'CONSUMED' AND consumption_ref IS NOT NULL AND "
            "consumed_intent_sha256 IS NOT NULL AND consumed_at_ns IS NOT NULL "
            "AND consumed_record_version IS NOT NULL) OR "
            "(state != 'CONSUMED' AND consumption_ref IS NULL AND "
            "consumed_intent_sha256 IS NULL AND consumed_at_ns IS NULL "
            "AND consumed_record_version IS NULL)",
            name="ck_strategy_target_consumption_state",
        ),
        sa.UniqueConstraint(
            "owner_subject",
            "target_ref",
            "target_version",
            "approval_version",
            name="uq_strategy_target_approval_target_version",
        ),
        sa.UniqueConstraint(
            "owner_subject",
            "principal_ref",
            "actor_ref",
            "delegate_ref",
            "operation_key_sha256",
            name="uq_strategy_target_approval_operation_key",
        ),
        sa.UniqueConstraint("intent_id", name="uq_strategy_target_approval_intent"),
    )
    op.create_index(
        "ix_strategy_target_approval_owner_state", _APPROVALS, ["owner_subject", "state"]
    )
    op.create_index(
        "ix_strategy_target_approval_scope",
        _APPROVALS,
        ["owner_subject", "execution_domain_ref", "account_ref", "strategy_ref"],
    )


def _create_event_table() -> None:
    op.create_table(
        _EVENTS,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("approval_ref", sa.String(128), nullable=False),
        sa.Column("approval_version", sa.Integer(), nullable=False),
        sa.Column("record_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("owner_subject", sa.String(256), nullable=False),
        sa.Column("actor_subject", sa.String(256), nullable=False),
        sa.Column("principal_ref", sa.String(128), nullable=False),
        sa.Column("actor_ref", sa.String(128), nullable=False),
        sa.Column("delegate_ref", sa.String(128), nullable=False),
        sa.Column("target_sha256", sa.String(64), nullable=False),
        sa.Column("occurred_at_ns", sa.BigInteger(), nullable=False),
        sa.Column("reason_code", sa.String(128), nullable=True),
        sa.Column("operation_key_sha256", sa.String(64), nullable=True),
        sa.Column("intent_id", sa.String(128), nullable=True),
        sa.Column("intent_sha256", sa.String(64), nullable=True),
        sa.Column("consumption_ref", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(
            ["approval_ref"],
            [f"{_APPROVALS}.approval_ref"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "event_type IN ('APPROVED', 'OPERATION_RESERVED', 'REVOKED', 'CONSUMED')",
            name="ck_strategy_target_approval_event_type",
        ),
        sa.UniqueConstraint(
            "approval_ref",
            "approval_version",
            "record_version",
            name="uq_strategy_target_approval_event_version",
        ),
    )
    op.create_index(
        "ix_strategy_target_approval_event_owner_time",
        _EVENTS,
        ["owner_subject", "occurred_at_ns"],
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_APPROVALS):
        _validate_approval_table()
    else:
        _create_approval_table()

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_EVENTS):
        _validate_event_table()
    else:
        _create_event_table()


def downgrade() -> None:
    op.drop_index("ix_strategy_target_approval_event_owner_time", table_name=_EVENTS)
    op.drop_table(_EVENTS)
    op.drop_index("ix_strategy_target_approval_scope", table_name=_APPROVALS)
    op.drop_index("ix_strategy_target_approval_owner_state", table_name=_APPROVALS)
    op.drop_table(_APPROVALS)
