"""Durable, single-use approvals for immutable strategy order targets.

Execution remains the authority for intent admission and order state.  This
model records AFI's approved target, the idempotent HTTP-to-intent reservation,
and the trusted one-time authority consumption as separate facts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base


class StrategyTargetApproval(Base):
    """One immutable approved order target and its one-use authority state.

    ``state == CONSUMED`` means the AFI authority committed a consumption
    receipt.  It does not mean Execution accepted an order or that a provider
    was called.  The Execution journal remains authoritative for those facts.
    """

    __tablename__ = "strategy_target_approvals"
    __table_args__ = (
        UniqueConstraint(
            "owner_subject",
            "target_ref",
            "target_version",
            "approval_version",
            name="uq_strategy_target_approval_target_version",
        ),
        UniqueConstraint(
            "owner_subject",
            "principal_ref",
            "actor_ref",
            "delegate_ref",
            "operation_key_sha256",
            name="uq_strategy_target_approval_operation_key",
        ),
        UniqueConstraint("intent_id", name="uq_strategy_target_approval_intent"),
        CheckConstraint("approval_version > 0", name="ck_strategy_target_approval_version"),
        CheckConstraint("record_version > 0", name="ck_strategy_target_record_version"),
        CheckConstraint(
            "state IN ('APPROVED', 'REVOKED', 'CONSUMED')",
            name="ck_strategy_target_approval_state",
        ),
        CheckConstraint("length(target_sha256) = 64", name="ck_strategy_target_hash_length"),
        CheckConstraint(
            "(operation_key_sha256 IS NULL AND operation_request_sha256 IS NULL "
            "AND intent_id IS NULL AND operation_reserved_at_ns IS NULL) OR "
            "(operation_key_sha256 IS NOT NULL AND operation_request_sha256 IS NOT NULL "
            "AND intent_id IS NOT NULL AND operation_reserved_at_ns IS NOT NULL)",
            name="ck_strategy_target_operation_reservation_complete",
        ),
        CheckConstraint(
            "(state = 'REVOKED' AND revoked_at_ns IS NOT NULL AND "
            "revoked_by_subject IS NOT NULL AND revoked_by_actor_ref IS NOT NULL "
            "AND revocation_reason_code IS NOT NULL) OR "
            "(state != 'REVOKED' AND revoked_at_ns IS NULL AND "
            "revoked_by_subject IS NULL AND revoked_by_actor_ref IS NULL "
            "AND revocation_reason_code IS NULL)",
            name="ck_strategy_target_revocation_state",
        ),
        CheckConstraint(
            "(state = 'CONSUMED' AND consumption_ref IS NOT NULL AND "
            "consumed_intent_sha256 IS NOT NULL AND consumed_at_ns IS NOT NULL "
            "AND consumed_record_version IS NOT NULL) OR "
            "(state != 'CONSUMED' AND consumption_ref IS NULL AND "
            "consumed_intent_sha256 IS NULL AND consumed_at_ns IS NULL "
            "AND consumed_record_version IS NULL)",
            name="ck_strategy_target_consumption_state",
        ),
        Index("ix_strategy_target_approval_owner_state", "owner_subject", "state"),
        Index(
            "ix_strategy_target_approval_scope",
            "owner_subject",
            "execution_domain_ref",
            "account_ref",
            "strategy_ref",
        ),
    )

    approval_ref = Column(String(128), primary_key=True, default=lambda: uuid.uuid4().hex)
    approval_version = Column(Integer, nullable=False, default=1)
    record_version = Column(Integer, nullable=False, default=1)
    state = Column(String(16), nullable=False, default="APPROVED")

    owner_subject = Column(String(256), nullable=False)
    principal_ref = Column(String(128), nullable=False)
    actor_ref = Column(String(128), nullable=False)
    delegate_ref = Column(String(128), nullable=False, default="")
    scope_ref = Column(String(128), nullable=False)
    execution_domain_ref = Column(String(128), nullable=False)
    account_ref = Column(String(128), nullable=False)
    strategy_ref = Column(String(128), nullable=False)
    strategy_version = Column(Integer, nullable=False)
    membership_version = Column(Integer, nullable=True)
    membership_sha256 = Column(String(64), nullable=True)

    target_ref = Column(String(128), nullable=False)
    target_version = Column(Integer, nullable=False)
    target_sha256 = Column(String(64), nullable=False)
    canonical_target_json = Column(Text, nullable=False)
    policy_ref = Column(String(128), nullable=False)
    policy_version = Column(Integer, nullable=False)
    policy_sha256 = Column(String(64), nullable=False)

    approved_by_subject = Column(String(256), nullable=False)
    approved_by_principal_ref = Column(String(128), nullable=False)
    approved_by_actor_ref = Column(String(128), nullable=False)
    approved_by_delegate_ref = Column(String(128), nullable=False, default="")
    approved_at_ns = Column(BigInteger, nullable=False)
    expires_at_ns = Column(BigInteger, nullable=False)

    operation_key_sha256 = Column(String(64), nullable=True)
    operation_request_sha256 = Column(String(64), nullable=True)
    intent_id = Column(String(128), nullable=True)
    operation_reserved_at_ns = Column(BigInteger, nullable=True)

    revoked_by_subject = Column(String(256), nullable=True)
    revoked_by_actor_ref = Column(String(128), nullable=True)
    revoked_at_ns = Column(BigInteger, nullable=True)
    revocation_reason_code = Column(String(128), nullable=True)

    consumption_ref = Column(String(128), nullable=True)
    consumed_intent_sha256 = Column(String(64), nullable=True)
    consumed_at_ns = Column(BigInteger, nullable=True)
    consumed_record_version = Column(Integer, nullable=True)

    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class StrategyTargetApprovalEvent(Base):
    """Append-only audit facts for approval, reservation, revoke and consume."""

    __tablename__ = "strategy_target_approval_events"
    __table_args__ = (
        UniqueConstraint(
            "approval_ref",
            "approval_version",
            "record_version",
            name="uq_strategy_target_approval_event_version",
        ),
        CheckConstraint(
            "event_type IN ('APPROVED', 'OPERATION_RESERVED', 'REVOKED', 'CONSUMED')",
            name="ck_strategy_target_approval_event_type",
        ),
        Index("ix_strategy_target_approval_event_owner_time", "owner_subject", "occurred_at_ns"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    approval_ref = Column(
        String(128),
        ForeignKey("strategy_target_approvals.approval_ref", ondelete="RESTRICT"),
        nullable=False,
    )
    approval_version = Column(Integer, nullable=False)
    record_version = Column(Integer, nullable=False)
    event_type = Column(String(24), nullable=False)
    owner_subject = Column(String(256), nullable=False)
    actor_subject = Column(String(256), nullable=False)
    principal_ref = Column(String(128), nullable=False)
    actor_ref = Column(String(128), nullable=False)
    delegate_ref = Column(String(128), nullable=False, default="")
    target_sha256 = Column(String(64), nullable=False)
    occurred_at_ns = Column(BigInteger, nullable=False)
    reason_code = Column(String(128), nullable=True)
    operation_key_sha256 = Column(String(64), nullable=True)
    intent_id = Column(String(128), nullable=True)
    intent_sha256 = Column(String(64), nullable=True)
    consumption_ref = Column(String(128), nullable=True)
