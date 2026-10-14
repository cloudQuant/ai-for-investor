"""Neutral, non-authoritative read views for the AI-for-Investor application.

These DTOs are the only shapes the application may project from the shared
service packages.  They deliberately carry no domain engine: an account view
holds provider facts with an explicit quality marker, and a health view holds
a producer's heartbeat observation.  Nothing here is an order, a risk permit,
a strategy ledger or a portfolio authority.

A missing fact is never a zero.  Callers must branch on :class:`ReadQuality`
instead of defaulting a numeric field, because "the service has not observed
this yet" and "the observed value is zero" are different product statements.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

__all__ = [
    "AccountReadView",
    "ReadQuality",
    "ServiceReadContractError",
    "StrategyHealthView",
]


class ServiceReadContractError(ValueError):
    """A neutral read view was built from an inconsistent or unsafe input."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ReadQuality(str, Enum):
    """Why a view does or does not carry a current observation."""

    #: A current observation from the service within its freshness bound.
    FRESH = "fresh"
    #: The service observed something, but it is older than the bound.
    STALE = "stale"
    #: The producer never reported this fact; no value exists to project.
    NOT_COLLECTED = "not_collected"
    #: The read path itself is unusable right now.
    UNAVAILABLE = "unavailable"


#: Qualities that must never be accompanied by a projected numeric value.
_ABSENT_QUALITIES = frozenset({ReadQuality.NOT_COLLECTED, ReadQuality.UNAVAILABLE})


def _text(value: Any, code: str, *, maximum: int = 256) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        raise ServiceReadContractError(code)
    return value


def _optional_decimal(value: Any, code: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ServiceReadContractError(code)
    number = Decimal(str(value))
    if not number.is_finite():
        raise ServiceReadContractError(code)
    return number


def _optional_seconds(value: Any, code: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ServiceReadContractError(code)
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")) or number < 0:
        raise ServiceReadContractError(code)
    return number


@dataclass(frozen=True)
class AccountReadView:
    """One authorized provider account observation, or its explicit absence.

    ``cash`` and ``value`` are the provider's own figures for the requested
    currency.  They are not strategy allocations, virtual positions or a
    portfolio valuation, and the application must not present them as such.
    """

    account_ref: str
    execution_domain_ref: str
    currency: str
    quality: ReadQuality
    source_service_id: str | None = None
    session_generation: str | None = None
    cursor: int | None = None
    cash: Decimal | None = None
    value: Decimal | None = None
    observed_at_utc: str | None = None
    received_age_seconds: float | None = None
    fresh_for_seconds: float | None = None
    detail_code: str | None = None
    positions_count: int | None = None
    open_orders_count: int | None = None

    def __post_init__(self) -> None:
        _text(self.account_ref, "INVALID_ACCOUNT_REF")
        _text(self.execution_domain_ref, "INVALID_EXECUTION_DOMAIN_REF")
        _text(self.currency, "INVALID_CURRENCY", maximum=16)
        if not isinstance(self.quality, ReadQuality):
            raise ServiceReadContractError("INVALID_QUALITY")
        if self.quality in _ABSENT_QUALITIES and any(
            item is not None for item in (self.cash, self.value, self.observed_at_utc)
        ):
            # An unavailable or never-collected fact must not carry numbers
            # that a caller could read as a real balance.
            raise ServiceReadContractError("ABSENT_VIEW_MUST_NOT_CARRY_VALUES")
        _optional_decimal(self.cash, "INVALID_CASH")
        _optional_decimal(self.value, "INVALID_VALUE")
        _optional_seconds(self.received_age_seconds, "INVALID_RECEIVED_AGE")
        _optional_seconds(self.fresh_for_seconds, "INVALID_FRESH_FOR")
        for count in (self.positions_count, self.open_orders_count):
            if count is not None and (type(count) is not int or count < 0):
                raise ServiceReadContractError("INVALID_COUNT")
        if self.cursor is not None and (type(self.cursor) is not int or self.cursor < 0):
            raise ServiceReadContractError("INVALID_CURSOR")

    @property
    def has_current_facts(self) -> bool:
        """Return whether a numeric balance may be displayed as current."""

        return self.quality is ReadQuality.FRESH and self.cash is not None

    @classmethod
    def unavailable(
        cls, account_ref: str, execution_domain_ref: str, currency: str, detail_code: str
    ) -> AccountReadView:
        """Build the explicit view used when the read path cannot answer."""

        return cls(
            account_ref=account_ref,
            execution_domain_ref=execution_domain_ref,
            currency=currency,
            quality=ReadQuality.UNAVAILABLE,
            detail_code=_text(detail_code, "INVALID_DETAIL_CODE"),
        )


@dataclass(frozen=True)
class StrategyHealthView:
    """One authorized producer heartbeat observation for a strategy scope.

    ``metrics`` are the producer's own flat numbers.  A metrics-only producer
    is not healthy: only a fresh heartbeat is, and its absence means the
    application must report "not collected" rather than infer health from
    order activity or a running process.
    """

    strategy_ref: str
    scope_ref: str
    quality: ReadQuality
    stream_id: str | None = None
    sequence: int | None = None
    heartbeat_age_seconds: float | None = None
    metrics_age_seconds: float | None = None
    metrics: Mapping[str, float] = field(default_factory=dict)
    detail_code: str | None = None

    def __post_init__(self) -> None:
        _text(self.strategy_ref, "INVALID_STRATEGY_REF")
        _text(self.scope_ref, "INVALID_SCOPE_REF")
        if not isinstance(self.quality, ReadQuality):
            raise ServiceReadContractError("INVALID_QUALITY")
        _optional_seconds(self.heartbeat_age_seconds, "INVALID_HEARTBEAT_AGE")
        _optional_seconds(self.metrics_age_seconds, "INVALID_METRICS_AGE")
        if self.sequence is not None and (type(self.sequence) is not int or self.sequence < 1):
            raise ServiceReadContractError("INVALID_SEQUENCE")
        if self.quality is ReadQuality.NOT_COLLECTED and self.metrics:
            raise ServiceReadContractError("NOT_COLLECTED_MUST_NOT_CARRY_METRICS")
        normalized: dict[str, float] = {}
        for key, value in dict(self.metrics).items():
            _text(key, "INVALID_METRIC_NAME", maximum=64)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ServiceReadContractError("INVALID_METRIC_VALUE")
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")):
                raise ServiceReadContractError("INVALID_METRIC_VALUE")
            normalized[key] = number
        object.__setattr__(self, "metrics", normalized)

    @property
    def is_healthy(self) -> bool:
        """Return whether a fresh heartbeat proves the producer is reporting."""

        return self.quality is ReadQuality.FRESH

    @classmethod
    def not_collected(cls, strategy_ref: str, scope_ref: str) -> StrategyHealthView:
        """Build the explicit view used when no producer ever reported."""

        return cls(
            strategy_ref=strategy_ref,
            scope_ref=scope_ref,
            quality=ReadQuality.NOT_COLLECTED,
        )

    @classmethod
    def unavailable(cls, strategy_ref: str, scope_ref: str, detail_code: str) -> StrategyHealthView:
        """Build the explicit view used when the read path cannot answer."""

        return cls(
            strategy_ref=strategy_ref,
            scope_ref=scope_ref,
            quality=ReadQuality.UNAVAILABLE,
            detail_code=_text(detail_code, "INVALID_DETAIL_CODE"),
        )
