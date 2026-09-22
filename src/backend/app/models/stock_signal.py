"""Persisted, versioned stock-signal predictions and batch runs."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Literal, TypeAlias

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
JSONMapping: TypeAlias = dict[str, JSONValue]
SignalAction: TypeAlias = Literal["BUY", "SELL", "WATCH"]


class StockSignalRun(Base):
    """An idempotent audit record for a scheduled signal batch."""

    __tablename__ = "stock_signal_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    owner_scope: Mapped[str] = mapped_column(
        String(80), nullable=False, default="system", index=True
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="nightly_sse50", index=True
    )
    universe_code: Mapped[str] = mapped_column(
        String(32), nullable=False, default="SSE50", index=True
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    scheduled_for_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    expected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    degraded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    universe_snapshot_json: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    config_snapshot_json: Mapped[JSONMapping] = mapped_column(JSON, nullable=False, default=dict)
    error_summary_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, onupdate=_now
    )


class StockSignalPrediction(Base):
    """A point-in-time prediction and its later, immutable market outcome."""

    __tablename__ = "stock_signal_predictions"
    __table_args__ = (
        UniqueConstraint("prediction_key", name="uq_stock_signal_predictions_prediction_key"),
        Index("ix_stock_signal_prediction_symbol_date", "symbol", "as_of_date"),
        Index(
            "ix_stock_signal_prediction_scope_symbol_date", "owner_scope", "symbol", "as_of_date"
        ),
        Index("ix_stock_signal_prediction_universe_date", "universe_code", "as_of_date"),
        Index(
            "ix_stock_signal_prediction_outcome_next_date", "outcome_status", "next_trading_date"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    prediction_key: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("stock_signal_runs.id"), nullable=True, index=True
    )
    report_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("stock_analysis_reports.id"), nullable=True, index=True
    )
    owner_scope: Mapped[str] = mapped_column(
        String(80), nullable=False, default="system", index=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", index=True)
    universe_code: Mapped[str] = mapped_column(
        String(32), nullable=False, default="MANUAL", index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    market_type: Mapped[str] = mapped_column(String(32), nullable=False, default="A股")
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    as_of_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    next_trading_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    signal_action: Mapped[SignalAction] = mapped_column(
        String(16), nullable=False, default="WATCH", index=True
    )
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    buy_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    sell_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    watch_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_excess_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    eligibility_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="rejected", index=True
    )
    quality_reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    data_freshness_json: Mapped[JSONMapping] = mapped_column(JSON, nullable=False, default=dict)

    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_snapshot_json: Mapped[JSONMapping] = mapped_column(JSON, nullable=False, default=dict)
    policy_snapshot_json: Mapped[JSONMapping] = mapped_column(JSON, nullable=False, default=dict)
    source_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    outcome_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    outcome_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizon_1d_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizon_5d_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizon_20d_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_1d_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_5d_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_20d_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    excess_1d_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    excess_5d_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    excess_20d_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    buy_is_correct_20d: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sell_is_correct_20d: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, onupdate=_now
    )
