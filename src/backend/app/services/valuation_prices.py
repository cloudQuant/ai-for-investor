"""Price, size, currency, and PnL calculations for trading positions."""

from __future__ import annotations

from typing import Any

from app.services.trading_asset_info_service import (
    LONG_POSITION_FIELD_KEYS,
    POSITION_SIZE_FIELD_KEYS,
    SHORT_POSITION_FIELD_KEYS,
)
from app.services.valuation_numeric import (
    _COMMON_QUOTE_SUFFIXES,
    EPSILON,
    MARKABLE_NET_PNL_FIELD_KEYS,
    _explicit_inverse_flag,
    _first_number,
    _first_text,
    _normalise_rate,
    safe_float,
)
from app.services.valuation_types import PositionSpec


def _row_multiplier(
    row: dict[str, Any],
    spec: PositionSpec,
    *,
    inverse_contract: bool = False,
) -> float:
    values = (
        (
            row.get("contract_value"),
            row.get("contractValue"),
            row.get("contract_value_amount"),
            row.get("contractValueAmount"),
            row.get("contract_notional_value"),
            row.get("okx_contract_value"),
            row.get("ctVal"),
            row.get("multiplier"),
            row.get("mult"),
            row.get("contract_size"),
            row.get("trade_contract_size"),
            row.get("contract_multiplier"),
            row.get("ctMult"),
            row.get("VolumeMultiple"),
            row.get("CONTRACT_MULTIPLIER"),
        )
        if inverse_contract
        else (
            row.get("multiplier"),
            row.get("mult"),
            row.get("contract_size"),
            row.get("trade_contract_size"),
            row.get("contract_notional_value"),
            row.get("okx_contract_value"),
            row.get("contract_multiplier"),
            row.get("ctVal"),
            row.get("ctMult"),
            row.get("VolumeMultiple"),
            row.get("CONTRACT_MULTIPLIER"),
        )
    )
    return max(_first_number(*values, default=spec.multiplier) or spec.multiplier, EPSILON)


def _row_size(row: dict[str, Any]) -> float:
    long_position = _first_number(*(row.get(key) for key in LONG_POSITION_FIELD_KEYS))
    short_position = _first_number(*(row.get(key) for key in SHORT_POSITION_FIELD_KEYS))
    size_value = None
    for key in POSITION_SIZE_FIELD_KEYS:
        value = row.get(key)
        if value in (None, ""):
            continue
        size_value = value
        break
    size_number = _first_number(size_value)
    has_explicit_size = size_value not in (None, "") and size_number is not None
    size = safe_float(size_number, 0.0) or 0.0
    if (
        not has_explicit_size
        and abs(size) <= EPSILON
        and (long_position is not None or short_position is not None)
    ):
        long_size = max(long_position or 0.0, 0.0)
        short_size = max(short_position or 0.0, 0.0)
        if long_size > EPSILON or short_size > EPSILON:
            return long_size - short_size
    direction_key = ""
    direction_value = ""
    for key in (
        "direction",
        "side",
        "position_side",
        "positionSide",
        "PositionSide",
        "posSide",
        "positionIdx",
        "position_idx",
        "trade_action",
        "position_type",
        "type",
        "PosiDirection",
        "posi_direction",
        "position_direction",
    ):
        value = row.get(key)
        if value not in (None, ""):
            direction_key = key
            direction_value = str(value).strip()
            break
    direction = direction_value.lower()
    if direction in {"short", "sell", "sold", "position_type_sell", "deal_type_sell"}:
        return -abs(size)
    if direction == "flat":
        return 0.0
    try:
        code = int(float(direction_value))
    except (TypeError, ValueError):
        code = None
    if direction_key in {"trade_action", "position_type", "type"} and code == 1:
        return -abs(size)
    if direction_key in {"PosiDirection", "posi_direction", "position_direction"} and code == 3:
        return -abs(size)
    if direction_key in {"positionIdx", "position_idx"} and code == 2:
        return -abs(size)
    return size


