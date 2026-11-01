"""Durable HTTP idempotency mapping for approved Execution targets."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ApprovedTargetHttpOperation(Base):
    """Map one authenticated Idempotency-Key to one stable Execution intent.

    This is only an HTTP-to-intent identity map; Execution remains the order
    ledger. Approval reservation/consumption is recorded on the separate
    ``StrategyTargetApproval`` authority row.
    """

    __tablename__ = "approved_target_http_operations"
    __table_args__ = (
        UniqueConstraint(
            "owner_subject",
            "principal_ref",
            "actor_ref",
            "delegate_ref",
            "operation_key_sha256",
            name="uq_approved_target_http_authority_key",
        ),
        UniqueConstraint("approval_ref", name="uq_approved_target_http_approval"),
        UniqueConstraint("intent_id", name="uq_approved_target_http_intent"),
        CheckConstraint(
            "length(operation_key_sha256) = 64",
            name="ck_approved_target_http_key_hash",
        ),
        CheckConstraint(
            "length(request_sha256) = 64",
            name="ck_approved_target_http_request_hash",
        ),
        CheckConstraint(
            "length(target_sha256) = 64",
            name="ck_approved_target_http_target_hash",
        ),
        CheckConstraint("approval_version > 0", name="ck_approved_target_http_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_subject: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    principal_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    delegate_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    operation_key_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_ref: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("strategy_target_approvals.approval_ref", ondelete="RESTRICT"),
        nullable=False,
    )
    approval_version: Mapped[int] = mapped_column(Integer, nullable=False)
    target_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    selector_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    account_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
