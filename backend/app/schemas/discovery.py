from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


class OpenSourceProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_full_name: str
    repo_url: str
    description: Optional[str] = None
    stars: int
    forks: int
    language: Optional[str] = None
    license: Optional[str] = None
    topics: list[str] = []
    overall_score: float
    status: str
    risk_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ProjectScoreUpdate(BaseModel):
    score_relevance: Optional[float] = None
    score_activity: Optional[float] = None
    score_influence: Optional[float] = None
    score_reproducibility: Optional[float] = None
    score_security: Optional[float] = None
    overall_score: Optional[float] = None
    status: Optional[str] = None
    risk_note: Optional[str] = None


class ProjectReviewUpdate(BaseModel):
    status: Optional[str] = None
    note: Optional[str] = None
    score_relevance: Optional[float] = None
    score_activity: Optional[float] = None
    score_influence: Optional[float] = None
    score_reproducibility: Optional[float] = None
    score_security: Optional[float] = None
    overall_score: Optional[float] = None
    risk_note: Optional[str] = None


class DiscoveryKeywordCreate(BaseModel):
    keyword: str


class WeeklyReportCandidateCreate(BaseModel):
    project_id: int
    week_number: int
    year: int
    notes: Optional[str] = None
    rationale: Optional[str] = None
    editorial_notes: Optional[str] = None


class WeeklyReportCandidateUpdate(BaseModel):
    notes: Optional[str] = None
    rationale: Optional[str] = None
    editorial_notes: Optional[str] = None
    status: Optional[str] = None
    is_selected: Optional[bool] = None


class WeeklyReportCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    week_number: int
    year: int
    notes: Optional[str] = None
    rationale: Optional[str] = None
    editorial_notes: Optional[str] = None
    status: str
    is_selected: bool
    created_at: datetime
