"""Schemas for native stock analysis."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

StockAnalysisStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
StockAnalysisExportFormat = Literal["markdown", "html", "docx", "pdf"]
StockAnalysisModule = Literal["market", "social", "news", "fundamentals", "risk"]


def _default_stock_analysis_modules() -> list[StockAnalysisModule]:
    return ["market", "social", "news", "fundamentals", "risk"]


def _default_stock_analysis_export_formats() -> list[StockAnalysisExportFormat]:
    return ["markdown", "html", "docx", "pdf"]


class StockAnalysisSinaFzbSnapshotSelection(BaseModel):
    """One explicit OpenData publication/capture selector for the requested instrument."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(pattern=r"^[0-9]{6}\.(?:SH|SZ)$")
    publication_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    capture_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class StockAnalysisSinaLrbSnapshotSelection(BaseModel):
    """One explicit OpenData publication/capture selector for Sina LRB evidence."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(pattern=r"^[0-9]{6}\.(?:SH|SZ)$")
    publication_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    capture_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class StockAnalysisParams(BaseModel):
    """User-facing stock analysis parameters."""

    symbol: str = Field(..., min_length=1, max_length=32)
    market_type: str = Field("A股", max_length=32)
    analysis_date: date | None = None
    research_depth: str = Field("标准", max_length=32)
    selected_modules: list[StockAnalysisModule] = Field(
        default_factory=_default_stock_analysis_modules
    )
    include_sentiment: bool = True
    include_risk: bool = True
    language: str = Field("zh-CN", max_length=16)
    model_id: str | None = Field(None, max_length=200)
    opendata_sina_fzb_snapshot: StockAnalysisSinaFzbSnapshotSelection | None = None
    opendata_sina_lrb_snapshot: StockAnalysisSinaLrbSnapshotSelection | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = " ".join(str(value or "").split()).upper()
        if not normalized:
            raise ValueError("symbol must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_sina_snapshot_instrument_scope(self) -> StockAnalysisParams:
        fzb_selection = self.opendata_sina_fzb_snapshot
        lrb_selection = self.opendata_sina_lrb_snapshot
        if fzb_selection is not None and lrb_selection is not None:
            raise ValueError("Sina FZB and LRB snapshots cannot be selected together")

        selection = fzb_selection or lrb_selection
        if selection is None:
            return self
        if self.market_type != "A股":
            raise ValueError("Sina financial snapshot selection requires market_type='A股'")

        symbol = self.symbol.strip().upper()
        if "." in symbol:
            if symbol.count(".") != 1:
                raise ValueError("Sina snapshot symbol must identify one SH/SZ instrument")
            code, exchange = symbol.split(".", 1)
        elif symbol.startswith(("SH", "SZ")):
            exchange, code = symbol[:2], symbol[2:]
        else:
            code = symbol
            if code.startswith("6"):
                exchange = "SH"
            elif code.startswith(("0", "3")):
                exchange = "SZ"
            else:
                raise ValueError("Sina snapshot requires an explicit SH/SZ A-share symbol")

        if selection.instrument_id != f"{code}.{exchange}":
            raise ValueError("Sina snapshot instrument_id must match the analysis symbol")
        return self


class StockAnalysisTaskCard(BaseModel):
    """Compact task payload embedded in AI chat messages."""

    task_id: str
    symbol: str
    status: StockAnalysisStatus
    progress: int = Field(ge=0, le=100)
    current_step: str | None = None
    message: str | None = None


class StockAnalysisReportCard(BaseModel):
    """Compact report payload embedded in AI chat messages."""

    report_id: str
    symbol: str
    summary: str
    decision_label: str
    risk_level: str
    confidence_score: float | None = None
    export_formats: list[StockAnalysisExportFormat] = Field(
        default_factory=_default_stock_analysis_export_formats
    )


class StockAnalysisTaskResponse(BaseModel):
    """Task detail response."""

    task_id: str
    status: StockAnalysisStatus
    symbol: str
    symbol_name: str | None = None
    market_type: str
    analysis_date: str
    research_depth: str
    selected_modules: list[str]
    progress: int
    current_step: str | None = None
    message: str | None = None
    error_message: str | None = None
    report_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class StockAnalysisResultResponse(BaseModel):
    """Task result response."""

    task_id: str
    report_id: str | None = None
    status: StockAnalysisStatus
    report: dict[str, Any] | None = None


class StockAnalysisExportResponse(BaseModel):
    """Stored export metadata."""

    id: str
    report_id: str
    format: StockAnalysisExportFormat
    file_name: str
    content_type: str
    file_size: int
    status: str
    created_at: datetime


class StockAnalysisSaveToKnowledgeBaseRequest(BaseModel):
    """Persist a stock analysis report as a knowledge base document."""

    knowledge_base_id: str = Field(..., min_length=1)
    title: str | None = Field(None, min_length=1, max_length=500)
    parent_id: str | None = None


class StockAnalysisSaveToKnowledgeBaseResponse(BaseModel):
    """Knowledge base document created from a stock analysis report."""

    document_id: str
    knowledge_base_id: str
    report_id: str
    title: str
    content_type: str
    status: str
    index_status: str
    created_at: datetime


class StockAnalysisSaveToWorkspaceRequest(BaseModel):
    """Persist a stock analysis report reference into a research workspace."""

    workspace_id: str = Field(..., min_length=1)
    title: str | None = Field(None, min_length=1, max_length=500)


class StockAnalysisSaveToWorkspaceResponse(BaseModel):
    """Workspace report reference created from a stock analysis report."""

    workspace_id: str
    report_id: str
    task_id: str
    title: str
    symbol: str
    decision_label: str
    risk_level: str
    saved_at: datetime