def _row_margin_rate(row: dict[str, Any], spec: PositionSpec, size: float) -> float:
    margin_value = _first_number(
        row.get("margin"),
        row.get("margin_rate"),
        row.get("margin_ratio"),
        row.get("required_margin_percent"),
        row.get("require_margin_percent"),
        row.get("maintain_margin_percent"),
        row.get("MARGIN_RATIO"),
    )
    if margin_value is not None:
        return _normalise_rate(margin_value, spec.margin_rate)
    leverage = _first_number(
        row.get("leverage"),
        row.get("lever"),
        row.get("max_leverage"),
        row.get("maxLeverage"),
    )
    if leverage and leverage > 0:
        return 1.0 / leverage
    if size > 0:
        row_long_value = _first_number(
            row.get("long_margin_rate"),
            row.get("LongMarginRatio"),
            row.get("LongMarginRatioByMoney"),
            row.get("LONG_MARGIN_RATE"),
            row.get("MARGIN_BUY"),
        )
        if row_long_value is not None:
            return _normalise_rate(row_long_value, spec.margin_rate)
    if size < 0:
        row_short_value = _first_number(
            row.get("short_margin_rate"),
            row.get("ShortMarginRatio"),
            row.get("ShortMarginRatioByMoney"),
            row.get("SHORT_MARGIN_RATE"),
            row.get("MARGIN_SELL"),
        )
        if row_short_value is not None:
            return _normalise_rate(row_short_value, spec.margin_rate)
    if size > 0 and spec.long_margin_rate is not None:
        return spec.long_margin_rate
    if size < 0 and spec.short_margin_rate is not None:
        return spec.short_margin_rate
    return spec.margin_rate


def _currency_code(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip().upper() if ch.isalnum())


def _contract_value_currency(row: dict[str, Any], spec: PositionSpec) -> str:
    return _currency_code(
        _first_text(
            row.get("contract_value_currency"),
            row.get("contract_value_ccy"),
            row.get("ctValCcy"),
            row.get("contractValueCurrency"),
            spec.contract_value_currency,
        )
    )


