"""Owner-bound immutable offline facts datasets for portfolio analytics V1."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class PortfolioAnalyticsDatasetV1(Base):
    """One explicitly user-supplied offline V1 facts payload bound to a cut."""

    __tablename__ = "portfolio_analytics_datasets_v1"
    __table_args__ = (
        UniqueConstraint("dataset_ref", name="uq_portfolio_analytics_dataset_v1_ref"),
        UniqueConstraint(
            "owner_subject",
            "portfolio_ref",
            "membership_version",
            "idempotency_key_sha256",
            name="uq_portfolio_analytics_dataset_v1_idempotency",
        ),
        ForeignKeyConstraint(
            ["owner_subject", "portfolio_ref", "membership_version"],
            [
                "portfolio_composition_versions.owner_subject",
                "portfolio_composition_versions.portfolio_ref",
                "portfolio_composition_versions.membership_version",
            ],
            ondelete="RESTRICT",
            name="fk_portfolio_analytics_dataset_v1_membership",
        ),
        CheckConstraint(
            "membership_version > 0", name="ck_portfolio_analytics_dataset_v1_membership_version"
        ),
        CheckConstraint(
            "source_type IN ('research', 'imported', 'paper')",
            name="ck_portfolio_analytics_dataset_v1_source_type",
        ),
        CheckConstraint(
            "source_trust = 'USER_SUPPLIED_OFFLINE'",
            name="ck_portfolio_analytics_dataset_v1_source_trust",
        ),
        CheckConstraint(
            "length(membership_sha256) = 64", name="ck_portfolio_analytics_dataset_v1_membership_sha"
        ),
        CheckConstraint("length(facts_sha256) = 64", name="ck_portfolio_analytics_dataset_v1_facts_sha"),
        CheckConstraint(
            "length(idempotency_key_sha256) = 64",
            name="ck_portfolio_analytics_dataset_v1_idempotency_sha",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_subject: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    portfolio_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    membership_version: Mapped[int] = mapped_column(Integer, nullable=False)
    membership_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_trust: Mapped[str] = mapped_column(
        String(32), nullable=False, default="USER_SUPPLIED_OFFLINE"
    )
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_generation: Mapped[str] = mapped_column(String(128), nullable=False)
    facts_snapshot_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    facts_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    facts_json: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
