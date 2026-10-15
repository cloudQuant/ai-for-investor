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

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any

__all__ = [
    "AccountBookReadView",
    "AccountReadView",
    "OrderReadView",
    "ReadQuality",
    "ServiceReadContractError",
    "StrategyHealthView",
]


class ServiceReadContractError(ValueError):
    """A neutral read view was built from an inconsistent or unsafe input."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _freeze_json(value: Any, code: str) -> Any:
    """Copy a JSON-shaped service response into immutable containers."""

    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ServiceReadContractError(code)
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ServiceReadContractError(code)
        return MappingProxyType({key: _freeze_json(item, code) for key, item in value.items()})
    if type(value) in {list, tuple}:
        return tuple(_freeze_json(item, code) for item in value)
    raise ServiceReadContractError(code)


def _thaw_json(value: Any) -> Any:
    """Return a JSON-serializable copy of a frozen service response."""

    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class AccountBookReadView:
    """An exact account-level execution-book projection from the SDK service.

    The legacy projection contains owner positions, fees, coverage cursors and
    residuals. Its optional persisted ``financial`` child can carry owner-book
    cash and cost basis on a separate ledger cut. Neither source supplies a
    provider account total, market value, marks, or FX conversions; consumers
    must keep those unavailable when their provider source lacks them and must
    not add owner-book amounts to account totals.
    """

    account_ref: str
    account_key_id: str
    projection: Mapping[str, Any]

    def __post_init__(self) -> None:
        _text(self.account_ref, "INVALID_ACCOUNT_REF")
        _text(self.account_key_id, "INVALID_ACCOUNT_KEY_ID")
        projection = _freeze_json(self.projection, "INVALID_ACCOUNT_BOOK_REPLY")
        legacy_fields = {
            "view",
            "coverage",
            "state",
            "books",
            "managed_orders",
            "managed_fills",
            "external_orders",
            "external_fills",
            "provider_position_change",
            "position_residual",
            "fee_residual",
        }
        projection_fields = (
            frozenset(projection) if isinstance(projection, Mapping) else frozenset()
        )
        if not isinstance(projection, Mapping) or projection_fields not in {
            frozenset(legacy_fields),
            frozenset(legacy_fields | {"financial"}),
        }:
            raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_REPLY")
        if projection["view"] != "ACCOUNT" or projection["state"] not in {
            "PARTIAL",
            "RESIDUAL",
            "BALANCED",
        }:
            raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_REPLY")

        coverage = projection["coverage"]
        coverage_fields = {
            "account_key",
            "scope_directory_revision",
            "journal_generation",
            "baseline_execution_cursor",
            "current_execution_cursor",
            "complete",
            "reasons",
            "scanned_outbox_events",
            "outbox_history_contiguous",
            "outbox_scan_complete",
            "continuations",
            "input_continuations",
            "quarantined_intents",
        }
        if not isinstance(coverage, Mapping) or set(coverage) != coverage_fields:
            raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_COVERAGE")
        # The SDK's ExecutionScope account token is a separate internal key
        # from Base AccountKey.account_key_id. Keep the trusted deployment key
        # for AFI-side deduplication, but validate the service token on its own.
        _text(coverage["account_key"], "INVALID_ACCOUNT_BOOK_COVERAGE")
        for name in ("scope_directory_revision", "journal_generation"):
            _text(coverage[name], "INVALID_ACCOUNT_BOOK_COVERAGE")
        for name in (
            "baseline_execution_cursor",
            "current_execution_cursor",
            "scanned_outbox_events",
        ):
            if type(coverage[name]) is not int or coverage[name] < 0:
                raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_COVERAGE")
        if coverage["baseline_execution_cursor"] > coverage["current_execution_cursor"]:
            raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_COVERAGE")
        if any(
            type(coverage[name]) is not bool
            for name in ("complete", "outbox_history_contiguous", "outbox_scan_complete")
        ):
            raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_COVERAGE")
        if type(coverage["reasons"]) is not tuple or any(
            type(reason) is not str for reason in coverage["reasons"]
        ):
            raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_COVERAGE")
        for name in ("continuations", "input_continuations", "quarantined_intents"):
            if type(coverage[name]) is not tuple:
                raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_COVERAGE")

        if "financial" in projection:
            _validate_account_book_financial(projection["financial"], coverage)

        books = projection["books"]
        if type(books) is not tuple:
            raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_REPLY")
        owner_keys: set[tuple[str, str]] = set()
        for book in books:
            if not isinstance(book, Mapping) or set(book) != {
                "owner_kind",
                "owner_ref",
                "current_positions",
                "fees_since_baseline",
            }:
                raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_REPLY")
            owner_kind = book["owner_kind"]
            if owner_kind not in {"STRATEGY", "MANUAL_BOOK", "UNALLOCATED"}:
                raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_REPLY")
            owner_ref = _text(book["owner_ref"], "INVALID_ACCOUNT_BOOK_REPLY")
            owner_key = (owner_kind, owner_ref)
            if owner_key in owner_keys:
                raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_REPLY")
            owner_keys.add(owner_key)
            positions = book["current_positions"]
            fees = book["fees_since_baseline"]
            if type(positions) is not tuple or type(fees) is not tuple:
                raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_REPLY")
            if any(
                not isinstance(item, Mapping)
                or set(item) != {"instrument", "net_quantity"}
                or type(item["instrument"]) is not str
                or type(item["net_quantity"]) is not str
                for item in positions
            ):
                raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_REPLY")
            if any(
                not isinstance(item, Mapping)
                or set(item) != {"currency", "amount"}
                or type(item["currency"]) is not str
                or type(item["amount"]) is not str
                for item in fees
            ):
                raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_REPLY")

        for name in ("provider_position_change", "position_residual"):
            items = projection[name]
            if type(items) is not tuple or any(
                not isinstance(item, Mapping)
                or set(item) != {"instrument", "net_quantity"}
                or type(item["instrument"]) is not str
                or type(item["net_quantity"]) is not str
                for item in items
            ):
                raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_REPLY")
        fees = projection["fee_residual"]
        if type(fees) is not tuple or any(
            not isinstance(item, Mapping)
            or set(item) != {"currency", "amount"}
            or type(item["currency"]) is not str
            or type(item["amount"]) is not str
            for item in fees
        ):
            raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_REPLY")
        for name in ("managed_orders", "managed_fills", "external_orders", "external_fills"):
            if type(projection[name]) is not tuple or any(
                not isinstance(item, Mapping) for item in projection[name]
            ):
                raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_REPLY")
        object.__setattr__(self, "projection", projection)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible copy for the HTTP projection."""

        return _thaw_json(self.projection)


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


