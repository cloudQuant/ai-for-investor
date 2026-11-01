"""Durable AFI idempotency mapping for manual intents sent to Execution."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ServiceOrderOperation(Base):
    """Map one authenticated operation key to the SDK-owned durable intent.

    The Execution journal remains authoritative for order state. This table
    preserves the HTTP operation identity and prevents AFI restarts or parallel
    workers from minting a second intent for the same caller key.
    """

    __tablename__ = "service_order_operations"
    __table_args__ = (
        UniqueConstraint(
            "owner_subject",
            "principal_ref",
            "actor_ref",
            "delegate_ref",
            "operation_key_sha256",
            name="uq_service_order_operation_authority_key",
        ),
        UniqueConstraint("intent_id", name="uq_service_order_operation_intent"),
        CheckConstraint("length(operation_key_sha256) = 64", name="ck_service_order_key_hash"),
        CheckConstraint("length(request_sha256) = 64", name="ck_service_order_request_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_subject: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    principal_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    delegate_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    operation_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="manual_order")
    operation_key_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    account_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    manual_book_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    last_service_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_record_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
