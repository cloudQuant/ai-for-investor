"""Strict contracts for the operator-facing capability ledger surface.

These DTOs deliberately carry no descriptor or evidence hash.  A caller names
the capability and the lifecycle stage it wants recorded; the server derives
both digests from the live reviewed policy and the durable receipt plane, so an
operator cannot pre-supply a hash that the checker would then have to trust.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CapabilityLedgerStage = Literal[
    "declared",
    "installed",
    "verified",
    "authorized",
    "retired",
]

_DURABLE_STAGES = frozenset({"verified", "authorized"})


class _StrictLedgerModel(BaseModel):
    """Base model that rejects misspelled operator fields."""

    model_config = ConfigDict(extra="forbid")


class MarketDataCapabilityLedgerRecordRequest(_StrictLedgerModel):
    """One append-only lifecycle attestation request.

    ``effective_until`` is required because an open-ended activation window
    cannot later be superseded without creating two current records, which the
    durable reader reports as ``CAPABILITY_LEDGER_AMBIGUOUS``.  An immediate
    kill remains the environment setting, exactly as the reader documents.
    """

    capability_id: str = Field(min_length=1, max_length=192)
    stage: CapabilityLedgerStage
    effective_from: datetime | None = None
    effective_until: datetime
    verified_until: datetime | None = None
    authorized_until: datetime | None = None

    @field_validator("capability_id")
    @classmethod
    def normalize_capability_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("capability_id must not be blank")
        return normalized

    @field_validator("effective_from", "effective_until", "verified_until", "authorized_until")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("capability ledger timestamps must carry an offset")
        return value

    @model_validator(mode="after")
    def validate_stage_shape(self) -> MarketDataCapabilityLedgerRecordRequest:
        if self.effective_from is not None and self.effective_until <= self.effective_from:
            raise ValueError("effective_until must be after effective_from")
        if self.stage in _DURABLE_STAGES:
            required = self.verified_until if self.stage == "verified" else self.authorized_until
            if required is None:
                raise ValueError(f"{self.stage} stage requires an attestation expiry")
        if self.stage in {"declared", "installed", "retired"}:
            if self.verified_until is not None or self.authorized_until is not None:
                raise ValueError(f"{self.stage} stage cannot carry an attestation expiry")
        if self.stage == "authorized" and self.verified_until is not None:
            raise ValueError("authorized stage carries forward the recorded verification")
        return self


class MarketDataCapabilityEvidenceRouteResponse(_StrictLedgerModel):
    """Per-route durable artifact count behind one derived evidence digest."""

    capability_id: str
    route_id: str
    artifact_count: int


class MarketDataCapabilityEvidenceResponse(_StrictLedgerModel):
    """Preview or re-verification result for one capability's evidence plane."""

    capability_id: str
    descriptor_sha256: str
    evidence_kind: str
    evidence_sha256: str
    artifact_count: int
    window_end: datetime
    routes: tuple[MarketDataCapabilityEvidenceRouteResponse, ...] = ()
    matches_stored: bool | None = None
    reason_code: str | None = None


class MarketDataCapabilityLedgerReceiptResponse(_StrictLedgerModel):
    """The append receipt an operator keeps as proof of their own decision."""

    ledger_record_id: str
    capability_id: str
    revision: int
    stage: CapabilityLedgerStage
    descriptor_sha256: str
    evidence_sha256: str
    evidence_kind: str
    artifact_count: int
    declared_capability: bool
    installed_capability: bool
    verified_capability: bool
    authorized_capability: bool
    effective_from: datetime
    effective_until: datetime
    verified_at: datetime | None = None
    verified_until: datetime | None = None
    authorized_at: datetime | None = None
    authorized_until: datetime | None = None
    actor_user_id: str
    receipt_sha256: str
