"""Persistent coordination records for AkShare scheduled runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AkshareTaskRunClaim(Base):
    """One idempotent business-period claim and its current fencing lease."""

    __tablename__ = "ak_task_run_claims"

    claim_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    script_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    period_key: Mapped[str] = mapped_column(String(255), nullable=False)
    parameter_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fencing_token: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    execution_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class AkshareSchedulerControl(Base):
    """A row lock used to serialize shared concurrency and source-rate claims."""

    __tablename__ = "ak_scheduler_control"

    control_id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    source_next_allowed_at: Mapped[dict[str, str]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
