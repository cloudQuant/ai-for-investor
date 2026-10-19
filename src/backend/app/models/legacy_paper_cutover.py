"""Durable cutover receipts and in-flight legacy writer claims."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class LegacyPaperCutoverReceipt(Base):
    """Immutable evidence binding managed use to its exact legacy source."""

    __tablename__ = "legacy_paper_cutover_receipts"
    __table_args__ = (
        CheckConstraint("state = 'ACTIVE'", name="ck_legacy_paper_cutover_active"),
        CheckConstraint(
            "source_kind IN ('empty_account', 'imported_legacy')",
            name="ck_legacy_paper_cutover_source_kind",
        ),
        CheckConstraint(
            "(source_kind = 'empty_account' AND receipt_version = 1 "
            "AND source_import_receipt_id IS NULL AND source_import_generation IS NULL "
            "AND target_import_sha256 IS NULL AND source_order_count = 0 "
            "AND source_position_count = 0 AND source_trade_count = 0) "
            "OR (source_kind = 'imported_legacy' AND receipt_version = 2 "
            "AND source_import_receipt_id IS NOT NULL "
            "AND source_import_generation IS NOT NULL AND source_import_generation > 0 "
            "AND target_import_sha256 IS NOT NULL "
            "AND length(target_import_sha256) = 64 "
            "AND source_order_count >= 0 AND source_position_count >= 0 "
            "AND source_trade_count >= 0 "
            "AND source_order_count + source_position_count + source_trade_count > 0)",
            name="ck_legacy_paper_cutover_source_profile",
        ),
        CheckConstraint(
            "length(source_inventory_sha256) = 64", name="ck_legacy_paper_cutover_inventory_hash"
        ),
        CheckConstraint("length(binding_sha256) = 64", name="ck_legacy_paper_cutover_binding_hash"),
        CheckConstraint(
            "length(paper_domain_sha256) = 64", name="ck_legacy_paper_cutover_domain_hash"
        ),
        Index("ix_legacy_paper_cutover_owner", "owner_subject"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    legacy_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("paper_trading_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    owner_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    receipt_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_inventory_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(
        String(24), nullable=False, default="empty_account"
    )
    source_import_receipt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("legacy_paper_import_receipts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_import_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_import_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    paper_domain_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    account_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_domain_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    initial_cash: Mapped[str] = mapped_column(String(64), nullable=False)
    initial_fees: Mapped[str] = mapped_column(String(64), nullable=False)
    fee_rate: Mapped[str] = mapped_column(String(64), nullable=False)
    source_order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_trade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class LegacyPaperWriterLease(Base):
    """Short-lived DB claim held across a legacy order mutation."""

    __tablename__ = "legacy_paper_writer_leases"
    __table_args__ = (Index("ix_legacy_paper_writer_leases_account", "account_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("paper_trading_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


__all__ = ["LegacyPaperCutoverReceipt", "LegacyPaperWriterLease"]
