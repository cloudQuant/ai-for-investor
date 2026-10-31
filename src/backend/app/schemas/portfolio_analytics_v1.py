"""Strict HTTP payloads for persisted, user-supplied offline analytics V1."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_VERSIONED_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*-v[1-9][0-9]*$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,11}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_FACTS_BYTES = 768_000


def _reference(value: str) -> str:
    if _REFERENCE_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid reference")
    return value


def _versioned_reference(value: str) -> str:
    if _VERSIONED_REFERENCE_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid versioned reference")
    return value


def _currency(value: str) -> str:
    if _CURRENCY_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid currency")
    return value


def _date_text(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("date must be an ISO calendar date") from error
    if parsed.isoformat() != value:
        raise ValueError("date must be canonical ISO calendar date")
    return value


def _decimal_text(value: str) -> str:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError("decimal text is invalid") from error
    if not parsed.is_finite():
        raise ValueError("decimal text must be finite")
    parts = parsed.as_tuple()
    # is_finite() above has already excluded the NaN/Infinity tuples, whose
    # exponent is a sentinel string instead of an int.
    exponent = cast(int, parts.exponent)
    if len(parts.digits) > 64 or abs(exponent) > 36:
        raise ValueError("decimal text exceeds the supported range")
    canonical = format(parsed, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical in {"", "-0"}:
        canonical = "0"
    if canonical != value:
        raise ValueError("decimal text must use canonical fixed-point form")
    return value


def _unique_sorted(values: list[str]) -> list[str]:
    if values != sorted(values) or len(values) != len(set(values)):
        raise ValueError("references must be unique and sorted")
    return values


Reference = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128), AfterValidator(_reference)]
VersionedReference = Annotated[
    str,
    StringConstraints(strict=True, min_length=3, max_length=128),
    AfterValidator(_versioned_reference),
]
Currency = Annotated[
    str,
    StringConstraints(strict=True, min_length=2, max_length=12),
    AfterValidator(_currency),
]
IsoDate = Annotated[
    str,
    StringConstraints(strict=True, min_length=10, max_length=10),
    AfterValidator(_date_text),
]
DecimalText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=128),
    AfterValidator(_decimal_text),
]
Sha256 = Annotated[
    str,
    StringConstraints(strict=True, min_length=64, max_length=64),
    Field(pattern=r"^[0-9a-f]{64}$"),
]


class _StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PortfolioAnalyticsMembershipV1(_StrictPayload):
    content_sha256: Sha256
    effective_end_date_utc_exclusive: IsoDate | None
    effective_start_date_utc: IsoDate
    member_refs: list[Reference] = Field(min_length=1, max_length=256)
    membership_version: int = Field(gt=0, le=2_147_483_647)
    portfolio_ref: Reference
    source_ref: Reference
    source_version: VersionedReference

    @model_validator(mode="after")
    def validate_members(self) -> PortfolioAnalyticsMembershipV1:
        _unique_sorted(self.member_refs)
        start = date.fromisoformat(self.effective_start_date_utc)
        end = (
            date.fromisoformat(self.effective_end_date_utc_exclusive)
            if self.effective_end_date_utc_exclusive is not None
            else None
        )
        if end is not None and end <= start:
            raise ValueError("membership interval is invalid")
        document = {
            "effective_end_date_utc_exclusive": self.effective_end_date_utc_exclusive,
            "effective_start_date_utc": self.effective_start_date_utc,
            "member_refs": self.member_refs,
            "membership_version": self.membership_version,
            "portfolio_ref": self.portfolio_ref,
            "source_ref": self.source_ref,
            "source_version": self.source_version,
            "version": 1,
        }
        digest = hashlib.sha256(_canonical_json(document)).hexdigest()
        if digest != self.content_sha256:
            raise ValueError("membership facts digest does not match")
        return self


class PortfolioAnalyticsCashBalanceV1(_StrictPayload):
    amount: DecimalText
    balance_ref: Reference
    currency: Currency
    member_ref: Reference


class PortfolioAnalyticsSpotPositionV1(_StrictPayload):
    base_currency: Currency
    instrument_metadata_ref: Reference
    instrument_metadata_version: VersionedReference
    instrument_ref: Reference
    member_ref: Reference
    position_ref: Reference
    price_as_of_ns: int = Field(gt=0)
    price_observation_ref: Reference
    price_source_cursor: Reference
    price_source_generation: Reference
    price_source_ref: Reference
    price_source_version: VersionedReference
    price_unit: Literal["QUOTE_PER_BASE"]
    price_valid_until_ns: int = Field(gt=0)
    product_kind: Reference
    quantity: DecimalText
    quote_currency: Currency
    unit_price: DecimalText


class PortfolioAnalyticsValuationPointV1(_StrictPayload):
    as_of_ns: int = Field(gt=0)
    cash_balances: list[PortfolioAnalyticsCashBalanceV1] = Field(max_length=10_000)
    covered_asset_classes: list[Reference] = Field(max_length=8)
    covered_member_refs: list[Reference] = Field(max_length=256)
    coverage_complete: bool
    snapshot_ref: Reference
    source_cursor: Reference
    source_generation: Reference
    spot_positions: list[PortfolioAnalyticsSpotPositionV1] = Field(max_length=10_000)
    valuation_cut_policy: Literal["UTC_CALENDAR_DAY_END_V1"]
    valuation_date_utc: IsoDate

    @model_validator(mode="after")
    def validate_canonical_rows(self) -> PortfolioAnalyticsValuationPointV1:
        _unique_sorted(self.covered_member_refs)
        _unique_sorted(self.covered_asset_classes)
        for rows, key in (
            (self.cash_balances, "balance_ref"),
            (self.spot_positions, "position_ref"),
        ):
            refs = [getattr(row, key) for row in rows]
            _unique_sorted(refs)
        return self


class PortfolioAnalyticsExternalFlowV1(_StrictPayload):
    amount: DecimalText
    currency: Currency
    direction: Literal["CONTRIBUTION", "WITHDRAWAL"]
    effective_at_ns: int = Field(gt=0)
    flow_ref: Reference
    source_cursor: Reference
    source_generation: Reference
    source_ref: Reference
    source_version: VersionedReference


class PortfolioAnalyticsFlowCoverageV1(_StrictPayload):
    complete: bool
    end_as_of_ns: int = Field(gt=0)
    end_cursor: Reference
    source_generation: Reference
    source_ref: Reference
    source_version: VersionedReference
    start_as_of_ns: int = Field(gt=0)
    start_cursor: Reference


class PortfolioAnalyticsFxObservationV1(_StrictPayload):
    as_of_ns: int = Field(gt=0)
    base_currency: Currency
    direction: Literal["BASE_TO_QUOTE"]
    observation_ref: Reference
    quote_currency: Currency
    rate: DecimalText
    rate_unit: Literal["QUOTE_PER_BASE"]
    source_cursor: Reference
    source_generation: Reference
    source_ref: Reference
    source_version: VersionedReference
    valid_until_ns: int = Field(gt=0)


class PortfolioAnalyticsFactsV1(_StrictPayload):
    beginning: PortfolioAnalyticsValuationPointV1
    ending: PortfolioAnalyticsValuationPointV1
    external_flows: list[PortfolioAnalyticsExternalFlowV1] = Field(max_length=10_000)
    facts_snapshot_ref: Reference
    flow_coverage: PortfolioAnalyticsFlowCoverageV1
    fx_observations: list[PortfolioAnalyticsFxObservationV1] = Field(max_length=10_000)
    membership: PortfolioAnalyticsMembershipV1
    portfolio_ref: Reference
    source_generation: Reference
    source_mode: Literal["research", "imported", "paper"]
    source_ref: Reference
    source_version: VersionedReference
    valuation_basis_ref: Literal["cash_spot_after_booked_internal_flows_v1"]
    version: Literal[1]

    @model_validator(mode="after")
    def validate_source_and_canonical_rows(self) -> PortfolioAnalyticsFactsV1:
        if self.portfolio_ref != self.membership.portfolio_ref:
            raise ValueError("facts and membership portfolios must match")
        _unique_sorted([row.flow_ref for row in self.external_flows])
        _unique_sorted([row.observation_ref for row in self.fx_observations])
        return self


class PortfolioAnalyticsDatasetCreateV1(_StrictPayload):
    """Persist one immutable dataset explicitly labeled as user-supplied offline data."""

    idempotency_key: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
    source_trust: Literal["USER_SUPPLIED_OFFLINE"]
    facts: PortfolioAnalyticsFactsV1

    @model_validator(mode="after")
    def validate_idempotency_key(self) -> PortfolioAnalyticsDatasetCreateV1:
        if self.idempotency_key != self.idempotency_key.strip() or not self.idempotency_key.isprintable():
            raise ValueError("idempotency key is invalid")
        if len(_canonical_json(self.facts.model_dump(mode="json"))) > _MAX_FACTS_BYTES:
            raise ValueError("facts exceed the offline dataset size limit")
        return self


class PortfolioAnalyticsV1TaskSelection(_StrictPayload):
    period_end_date_utc: IsoDate
    period_start_date_utc: IsoDate
    reporting_currency: Currency

    @model_validator(mode="after")
    def validate_period(self) -> PortfolioAnalyticsV1TaskSelection:
        if date.fromisoformat(self.period_end_date_utc) <= date.fromisoformat(
            self.period_start_date_utc
        ):
            raise ValueError("period end must be after period start")
        return self


class PortfolioAnalyticsTaskCreateV1(_StrictPayload):
    """Select an owned persisted dataset; financial facts never come from this request."""

    dataset_ref: Reference
    idempotency_key: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
    request: PortfolioAnalyticsV1TaskSelection

    @model_validator(mode="after")
    def validate_idempotency_key(self) -> PortfolioAnalyticsTaskCreateV1:
        if self.idempotency_key != self.idempotency_key.strip() or not self.idempotency_key.isprintable():
            raise ValueError("idempotency key is invalid")
        return self


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
