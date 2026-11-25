"""Canonical isolation proof for discovery and sealed-holdout snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, cast

from app.models.ai_research_v2 import ResearchDatasetSnapshot
from app.services.research.canonical import content_hash

HOLDOUT_ISOLATION_SCHEMA = "holdout-isolation-manifest-v1"
DEFAULT_LABEL_HORIZON_DAYS = 1


@dataclass(frozen=True, slots=True)
class HoldoutIsolationManifest:
    discovery_universe: tuple[str, ...]
    sealed_universe: tuple[str, ...]
    discovery_start: datetime
    discovery_end: datetime
    sealed_start: datetime
    sealed_end: datetime
    discovery_content_hash: str
    sealed_content_hash: str
    discovery_identity_hash: str
    sealed_identity_hash: str
    discovery_object_identity: tuple[str, str, str]
    sealed_object_identity: tuple[str, str, str]
    candidate_frozen_at: datetime
    label_horizon_days: int
    label_mature_at: datetime
    manifest_hash: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": HOLDOUT_ISOLATION_SCHEMA,
            "discovery_universe": list(self.discovery_universe),
            "sealed_universe": list(self.sealed_universe),
            "discovery_start": self.discovery_start.isoformat(),
            "discovery_end": self.discovery_end.isoformat(),
            "sealed_start": self.sealed_start.isoformat(),
            "sealed_end": self.sealed_end.isoformat(),
            "discovery_content_hash": self.discovery_content_hash,
            "sealed_content_hash": self.sealed_content_hash,
            "discovery_identity_hash": self.discovery_identity_hash,
            "sealed_identity_hash": self.sealed_identity_hash,
            "discovery_object_identity": list(self.discovery_object_identity),
            "sealed_object_identity": list(self.sealed_object_identity),
            "candidate_frozen_at": self.candidate_frozen_at.isoformat(),
            "label_horizon_days": self.label_horizon_days,
            "label_mature_at": self.label_mature_at.isoformat(),
        }


def build_holdout_isolation_manifest(
    *,
    discovery: ResearchDatasetSnapshot,
    sealed: ResearchDatasetSnapshot,
    candidate_frozen_at: datetime | None,
    label_horizon_days: int = DEFAULT_LABEL_HORIZON_DAYS,
) -> HoldoutIsolationManifest:
    """Validate and hash all non-overlap facts from immutable snapshot metadata."""

    if (
        discovery.partition_kind != "DISCOVERY"
        or sealed.partition_kind != "SEALED_HOLDOUT"
        or type(label_horizon_days) is not int
        or label_horizon_days < 1
    ):
        raise ValueError("HOLDOUT_ISOLATION_METADATA_INVALID")

    discovery_universe = _universe(discovery.instrument_manifest)
    sealed_universe = _universe(sealed.instrument_manifest)
    discovery_start, discovery_end = _date_range(discovery.split_manifest)
    sealed_start, sealed_end = _date_range(sealed.split_manifest)
    discovery_object = _object_identity(discovery)
    sealed_object = _object_identity(sealed)
    discovery_content = _required_hash(discovery.content_hash)
    sealed_content = _required_hash(sealed.content_hash)
    discovery_identity = _required_hash(discovery.snapshot_identity_hash)
    sealed_identity = _required_hash(sealed.snapshot_identity_hash)

    if set(discovery_universe).intersection(sealed_universe):
        raise ValueError("HOLDOUT_ISOLATION_UNIVERSE_OVERLAP")
    if sealed_start <= discovery_end:
        raise ValueError("HOLDOUT_ISOLATION_TIME_OVERLAP")
    if discovery_object == sealed_object or discovery_identity == sealed_identity:
        raise ValueError("HOLDOUT_ISOLATION_OBJECT_IDENTITY_REUSED")
    if candidate_frozen_at is None:
        raise ValueError("HOLDOUT_ISOLATION_MANIFEST_REQUIRED")
    frozen_at = _as_utc(candidate_frozen_at)
    mature_at = frozen_at + timedelta(days=label_horizon_days)
    if sealed_start <= mature_at:
        raise ValueError("HOLDOUT_SEALED_START_BEFORE_FREEZE_MATURITY")
    if sealed_end < sealed_start or _as_utc(sealed.point_in_time_cutoff) < sealed_end:
        raise ValueError("HOLDOUT_ISOLATION_METADATA_INVALID")

    manifest = HoldoutIsolationManifest(
        discovery_universe=discovery_universe,
        sealed_universe=sealed_universe,
        discovery_start=discovery_start,
        discovery_end=discovery_end,
        sealed_start=sealed_start,
        sealed_end=sealed_end,
        discovery_content_hash=discovery_content,
        sealed_content_hash=sealed_content,
        discovery_identity_hash=discovery_identity,
        sealed_identity_hash=sealed_identity,
        discovery_object_identity=discovery_object,
        sealed_object_identity=sealed_object,
        candidate_frozen_at=frozen_at,
        label_horizon_days=label_horizon_days,
        label_mature_at=mature_at,
        manifest_hash="",
    )
    return replace(manifest, manifest_hash=content_hash(manifest.to_mapping()))


def _universe(value: Mapping[str, Any]) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        raise ValueError("HOLDOUT_ISOLATION_MANIFEST_REQUIRED")
    symbols = value.get("symbols")
    if (
        not isinstance(symbols, list)
        or not symbols
        or any(not isinstance(symbol, str) or not symbol.strip() for symbol in symbols)
    ):
        raise ValueError("HOLDOUT_ISOLATION_MANIFEST_REQUIRED")
    return tuple(sorted(set(symbols)))


def _date_range(value: Mapping[str, Any]) -> tuple[datetime, datetime]:
    if not isinstance(value, Mapping) or "start" not in value or "end" not in value:
        raise ValueError("HOLDOUT_ISOLATION_MANIFEST_REQUIRED")
    start = _parse_date(value["start"])
    end = _parse_date(value["end"])
    if end < start:
        raise ValueError("HOLDOUT_ISOLATION_METADATA_INVALID")
    return start, end


def _parse_date(value: object) -> datetime:
    try:
        if isinstance(value, datetime):
            return _as_utc(value)
        if isinstance(value, str):
            return datetime.combine(date.fromisoformat(value), datetime.min.time(), timezone.utc)
    except (TypeError, ValueError):
        pass
    raise ValueError("HOLDOUT_ISOLATION_MANIFEST_REQUIRED")


def _object_identity(snapshot: ResearchDatasetSnapshot) -> tuple[str, str, str]:
    values = (snapshot.object_logical_id, snapshot.object_version, snapshot.object_digest)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("HOLDOUT_ISOLATION_MANIFEST_REQUIRED")
    return cast(tuple[str, str, str], values)


def _required_hash(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("HOLDOUT_ISOLATION_MANIFEST_REQUIRED")
    return value


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