_FINANCIAL_UNAVAILABLE_CODES = frozenset(
    {
        "FINANCIAL_DIRECTORY_UNAVAILABLE",
        "FINANCIAL_DIRECTORY_MISMATCH",
        "PERSISTED_PROJECTION_UNAVAILABLE",
        "INCOMPLETE_PERSISTED_PROJECTION",
        "FINANCIAL_EXECUTION_CUT_MISMATCH",
    }
)
_FINANCIAL_LEDGER_SOURCES = frozenset({"execution_outbox", "account_facts", "account_activity"})


def _financial_decimal(value: Any, code: str) -> Decimal:
    if type(value) is not str:
        raise ServiceReadContractError(code)
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ServiceReadContractError(code) from None
    if not number.is_finite():
        raise ServiceReadContractError(code)
    return number


def _financial_text(value: Any, code: str, *, maximum: int = 256) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or not value.isascii()
        or any(ord(char) < 0x21 for char in value)
    ):
        raise ServiceReadContractError(code)
    return value


def _validate_financial_money_rows(value: Any, code: str) -> None:
    if type(value) is not tuple:
        raise ServiceReadContractError(code)
    currencies: set[str] = set()
    for row in value:
        if not isinstance(row, Mapping) or set(row) != {"currency", "amount"}:
            raise ServiceReadContractError(code)
        currency = _financial_text(row["currency"], code, maximum=16)
        if currency in currencies:
            raise ServiceReadContractError(code)
        currencies.add(currency)
        _financial_decimal(row["amount"], code)


