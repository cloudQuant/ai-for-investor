"""Durable source-side handoff receipts for non-empty legacy paper imports.

The receipt freezes the original paper account tables and retains their exact
canonical snapshot.  Related approval, alert, risk-rule and reporting records
remain in their original AFI tables; the bounded preservation digest is an
inventory only and never grants those controls to the new Execution owner.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

_SNAPSHOT_TEXT = Text().with_variant(mysql.LONGTEXT(), "mysql")


class LegacyPaperImportReceipt(Base):
    """Immutable source snapshot and monotone cross-store import state."""

    __tablename__ = "legacy_paper_import_receipts"
    __table_args__ = (
        UniqueConstraint(
            "legacy_account_id", "generation", name="uq_legacy_paper_import_generation"
        ),
        UniqueConstraint("active_fence_key", name="uq_legacy_paper_import_active_fence"),
        CheckConstraint("generation > 0", name="ck_legacy_paper_import_generation_positive"),
        CheckConstraint("receipt_version = 1", name="ck_legacy_paper_import_version"),
        CheckConstraint(
            "state IN ('PREPARED', 'COMMITTED', 'ACTIVE', 'ABORTED')",
            name="ck_legacy_paper_import_state",
        ),
        CheckConstraint(
            "length(source_inventory_sha256) = 64", name="ck_legacy_paper_import_source_hash"
        ),
        CheckConstraint(
            "length(target_import_sha256) = 64", name="ck_legacy_paper_import_target_hash"
        ),
        CheckConstraint(
            "length(target_domain_sha256) = 64", name="ck_legacy_paper_import_domain_hash"
        ),
        CheckConstraint("length(binding_sha256) = 64", name="ck_legacy_paper_import_binding_hash"),
        CheckConstraint(
            "length(preserved_context_sha256) = 64", name="ck_legacy_paper_import_context_hash"
        ),
        CheckConstraint("source_order_count >= 0", name="ck_legacy_paper_import_order_count"),
        CheckConstraint("source_position_count >= 0", name="ck_legacy_paper_import_position_count"),
        CheckConstraint("source_trade_count >= 0", name="ck_legacy_paper_import_trade_count"),
        Index("ix_legacy_paper_import_owner", "owner_subject"),
        Index("ix_legacy_paper_import_target_scope", "target_scope_key"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    legacy_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("paper_trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    active_fence_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    owner_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="PREPARED")
    receipt_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_inventory_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot_json: Mapped[str] = mapped_column(_SNAPSHOT_TEXT, nullable=False)
    target_import_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    target_domain_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    target_scope_key: Mapped[str] = mapped_column(String(128), nullable=False)
    target_account_key: Mapped[str] = mapped_column(String(128), nullable=False)
    cash_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    opening_cash: Mapped[str] = mapped_column(String(64), nullable=False)
    cumulative_fees: Mapped[str] = mapped_column(String(64), nullable=False)
    unallocated_equity_residual: Mapped[str] = mapped_column(String(64), nullable=False)
    source_order_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_position_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    preserved_context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    preserved_context_json: Mapped[str] = mapped_column(_SNAPSHOT_TEXT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


@dataclass(frozen=True, slots=True)
class LegacyPaperImportReceiptView:
    """Read-only, owner-scoped receipt projection without raw source rows."""

    receipt_id: str
    legacy_account_id: str
    generation: int
    state: str
    owner_subject: str
    source_inventory_sha256: str
    target_import_sha256: str
    target_domain_sha256: str
    binding_sha256: str
    target_scope_key: str
    target_account_key: str
    cash_currency: str
    opening_cash: str
    cumulative_fees: str
    unallocated_equity_residual: str
    source_order_count: int
    source_position_count: int
    source_trade_count: int
    preserved_context_sha256: str
    created_at: datetime
    updated_at: datetime


__all__ = ["LegacyPaperImportReceipt", "LegacyPaperImportReceiptView"]
