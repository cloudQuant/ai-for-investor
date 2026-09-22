from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TypeAlias

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]


class ScannerPlanModel(Base):
    __tablename__ = "scanner_plans"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_scanner_plans_owner_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    universe_pool_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    indicator_rules: Mapped[list[JSONValue]] = mapped_column(JSON, nullable=False, default=list)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    timeframe: Mapped[str] = mapped_column(String(20), nullable=False, default="1d")
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    schedule_frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="daily")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    result_table_name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    result_table_status: Mapped[str] = mapped_column(String(20), nullable=False, default="missing")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )

    runs: Mapped[list[ScannerPlanRunModel]] = relationship(
        "ScannerPlanRunModel",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="ScannerPlanRunModel.started_at.desc()",
    )


class ScannerPlanRunModel(Base):
    __tablename__ = "scanner_plan_runs"
    __table_args__ = (
        UniqueConstraint("plan_id", "run_date", name="uq_scanner_plan_runs_plan_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("scanner_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_date: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed", index=True)
    universe_pool_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    timeframe: Mapped[str] = mapped_column(String(20), nullable=False, default="1d")
    universe_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matches: Mapped[list[JSONValue]] = mapped_column(JSON, nullable=False, default=list)
    metrics: Mapped[dict[str, JSONValue]] = mapped_column(JSON, nullable=False, default=dict)
    source_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    plan: Mapped[ScannerPlanModel] = relationship("ScannerPlanModel", back_populates="runs")