def _row_contract_text(row: dict[str, Any], spec: PositionSpec, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _is_inverse_contract(row: dict[str, Any], spec: PositionSpec) -> bool:
    explicit_flag = _explicit_inverse_flag(row)
    if explicit_flag is not None:
        return explicit_flag

    contract_type = _first_text(
        row.get("contract_type"),
        row.get("ctType"),
        row.get("contractType"),
        row.get("category"),
        spec.contract_type,
    ).lower()
    if "inverse" in contract_type:
        return True
    if "linear" in contract_type:
        return False
    if spec.is_inverse is not None:
        return spec.is_inverse

    contract_ccy = _contract_value_currency(row, spec)
    if not contract_ccy:
        return False
    base_ccy = _currency_code(
        _first_text(
            _row_contract_text(row, spec, "base_asset", "baseCcy"),
            spec.base_asset,
        )
    )
    quote_ccy = _currency_code(
        _first_text(
            _row_contract_text(row, spec, "quote_asset", "quoteCcy"),
            spec.quote_asset,
        )
    )
    settle_ccy = _currency_code(
        _first_text(
            _row_contract_text(row, spec, "settle_currency", "settleCcy"),
            _row_contract_text(row, spec, "fee_currency", "feeCcy"),
            spec.settle_currency,
            spec.fee_currency,
        )
    )
    if quote_ccy and contract_ccy == quote_ccy and contract_ccy != base_ccy:
        return True
    return bool(base_ccy and settle_ccy == base_ccy and contract_ccy != base_ccy)


def _position_notional(
    size: float,
    price: float,
    multiplier: float,
    *,
    inverse_contract: bool = False,
) -> float:
    abs_size = abs(float(size or 0.0))
    if abs_size <= EPSILON:
        return 0.0
    if inverse_contract:
        return abs_size * multiplier
    return abs_size * float(price or 0.0) * multiplier


def _calculated_gross_pnl(
    *,
    size: float,
    entry_price: float,
    current_price: float,
    multiplier: float,
    inverse_contract: bool = False,
) -> float:
    if inverse_contract:
        if entry_price <= EPSILON or current_price <= EPSILON:
            return 0.0
        return float(size or 0.0) * multiplier * ((current_price / entry_price) - 1.0)
    return (current_price - entry_price) * size * multiplier


def _commission_rate_for_role(spec: PositionSpec, role: str = "open") -> float:
    role_text = str(role or "open").strip().lower()
    if role_text == "open":
        if spec.open_commission_rate is not None:
            return spec.open_commission_rate
        if spec.taker_commission_rate is not None:
            return max(spec.taker_commission_rate, 0.0)
        return spec.commission_rate
    if role_text in {"close_today", "closetoday"}:
        if spec.close_today_commission_rate is not None:
            return spec.close_today_commission_rate
        if spec.close_commission_rate is not None:
            return spec.close_commission_rate
        if spec.taker_commission_rate is not None:
            return max(spec.taker_commission_rate, 0.0)
        return spec.commission_rate
    if role_text in {"close_yesterday", "closeyesterday"}:
        if spec.close_yesterday_commission_rate is not None:
            return spec.close_yesterday_commission_rate
        if spec.close_commission_rate is not None:
            return spec.close_commission_rate
        if spec.taker_commission_rate is not None:
            return max(spec.taker_commission_rate, 0.0)
        return spec.commission_rate
    if role_text == "close":
        if spec.close_commission_rate is not None:
            return spec.close_commission_rate
        if spec.taker_commission_rate is not None:
            return max(spec.taker_commission_rate, 0.0)
        return spec.commission_rate
    if role_text == "maker" and spec.maker_commission_rate is not None:
        return spec.maker_commission_rate
    if role_text == "taker" and spec.taker_commission_rate is not None:
        return spec.taker_commission_rate
    return spec.commission_rate


def _commission_amount_for_role(spec: PositionSpec, role: str = "open") -> float:
    role_text = str(role or "open").strip().lower()
    if role_text == "open":
        if spec.open_commission_amount is not None:
            return spec.open_commission_amount
        return spec.commission_amount
    if role_text in {"close_today", "closetoday"}:
        if spec.close_today_commission_amount is not None:
            return spec.close_today_commission_amount
        if spec.close_commission_amount is not None:
            return spec.close_commission_amount
        return spec.commission_amount
    if role_text in {"close_yesterday", "closeyesterday"}:
        if spec.close_yesterday_commission_amount is not None:
            return spec.close_yesterday_commission_amount
        if spec.close_commission_amount is not None:
            return spec.close_commission_amount
        return spec.commission_amount
    if role_text == "close" and spec.close_commission_amount is not None:
        return spec.close_commission_amount
    return spec.commission_amount


def _estimate_commission_for_role(
    *,
    size: float,
    price: float,
    multiplier: float,
    spec: PositionSpec,
    role: str,
    inverse_contract: bool = False,
) -> float:
    abs_size = abs(float(size or 0.0))
    if abs_size <= EPSILON:
        return 0.0
    notional = _position_notional(
        abs_size,
        price,
        multiplier,
        inverse_contract=inverse_contract,
    )
    return notional * _commission_rate_for_role(
        spec, role
    ) + abs_size * _commission_amount_for_role(spec, role)


def _compact_symbol(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _row_symbol(row: dict[str, Any]) -> str:
    return _first_text(
        row.get("data_name"),
        row.get("symbol"),
        row.get("instrument"),
        row.get("InstrumentID"),
        row.get("contract"),
        row.get("instrument_id"),
        row.get("instId"),
        row.get("position_symbol_name"),
        row.get("symbol_name"),
    )


def _row_fee_currency(row: dict[str, Any]) -> str:
    fee_currency = _nested_fee_currency(
        row.get("fee"),
        row.get("fees"),
        row.get("commission"),
        row.get("comm"),
        row.get("Commission"),
        row.get("commissionAmount"),
        row.get("trade_fee"),
        row.get("tradeFee"),
        row.get("fillFee"),
        row.get("execFee"),
        row.get("execCommission"),
    )
    return _currency_code(
        _first_text(
            row.get("fee_currency"),
            row.get("trade_fee_currency"),
            row.get("commissionAsset"),
            row.get("commission_asset"),
            row.get("feeCurrency"),
            row.get("fillFeeCcy"),
            row.get("fill_fee_currency"),
            row.get("feeCcy"),
            row.get("fee_ccy"),
            fee_currency,
        )
    )


def _nested_fee_currency(*values: Any) -> str:
    currencies: list[str] = []
    seen: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            currency = _first_text(
                value.get("currency"),
                value.get("ccy"),
                value.get("asset"),
                value.get("coin"),
                value.get("fee_currency"),
                value.get("feeCurrency"),
                value.get("feeCcy"),
                value.get("commissionAsset"),
                value.get("commission_asset"),
            )
            code = _currency_code(currency)
            if code and code not in seen:
                seen.add(code)
                currencies.append(code)
            for nested_key in ("fee", "fees", "commission", "comm"):
                nested = value.get(nested_key)
                if nested is not value:
                    collect(nested)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                collect(item)

    for value in values:
        collect(value)
    if not currencies:
        return ""
    return currencies[0] if len(currencies) == 1 else "mixed"


_RAW_EXCHANGE_GROSS_PNL_KEYS = frozenset(
    {
        "position_unrealized_pnl",
        "position_unrealised_pnl",
        "unrealized_profit",
        "unrealised_profit",
        "unrealizedProfit",
        "unrealisedProfit",
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
    }
)
_RECALCULABLE_POSITION_PNL_KEYS = frozenset(
    (*MARKABLE_NET_PNL_FIELD_KEYS, "gross_pnl", "position_profit", "PositionProfit")
)


def _row_pnl_currency(row: dict[str, Any]) -> str:
    return _currency_code(
        _first_text(
            row.get("pnl_currency"),
            row.get("pnlCurrency"),
            row.get("pnlCcy"),
            row.get("uplCcy"),
            row.get("unrealizedPnlCurrency"),
            row.get("unrealisedPnlCurrency"),
            row.get("profit_currency"),
            row.get("profitCurrency"),
            row.get("currency"),
            row.get("ccy"),
        )
    )


def _quote_currency_candidates(
    row: dict[str, Any],
    spec: PositionSpec,
    *,
    inverse_contract: bool = False,
) -> set[str]:
    candidates = {
        _currency_code(
            _first_text(
                row.get("quote_asset"),
                row.get("quoteCcy"),
                spec.quote_asset,
            )
        )
    }
    if inverse_contract:
        candidates.add(
            _currency_code(
                _first_text(
                    row.get("contract_value_currency"),
                    row.get("contract_value_ccy"),
                    row.get("ctValCcy"),
                    row.get("contractValueCurrency"),
                    spec.contract_value_currency,
                )
            )
        )
    compact = _compact_symbol(_row_symbol(row))
    for quote in _COMMON_QUOTE_SUFFIXES:
        if compact.endswith(quote) and len(compact) > len(quote):
            candidates.add(quote)
    return {item for item in candidates if item}


def _base_currency_candidates(
    row: dict[str, Any],
    spec: PositionSpec,
    *,
    inverse_contract: bool = False,
) -> set[str]:
    candidates = {
        _currency_code(
            _first_text(
                row.get("base_asset"),
                row.get("baseCcy"),
                spec.base_asset,
            )
        )
    }
    if inverse_contract:
        candidates.add(
            _currency_code(
                _first_text(
                    row.get("settle_currency"),
                    row.get("settleCcy"),
                    spec.settle_currency,
                )
            )
        )
    compact = _compact_symbol(_row_symbol(row))
    for quote in _COMMON_QUOTE_SUFFIXES:
        if compact.endswith(quote) and len(compact) > len(quote):
            candidates.add(compact[: -len(quote)])
    return {item for item in candidates if item}


def _fee_conversion_rate(
    row: dict[str, Any],
    spec: PositionSpec,
    *,
    entry_price: float | None = None,
    current_price: float | None = None,
    inverse_contract: bool = False,
) -> float | None:
    fee_currency = _row_fee_currency(row)
    if not fee_currency:
        return 1.0
    if fee_currency in _quote_currency_candidates(
        row,
        spec,
        inverse_contract=inverse_contract,
    ):
        return 1.0
    if fee_currency in _base_currency_candidates(
        row,
        spec,
        inverse_contract=inverse_contract,
    ):
        price = _first_number(
            row.get("fee_price"),
            row.get("fillPx"),
            row.get("fill_price"),
            row.get("execPrice"),
            row.get("exec_price"),
            row.get("price"),
            row.get("avgPx"),
            row.get("avg_price"),
            row.get("avgPrice"),
            entry_price,
            current_price,
        )
        if price is not None and price > EPSILON:
            return price
    return None


def _pnl_valuation_conversion_rate(
    row: dict[str, Any],
    spec: PositionSpec,
    *,
    current_price: float | None = None,
    inverse_contract: bool = False,
    field_key: str | None = None,
) -> float | None:
    pnl_currency = _row_pnl_currency(row)
    if pnl_currency:
        if pnl_currency in _quote_currency_candidates(
            row,
            spec,
            inverse_contract=inverse_contract,
        ):
            return 1.0
        if pnl_currency in _base_currency_candidates(
            row,
            spec,
            inverse_contract=inverse_contract,
        ):
            price = current_price or _first_number(
                row.get("markPx"),
                row.get("mark_price"),
                row.get("current_price"),
                row.get("last_price"),
                row.get("lastPrice"),
            )
            if price and price > EPSILON:
                return price
            return None
        return 1.0

    if inverse_contract and str(field_key or "") in _RAW_EXCHANGE_GROSS_PNL_KEYS:
        settlement_currency = _currency_code(
            _first_text(
                row.get("settle_currency"),
                row.get("settleCcy"),
                row.get("settleCoin"),
                spec.settle_currency,
            )
        )
        if settlement_currency and settlement_currency in _quote_currency_candidates(
            row,
            spec,
            inverse_contract=inverse_contract,
        ):
            return 1.0
        price = current_price or _first_number(
            row.get("markPx"),
            row.get("mark_price"),
            row.get("current_price"),
            row.get("last_price"),
            row.get("lastPrice"),
        )
        if price and price > EPSILON:
            return price
        return None
    return 1.0


def _normalized_pnl_amount(
    row: dict[str, Any],
    spec: PositionSpec,
    *,
    field_key: str | None,
    value: Any,
    current_price: float | None = None,
    inverse_contract: bool = False,
) -> float | None:
    amount = safe_float(value, None)
    if amount is None:
        return None
    conversion_rate = _pnl_valuation_conversion_rate(
        row,
        spec,
        current_price=current_price,
        inverse_contract=inverse_contract,
        field_key=field_key,
    )
    if conversion_rate is None:
        return None
    return amount * conversion_rate


def _should_recalculate_generic_pnl(
    *,
    field_key: str | None,
    explicit_net_pnl_value: Any,
    size: float,
    entry_price: float,
    current_price: float,
    multiplier: float,
    has_multiplier: bool,
) -> bool:
    if explicit_net_pnl_value not in (None, ""):
        return False
    if field_key not in _RECALCULABLE_POSITION_PNL_KEYS:
        return False
    if not has_multiplier:
        return False
    return (
        abs(size) > EPSILON
        and entry_price > EPSILON
        and current_price > EPSILON
        and multiplier > EPSILON
    )


def _numbers_close(left: float, right: float) -> bool:
    return abs(left - right) <= max(abs(left), abs(right), 1.0) * 1e-6


def _should_recalculate_unscaled_exchange_pnl(
    *,
    field_key: str | None,
    explicit_net_pnl_value: Any,
    explicit_gross_pnl_value: Any,
    size: float,
    entry_price: float,
    current_price: float,
    multiplier: float,
    has_multiplier: bool,
    inverse_contract: bool,
) -> bool:
    if explicit_net_pnl_value not in (None, ""):
        return False
    if field_key not in _RAW_EXCHANGE_GROSS_PNL_KEYS:
        return False
    if inverse_contract or not has_multiplier or multiplier <= 1.0 + EPSILON:
        return False
    explicit = safe_float(explicit_gross_pnl_value, None)
    if (
        abs(size) <= EPSILON
        or entry_price <= EPSILON
        or current_price <= EPSILON
        or explicit is None
    ):
        return False
    scaled = (current_price - entry_price) * size * multiplier
    unscaled = (current_price - entry_price) * size
    if _numbers_close(explicit, scaled):
        return False
    return _numbers_close(explicit, unscaled)
