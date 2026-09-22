"""
Backtest comparison models.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, TypeAlias

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.backtest import BacktestTask
    from app.models.user import User

JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]


class ComparisonType(str, Enum):
    """Comparison type enum."""

    METRICS = "metrics"  # Metrics comparison
    EQUITY = "equity"  # Equity curve comparison
    TRADES = "trades"  # Trade comparison
    DRAWDOWN = "drawdown"  # Drawdown comparison


class Comparison(Base):
    """Backtest result comparison table.

    Attributes:
        id: Unique comparison identifier (UUID).
        user_id: User ID who owns the comparison.
        name: Comparison name.
        description: Comparison description.
        type: Comparison type.
        backtest_task_ids: List of backtest task IDs.
        comparison_data: Comparison results (JSON).
        is_favorite: Whether marked as favorite.
        is_public: Whether publicly visible.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    __tablename__ = "backtest_comparisons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)  # Comparison name
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(
        String(20), default=ComparisonType.METRICS, nullable=False
    )  # Comparison type

    # Compared backtest task ID list
    backtest_task_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False
    )  # Backtest task ID list

    # Comparison results (JSON stored)
    comparison_data: Mapped[dict[str, JSONValue]] = mapped_column(
        JSON, nullable=False
    )  # Comparison results

    # Flags
    is_favorite: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # Whether favorited
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # Whether public

    # Timestamps
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="comparisons")
    backtest_tasks: Mapped[list["BacktestTask"]] = relationship(
        "BacktestTask", secondary="comparison_backtest_association"
    )
    shares: Mapped[list["ComparisonShare"]] = relationship(
        "ComparisonShare", back_populates="comparison"
    )


class ComparisonShare(Base):
    """Comparison share table.

    Attributes:
        id: Unique share identifier (UUID).
        comparison_id: Associated comparison ID.
        shared_with_user_id: User ID to share with.
        can_edit: Whether edit permission is granted.
        created_at: Share creation timestamp.
    """

    __tablename__ = "comparison_shares"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    comparison_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("backtest_comparisons.id"), nullable=False, index=True
    )
    shared_with_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    can_edit: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # Whether edit is allowed
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    comparison: Mapped["Comparison"] = relationship("Comparison", back_populates="shares")
    shared_with_user: Mapped["User"] = relationship("User")


# Many-to-many association table (comparison - backtest tasks)
comparison_backtest_association = Table(
    "comparison_backtest_association",
    Base.metadata,
    Column("comparison_id", String(36), ForeignKey("backtest_comparisons.id"), primary_key=True),
    Column("backtest_task_id", String(36), ForeignKey("backtest_tasks.id"), primary_key=True),
)
