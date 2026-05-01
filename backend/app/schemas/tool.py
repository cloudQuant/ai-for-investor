from pydantic import BaseModel, Field, ConfigDict, field_validator
from datetime import datetime
from typing import Optional, Any


class ToolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: Optional[str] = None
    risk_level: str
    run_mode: str
    source_url: Optional[str] = None
    license: Optional[str] = None
    access_type: str
    config_status: str = "draft"
    is_active: bool

    @field_validator("config_status", mode="before")
    @classmethod
    def default_config_status(cls, value):
        return value or "draft"


class ToolDetailResponse(ToolResponse):
    manifest: Optional[dict[str, Any]] = None
    resource_cost: Optional[str] = None
    usage_limitations: Optional[str] = None
    financial_risk_reminder: Optional[str] = None
    execution_risk_reminder: Optional[str] = None
    created_at: datetime


class ToolManifestCreate(BaseModel):
    name: str
    version: str
    image: Optional[str] = None
    entrypoint: dict[str, Any]
    parameters_schema: dict[str, Any]
    resources: dict[str, Any]
    network: dict[str, Any]
    output: Optional[dict[str, Any]] = None
    security_review: Optional[dict[str, Any]] = None


class ToolManifestUpdate(BaseModel):
    name: Optional[str] = None
    version: Optional[str] = None
    image: Optional[str] = None
    entrypoint: Optional[dict[str, Any]] = None
    parameters_schema: Optional[dict[str, Any]] = None
    resources: Optional[dict[str, Any]] = None
    network: Optional[dict[str, Any]] = None
    output: Optional[dict[str, Any]] = None
    security_review: Optional[dict[str, Any]] = None


class ToolConfigCreate(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None
    risk_level: str = "low"
    run_mode: str = "external"
    source_url: Optional[str] = None
    license: Optional[str] = None
    manifest_id: Optional[int] = None
    resource_cost: Optional[str] = None
    usage_limitations: Optional[str] = None
    financial_risk_reminder: Optional[str] = None
    execution_risk_reminder: Optional[str] = None


class ToolConfigUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    risk_level: Optional[str] = None
    run_mode: Optional[str] = None
    source_url: Optional[str] = None
    license: Optional[str] = None
    manifest_id: Optional[int] = None
    resource_cost: Optional[str] = None
    usage_limitations: Optional[str] = None
    financial_risk_reminder: Optional[str] = None
    execution_risk_reminder: Optional[str] = None


class ToolJobCreate(BaseModel):
    tool_id: int
    parameters: dict[str, Any] = {}


class ToolJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    tool_id: int
    user_id: int
    parameters: dict[str, Any]
    status: str
    result_summary: Optional[str] = None
    error_message: Optional[str] = None
    queued_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ToolManifestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: str
    image: Optional[str] = None
    entrypoint: Optional[dict[str, Any]] = None
    parameters_schema: Optional[dict[str, Any]] = None
    resources: Optional[dict[str, Any]] = None
    network: Optional[dict[str, Any]] = None
    output: Optional[dict[str, Any]] = None
    security_review: Optional[dict[str, Any]] = None
