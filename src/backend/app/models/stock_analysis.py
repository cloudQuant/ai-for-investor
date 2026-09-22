"""ORM models for native stock analysis."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TypeAlias, TypedDict

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
JSONMapping: TypeAlias = dict[str, JSONValue]


class StockAnalysisStepEvent(TypedDict):
    progress: int
    status: str
    step: str
    message: str
    timestamp: str


class StockAnalysisTaskModel(Base):
    """Persisted stock analysis task lifecycle."""

    __tablename__ = "stock_analysis_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    assistant_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="ai_assistant")
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    market_type: Mapped[str] = mapped_column(String(32), nullable=False, default="A股")
    analysis_date: Mapped[str] = mapped_column(String(32), nullable=False)
    research_depth: Mapped[str] = mapped_column(String(32), nullable=False, default="标准")
    selected_modules: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameters_json: Mapped[JSONMapping | None] = mapped_column(JSON, nullable=True)
    step_events_json: Mapped[list[StockAnalysisStepEvent] | None] = mapped_column(
        JSON, nullable=True
    )
    data_quality_json: Mapped[JSONMapping | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=_now, onupdate=_now
    )


class StockAnalysisReportModel(Base):
    """Persisted normalized stock analysis report."""

    __tablename__ = "stock_analysis_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stock_analysis_tasks.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    market_type: Mapped[str] = mapped_column(String(32), nullable=False, default="A股")
    analysis_date: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_label: Mapped[str] = mapped_column(String(20), nullable=False, default="观望")
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="中等")
    technical_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fundamental_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    news_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_snapshot_json: Mapped[JSONMapping | None] = mapped_column(JSON, nullable=True)
    data_quality_json: Mapped[JSONMapping | None] = mapped_column(JSON, nullable=True)
    report_json: Mapped[JSONMapping] = mapped_column(JSON, nullable=False)
    markdown_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=_now)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=_now, onupdate=_now
    )


class StockAnalysisExportModel(Base):
    """Persisted stock analysis export metadata."""

    __tablename__ = "stock_analysis_exports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    report_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stock_analysis_reports.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=_now)