def _validate_financial_ledger_cut(value: Any, coverage: Mapping[str, Any]) -> None:
    code = "INVALID_ACCOUNT_BOOK_FINANCIAL"
    if not isinstance(value, Mapping) or set(value) != {
        "account_key",
        "owner_directory_revision",
        "captured_at_ns",
        "watermarks",
    }:
        raise ServiceReadContractError(code)
    if _financial_text(value["account_key"], code) != coverage["account_key"]:
        raise ServiceReadContractError(code)
    _financial_text(value["owner_directory_revision"], code)
    captured_at_ns = value["captured_at_ns"]
    if type(captured_at_ns) is not int or captured_at_ns <= 0:
        raise ServiceReadContractError(code)

    watermarks = value["watermarks"]
    if type(watermarks) is not tuple or len(watermarks) != len(_FINANCIAL_LEDGER_SOURCES):
        raise ServiceReadContractError(code)
    by_kind: dict[str, Mapping[str, Any]] = {}
    for watermark in watermarks:
        if not isinstance(watermark, Mapping) or set(watermark) != {
            "source_kind",
            "source_ref",
            "generation",
            "cursor",
            "as_of_ns",
        }:
            raise ServiceReadContractError(code)
        kind = watermark["source_kind"]
        if type(kind) is not str or kind not in _FINANCIAL_LEDGER_SOURCES or kind in by_kind:
            raise ServiceReadContractError(code)
        _financial_text(watermark["source_ref"], code)
        _financial_text(watermark["generation"], code)
        cursor = watermark["cursor"]
        as_of_ns = watermark["as_of_ns"]
        if type(cursor) is not int or cursor < 0:
            raise ServiceReadContractError(code)
        if type(as_of_ns) is not int or as_of_ns <= 0 or as_of_ns > captured_at_ns:
            raise ServiceReadContractError(code)
        by_kind[kind] = watermark
    if set(by_kind) != _FINANCIAL_LEDGER_SOURCES:
        raise ServiceReadContractError(code)

    execution = by_kind["execution_outbox"]
    if (
        execution["generation"] != coverage["journal_generation"]
        or execution["cursor"] != coverage["current_execution_cursor"]
    ):
        raise ServiceReadContractError(code)


def _validate_financial_book(value: Any, ledger_cut: Mapping[str, Any]) -> tuple[str, str]:
    code = "INVALID_ACCOUNT_BOOK_FINANCIAL"
    if not isinstance(value, Mapping) or set(value) != {
        "owner",
        "ledger_cut",
        "cash",
        "positions",
        "cumulative_fees",
        "realized_pnl",
        "cost_basis_complete",
    }:
        raise ServiceReadContractError(code)
    if value["ledger_cut"] != ledger_cut:
        raise ServiceReadContractError(code)
    owner = value["owner"]
    if not isinstance(owner, Mapping) or set(owner) != {
        "kind",
        "owner_ref",
        "execution_scope_key",
    }:
        raise ServiceReadContractError(code)
    kind = owner["kind"]
    owner_ref = _financial_text(owner["owner_ref"], code)
    execution_scope_key = owner["execution_scope_key"]
    if type(kind) is not str or kind not in {"STRATEGY", "MANUAL_BOOK"}:
        # UNALLOCATED is represented only by the separate residual fields.
        raise ServiceReadContractError(code)
    if kind == "STRATEGY":
        _financial_text(execution_scope_key, code)
    elif execution_scope_key is not None:
        _financial_text(execution_scope_key, code)
    if owner_ref == "UNALLOCATED":
        raise ServiceReadContractError(code)

    _validate_financial_money_rows(value["cash"], code)
    _validate_financial_money_rows(value["cumulative_fees"], code)
    _validate_financial_money_rows(value["realized_pnl"], code)
    positions = value["positions"]
    if type(positions) is not tuple:
        raise ServiceReadContractError(code)
    instruments: set[str] = set()
    for position in positions:
        if not isinstance(position, Mapping) or set(position) != {
            "instrument",
            "quantity",
            "cost_basis",
            "cost_currency",
            "cost_method",
            "product_model",
            "metadata_version",
        }:
            raise ServiceReadContractError(code)
        instrument = _financial_text(position["instrument"], code)
        if instrument in instruments:
            raise ServiceReadContractError(code)
        instruments.add(instrument)
        quantity = _financial_decimal(position["quantity"], code)
        if quantity < 0:
            raise ServiceReadContractError(code)
        if position["cost_basis"] is not None:
            cost_basis = _financial_decimal(position["cost_basis"], code)
            if (
                cost_basis < 0
                or (quantity == 0 and cost_basis != 0)
                or (quantity > 0 and cost_basis == 0)
            ):
                raise ServiceReadContractError(code)
            _financial_text(position["cost_currency"], code, maximum=16)
        elif position["cost_currency"] is not None or quantity == 0:
            raise ServiceReadContractError(code)
        if position["cost_method"] != "AVERAGE_COST" or position["product_model"] != "SPOT":
            raise ServiceReadContractError(code)
        _financial_text(position["metadata_version"], code)
    if type(value["cost_basis_complete"]) is not bool:
        raise ServiceReadContractError(code)
    return kind, owner_ref


