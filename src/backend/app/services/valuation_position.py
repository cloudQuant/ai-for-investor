"""Position-row fee, margin, and explicit-price normalization helpers."""

from __future__ import annotations

from typing import Any

from app.services.valuation_numeric import (
    COMMISSION_FIELD_KEYS,
    EPSILON,
    OKX_SIGNED_FEE_FIELD_KEYS,
    _first_number,
    _first_number_with_key,
    _truthy,
    _uses_okx_fee_sign,
)
from app.services.valuation_prices import (
    _estimate_commission_for_role,
    _fee_conversion_rate,
)
from app.services.valuation_types import PositionSpec


def _row_commission(
    row: dict[str, Any],
    spec: PositionSpec,
    market_value: float,
    size: float,
    *,
    entry_market_value: float | None = None,
    multiplier: float | None = None,
    entry_price: float | None = None,
    current_price: float | None = None,
    inverse_contract: bool = False,
) -> float:
    explicit_key, explicit = _first_number_with_key(row, COMMISSION_FIELD_KEYS)
    if explicit is not None:
        explicit_commission: float | None = None
        if _truthy(row.get("commission_signed")):
            explicit_commission = explicit
        else:
            conversion_rate = _fee_conversion_rate(
                row,
                spec,
                entry_price=entry_price,
                current_price=current_price,
                inverse_contract=inverse_contract,
            )
            if conversion_rate is not None:
                if explicit_key in OKX_SIGNED_FEE_FIELD_KEYS and _uses_okx_fee_sign(row):
                    explicit_commission = -explicit * conversion_rate
                else:
                    explicit_commission = abs(explicit) * conversion_rate
        if explicit_commission is not None and not _zero_commission_needs_estimate(
            row,
            spec,
            explicit_commission,
        ):
            return explicit_commission
        # Incompatible fee currency, or an unconfirmed zero fee on an open
        # position. Fall back to a local asset-spec estimate.
    effective_multiplier = max(multiplier or spec.multiplier, EPSILON)
    if inverse_contract:
        effective_entry_price = float(entry_price or 0.0)
    else:
        fee_base = (
            entry_market_value if entry_market_value and entry_market_value > 0 else market_value
        )
        effective_entry_price = (
            fee_base / (abs(size) * effective_multiplier) if abs(size) > EPSILON else 0.0
        )
    return _estimate_commission_for_role(
        size=size,
        price=effective_entry_price,
        multiplier=effective_multiplier,
        spec=spec,
        role="open",
        inverse_contract=inverse_contract,
    )


def _row_margin_value(
    row: dict[str, Any],
    spec: PositionSpec,
    market_value: float,
    margin_rate: float,
    size: float,
) -> float:
    explicit = _first_number(
        row.get("margin_value"),
        row.get("use_margin"),
        row.get("initial_margin"),
        row.get("maintain_margin"),
        row.get("initialMargin"),
        row.get("maintMargin"),
        row.get("positionIM"),
        row.get("positionIMByMp"),
        row.get("positionMM"),
        row.get("positionMMByMp"),
        row.get("isolatedMargin"),
        row.get("isolated_margin"),
        row.get("imr"),
        row.get("mmr"),
    )
    if explicit is not None:
        return abs(explicit)
    row_margin_amount = _first_number(
        row.get("margin_amount"),
        row.get("initial_margin_per_lot"),
        row.get("margin_initial"),
        row.get("initial_margin_amount"),
        row.get("SYMBOL_MARGIN_INITIAL"),
        row.get("MARGIN_PER_LOT"),
    )
    if row_margin_amount is not None and row_margin_amount > 0:
        return abs(size) * row_margin_amount
    if size > 0:
        row_long_margin_amount = _first_number(
            row.get("long_margin_amount"),
            row.get("LongMarginRatioByVolume"),
            row.get("LONG_MARGIN_AMOUNT"),
            row.get("LONG_MARGIN_PER_LOT"),
        )
        if row_long_margin_amount is not None and row_long_margin_amount > 0:
            return abs(size) * row_long_margin_amount
        if spec.long_margin_amount is not None and spec.long_margin_amount > 0:
            return abs(size) * spec.long_margin_amount
    if size < 0:
        row_short_margin_amount = _first_number(
            row.get("short_margin_amount"),
            row.get("ShortMarginRatioByVolume"),
            row.get("SHORT_MARGIN_AMOUNT"),
            row.get("SHORT_MARGIN_PER_LOT"),
        )
        if row_short_margin_amount is not None and row_short_margin_amount > 0:
            return abs(size) * row_short_margin_amount
        if spec.short_margin_amount is not None and spec.short_margin_amount > 0:
            return abs(size) * spec.short_margin_amount
    if spec.margin_amount > 0:
        return abs(size) * spec.margin_amount
    return market_value * margin_rate


def _spec_has_nonzero_commission(spec: PositionSpec) -> bool:
    for value in (
        spec.commission_rate,
        spec.commission_amount,
        spec.open_commission_rate,
        spec.close_commission_rate,
        spec.close_today_commission_rate,
        spec.close_yesterday_commission_rate,
        spec.maker_commission_rate,
        spec.taker_commission_rate,
        spec.open_commission_amount,
        spec.close_commission_amount,
        spec.close_today_commission_amount,
        spec.close_yesterday_commission_amount,
    ):
        if value is not None and abs(float(value or 0.0)) > EPSILON:
            return True
    return False


