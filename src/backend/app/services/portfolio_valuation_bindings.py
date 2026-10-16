"""Exact, server-owned market-data joins for display-only portfolio inputs."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.data.deps import get_authorized_market_data_access
from app.api.data.queries import (
    build_market_data_query_service,
    evaluate_market_data_capabilities,
    execute_market_data_query_with_singleflight,
)
from app.schemas.auth import TokenPayload
from app.schemas.market_data_platform import MarketDataQueryRequest
from app.services.market_data.access import MarketDataAccessAuthorizer, MarketDataQueryAccess
from app.services.market_data.capability_ledger import MarketDataCapabilityEvaluation
from app.services.market_data.dataset_contracts import DEFAULT_DATASET_CONTRACT_REGISTRY
from app.services.market_data.query_service import MarketDataQueryExecution, MarketDataQueryService

InputStatus = Literal[
    "available", "coverage_incomplete", "error", "missing", "not_calculated",
    "not_required", "stale", "unavailable", "unsupported",
]
_MAX_CONFIG_BYTES = 262_144
_MAX_QUERIES_PER_PROJECTION = 128
_ACCESS_DENIALS = frozenset(
    {
        "MARKET_DATA_ACCESS_DENIED",
        "MARKET_DATA_ACCESS_CHANGED_DURING_FETCH",
        "MARKET_DATA_PRINCIPAL_REVOKED",
        "MARKET_DATA_READ_ENTITLEMENT_DENIED",
        "MARKET_DATA_QUERY_V2_DISABLED",
        "MARKET_DATA_QUERY_LIMIT_REACHED",
        "SOURCE_ROUTE_AUTHORIZATION_DENIED",
        "SOURCE_LOCAL_SOURCE_AUTHORIZATION_DENIED",
        "SOURCE_REGISTRY_DISABLED",
        "SOURCE_LICENSE_DENIED",
        "SOURCE_USE_DENIED",
    }
)
_SAFE_QUERY_ERRORS = _ACCESS_DENIALS | frozenset(
    {
        "DATASET_UNAVAILABLE",
        "DATA_FAMILY_UNCONFIGURED",
        "IDENTITY_NOT_FOUND",
        "IDENTITY_AMBIGUOUS",
        "IDENTITY_NOT_KNOWN_AT_CUTOFF",
        "SNAPSHOT_FRESHNESS_POLICY_UNAVAILABLE",
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AccountMarketKey(_StrictModel):
    """All public SDK key fields; lookup is case-sensitive and exact."""

    provider: str = Field(min_length=1, max_length=128)
    venue: str = Field(min_length=1, max_length=128)
    environment: str = Field(min_length=1, max_length=64)
    product_type: str = Field(min_length=1, max_length=128)
    instrument_id: str = Field(min_length=1, max_length=255)
    native_symbol: str = Field(min_length=1, max_length=255)

    @field_validator("provider", "venue", "environment", "product_type", "instrument_id", "native_symbol")
    @classmethod
    def validate_key_part(cls, value: str) -> str:
        value = value.strip()
        if not value or not value.isprintable():
            raise ValueError("market-key fields must be non-empty printable text")
        return value

    def exact_key(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.provider, self.venue, self.environment, self.product_type,
            self.instrument_id, self.native_symbol,
        )


class MarketDataReadBinding(_StrictModel):
    """One fixed normal-v2 market query and its expected resolved identity."""

    canonical_id: str = Field(min_length=3, max_length=512)
    asset_type: Literal["bond", "crypto", "fund", "futures", "fx", "option", "stock"]
    venue: str = Field(min_length=1, max_length=128)
    product_type: str = Field(min_length=1, max_length=64)
    metadata_version: str = Field(min_length=1, max_length=64)
    family_id: str = Field(min_length=3, max_length=128)
    family_contract_version: str = Field(min_length=1, max_length=64)
    dataset_code: str = Field(min_length=1, max_length=255)
    data_kind: Literal["bars", "quote_snapshot", "reference_series"]
    frequency: str = Field(min_length=1, max_length=32)
    required_fields: tuple[str, ...] = Field(min_length=1, max_length=32)
    value_field: str = Field(min_length=1, max_length=128)
    adjustment: str | None = Field(default=None, max_length=128)
    price_basis: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=1, max_length=32)
    unit: str = Field(min_length=1, max_length=128)
    source_policy_id: str = Field(min_length=1, max_length=128)
    query_window_seconds: int = Field(ge=1, le=31_536_000)
    page_size: int = Field(ge=1, le=2000)
    freshness_max_age_seconds: int = Field(ge=1, le=31_536_000)
    binding_ref: str = Field(min_length=1, max_length=128)
    binding_version: str = Field(min_length=1, max_length=64)
    valid_from_utc: datetime
    valid_to_utc: datetime | None = None
    provenance_ref: str = Field(min_length=1, max_length=255)
    fx_base_currency: str | None = Field(default=None, max_length=3)
    fx_quote_currency: str | None = Field(default=None, max_length=3)

    @field_validator(
        "canonical_id", "venue", "product_type", "metadata_version", "family_id",
        "family_contract_version", "dataset_code", "frequency", "value_field",
        "price_basis", "currency", "unit", "source_policy_id", "binding_ref",
        "binding_version", "provenance_ref",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value or not value.isprintable():
            raise ValueError("valuation binding text must be non-empty printable text")
        return value

    @field_validator("required_fields", mode="before")
    @classmethod
    def validate_fields(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)) or not value:
            raise ValueError("required_fields must be a non-empty list or tuple")
        fields = tuple(item.strip() for item in value if isinstance(item, str))
        if len(fields) != len(value) or any(not item for item in fields):
            raise ValueError("required_fields must contain non-empty strings")
        if len(fields) != len(set(fields)):
            raise ValueError("required_fields must be distinct")
        return tuple(sorted(fields))

    @field_validator("valid_from_utc", "valid_to_utc")
    @classmethod
    def validate_validity_time(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @field_validator("currency", "fx_base_currency", "fx_quote_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None

    @model_validator(mode="after")
    def validate_query_contract(self) -> MarketDataReadBinding:
        if self.value_field not in self.required_fields:
            raise ValueError("value_field must be in required_fields")
        if self.valid_to_utc is not None and self.valid_to_utc <= self.valid_from_utc:
            raise ValueError("valid_to_utc must be later than valid_from_utc")
        if (self.fx_base_currency is None) != (self.fx_quote_currency is None):
            raise ValueError("FX identity requires both base and quote currency")
        if self.fx_base_currency is not None and self.asset_type != "fx":
            raise ValueError("only FX market identities may declare a currency pair")
        DEFAULT_DATASET_CONTRACT_REGISTRY.assert_query_binding(
            family_id=self.family_id,
            family_contract_version=self.family_contract_version,
            asset_type=self.asset_type,
            dataset_code=self.dataset_code,
            data_kind=self.data_kind,
            frequency=self.frequency,
            required_fields=self.required_fields,
            source_policy_id=self.source_policy_id,
            adjustment=self.adjustment,
            price_basis=self.price_basis,
            currency=self.currency,
            unit=self.unit,
            explicit_semantic_axis_names=frozenset(
                {"adjustment", "price_basis", "currency", "unit"}
            ),
        )
        return self

    def is_active(self, instant: datetime) -> bool:
        instant = _aware_utc(instant)
        return self.valid_from_utc <= instant and (
            self.valid_to_utc is None or instant < self.valid_to_utc
        )

    def request(self, now: datetime) -> MarketDataQueryRequest:
        now = _aware_utc(now)
        return MarketDataQueryRequest.model_validate(
            {
                "identity": {"canonical_id": self.canonical_id},
                "family_id": self.family_id,
                "family_contract_version": self.family_contract_version,
                "dataset_code": self.dataset_code,
                "data_kind": self.data_kind,
                "frequency": self.frequency,
                "start": now - timedelta(seconds=self.query_window_seconds),
                "end": now,
                "required_fields": list(self.required_fields),
                "adjustment": self.adjustment,
                "price_basis": self.price_basis,
                "currency": self.currency,
                "unit": self.unit,
                "source_policy_id": self.source_policy_id,
                "consistency": "display",
                "purpose": "display",
                "mode": "local_first",
                "page_size": self.page_size,
            }
        )


class InstrumentValuationBinding(_StrictModel):
    """Exact account key crosswalk and explicit contract multiplier evidence."""

    market_key: AccountMarketKey
    binding_ref: str = Field(min_length=1, max_length=128)
    binding_version: str = Field(min_length=1, max_length=64)
    valid_from_utc: datetime
    valid_to_utc: datetime | None = None
    market_data: MarketDataReadBinding | None
    multiplier: Decimal | None
    quantity_unit: str = Field(min_length=1, max_length=128)
    multiplier_provenance_ref: str = Field(min_length=1, max_length=255)
    multiplier_metadata_version: str = Field(min_length=1, max_length=64)
    multiplier_valid_from_utc: datetime
    multiplier_valid_to_utc: datetime | None = None

    @field_validator(
        "binding_ref", "binding_version", "quantity_unit", "multiplier_provenance_ref",
        "multiplier_metadata_version",
    )
    @classmethod
    def validate_binding_text(cls, value: str) -> str:
        value = value.strip()
        if not value or not value.isprintable():
            raise ValueError("binding evidence text must be non-empty printable text")
        return value

    @field_validator(
        "valid_from_utc", "valid_to_utc", "multiplier_valid_from_utc", "multiplier_valid_to_utc"
    )
    @classmethod
    def validate_binding_time(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_instrument_evidence(self) -> InstrumentValuationBinding:
        for start, end in (
            (self.valid_from_utc, self.valid_to_utc),
            (self.multiplier_valid_from_utc, self.multiplier_valid_to_utc),
        ):
            if end is not None and end <= start:
                raise ValueError("binding validity end must be later than start")
        if self.multiplier is not None and (
            not self.multiplier.is_finite() or self.multiplier <= 0
        ):
            raise ValueError("configured multiplier must be finite and positive")
        return self

    def is_active(self, instant: datetime) -> bool:
        instant = _aware_utc(instant)
        return self.valid_from_utc <= instant and (
            self.valid_to_utc is None or instant < self.valid_to_utc
        )


class FxPairBinding(_StrictModel):
    """Exact ordered currency pair and normal-v2 source binding."""

    from_currency: str = Field(min_length=3, max_length=3)
    to_currency: str = Field(min_length=3, max_length=3)
    rate_convention: Literal["to_per_from"]
    binding_ref: str = Field(min_length=1, max_length=128)
    binding_version: str = Field(min_length=1, max_length=64)
    valid_from_utc: datetime
    valid_to_utc: datetime | None = None
    market_data: MarketDataReadBinding

    @field_validator("from_currency", "to_currency")
    @classmethod
    def normalize_pair_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("currency must be a three-letter code")
        return value

    @field_validator("binding_ref", "binding_version")
    @classmethod
    def validate_pair_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("FX binding identity must be non-empty")
        return value

    @field_validator("valid_from_utc", "valid_to_utc")
    @classmethod
    def validate_pair_time(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_pair_binding(self) -> FxPairBinding:
        data = self.market_data
        if self.from_currency == self.to_currency:
            raise ValueError("FX currencies must differ")
        if self.valid_to_utc is not None and self.valid_to_utc <= self.valid_from_utc:
            raise ValueError("FX validity end must be later than start")
        if (
            data.asset_type != "fx"
            or data.fx_base_currency != self.from_currency
            or data.fx_quote_currency != self.to_currency
        ):
            raise ValueError("FX market identity must bind the configured ordered pair")
        return self

    def is_active(self, instant: datetime) -> bool:
        instant = _aware_utc(instant)
        return self.valid_from_utc <= instant and (
            self.valid_to_utc is None or instant < self.valid_to_utc
        )


class PortfolioValuationBindingsConfig(_StrictModel):
    """Deployment JSON schema; it contains no browser-controlled selectors."""

    version: Literal["portfolio-valuation-bindings-v1"]
    instruments: tuple[InstrumentValuationBinding, ...] = Field(max_length=4096)
    fx_pairs: tuple[FxPairBinding, ...] = Field(max_length=512)

    @model_validator(mode="after")
    def reject_duplicate_bindings(self) -> PortfolioValuationBindingsConfig:
        instrument_keys = [entry.market_key.exact_key() for entry in self.instruments]
        pairs = [(entry.from_currency, entry.to_currency) for entry in self.fx_pairs]
        if len(instrument_keys) != len(set(instrument_keys)) or len(pairs) != len(set(pairs)):
            raise ValueError("valuation binding keys must be unique")
        return self


class PortfolioValuationBindingRegistry:
    """Read-only exact lookup assembled from settings during normal startup."""

    def __init__(self, config: PortfolioValuationBindingsConfig) -> None:
        self.version = config.version
        self._instruments = MappingProxyType(
            {item.market_key.exact_key(): item for item in config.instruments}
        )
        self._fx = MappingProxyType(
            {(item.from_currency, item.to_currency): item for item in config.fx_pairs}
        )

    @classmethod
    def from_json(cls, raw: str | None) -> PortfolioValuationBindingRegistry:
        if raw is None or not raw.strip():
            return cls(
                PortfolioValuationBindingsConfig(
                    version="portfolio-valuation-bindings-v1", instruments=(), fx_pairs=()
                )
            )
        if len(raw.encode("utf-8")) > _MAX_CONFIG_BYTES:
            raise ValueError("PORTFOLIO_VALUATION_BINDINGS_INVALID")
        try:
            return cls(PortfolioValuationBindingsConfig.model_validate_json(raw))
        except (ValidationError, TypeError, ValueError):
            raise ValueError("PORTFOLIO_VALUATION_BINDINGS_INVALID") from None

    def instrument(self, value: object) -> InstrumentValuationBinding | None:
        try:
            key = AccountMarketKey.model_validate(value).exact_key()
        except (ValidationError, TypeError, ValueError):
            return None
        return self._instruments.get(key)

    def fx_pair(self, source: str, target: str) -> FxPairBinding | None:
        return self._fx.get((source.upper(), target.upper()))


async def attach_market_valuation_inputs(
    projection: dict[str, Any],
    *,
    registry: PortfolioValuationBindingRegistry,
    current_user: TokenPayload,
    db: AsyncSession,
    clock: Any = None,
) -> dict[str, Any]:
    """Join exact account positions to separately authorized market-v2 facts."""
    if projection.get("source_type") != "live":
        return projection
    now = _aware_utc((clock or _utc_now)())
    rows = _positions(projection)
    if not rows:
        projection["market_valuation"] = _summary((), code=None)
        return projection

    bindings: list[tuple[dict[str, Any], InstrumentValuationBinding | None, datetime | None]] = []
    needs_market_read = False
    for position in rows:
        binding = registry.instrument(position.get("instrument"))
        position_at = _parse_time(position.get("observed_at_utc"))
        bindings.append((position, binding, position_at))
        if binding is None:
            _unavailable(position, "VALUATION_BINDING_NOT_CONFIGURED", unsupported=True)
            continue
        position["valuation_binding"] = {
            "status": "configured",
            "binding_ref": binding.binding_ref,
            "binding_version": binding.binding_version,
            "valid_from_utc": _iso(binding.valid_from_utc),
            "valid_to_utc": _iso(binding.valid_to_utc),
        }
        _multiplier(position, binding, position_at)
        if binding.market_data is None:
            _input(position, "mark_price", "unsupported", "MARK_PRICE_BINDING_UNAVAILABLE")
            _input(position, "fx_rate", "unsupported", "FX_REQUIRES_MARK_PRICE_CURRENCY")
        elif position_at is None:
            position["valuation_inputs"]["mark_price"] = _input_record(
                "unavailable", "ACCOUNT_POSITION_TIMESTAMP_MISSING", binding.market_data
            )
            position["valuation_inputs"]["market_cut"] = _cut(
                position.get("observed_at_utc"), None, None, binding.market_data
            )
            _input(position, "fx_rate", "unavailable", "ACCOUNT_POSITION_TIMESTAMP_MISSING")
        elif (
            not binding.is_active(now)
            or not binding.is_active(position_at)
            or not binding.market_data.is_active(now)
            or not binding.market_data.is_active(position_at)
        ):
            binding_code = (
                "VALUATION_BINDING_OUTSIDE_VALIDITY"
                if not binding.is_active(now) or not binding.is_active(position_at)
                else "MARKET_DATA_BINDING_OUTSIDE_VALIDITY"
            )
            position["valuation_inputs"]["mark_price"] = _input_record(
                "stale", binding_code, binding.market_data
            )
            position["valuation_inputs"]["market_cut"] = _cut(
                position.get("observed_at_utc"), None, None, binding.market_data
            )
            _input(position, "fx_rate", "unavailable", "FX_REQUIRES_CURRENT_MARK_BINDING")
        else:
            needs_market_read = True
        _overall(position)

    query_context = await _query_context(db, current_user) if needs_market_read else None
    if query_context is not None and query_context[3] is not None:
        for position, binding, position_at in bindings:
            if (
                binding is None
                or binding.market_data is None
                or position_at is None
                or not binding.is_active(now)
                or not binding.is_active(position_at)
                or not binding.market_data.is_active(now)
                or not binding.market_data.is_active(position_at)
            ):
                continue
            _input(position, "mark_price", "unavailable", query_context[3])
            position["valuation_inputs"]["market_cut"] = _cut(
                position.get("observed_at_utc"), None, None, binding.market_data
            )
            source_currency = binding.market_data.currency.upper()
            target_currency = str(projection.get("base_currency") or "").upper()
            if source_currency == target_currency:
                _input(
                    position,
                    "fx_rate",
                    "not_required",
                    None,
                    from_currency=target_currency,
                    to_currency=target_currency,
                    rate_convention="to_per_from",
                )
            else:
                _input(
                    position,
                    "fx_rate",
                    "unavailable",
                    query_context[3],
                    from_currency=source_currency,
                    to_currency=target_currency or None,
                )
                fx_binding = registry.fx_pair(source_currency, target_currency)
                if fx_binding is not None:
                    position["valuation_inputs"]["fx_market_cut"] = _cut(
                        position.get("observed_at_utc"), None, None, fx_binding.market_data
                    )
            _overall(position)
        projection["market_valuation"] = _summary(rows, code=query_context[3])
        return projection

    request_cache: dict[str, tuple[MarketDataQueryExecution | None, str | None]] = {}
    for position, binding, position_at in bindings:
        if binding is None or binding.market_data is None:
            continue
        if (
            not binding.is_active(now)
            or position_at is None
            or not binding.is_active(position_at)
            or not binding.market_data.is_active(now)
            or not binding.market_data.is_active(position_at)
        ):
            continue
        price_binding = binding.market_data
        execution, error_code = await _execute_query(
            price_binding, now=now, context=query_context, cache=request_cache, db=db
        )
        mark, observation = _project_market_input(
            execution, price_binding, now=now, error_code=error_code
        )
        position["valuation_inputs"]["mark_price"] = mark
        position["valuation_inputs"]["market_cut"] = _cut(
            position.get("observed_at_utc"), execution, observation, price_binding
        )
        source_currency = mark.get("currency") or position.get("price_currency")
        target_currency = str(projection.get("base_currency") or "").upper()
        if not source_currency:
            _input(position, "fx_rate", "missing", "POSITION_PRICE_CURRENCY_MISSING")
        elif source_currency.upper() == target_currency:
            _input(
                position, "fx_rate", "not_required", None,
                from_currency=target_currency, to_currency=target_currency,
                rate_convention="to_per_from",
            )
        else:
            await _project_fx(
                position,
                registry.fx_pair(source_currency, target_currency),
                source_currency=source_currency,
                target_currency=target_currency,
                position_at=position_at,
                now=now,
                query_context=query_context,
                request_cache=request_cache,
                db=db,
            )
        _overall(position)

    projection["market_valuation"] = _summary(rows, code=None)
    return projection


async def _query_context(
    db: AsyncSession, current_user: TokenPayload
) -> tuple[MarketDataQueryAccess | None, MarketDataQueryService | None, MarketDataCapabilityEvaluation | None, str | None]:
    authorizer = MarketDataAccessAuthorizer(db)
    try:
        access = await get_authorized_market_data_access(
            current_user=current_user, access_authorizer=authorizer
        )
    except HTTPException as error:
        if error.status_code == 403:
            return None, None, None, "MARKET_DATA_ACCESS_DENIED"
        raise
    capability = await evaluate_market_data_capabilities(db)
    if not capability.response.query_v2_enabled:
        return access, None, capability, "MARKET_DATA_QUERY_V2_DISABLED"
    return access, build_market_data_query_service(db, capability), capability, None


async def _execute_query(
    binding: MarketDataReadBinding,
    *,
    now: datetime,
    context: tuple[MarketDataQueryAccess | None, MarketDataQueryService | None, MarketDataCapabilityEvaluation | None, str | None] | None,
    cache: dict[str, tuple[MarketDataQueryExecution | None, str | None]],
    db: AsyncSession,
) -> tuple[MarketDataQueryExecution | None, str | None]:
    assert context is not None and context[0] is not None and context[1] is not None
    request = binding.request(now)
    if request.query_fingerprint in cache:
        return cache[request.query_fingerprint]
    if len(cache) >= _MAX_QUERIES_PER_PROJECTION:
        result = (None, "MARKET_DATA_QUERY_LIMIT_REACHED")
        cache[request.query_fingerprint] = result
        return result
    try:
        execution = await execute_market_data_query_with_singleflight(
            service=context[1], db=db, request=request, access=context[0]
        )
        result = (execution, None) if type(execution) is MarketDataQueryExecution else (
            None, "MARKET_DATA_QUERY_CONTRACT_INVALID"
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        await db.rollback()
        code = getattr(error, "code", None)
        result = (None, code if isinstance(code, str) and code in _SAFE_QUERY_ERRORS else "MARKET_DATA_QUERY_FAILED")
    cache[request.query_fingerprint] = result
    return result


async def _project_fx(
    position: dict[str, Any],
    binding: FxPairBinding | None,
    *,
    source_currency: str,
    target_currency: str,
    position_at: datetime,
    now: datetime,
    query_context: tuple[MarketDataQueryAccess | None, MarketDataQueryService | None, MarketDataCapabilityEvaluation | None, str | None] | None,
    request_cache: dict[str, tuple[MarketDataQueryExecution | None, str | None]],
    db: AsyncSession,
) -> None:
    if binding is None:
        _input(position, "fx_rate", "unsupported", "FX_BINDING_NOT_CONFIGURED", from_currency=source_currency, to_currency=target_currency)
        return
    if not binding.is_active(now) or not binding.is_active(position_at):
        _input(position, "fx_rate", "stale", "FX_BINDING_OUTSIDE_VALIDITY", from_currency=source_currency, to_currency=target_currency, binding_ref=binding.binding_ref)
        return
    if not binding.market_data.is_active(now) or not binding.market_data.is_active(position_at):
        _input(position, "fx_rate", "stale", "FX_MARKET_DATA_BINDING_OUTSIDE_VALIDITY", from_currency=source_currency, to_currency=target_currency, binding_ref=binding.binding_ref)
        return
    if binding.market_data.currency != target_currency:
        _input(position, "fx_rate", "error", "FX_QUERY_CURRENCY_MISMATCH", from_currency=source_currency, to_currency=target_currency)
        return
    execution, error_code = await _execute_query(
        binding.market_data, now=now, context=query_context, cache=request_cache, db=db
    )
    result, observation = _project_market_input(
        execution,
        binding.market_data,
        now=now,
        error_code=error_code,
        expected_fx_pair=(source_currency, target_currency),
        expected_rate_convention=binding.rate_convention,
    )
    if result.get("status") == "available":
        rate = _to_decimal(result.get("value"))
        if rate is not None and rate <= 0:
            result.update(status="error", code="FX_RATE_NON_POSITIVE")
    result.update(
        {
            "from_currency": source_currency,
            "to_currency": target_currency,
            "rate_convention": binding.rate_convention,
            "binding_ref": binding.binding_ref,
            "binding_version": binding.binding_version,
        }
    )
    position["valuation_inputs"]["fx_rate"] = result
    position["valuation_inputs"]["fx_market_cut"] = _cut(
        position_at, execution, observation, binding.market_data
    )


def _project_market_input(
    execution: MarketDataQueryExecution | None,
    binding: MarketDataReadBinding,
    *,
    now: datetime,
    error_code: str | None,
    expected_fx_pair: tuple[str, str] | None = None,
    expected_rate_convention: str | None = None,
) -> tuple[dict[str, Any], Any | None]:
    if error_code is not None or execution is None:
        code = error_code or "MARKET_DATA_QUERY_UNAVAILABLE"
        status: InputStatus = "unavailable" if code in _ACCESS_DENIALS else "error"
        return _input_record(status, code, binding), None
    identity = execution.context.identity
    query = execution.context.query
    details = identity.identity.details
    valid = (
        query.canonical_id == binding.canonical_id
        and query.instrument_metadata_version == binding.metadata_version
        and query.identity.canonical_id == binding.canonical_id
        and query.family_id == binding.family_id
        and query.family_contract_version == binding.family_contract_version
        and query.dataset_code == binding.dataset_code
        and query.data_kind == binding.data_kind
        and query.frequency == binding.frequency
        and query.required_fields == binding.required_fields
        and query.adjustment == binding.adjustment
        and query.price_basis == binding.price_basis
        and query.currency == binding.currency
        and query.unit == binding.unit
        and query.source_policy_id == binding.source_policy_id
        and identity.asset_type == binding.asset_type
        and identity.venue == binding.venue
        and identity.metadata_version == binding.metadata_version
        and identity.identity.canonical_id == binding.canonical_id
        and identity.identity.venue == binding.venue
        and identity.identity.metadata_version == binding.metadata_version
        and identity.identity.product_type == binding.product_type
        and identity.identity.currency == binding.currency
    )
    if expected_fx_pair is not None:
        price_convention = getattr(details, "price_convention", None)
        normalized_price_convention = (
            price_convention.strip().casefold()
            if isinstance(price_convention, str)
            else None
        )
        from_currency, to_currency = expected_fx_pair
        quote_per_base_convention = f"{to_currency}_per_{from_currency}".casefold()
        valid = valid and (
            getattr(details, "kind", None) == "FX"
            and getattr(details, "base_currency", None) == from_currency
            and getattr(details, "quote_currency", None) == to_currency
            and expected_rate_convention == "to_per_from"
            and normalized_price_convention == quote_per_base_convention
        )
    if not valid:
        return _input_record("error", "MARKET_DATA_IDENTITY_BINDING_MISMATCH", binding), None
    if not execution.observations:
        coverage = _coverage(execution)
        status = "missing" if coverage["status"] == "complete" else "coverage_incomplete"
        code = "MARKET_DATA_VALUE_MISSING" if status == "missing" else "MARKET_DATA_COVERAGE_INCOMPLETE"
        return _input_record(status, code, binding, query_id=query.query_fingerprint, coverage=coverage), None

    observation = max(
        execution.observations,
        key=lambda item: (_aware_utc(item.event_at), item.revision_number),
    )
    raw_value = observation.fields.get(binding.value_field)
    if observation.quality.value != "pass":
        return _input_record("error", "MARKET_DATA_OBSERVATION_QUALITY_REJECTED", binding, value=_number_text(raw_value), observation=observation, execution=execution), observation
    try:
        value = _to_decimal(raw_value)
    except (InvalidOperation, ValueError, TypeError):
        return _input_record("error", "MARKET_DATA_VALUE_INVALID", binding, observation=observation, execution=execution), observation
    if value is None:
        return _input_record("missing", "MARKET_DATA_VALUE_MISSING", binding, observation=observation, execution=execution), observation
    age = (now - _aware_utc(observation.event_at)).total_seconds()
    if age < 0:
        status, code = "error", "MARKET_DATA_EVENT_TIME_IN_FUTURE"
    elif age > binding.freshness_max_age_seconds:
        status, code = "stale", "MARKET_DATA_OBSERVATION_STALE"
    elif _text(execution.coverage.status) != "complete" or execution.next_cursor is not None:
        status, code = "coverage_incomplete", "MARKET_DATA_COVERAGE_INCOMPLETE"
    else:
        status, code = "available", None
    result = _input_record(status, code, binding, value=format(value, "f"), observation=observation, execution=execution)
    result["age_seconds"] = max(0, age)
    result["freshness_max_age_seconds"] = binding.freshness_max_age_seconds
    return result, observation


def _input_record(
    status: InputStatus,
    code: str | None,
    binding: MarketDataReadBinding | None = None,
    *,
    value: str | None = None,
    query_id: str | None = None,
    observation: Any | None = None,
    execution: MarketDataQueryExecution | None = None,
    coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status, "code": code, "value": value}
    if binding is not None:
        result.update(
            {
                "currency": binding.currency,
                "unit": binding.unit,
                "price_basis": binding.price_basis,
                "source": {
                    "binding_ref": binding.binding_ref,
                    "binding_version": binding.binding_version,
                    "provenance_ref": binding.provenance_ref,
                    "canonical_id": binding.canonical_id,
                    "metadata_version": binding.metadata_version,
                    "family_id": binding.family_id,
                    "family_contract_version": binding.family_contract_version,
                    "source_policy_id": binding.source_policy_id,
                    "query_id": query_id,
                },
            }
        )
    if observation is not None:
        result.update(
            {
                "observed_at_utc": _iso(observation.event_at),
                "available_at_utc": _iso(observation.available_at),
                "committed_at_utc": _iso(observation.committed_at),
                "quality": _text(observation.quality),
                "revision_id": observation.revision_id,
                "source_snapshot_id": observation.source_snapshot_id,
                "revision_number": observation.revision_number,
            }
        )
    if execution is not None:
        result["coverage"] = _coverage(execution)
        result["query_cut"] = {
            "knowledge_cutoff_utc": _iso(execution.knowledge_cutoff),
            "identity_knowledge_cutoff_utc": _iso(execution.identity_knowledge_cutoff),
            "cursor_available": execution.next_cursor is not None,
            "fetches": [
                {
                    "route_id": item.route_id,
                    "provider_id": item.provider_id,
                    "source_snapshot_id": item.source_snapshot_id,
                }
                for item in execution.fetches
            ],
            "warnings": [_text(item.code) for item in execution.warnings],
        }
    elif coverage is not None:
        result["coverage"] = coverage
    return result


def _multiplier(position: dict[str, Any], binding: InstrumentValuationBinding, at: datetime | None) -> None:
    if binding.multiplier is None:
        _input(position, "contract_multiplier", "unsupported", "CONTRACT_MULTIPLIER_UNSUPPORTED", provenance_ref=binding.multiplier_provenance_ref, metadata_version=binding.multiplier_metadata_version)
    elif at is None:
        _input(
            position,
            "contract_multiplier",
            "unavailable",
            "ACCOUNT_POSITION_TIMESTAMP_MISSING",
            value=format(binding.multiplier, "f"),
            quantity_unit=binding.quantity_unit,
            provenance_ref=binding.multiplier_provenance_ref,
            metadata_version=binding.multiplier_metadata_version,
            valid_from_utc=_iso(binding.multiplier_valid_from_utc),
            valid_to_utc=_iso(binding.multiplier_valid_to_utc),
        )
    elif not _active(binding.multiplier_valid_from_utc, binding.multiplier_valid_to_utc, at):
        _input(
            position,
            "contract_multiplier",
            "stale",
            "CONTRACT_MULTIPLIER_OUTSIDE_VALIDITY",
            value=format(binding.multiplier, "f"),
            quantity_unit=binding.quantity_unit,
            provenance_ref=binding.multiplier_provenance_ref,
            metadata_version=binding.multiplier_metadata_version,
            valid_from_utc=_iso(binding.multiplier_valid_from_utc),
            valid_to_utc=_iso(binding.multiplier_valid_to_utc),
        )
    elif position.get("qty_unit") != binding.quantity_unit:
        _input(
            position,
            "contract_multiplier",
            "error",
            "CONTRACT_MULTIPLIER_UNIT_MISMATCH",
            value=format(binding.multiplier, "f"),
            quantity_unit=binding.quantity_unit,
            position_quantity_unit=position.get("qty_unit"),
            provenance_ref=binding.multiplier_provenance_ref,
            metadata_version=binding.multiplier_metadata_version,
            valid_from_utc=_iso(binding.multiplier_valid_from_utc),
            valid_to_utc=_iso(binding.multiplier_valid_to_utc),
        )
    else:
        _input(
            position,
            "contract_multiplier",
            "available",
            None,
            value=format(binding.multiplier, "f"),
            quantity_unit=binding.quantity_unit,
            provenance_ref=binding.multiplier_provenance_ref,
            metadata_version=binding.multiplier_metadata_version,
            valid_from_utc=_iso(binding.multiplier_valid_from_utc),
            valid_to_utc=_iso(binding.multiplier_valid_to_utc),
        )


def _input(position: dict[str, Any], name: str, status: InputStatus, code: str | None, **extra: Any) -> None:
    position.setdefault("valuation_inputs", {})[name] = {"status": status, "code": code, "value": extra.pop("value", None), **extra}


def _unavailable(position: dict[str, Any], code: str, *, unsupported: bool = False) -> None:
    status: InputStatus = "unsupported" if unsupported else "unavailable"
    for name in ("mark_price", "contract_multiplier", "fx_rate"):
        _input(position, name, status, code)
    _overall(position)


def _overall(position: dict[str, Any]) -> None:
    inputs = position.setdefault("valuation_inputs", {})
    statuses = [inputs.get(key, {}).get("status") for key in ("mark_price", "contract_multiplier", "fx_rate")]
    for status in ("error", "unavailable", "coverage_incomplete", "stale", "missing", "unsupported"):
        if status in statuses:
            inputs["status"] = status
            break
    else:
        inputs["status"] = "available"
    inputs["market_value"] = {"status": "not_calculated", "code": "AFI04_VALUATION_NOT_CALCULATED", "value": None}


def _cut(account_at: object, execution: MarketDataQueryExecution | None, observation: Any | None, binding: MarketDataReadBinding) -> dict[str, Any]:
    account_time = _parse_time(account_at)
    market_time = _aware_utc(observation.event_at) if observation is not None else None
    return {
        "cut_model": "independent_account_and_market_data_cuts",
        "atomic": False,
        "account_position_observed_at_utc": _iso(account_time),
        "market_event_at_utc": _iso(market_time),
        "market_available_at_utc": _iso(observation.available_at) if observation is not None else None,
        "market_committed_at_utc": _iso(observation.committed_at) if observation is not None else None,
        "account_to_market_skew_ns": _skew_ns(account_time, market_time),
        "query_id": execution.context.query.query_fingerprint if execution else None,
        "knowledge_cutoff_utc": _iso(execution.knowledge_cutoff) if execution else None,
        "identity_metadata_version": binding.metadata_version,
        "cursor_available": bool(execution and execution.next_cursor is not None),
        "coverage": _coverage(execution) if execution else None,
    }


def _coverage(execution: MarketDataQueryExecution) -> dict[str, Any]:
    value = execution.coverage
    return {
        "status": _text(value.status),
        "expected_event_count": len(value.expected_event_keys),
        "accepted_event_count": len(value.accepted_event_keys),
        "missing_event_count": len(value.missing_event_keys),
        "coverage_ratio": value.coverage_ratio,
        "rejection_counts": dict(value.rejection_counts),
        "next_page_available": execution.next_cursor is not None,
    }


def _positions(projection: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for account in projection.get("accounts", ()):
        observation = account.get("provider_observation")
        if isinstance(observation, Mapping) and observation.get("status") in {"available", "stale"}:
            result.extend(item for item in observation.get("positions", ()) if isinstance(item, dict))
    return result


def _summary(positions: Any, *, code: str | None) -> dict[str, Any]:
    rows = list(positions)
    counts: dict[str, int] = {}
    event_times: list[datetime] = []
    for position in rows:
        inputs = position.get("valuation_inputs", {})
        status = str(inputs.get("status", "unavailable"))
        counts[status] = counts.get(status, 0) + 1
        event_time = _parse_time(inputs.get("market_cut", {}).get("market_event_at_utc"))
        if event_time is not None:
            event_times.append(event_time)
    event_times.sort()
    return {
        "status": "not_collected" if not rows else "current" if all(row.get("valuation_inputs", {}).get("status") == "available" for row in rows) else "incomplete",
        "code": code,
        "position_count": len(rows),
        "position_status_counts": counts,
        "cut_model": "independent_market_query_per_identity",
        "atomic": False,
        "market_event_skew_ns": _skew_ns(event_times[0], event_times[-1]) if len(event_times) > 1 else None,
        "reconciliation_status": "not_established",
        "account_total_included": False,
        "creditable": False,
    }


def _active(start: datetime, end: datetime | None, at: datetime) -> bool:
    at = _aware_utc(at)
    return _aware_utc(start) <= at and (end is None or at < _aware_utc(end))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return value.astimezone(UTC)


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        try:
            return _aware_utc(value)
        except ValueError:
            return None
    if isinstance(value, str):
        try:
            return _aware_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("market value is not numeric")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("market value is not finite")
    return result


def _number_text(value: object) -> str | None:
    try:
        number = _to_decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return format(number, "f") if number is not None else None


def _text(value: object) -> str:
    return str(getattr(value, "value", value))


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _aware_utc(value).isoformat().replace("+00:00", "Z")
    return str(value)


def _skew_ns(first: datetime | None, second: datetime | None) -> str | None:
    if first is None or second is None:
        return None
    delta = second - first
    return str((delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000)


def _utc_now() -> datetime:
    return datetime.now(UTC)
