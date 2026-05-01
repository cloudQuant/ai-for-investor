from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, JSON, Float, Index
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum

from app.db.mysql import Base


class ToolRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class ToolRunMode(str, enum.Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    DOCUMENT = "document"


class ToolJobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class Tool(Base):
    __tablename__ = "tools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text)
    risk_level = Column(String(20), default=ToolRiskLevel.LOW.value)
    run_mode = Column(String(20), default=ToolRunMode.EXTERNAL.value)
    source_url = Column(String(500))
    license = Column(String(50))
    resource_cost = Column(String(255))
    usage_limitations = Column(Text)
    financial_risk_reminder = Column(Text)
    execution_risk_reminder = Column(Text)
    manifest_id = Column(Integer, ForeignKey("tool_manifests.id"), nullable=True)
    config_status = Column(String(20), default="draft", index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    manifest = relationship("ToolManifest", back_populates="tool")
    jobs = relationship("ToolJob", back_populates="tool")

    @property
    def access_type(self):
        if self.run_mode == ToolRunMode.INTERNAL.value:
            return "runnable_demo"
        if self.run_mode == ToolRunMode.DOCUMENT.value:
            return "documentation_only"
        return "external_demo"


class ToolManifest(Base):
    __tablename__ = "tool_manifests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    version = Column(String(20), nullable=False)
    image = Column(String(500))
    entrypoint = Column(JSON)
    parameters_schema = Column(JSON)
    resources = Column(JSON)
    network = Column(JSON)
    output = Column(JSON)
    security_review = Column(JSON)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    tool = relationship("Tool", back_populates="manifest", uselist=False)


class ToolJob(Base):
    __tablename__ = "tool_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(50), unique=True, nullable=False, index=True)
    tool_id = Column(Integer, ForeignKey("tools.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    parameters = Column(JSON)
    status = Column(String(20), default=ToolJobStatus.QUEUED.value, index=True)
    result_summary = Column(Text)
    error_message = Column(Text)
    queued_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_user_created", "user_id", "created_at"),
    )

    tool = relationship("Tool", back_populates="jobs")
    user = relationship("User", back_populates="tool_jobs")