def _validate_account_book_financial(value: Any, coverage: Mapping[str, Any]) -> None:
    code = "INVALID_ACCOUNT_BOOK_FINANCIAL"
    if not isinstance(value, Mapping) or type(value.get("available")) is not bool:
        raise ServiceReadContractError(code)
    if value["available"] is False:
        if set(value) != {"available", "code", "freshness", "cut_relationship"}:
            raise ServiceReadContractError(code)
        if (
            type(value["code"]) is not str
            or value["code"] not in _FINANCIAL_UNAVAILABLE_CODES
            or value["freshness"] != "NOT_ESTABLISHED"
            or value["cut_relationship"] != "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT"
        ):
            raise ServiceReadContractError(code)
        return

    if set(value) != {
        "available",
        "source",
        "freshness",
        "cut_relationship",
        "complete",
        "ledger_cut",
        "state",
        "books",
        "unallocated",
    }:
        raise ServiceReadContractError(code)
    state = value["state"]
    if (
        value["source"] != "PERSISTED_EXECUTION_FINANCIAL_PROJECTION"
        or value["freshness"] != "PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED"
        or value["cut_relationship"] != "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT"
        or type(value["complete"]) is not bool
        or value["complete"] is not True
        or type(state) is not str
        or state not in {"BALANCED", "RESIDUAL"}
    ):
        raise ServiceReadContractError(code)
    ledger_cut = value["ledger_cut"]
    _validate_financial_ledger_cut(ledger_cut, coverage)

    books = value["books"]
    if type(books) is not tuple or not books:
        raise ServiceReadContractError(code)
    owner_keys = [_validate_financial_book(book, ledger_cut) for book in books]
    if len(owner_keys) != len(set(owner_keys)):
        raise ServiceReadContractError(code)
    execution_scopes = [
        book["owner"]["execution_scope_key"]
        for book in books
        if book["owner"]["execution_scope_key"] is not None
    ]
    if len(execution_scopes) != len(set(execution_scopes)):
        raise ServiceReadContractError(code)

    unallocated = value["unallocated"]
    if not isinstance(unallocated, Mapping) or set(unallocated) != {
        "cash",
        "positions",
        "fees",
    }:
        raise ServiceReadContractError(code)
    _validate_financial_money_rows(unallocated["cash"], code)
    _validate_financial_money_rows(unallocated["fees"], code)
    for row in (*unallocated["cash"], *unallocated["fees"]):
        if _financial_decimal(row["amount"], code) == 0:
            raise ServiceReadContractError(code)
    residual_positions = unallocated["positions"]
    if type(residual_positions) is not tuple:
        raise ServiceReadContractError(code)
    residual_instruments: set[str] = set()
    for item in residual_positions:
        if type(item) is not tuple or len(item) != 2:
            raise ServiceReadContractError(code)
        instrument = _financial_text(item[0], code)
        if instrument in residual_instruments or _financial_decimal(item[1], code) == 0:
            raise ServiceReadContractError(code)
        residual_instruments.add(instrument)
    has_residual = bool(unallocated["cash"] or residual_positions or unallocated["fees"])
    expected_state = "RESIDUAL" if has_residual else "BALANCED"
    if state != expected_state:
        raise ServiceReadContractError(code)


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
    account_key: Mapping[str, Any] | None = None
    account_key_id: str | None = None

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
        if self.account_key is None:
            if self.account_key_id is not None:
                raise ServiceReadContractError("ACCOUNT_KEY_ID_WITHOUT_KEY")
        else:
            key = self.account_key
            required = {"provider", "venue", "environment", "account_id", "subaccount_id"}
            if not isinstance(key, Mapping) or set(key) != required:
                raise ServiceReadContractError("INVALID_ACCOUNT_KEY")
            normalized = dict(key)
            for name in ("provider", "venue", "environment", "account_id"):
                _text(normalized[name], "INVALID_ACCOUNT_KEY")
            subaccount_id = normalized["subaccount_id"]
            if subaccount_id is not None:
                _text(subaccount_id, "INVALID_ACCOUNT_KEY")
            if (
                type(self.account_key_id) is not str
                or len(self.account_key_id) != 72
                or not self.account_key_id.startswith("account-")
                or any(character not in "0123456789abcdef" for character in self.account_key_id[8:])
            ):
                raise ServiceReadContractError("INVALID_ACCOUNT_KEY_ID")
            object.__setattr__(self, "account_key", MappingProxyType(normalized))

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


