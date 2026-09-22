"""
Workspace and StrategyUnit ORM models.

Supports the "策略研究" (Strategy Research) workspace feature
introduced in iteration 124.
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, TypeAlias

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.user import User


WorkspaceJSONScalar: TypeAlias = str | int | float | bool | None
WorkspaceJSONValue: TypeAlias = (
    WorkspaceJSONScalar | list["WorkspaceJSONValue"] | dict[str, "WorkspaceJSONValue"]
)
WorkspaceJSONMapping: TypeAlias = dict[str, WorkspaceJSONValue]


class Workspace(Base):
    """Workspace table.

    A workspace is a logical container for strategy units, allowing users
    to organize, run, and compare multiple strategy configurations.

    Attributes:
        id: Unique workspace identifier (UUID).
        user_id: Owner user ID.
        name: Workspace display name.
        description: Optional description.
        settings: Workspace-level settings JSON (parallel_config, defaults, etc.).
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    __tablename__ = "workspaces"
    __table_args__ = (
        Index(
            "ix_workspaces_user_type_updated_id", "user_id", "workspace_type", "updated_at", "id"
        ),
        Index("ix_workspaces_user_updated_id", "user_id", "updated_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="research", index=True
    )
    settings: Mapped[WorkspaceJSONMapping | None] = mapped_column(JSON, default=dict, nullable=True)
    trading_config: Mapped[WorkspaceJSONMapping | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="workspaces")
    strategy_units: Mapped[list["StrategyUnit"]] = relationship(
        "StrategyUnit",
        back_populates="workspace",
        cascade="all, delete-orphan",
        order_by="StrategyUnit.sort_order",
    )


class StrategyUnit(Base):
    """Strategy unit table.

    A strategy unit represents a single strategy + symbol + timeframe
    configuration within a workspace.

    Attributes:
        id: Unique unit identifier (UUID).
        workspace_id: Parent workspace ID.
        group_name: Logical grouping label.
        strategy_id: Strategy template ID.
        strategy_name: Strategy display name.
        symbol: Trading symbol code.
        symbol_name: Symbol display name.
        timeframe: K-line timeframe (e.g. '1m', '5m', '15m', '1h', '1d').
        timeframe_n: Timeframe multiplier.
        category: Classification tag.
        sort_order: Display order within workspace.
        data_config: Data source configuration JSON.
        unit_settings: Unit-level settings JSON (margin, commission, slippage, etc.).
        params: Strategy parameters JSON.
        optimization_config: Optimization configuration JSON.
        run_status: Current run status (idle/queued/running/completed/failed/cancelled).
        run_count: Cumulative run count.
        last_run_time: Duration of last run in seconds.
        last_task_id: Most recent backtest task ID (reference to backtest_tasks).
        last_optimization_task_id: Most recent optimization task ID.
        metrics_snapshot: Key metrics from last completed run (JSON).
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    __tablename__ = "strategy_units"
    __table_args__ = (
        Index(
            "uq_strategy_units_trading_instance_id",
            "trading_instance_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_name: Mapped[str | None] = mapped_column(String(200), nullable=True, default="")
    strategy_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    strategy_name: Mapped[str | None] = mapped_column(String(200), nullable=True, default="")
    symbol: Mapped[str | None] = mapped_column(String(50), nullable=True, default="")
    symbol_name: Mapped[str | None] = mapped_column(String(200), nullable=True, default="")
    timeframe: Mapped[str | None] = mapped_column(String(10), nullable=True, default="1d")
    timeframe_n: Mapped[int | None] = mapped_column(Integer, default=1)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, default="")
    sort_order: Mapped[int | None] = mapped_column(Integer, default=0)

    # Configuration JSON fields
    data_config: Mapped[WorkspaceJSONMapping | None] = mapped_column(JSON, default=dict)
    unit_settings: Mapped[WorkspaceJSONMapping | None] = mapped_column(JSON, default=dict)
    params: Mapped[WorkspaceJSONMapping | None] = mapped_column(JSON, default=dict)
    optimization_config: Mapped[WorkspaceJSONMapping | None] = mapped_column(JSON, default=dict)
    trading_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="paper")
    gateway_config: Mapped[WorkspaceJSONMapping | None] = mapped_column(JSON, default=dict)
    lock_trading: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lock_running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trading_instance_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trading_snapshot: Mapped[WorkspaceJSONMapping | None] = mapped_column(JSON, default=dict)

    # Run state
    run_status: Mapped[str | None] = mapped_column(String(20), default="idle")
    run_count: Mapped[int | None] = mapped_column(Integer, default=0)
    last_run_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_optimization_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    bar_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics_snapshot: Mapped[WorkspaceJSONMapping | None] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="strategy_units")
