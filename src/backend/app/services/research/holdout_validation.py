"""Holdout finalization scalar validation."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from app.db.persistence_boundaries import is_holdout_sha256, stored_utc


def require_generation(value: int) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("HOLDOUT_FINALIZE_LEASE_STALE")


def lease_token_hash(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("HOLDOUT_FINALIZE_LEASE_STALE")
    return sha256(value.encode()).hexdigest()


def required_time(value: datetime | None) -> datetime:
    if value is None:
        raise ValueError("HOLDOUT_FINALIZE_AUTHORITY_INCONSISTENT")
    return stored_utc(value)


def required_identity(value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("HOLDOUT_FINALIZE_EXECUTION_INVALID")
    return value


def required_hash(value: str | None) -> str:
    if not isinstance(value, str) or not is_holdout_sha256(value):
        raise ValueError("HOLDOUT_FINALIZE_EXECUTION_INVALID")
    return value


def safe_reason_code(exc: ValueError) -> str:
    reason = str(exc)
    if reason.startswith(("HOLDOUT_", "PROMOTION_", "DATASET_")):
        return reason[:128]
    return "HOLDOUT_FINALIZE_REJECTED"