@dataclass(frozen=True)
class OrderReadView:
    """One authorized managed-order record, or its explicit absence.

    The service journal is the only authority for this state.  The application
    may display it and link it to a user's intent, but it must not treat it as
    a strategy ledger, a virtual position, or a permission to act.
    """

    intent_id: str
    quality: ReadQuality
    state: str | None = None
    provider_order_id: str | None = None
    filled_quantity: Decimal | None = None
    average_price: Decimal | None = None
    cumulative_commission: Decimal | None = None
    is_terminal: bool | None = None
    unknown_reason: str | None = None
    review_required: bool | None = None
    updated_at_ns: int | None = None
    detail_code: str | None = None

    def __post_init__(self) -> None:
        _text(self.intent_id, "INVALID_INTENT_ID")
        if not isinstance(self.quality, ReadQuality):
            raise ServiceReadContractError("INVALID_QUALITY")
        if self.quality in _ABSENT_QUALITIES:
            if any(
                item is not None
                for item in (
                    self.state,
                    self.provider_order_id,
                    self.filled_quantity,
                    self.average_price,
                    self.is_terminal,
                )
            ):
                # An unavailable or never-collected record must not carry a
                # state a caller could read as a real order fact.
                raise ServiceReadContractError("ABSENT_VIEW_MUST_NOT_CARRY_VALUES")
            return
        _text(self.state, "INVALID_STATE", maximum=32)
        if self.state != self.state.upper():
            raise ServiceReadContractError("INVALID_STATE")
        for value, code in (
            (self.provider_order_id, "INVALID_PROVIDER_ORDER_ID"),
            (self.unknown_reason, "INVALID_UNKNOWN_REASON"),
        ):
            if value is not None:
                _text(value, code)
        for value, code in (
            (self.filled_quantity, "INVALID_FILLED_QUANTITY"),
            (self.average_price, "INVALID_AVERAGE_PRICE"),
            (self.cumulative_commission, "INVALID_COMMISSION"),
        ):
            _optional_decimal(value, code)
        if self.is_terminal is not None and type(self.is_terminal) is not bool:
            raise ServiceReadContractError("INVALID_TERMINAL_FLAG")
        if self.updated_at_ns is not None and (
            type(self.updated_at_ns) is not int or self.updated_at_ns < 0
        ):
            raise ServiceReadContractError("INVALID_UPDATED_AT")

    @property
    def is_unknown(self) -> bool:
        """Return whether the provider outcome still needs reconciliation."""

        return self.state == "UNKNOWN"

    @classmethod
    def unavailable(cls, intent_id: str, detail_code: str) -> OrderReadView:
        """Build the explicit view used when the record cannot be read."""

        return cls(
            intent_id=intent_id,
            quality=ReadQuality.UNAVAILABLE,
            detail_code=_text(detail_code, "INVALID_DETAIL_CODE"),
        )

    @classmethod
    def not_collected(cls, intent_id: str) -> OrderReadView:
        """Build the explicit view used when the service holds no record."""

        return cls(intent_id=intent_id, quality=ReadQuality.NOT_COLLECTED)