def _zero_commission_needs_estimate(
    row: dict[str, Any],
    spec: PositionSpec,
    explicit_commission: float,
) -> bool:
    if abs(explicit_commission) > EPSILON:
        return False
    if str(row.get("commission_source") or "").strip().lower() == "gateway.trades":
        return False
    if _has_explicit_net_pnl(row):
        return False
    if not _spec_has_nonzero_commission(spec):
        return False
    return _has_any_gross_pnl(row) or _has_any_price(row)


def _has_explicit_net_pnl(row: dict[str, Any]) -> bool:
    return any(row.get(key) not in (None, "") for key in ("pnlcomm", "net_pnl", "netPnl", "netPNL"))


def _has_any_gross_pnl(row: dict[str, Any]) -> bool:
    return any(
        row.get(key) not in (None, "")
        for key in (
            "gross_pnl",
            "position_unrealized_pnl",
            "position_unrealised_pnl",
            "unrealized_profit",
            "unrealised_profit",
            "unRealizedProfit",
            "UnrealizedPnL",
            "unrealizedPnl",
            "unrealisedPnl",
            "unrealized_pnl",
            "unrealised_pnl",
            "unrealizedPNL",
            "unrealisedPNL",
            "unrealizedpnl",
            "unrealisedpnl",
            "floating_pnl",
            "upl",
            "up",
            "position_profit",
            "PositionProfit",
            "position_pnl",
            "profit",
            "pnl",
        )
    )


def _has_any_price(row: dict[str, Any]) -> bool:
    return any(
        row.get(key) not in (None, "")
        for key in (
            "price",
            "avg_price",
            "average_price",
            "price_open",
            "avgCost",
            "avgPrice",
            "avgPx",
            "entryPrice",
            "current_price",
            "latest_price",
            "last_price",
            "mark_price",
            "markPrice",
            "markPx",
            "market_price",
            "lastPrice",
            "LastPrice",
        )
    )


def _row_explicit_market_value(row: dict[str, Any]) -> float | None:
    if _truthy(row.get("market_value_estimated")):
        return None

    exchange_value = _first_number(
        row.get("marketValue"),
        row.get("MarketValue"),
        row.get("mktValue"),
        row.get("positionValue"),
        row.get("position_value"),
        row.get("notionalUsd"),
        row.get("notional_usd"),
        row.get("notional"),
        row.get("notionalValue"),
        row.get("notional_value"),
        row.get("position_notional_usd"),
        row.get("position_notional"),
        row.get("positionNotional"),
    )
    if exchange_value is not None and abs(exchange_value) > EPSILON:
        return abs(exchange_value)

    source_text = " ".join(
        str(row.get(key) or "").strip().lower()
        for key in ("position_source", "source", "asset_spec_source")
    )
    if "gateway" not in source_text:
        return None

    value = _first_number(
        row.get("market_value"),
        row.get("mktValue"),
        row.get("positionValue"),
        row.get("position_value"),
        row.get("notionalUsd"),
        row.get("notional_usd"),
        row.get("notional"),
        row.get("notionalValue"),
        row.get("notional_value"),
        row.get("position_notional_usd"),
        row.get("position_notional"),
        row.get("positionNotional"),
        row.get("value"),
    )
    if value is None or abs(value) <= EPSILON:
        return None
    return abs(value)


def _current_price(
    row: dict[str, Any],
    size: float,
    entry_price: float,
    multiplier: float,
    *,
    inverse_contract: bool = False,
) -> float:
    explicit = _first_number(
        row.get("current_price"),
        row.get("latest_price"),
        row.get("last_price"),
        row.get("last"),
        row.get("mark_price"),
        row.get("markPrice"),
        row.get("markPx"),
        row.get("index_price"),
        row.get("indexPrice"),
        row.get("idxPx"),
        row.get("market_price"),
        row.get("lastPrice"),
        row.get("LastPrice"),
        row.get("price_current"),
        row.get("marketPrice"),
        row.get("mktPrice"),
        row.get("mp"),
        row.get("PriceCurrent"),
        row.get("CurrentPrice"),
        row.get("SettlementPrice"),
        row.get("settlement_price"),
    )
    if explicit is not None and explicit > 0:
        return explicit

    market_value = abs(
        _first_number(
            row.get("market_value"),
            row.get("marketValue"),
            row.get("mktValue"),
            row.get("positionValue"),
            row.get("position_value"),
            row.get("notionalUsd"),
            row.get("notional_usd"),
            row.get("notional"),
            row.get("notionalValue"),
            row.get("notional_value"),
            row.get("position_notional_usd"),
            row.get("position_notional"),
            row.get("positionNotional"),
            row.get("value"),
            default=0.0,
        )
        or 0.0
    )
    if market_value > 0 and abs(size) > EPSILON and not inverse_contract:
        plain = market_value / abs(size)
        with_multiplier = market_value / (abs(size) * multiplier)
        if entry_price > 0 and multiplier > 1.0:
            return (
                plain
                if abs(plain - entry_price) <= abs(with_multiplier - entry_price)
                else with_multiplier
            )
        return plain

    return entry_price
