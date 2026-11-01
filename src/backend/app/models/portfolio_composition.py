"""Immutable membership versions for display-only portfolio compositions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, Integer, String, UniqueConstraint

from app.db.database import Base


class PortfolioCompositionVersion(Base):
    """One immutable, owner-scoped snapshot of display portfolio membership."""

    __tablename__ = "portfolio_composition_versions"
    __table_args__ = (
        UniqueConstraint(
            "owner_subject",
            "portfolio_ref",
            "membership_version",
            name="uq_portfolio_composition_owner_ref_version",
        ),
        CheckConstraint("membership_version > 0", name="ck_portfolio_composition_version_positive"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_subject = Column(String(256), nullable=False, index=True)
    portfolio_ref = Column(String(128), nullable=False)
    membership_version = Column(Integer, nullable=False)
    source_type = Column(String(16), nullable=False)
    base_currency = Column(String(16), nullable=False)
    members = Column(JSON, nullable=False)
    membership_sha256 = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
