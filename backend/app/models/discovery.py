from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, Float, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.db.mysql import Base


class DiscoveryKeyword(Base):
    __tablename__ = "discovery_keywords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword = Column(String(100), nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class OpenSourceProject(Base):
    __tablename__ = "open_source_projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_full_name = Column(String(255), unique=True, nullable=False, index=True)
    repo_url = Column(String(500), nullable=False)
    description = Column(Text)
    stars = Column(Integer, default=0)
    forks = Column(Integer, default=0)
    language = Column(String(50))
    license = Column(String(100))
    topics = Column(JSON)
    latest_commit_at = Column(DateTime)
    latest_release_at = Column(DateTime)
    readme_summary = Column(Text)
    score_relevance = Column(Float, default=0.0)
    score_activity = Column(Float, default=0.0)
    score_influence = Column(Float, default=0.0)
    score_reproducibility = Column(Float, default=0.0)
    score_security = Column(Float, default=0.0)
    overall_score = Column(Float, default=0.0)
    status = Column(String(20), default="pending", index=True)
    risk_note = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime, nullable=True)

    candidates = relationship("WeeklyReportCandidate", back_populates="project")


class ProjectSnapshot(Base):
    __tablename__ = "project_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("open_source_projects.id", ondelete="SET NULL"), nullable=True, index=True)
    keyword_id = Column(Integer, ForeignKey("discovery_keywords.id", ondelete="SET NULL"), nullable=True, index=True)
    repo_full_name = Column(String(255), nullable=True, index=True)
    repo_url = Column(String(500), nullable=True)
    description = Column(Text)
    stars = Column(Integer, default=0)
    forks = Column(Integer, default=0)
    language = Column(String(50))
    license_signal = Column(String(100))
    topics = Column(JSON)
    readme_summary = Column(Text)
    latest_commit_at = Column(DateTime)
    latest_release_at = Column(DateTime)
    raw_payload = Column(JSON)
    status = Column(String(20), default="success", index=True)
    error_detail = Column(JSON)
    retry_count = Column(Integer, default=0)
    collected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class ProjectScore(Base):
    __tablename__ = "project_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("open_source_projects.id", ondelete="CASCADE"), nullable=False)
    scorer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    score_relevance = Column(Float)
    score_activity = Column(Float)
    score_influence = Column(Float)
    score_reproducibility = Column(Float)
    score_security = Column(Float)
    overall_score = Column(Float)
    note = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WeeklyReportCandidate(Base):
    __tablename__ = "weekly_report_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("open_source_projects.id", ondelete="CASCADE"), nullable=False)
    added_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    week_number = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    notes = Column(Text)
    rationale = Column(Text)
    editorial_notes = Column(Text)
    status = Column(String(20), default="nominated", index=True)
    is_selected = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("OpenSourceProject", back_populates="candidates")
