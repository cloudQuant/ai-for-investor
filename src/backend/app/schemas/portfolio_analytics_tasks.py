"""Strict HTTP envelope for offline portfolio analytics V2 task requests."""

from __future__ import annotations

import json
import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_FACTS_KEYS = frozenset(
    {
        "facts_snapshot_ref",
        "loss_history",
        "nav_history",
        "portfolio_ref",
        "scenario",
        "source_generation",
        "source_mode",
        "source_ref",
        "source_version",
        "spot",
        "version",
    }
)
_REQUEST_KEYS = frozenset(
    {
        "confidence",
        "loss_horizon_ref",
        "portfolio_ref",
        "reporting_currency",
        "scenario_ref",
        "scenario_version",
        "version",
    }
)
_MAX_INPUT_BYTES = 67_108_864


class PortfolioAnalyticsTaskCreate(BaseModel):
    """One immutable supplied-facts snapshot and one V2 calculation request.

    The application owns the membership version and idempotency association;
    neither is inserted into the Risk V2 request DTO.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    idempotency_key: str = Field(min_length=1, max_length=128)
    facts: dict[str, Any]
    request: dict[str, Any]

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        if value != value.strip() or not value.isprintable():
            raise ValueError("invalid idempotency key")
        return value

    @field_validator("facts")
    @classmethod
    def validate_facts_shape(cls, value: dict[str, Any]) -> dict[str, Any]:
        if (
            type(value) is not dict
            or set(value) != _FACTS_KEYS
            or type(value.get("version")) is not int
            or value["version"] != 2
        ):
            raise ValueError("facts must match the exact V2 top-level schema")
        _validate_json_value(value)
        if len(_canonical_json(value)) > _MAX_INPUT_BYTES:
            raise ValueError("facts exceed the maximum supported input size")
        return value

    @field_validator("request")
    @classmethod
    def validate_request_shape(cls, value: dict[str, Any]) -> dict[str, Any]:
        if (
            type(value) is not dict
            or set(value) != _REQUEST_KEYS
            or type(value.get("version")) is not int
            or value["version"] != 2
        ):
            raise ValueError("request must match the exact V2 top-level schema")
        _validate_json_value(value)
        return value

    @model_validator(mode="after")
    def validate_cross_references(self) -> PortfolioAnalyticsTaskCreate:
        facts = self.facts
        request = self.request
        scenario = facts.get("scenario")
        losses = facts.get("loss_history")
        if type(scenario) is not dict or type(losses) is not dict:
            raise ValueError("facts datasets must be objects")
        if facts.get("portfolio_ref") != request.get("portfolio_ref"):
            raise ValueError("facts and request portfolio references must match")
        if request.get("loss_horizon_ref") != losses.get("horizon_ref"):
            raise ValueError("request horizon must identify the supplied loss dataset")
        if (
            request.get("scenario_ref") != scenario.get("scenario_ref")
            or request.get("scenario_version") != scenario.get("scenario_version")
        ):
            raise ValueError("request scenario must identify the supplied scenario dataset")
        if type(request.get("confidence")) is not str:
            raise ValueError("confidence must be a decimal string")
        return self


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("input must be finite JSON data") from error


def _validate_json_value(value: object, *, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("input nesting exceeds the supported limit")
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("input numbers must be finite")
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("input object keys must be strings")
        for item in value.values():
            _validate_json_value(item, depth=depth + 1)
        return
    raise ValueError("input must contain only JSON values")
