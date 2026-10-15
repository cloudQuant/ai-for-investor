"""Persistent AFI authority state for approved strategy targets."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base


class StrategyOrderApprovalPolicyVersion(Base):
    """Immutable owner-scoped AFI order-approval policy content."""

    __tablename__ = "strategy_order_approval_policy_versions"
    __table_args__ = (
        UniqueConstraint(
            "owner_subject",
            "policy_ref",
            "policy_version",
            name="uq_strategy_order_approval_policy_version",
        ),
        CheckConstraint("policy_version > 0", name="ck_strategy_order_policy_version_positive"),
        CheckConstraint("length(policy_sha256) = 64", name="ck_strategy_order_policy_hash_length"),
        Index("ix_strategy_order_approval_policy_owner", "owner_subject"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_subject = Column(String(256), nullable=False)
    policy_ref = Column(String(128), nullable=False)
    policy_version = Column(Integer, nullable=False)
    policy_sha256 = Column(String(64), nullable=False)
    canonical_policy_json = Column(Text, nullable=False)
    published_by_subject = Column(String(256), nullable=False)
    published_by_principal_ref = Column(String(128), nullable=False)
    published_by_actor_ref = Column(String(128), nullable=False)
    published_by_delegate_ref = Column(String(128), nullable=False, default="")
    published_at_ns = Column(BigInteger, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class StrategyOrderApprovalPolicyHead(Base):
    """The single currently published AFI policy for an owner."""

    __tablename__ = "strategy_order_approval_policy_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_subject", "policy_ref", "policy_version"],
            [
                "strategy_order_approval_policy_versions.owner_subject",
                "strategy_order_approval_policy_versions.policy_ref",
                "strategy_order_approval_policy_versions.policy_version",
            ],
            ondelete="RESTRICT",
            name="fk_strategy_order_policy_head_version",
        ),
        CheckConstraint("head_version > 0", name="ck_strategy_order_policy_head_version_positive"),
        CheckConstraint("length(policy_sha256) = 64", name="ck_strategy_order_policy_head_hash_length"),
    )

    owner_subject = Column(String(256), primary_key=True)
    policy_ref = Column(String(128), nullable=False)
    policy_version = Column(Integer, nullable=False)
    policy_sha256 = Column(String(64), nullable=False)
    head_version = Column(Integer, nullable=False, default=1)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class StrategyApprovalAuthorityEpoch(Base):
    """Per-owner serialization row for all approval-freshness source writes."""

    __tablename__ = "strategy_approval_authority_epochs"
    __table_args__ = (
        CheckConstraint("epoch >= 0", name="ck_strategy_approval_authority_epoch_nonnegative"),
    )

    owner_subject = Column(String(256), primary_key=True)
    epoch = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
