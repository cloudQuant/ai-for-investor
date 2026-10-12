"""Position valuation helpers for trading snapshots and portfolio views."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass as dataclass
from typing import Any
from typing import overload as overload

from app.services.trading_asset_info_service import (
    LONG_POSITION_FIELD_KEYS as LONG_POSITION_FIELD_KEYS,
)
from app.services.trading_asset_info_service import (
    POSITION_SIZE_FIELD_KEYS as POSITION_SIZE_FIELD_KEYS,
)
from app.services.trading_asset_info_service import (
    SHORT_POSITION_FIELD_KEYS as SHORT_POSITION_FIELD_KEYS,
)
from app.services.trading_asset_info_service import (
    symbol_aliases,
)
from app.services.valuation_numeric import (
    _COMMON_QUOTE_SUFFIXES as _COMMON_QUOTE_SUFFIXES,
)
from app.services.valuation_numeric import (
    _FIAT_CURRENCIES as _FIAT_CURRENCIES,
)
from app.services.valuation_numeric import (
    _MT5_FOREX_CONTRACT_SIZE as _MT5_FOREX_CONTRACT_SIZE,
)
from app.services.valuation_numeric import (
    _MT5_METAL_CONTRACT_SIZES as _MT5_METAL_CONTRACT_SIZES,
)
from app.services.valuation_numeric import (
    CARRY_PNL_FIELD_KEYS as CARRY_PNL_FIELD_KEYS,
)
from app.services.valuation_numeric import (
    COMMISSION_FIELD_KEYS as COMMISSION_FIELD_KEYS,
)
from app.services.valuation_numeric import (
    EPSILON as EPSILON,
)
from app.services.valuation_numeric import (
    EXPLICIT_NET_PNL_FIELD_KEYS as EXPLICIT_NET_PNL_FIELD_KEYS,
)
from app.services.valuation_numeric import (
    INVERSE_CONTRACT_FLAG_KEYS as INVERSE_CONTRACT_FLAG_KEYS,
)
from app.services.valuation_numeric import (
    MARKABLE_NET_PNL_FIELD_KEYS as MARKABLE_NET_PNL_FIELD_KEYS,
)
from app.services.valuation_numeric import (
    NET_PNL_FLAG_KEYS as NET_PNL_FLAG_KEYS,
)
from app.services.valuation_numeric import (
    OKX_SIGNED_FEE_FIELD_KEYS as OKX_SIGNED_FEE_FIELD_KEYS,
)
from app.services.valuation_numeric import (
    _as_dict as _as_dict,
)
from app.services.valuation_numeric import (
    _commission_amount_from_keys as _commission_amount_from_keys,
)
from app.services.valuation_numeric import (
    _commission_rate_from_config as _commission_rate_from_config,
)
from app.services.valuation_numeric import (
    _commission_rate_from_keys as _commission_rate_from_keys,
)
from app.services.valuation_numeric import (
    _explicit_inverse_flag as _explicit_inverse_flag,
)
from app.services.valuation_numeric import (
    _first_number as _first_number,
)
from app.services.valuation_numeric import (
    _first_number_with_key as _first_number_with_key,
)
from app.services.valuation_numeric import (
    _first_text as _first_text,
)
from app.services.valuation_numeric import (
    _normalise_ctp_commission_rate as _normalise_ctp_commission_rate,
)
from app.services.valuation_numeric import (
    _normalise_rate as _normalise_rate,
)
from app.services.valuation_numeric import (
    _normalise_signed_rate as _normalise_signed_rate,
)
from app.services.valuation_numeric import (
    _row_marks_pnl_as_net as _row_marks_pnl_as_net,
)
from app.services.valuation_numeric import (
    _sum_signed_amounts as _sum_signed_amounts,
)
from app.services.valuation_numeric import (
    _truthy as _truthy,
)
from app.services.valuation_numeric import (
    _uses_okx_fee_sign as _uses_okx_fee_sign,
)
from app.services.valuation_numeric import (
    safe_float as safe_float,
)
from app.services.valuation_position import (
    _current_price as _current_price,
)
from app.services.valuation_position import (
    _has_any_gross_pnl as _has_any_gross_pnl,
)
from app.services.valuation_position import (
    _has_any_price as _has_any_price,
)
from app.services.valuation_position import (
    _has_explicit_net_pnl as _has_explicit_net_pnl,
)
from app.services.valuation_position import (
    _row_commission as _row_commission,
)
from app.services.valuation_position import (
    _row_explicit_market_value as _row_explicit_market_value,
)
from app.services.valuation_position import (
    _row_margin_value as _row_margin_value,
)
from app.services.valuation_position import (
    _spec_has_nonzero_commission as _spec_has_nonzero_commission,
)
from app.services.valuation_position import (
    _zero_commission_needs_estimate as _zero_commission_needs_estimate,
)
from app.services.valuation_prices import (
    _RAW_EXCHANGE_GROSS_PNL_KEYS as _RAW_EXCHANGE_GROSS_PNL_KEYS,
)
from app.services.valuation_prices import (
    _RECALCULABLE_POSITION_PNL_KEYS as _RECALCULABLE_POSITION_PNL_KEYS,
)
from app.services.valuation_prices import (
    _base_currency_candidates as _base_currency_candidates,
)
from app.services.valuation_prices import (
    _calculated_gross_pnl as _calculated_gross_pnl,
)
from app.services.valuation_prices import (
    _commission_amount_for_role as _commission_amount_for_role,
)
from app.services.valuation_prices import (
    _commission_rate_for_role as _commission_rate_for_role,
)
from app.services.valuation_prices import (
    _compact_symbol as _compact_symbol,
)
from app.services.valuation_prices import (
    _contract_value_currency as _contract_value_currency,
)
from app.services.valuation_prices import (
    _currency_code as _currency_code,
)
from app.services.valuation_prices import (
    _estimate_commission_for_role as _estimate_commission_for_role,
)
from app.services.valuation_prices import (
    _fee_conversion_rate as _fee_conversion_rate,
)
from app.services.valuation_prices import (
    _is_inverse_contract as _is_inverse_contract,
)
from app.services.valuation_prices import (
    _nested_fee_currency as _nested_fee_currency,
)
from app.services.valuation_prices import (
    _normalized_pnl_amount as _normalized_pnl_amount,
)
from app.services.valuation_prices import (
    _numbers_close as _numbers_close,
)
from app.services.valuation_prices import (
    _pnl_valuation_conversion_rate as _pnl_valuation_conversion_rate,
)
from app.services.valuation_prices import (
    _position_notional as _position_notional,
)
from app.services.valuation_prices import (
    _quote_currency_candidates as _quote_currency_candidates,
)
from app.services.valuation_prices import (
    _row_contract_text as _row_contract_text,
)
from app.services.valuation_prices import (
    _row_fee_currency as _row_fee_currency,
)
from app.services.valuation_prices import (
    _row_margin_rate as _row_margin_rate,
)
from app.services.valuation_prices import (
    _row_multiplier as _row_multiplier,
)
from app.services.valuation_prices import (
    _row_pnl_currency as _row_pnl_currency,
)
from app.services.valuation_prices import (
    _row_size as _row_size,
)
from app.services.valuation_prices import (
    _row_symbol as _row_symbol,
)
from app.services.valuation_prices import (
    _should_recalculate_generic_pnl as _should_recalculate_generic_pnl,
)
from app.services.valuation_prices import (
    _should_recalculate_unscaled_exchange_pnl as _should_recalculate_unscaled_exchange_pnl,
)
from app.services.valuation_projection import (
    ValuedPosition as ValuedPosition,
)
from app.services.valuation_projection import (
    project_valued_position as project_valued_position,
)
from app.services.valuation_types import (
    PositionSpec as PositionSpec,
)


def _symbol_keys(symbol: str) -> set[str]:
    return set(symbol_aliases(symbol))


def _compact_symbol_text(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _compact_underlying_symbol(symbol: str) -> str:
    compact = _compact_symbol_text(symbol)
    if len(compact) >= 6:
        head = compact[:6]
        if head in _MT5_METAL_CONTRACT_SIZES:
            return head
        if head[:3] in _FIAT_CURRENCIES and head[3:6] in _FIAT_CURRENCIES:
            return head
    return compact


def _local_default_contract_spec(symbol: str) -> dict[str, Any]:
    compact = _compact_underlying_symbol(symbol)
    if compact in _MT5_METAL_CONTRACT_SIZES:
        return {
            "multiplier": _MT5_METAL_CONTRACT_SIZES[compact],
            "asset_type": "commodity",
            "source": "local_mt5_defaults",
        }
    if len(compact) == 6 and compact[:3] in _FIAT_CURRENCIES and compact[3:] in _FIAT_CURRENCIES:
        return {
            "multiplier": _MT5_FOREX_CONTRACT_SIZE,
            "asset_type": "forex",
            "source": "local_mt5_defaults",
        }
    return {}


def _allows_local_otc_default(config: dict[str, Any]) -> bool:
    asset_type_text = _first_text(
        config.get("asset_type"),
        config.get("assetClass"),
        config.get("category"),
        config.get("product_type"),
    ).lower()
    if asset_type_text in {
        "forex",
        "fx",
        "currency",
        "commodity",
        "metal",
        "metals",
        "cfd",
    }:
        return True

    context_text = " ".join(
        str(config.get(key) or "").strip().lower()
        for key in (
            "exchange",
            "exchange_id",
            "exchange_name",
            "gateway",
            "broker",
            "broker_type",
            "source",
            "asset_spec_source",
        )
    )
    return "mt5" in context_text or "metatrader" in context_text


def _contract_metadata(config: dict[str, Any], symbol: str) -> dict[str, Any]:
    keys = _symbol_keys(symbol)
    for container_key in ("contract_metadata", "contracts", "contract_specs", "instrument_specs"):
        container = config.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in keys:
            item = container.get(key)
            if isinstance(item, dict):
                return dict(item)
    return {}


def _config_is_inverse_contract(
    config: dict[str, Any],
    *,
    contract_type: str = "",
    contract_value_currency: str = "",
    base_asset: str = "",
    quote_asset: str = "",
    settle_currency: str = "",
    fee_currency: str = "",
) -> bool:
    explicit_flag = _explicit_inverse_flag(config)
    if explicit_flag is not None:
        return explicit_flag

    type_text = _first_text(
        config.get("contract_type"),
        config.get("ctType"),
        contract_type,
    ).lower()
    if "inverse" in type_text:
        return True
    if "linear" in type_text:
        return False

    contract_ccy = _currency_code(
        _first_text(
            config.get("contract_value_currency"),
            config.get("contract_value_ccy"),
            config.get("ctValCcy"),
            config.get("contractValueCurrency"),
            contract_value_currency,
        )
    )
    base_ccy = _currency_code(
        _first_text(config.get("base_asset"), config.get("baseCcy"), base_asset)
    )
    quote_ccy = _currency_code(
        _first_text(config.get("quote_asset"), config.get("quoteCcy"), quote_asset)
    )
    settle_ccy = _currency_code(
        _first_text(
            config.get("settle_currency"),
            config.get("settleCcy"),
            settle_currency,
        )
    )
    fee_ccy = _currency_code(
        _first_text(config.get("fee_currency"), config.get("feeCcy"), fee_currency)
    )
    if contract_ccy and quote_ccy and contract_ccy == quote_ccy and contract_ccy != base_ccy:
        return True
    if contract_ccy and base_ccy and contract_ccy == base_ccy:
        return False
    if base_ccy and quote_ccy and settle_ccy == base_ccy and settle_ccy != quote_ccy:
        return True
    return bool(
        (contract_ccy or settle_ccy)
        and base_ccy
        and quote_ccy
        and fee_ccy == base_ccy
        and fee_ccy != quote_ccy
    )


def _iter_configs(configs: Iterable[dict[str, Any] | None]) -> Iterable[dict[str, Any]]:
    for config in configs:
        if isinstance(config, dict):
            yield config


def contract_spec_for(
    symbol: str,
    *configs: dict[str, Any] | None,
) -> PositionSpec:
    """Extract contract multiplier, margin and commission settings.

    The UI stores these settings in several places depending on whether a unit
    came from a strategy template, a workspace override, or a live gateway
    instance. This helper intentionally accepts multiple dictionaries and uses
    the first explicit value it can find.
    """
    multiplier: float | None = None
    margin_rate: float | None = None
    margin_amount: float | None = None
    long_margin_rate: float | None = None
    short_margin_rate: float | None = None
    long_margin_amount: float | None = None
    short_margin_amount: float | None = None
    commission_rate: float | None = None
    commission_amount: float | None = None
    open_commission_rate: float | None = None
    close_commission_rate: float | None = None
    close_today_commission_rate: float | None = None
    close_yesterday_commission_rate: float | None = None
    maker_commission_rate: float | None = None
    taker_commission_rate: float | None = None
    open_commission_amount: float | None = None
    close_commission_amount: float | None = None
    close_today_commission_amount: float | None = None
    close_yesterday_commission_amount: float | None = None
    asset_type = ""
    contract_type = ""
    contract_value_currency = ""
    base_asset = ""
    quote_asset = ""
    settle_currency = ""
    fee_currency = ""
    source = ""
    is_inverse: bool | None = None
    has_multiplier = False
    has_margin_rate = False
    has_margin_amount = False
    has_commission = False
    allow_local_otc_default = False

    for config in _iter_configs(configs):
        if _allows_local_otc_default(config):
            allow_local_otc_default = True
        nested = [
            config,
            _as_dict(config.get("unit_settings")),
            _as_dict(config.get("params")),
            _as_dict(config.get("backtest")),
            _as_dict(config.get("simulate")),
            _as_dict(config.get("live")),
            _as_dict(config.get("gateway")),
            _as_dict(config.get("data")),
        ]
        meta = _contract_metadata(config, symbol)
        if meta:
            nested.insert(0, meta)
        for subconfig in nested:
            if not subconfig:
                continue
            if _allows_local_otc_default(subconfig):
                allow_local_otc_default = True
            subconfig_source = str(subconfig.get("source") or "").strip()
            if not asset_type:
                asset_type = _first_text(subconfig.get("asset_type"), subconfig.get("instType"))
            if not contract_type:
                contract_type = _first_text(subconfig.get("contract_type"), subconfig.get("ctType"))
            if not contract_value_currency:
                contract_value_currency = _first_text(
                    subconfig.get("contract_value_currency"),
                    subconfig.get("contract_value_ccy"),
                    subconfig.get("ctValCcy"),
                    subconfig.get("contractValueCurrency"),
                )
            if not base_asset:
                base_asset = _first_text(subconfig.get("base_asset"), subconfig.get("baseCcy"))
            if not quote_asset:
                quote_asset = _first_text(subconfig.get("quote_asset"), subconfig.get("quoteCcy"))
            if not settle_currency:
                settle_currency = _first_text(
                    subconfig.get("settle_currency"),
                    subconfig.get("settleCcy"),
                )
            if not fee_currency:
                fee_currency = _first_text(subconfig.get("fee_currency"), subconfig.get("feeCcy"))
            explicit_inverse = _explicit_inverse_flag(subconfig)
            if explicit_inverse is not None and is_inverse is None:
                is_inverse = explicit_inverse
            if multiplier is None:
                inverse_config = _config_is_inverse_contract(
                    subconfig,
                    contract_type=contract_type,
                    contract_value_currency=contract_value_currency,
                    base_asset=base_asset,
                    quote_asset=quote_asset,
                    settle_currency=settle_currency,
                    fee_currency=fee_currency,
                )
                if inverse_config and is_inverse is None:
                    is_inverse = True
                if inverse_config:
                    multiplier = _first_number(
                        subconfig.get("contract_value"),
                        subconfig.get("contractValue"),
                        subconfig.get("contract_value_amount"),
                        subconfig.get("contractValueAmount"),
                        subconfig.get("contract_notional_value"),
                        subconfig.get("okx_contract_value"),
                        subconfig.get("ctVal"),
                        subconfig.get("multiplier"),
                        subconfig.get("mult"),
                        subconfig.get("contract_size"),
                        subconfig.get("trade_contract_size"),
                        subconfig.get("contract_multiplier"),
                        subconfig.get("ctMult"),
                        subconfig.get("VolumeMultiple"),
                        subconfig.get("CONTRACT_MULTIPLIER"),
                    )
                else:
                    multiplier = _first_number(
                        subconfig.get("multiplier"),
                        subconfig.get("mult"),
                        subconfig.get("contract_size"),
                        subconfig.get("trade_contract_size"),
                        subconfig.get("contract_notional_value"),
                        subconfig.get("okx_contract_value"),
                        subconfig.get("contract_multiplier"),
                        subconfig.get("ctVal"),
                        subconfig.get("ctMult"),
                        subconfig.get("VolumeMultiple"),
                        subconfig.get("CONTRACT_MULTIPLIER"),
                    )
                if multiplier is not None:
                    has_multiplier = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if margin_rate is None:
                margin_value = _first_number(
                    subconfig.get("margin"),
                    subconfig.get("margin_rate"),
                    subconfig.get("margin_ratio"),
                    subconfig.get("required_margin_percent"),
                    subconfig.get("require_margin_percent"),
                    subconfig.get("maintain_margin_percent"),
                    subconfig.get("MARGIN_RATIO"),
                )
                if margin_value is not None:
                    margin_rate = _normalise_rate(margin_value, 1.0)
                    has_margin_rate = True
                    if subconfig_source and not source:
                        source = subconfig_source
                else:
                    leverage = _first_number(
                        subconfig.get("leverage"),
                        subconfig.get("lever"),
                        subconfig.get("max_leverage"),
                    )
                    if leverage and leverage > 0:
                        margin_rate = 1.0 / leverage
                        has_margin_rate = True
                        if subconfig_source and not source:
                            source = subconfig_source
            if margin_amount is None:
                margin_amount = _first_number(
                    subconfig.get("margin_amount"),
                    subconfig.get("initial_margin_per_lot"),
                    subconfig.get("margin_initial"),
                    subconfig.get("initial_margin_amount"),
                    subconfig.get("SYMBOL_MARGIN_INITIAL"),
                    subconfig.get("MARGIN_PER_LOT"),
                    subconfig.get("LONG_MARGIN_AMOUNT"),
                    subconfig.get("LONG_MARGIN_PER_LOT"),
                )
                if margin_amount is not None and margin_amount > 0:
                    has_margin_amount = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if long_margin_amount is None:
                long_amount_value = _first_number(
                    subconfig.get("long_margin_amount"),
                    subconfig.get("LongMarginRatioByVolume"),
                    subconfig.get("LONG_MARGIN_AMOUNT"),
                    subconfig.get("LONG_MARGIN_PER_LOT"),
                )
                if long_amount_value is not None and long_amount_value > 0:
                    long_margin_amount = long_amount_value
                    has_margin_amount = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if short_margin_amount is None:
                short_amount_value = _first_number(
                    subconfig.get("short_margin_amount"),
                    subconfig.get("ShortMarginRatioByVolume"),
                    subconfig.get("SHORT_MARGIN_AMOUNT"),
                    subconfig.get("SHORT_MARGIN_PER_LOT"),
                )
                if short_amount_value is not None and short_amount_value > 0:
                    short_margin_amount = short_amount_value
                    has_margin_amount = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if long_margin_rate is None:
                long_value = _first_number(
                    subconfig.get("long_margin_rate"),
                    subconfig.get("LongMarginRatio"),
                    subconfig.get("LongMarginRatioByMoney"),
                    subconfig.get("LONG_MARGIN_RATE"),
                    subconfig.get("MARGIN_BUY"),
                )
                if long_value is not None:
                    long_margin_rate = _normalise_rate(long_value, 1.0)
                    has_margin_rate = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if short_margin_rate is None:
                short_value = _first_number(
                    subconfig.get("short_margin_rate"),
                    subconfig.get("ShortMarginRatio"),
                    subconfig.get("ShortMarginRatioByMoney"),
                    subconfig.get("SHORT_MARGIN_RATE"),
                    subconfig.get("MARGIN_SELL"),
                )
                if short_value is not None:
                    short_margin_rate = _normalise_rate(short_value, 1.0)
                    has_margin_rate = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if commission_rate is None:
                commission_value = _commission_rate_from_config(subconfig)
                if commission_value is not None:
                    commission_rate = commission_value
                    has_commission = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if open_commission_rate is None:
                open_value = _commission_rate_from_keys(
                    subconfig,
                    (
                        "open_commission_rate",
                        "open_fee_rate",
                        "OpenRatioByMoney",
                        "OPEN_FEE_RATE",
                        "COMMISSION_OPEN_RATIO",
                    ),
                )
                if open_value is not None:
                    open_commission_rate = open_value
                    has_commission = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if close_commission_rate is None:
                close_value = _commission_rate_from_keys(
                    subconfig,
                    (
                        "close_commission_rate",
                        "close_fee_rate",
                        "CloseRatioByMoney",
                        "CLOSE_FEE_RATE",
                        "COMMISSION_CLOSE_RATIO",
                    ),
                )
                if close_value is not None:
                    close_commission_rate = close_value
                    has_commission = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if close_today_commission_rate is None:
                close_today_value = _commission_rate_from_keys(
                    subconfig,
                    (
                        "close_today_commission_rate",
                        "close_today_fee_rate",
                        "CloseTodayRatioByMoney",
                        "CLOSETODAY_FEE_RATE",
                        "CLOSE_TODAY_FEE_RATE",
                        "COMMISSION_CLOSE_TODAY_RATIO",
                    ),
                )
                if close_today_value is not None:
                    close_today_commission_rate = close_today_value
                    has_commission = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if close_yesterday_commission_rate is None:
                close_yesterday_value = _commission_rate_from_keys(
                    subconfig,
                    (
                        "close_yesterday_commission_rate",
                        "close_yesterday_fee_rate",
                        "CloseYesterdayRatioByMoney",
                        "CLOSEYESTERDAY_FEE_RATE",
                        "CLOSE_YESTERDAY_FEE_RATE",
                        "COMMISSION_CLOSE_YESTERDAY_RATIO",
                    ),
                )
                if close_yesterday_value is not None:
                    close_yesterday_commission_rate = close_yesterday_value
                    has_commission = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if maker_commission_rate is None:
                maker_value = _commission_rate_from_keys(
                    subconfig,
                    ("maker_commission_rate", "maker_fee_rate"),
                    signed=True,
                )
                if maker_value is not None:
                    maker_commission_rate = maker_value
                    has_commission = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if taker_commission_rate is None:
                taker_value = _commission_rate_from_keys(
                    subconfig,
                    ("taker_commission_rate", "taker_fee_rate"),
                    signed=True,
                )
                if taker_value is not None:
                    taker_commission_rate = taker_value
                    has_commission = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if commission_amount is None:
                if str(subconfig.get("commission_method") or "").lower() == "fixed_per_lot":
                    commission_amount = _first_number(
                        subconfig.get("open_commission_amount"),
                        subconfig.get("open_fee_amount"),
                        subconfig.get("open_commission_rate"),
                        subconfig.get("OpenRatioByVolume"),
                        subconfig.get("OPEN_FEE_AMOUNT"),
                        subconfig.get("OPEN_FEE_PER_LOT"),
                        subconfig.get("COMMISSION_OPEN_AMOUNT"),
                    )
                    if commission_amount is not None:
                        has_commission = True
                        if subconfig_source and not source:
                            source = subconfig_source
                if commission_amount is None:
                    commission_amount = _first_number(
                        subconfig.get("commission_amount"),
                        subconfig.get("fee_amount"),
                        subconfig.get("commission_per_lot"),
                        subconfig.get("open_fee_amount"),
                        subconfig.get("open_commission_amount"),
                        subconfig.get("OpenRatioByVolume"),
                        subconfig.get("OPEN_FEE_AMOUNT"),
                        subconfig.get("OPEN_FEE_PER_LOT"),
                        subconfig.get("COMMISSION_OPEN_AMOUNT"),
                    )
                    if commission_amount is not None:
                        has_commission = True
                        if subconfig_source and not source:
                            source = subconfig_source
            if open_commission_amount is None:
                open_amount = _commission_amount_from_keys(
                    subconfig,
                    (
                        "open_commission_amount",
                        "open_fee_amount",
                        "OpenRatioByVolume",
                        "OPEN_FEE_AMOUNT",
                        "OPEN_FEE_PER_LOT",
                        "COMMISSION_OPEN_AMOUNT",
                    ),
                )
                if open_amount is not None:
                    open_commission_amount = open_amount
                    has_commission = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if close_commission_amount is None:
                close_amount = _commission_amount_from_keys(
                    subconfig,
                    (
                        "close_commission_amount",
                        "close_fee_amount",
                        "CloseRatioByVolume",
                        "CLOSE_FEE_AMOUNT",
                        "CLOSE_FEE_PER_LOT",
                        "COMMISSION_CLOSE_AMOUNT",
                    ),
                )
                if close_amount is not None:
                    close_commission_amount = close_amount
                    has_commission = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if close_today_commission_amount is None:
                close_today_amount = _commission_amount_from_keys(
                    subconfig,
                    (
                        "close_today_commission_amount",
                        "close_today_fee_amount",
                        "CloseTodayRatioByVolume",
                        "CLOSETODAY_FEE_AMOUNT",
                        "CLOSE_TODAY_FEE_AMOUNT",
                        "CLOSE_TODAY_FEE_PER_LOT",
                        "COMMISSION_CLOSE_TODAY_AMOUNT",
                    ),
                )
                if close_today_amount is not None:
                    close_today_commission_amount = close_today_amount
                    has_commission = True
                    if subconfig_source and not source:
                        source = subconfig_source
            if close_yesterday_commission_amount is None:
                close_yesterday_amount = _commission_amount_from_keys(
                    subconfig,
                    (
                        "close_yesterday_commission_amount",
                        "close_yesterday_fee_amount",
                        "CloseYesterdayRatioByVolume",
                        "CLOSEYESTERDAY_FEE_AMOUNT",
                        "CLOSE_YESTERDAY_FEE_AMOUNT",
                        "CLOSE_YESTERDAY_FEE_PER_LOT",
                        "COMMISSION_CLOSE_YESTERDAY_AMOUNT",
                    ),
                )
                if close_yesterday_amount is not None:
                    close_yesterday_commission_amount = close_yesterday_amount
                    has_commission = True
                    if subconfig_source and not source:
                        source = subconfig_source

    if multiplier is None and allow_local_otc_default:
        local_default = _local_default_contract_spec(symbol)
        if local_default:
            multiplier = _first_number(local_default.get("multiplier"))
            has_multiplier = multiplier is not None
            if not asset_type:
                asset_type = _first_text(local_default.get("asset_type"))
            if not source:
                source = _first_text(local_default.get("source"))

    if commission_rate is None and taker_commission_rate is not None:
        commission_rate = taker_commission_rate
    if commission_rate is None and maker_commission_rate is not None:
        commission_rate = maker_commission_rate
    if open_commission_rate is None:
        open_commission_rate = commission_rate
    if open_commission_amount is None:
        open_commission_amount = commission_amount

    return PositionSpec(
        multiplier=max(multiplier or 1.0, EPSILON),
        margin_rate=max(margin_rate if margin_rate is not None else 1.0, 0.0),
        margin_amount=max(margin_amount or 0.0, 0.0),
        long_margin_rate=long_margin_rate,
        short_margin_rate=short_margin_rate,
        long_margin_amount=long_margin_amount,
        short_margin_amount=short_margin_amount,
        commission_rate=max(commission_rate or 0.0, 0.0),
        commission_amount=max(commission_amount or 0.0, 0.0),
        open_commission_rate=(
            max(open_commission_rate, 0.0) if open_commission_rate is not None else None
        ),
        close_commission_rate=(
            max(close_commission_rate, 0.0) if close_commission_rate is not None else None
        ),
        close_today_commission_rate=(
            max(close_today_commission_rate, 0.0)
            if close_today_commission_rate is not None
            else None
        ),
        close_yesterday_commission_rate=(
            max(close_yesterday_commission_rate, 0.0)
            if close_yesterday_commission_rate is not None
            else None
        ),
        maker_commission_rate=maker_commission_rate,
        taker_commission_rate=taker_commission_rate,
        open_commission_amount=open_commission_amount,
        close_commission_amount=close_commission_amount,
        close_today_commission_amount=close_today_commission_amount,
        close_yesterday_commission_amount=close_yesterday_commission_amount,
        asset_type=asset_type,
        contract_type=contract_type,
        contract_value_currency=contract_value_currency,
        base_asset=base_asset,
        quote_asset=quote_asset,
        settle_currency=settle_currency,
        fee_currency=fee_currency,
        source=source,
        is_inverse=is_inverse,
        has_multiplier=has_multiplier,
        has_margin_rate=has_margin_rate,
        has_margin_amount=has_margin_amount,
        has_commission=has_commission,
    )


def value_position(
    row: dict[str, Any],
    *,
    spec: PositionSpec | None = None,
) -> ValuedPosition | None:
    """Return a valued position row, or ``None`` for zero-size positions."""
    data_name = str(
        row.get("data_name")
        or row.get("symbol")
        or row.get("instrument")
        or row.get("InstrumentID")
        or row.get("contract")
        or row.get("instrument_id")
        or row.get("instId")
        or row.get("position_symbol_name")
        or row.get("symbol_name")
        or ""
    ).strip()
    size = _row_size(row)
    if abs(size) <= EPSILON:
        return None

    row_spec = spec or PositionSpec()
    inverse_contract = _is_inverse_contract(row, row_spec)
    multiplier_keys = (
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
    has_multiplier = row_spec.has_multiplier or _first_number(*multiplier_keys) is not None
    multiplier = _row_multiplier(row, row_spec, inverse_contract=inverse_contract)
    margin_rate = _row_margin_rate(row, row_spec, size)
    entry_price = safe_float(
        _first_number(
            row.get("price"),
            row.get("avg_price"),
            row.get("average_price"),
            row.get("price_open"),
            row.get("entry_price"),
            row.get("avgCost"),
            row.get("avgPrice"),
            row.get("avgPx"),
            row.get("avg_entry_price"),
            row.get("avgEntryPrice"),
            row.get("entryPrice"),
            row.get("ep"),
            row.get("open_avg_price"),
            row.get("openAvgPrice"),
            row.get("averageCost"),
            row.get("Price"),
            row.get("AveragePrice"),
            default=0.0,
        ),
        0.0,
    )
    if entry_price <= 0 and abs(size) > EPSILON and multiplier > 0 and not inverse_contract:
        position_cost = _first_number(
            row.get("PositionCost"),
            row.get("position_cost"),
            row.get("positionCost"),
            row.get("OpenCost"),
            row.get("open_cost"),
            row.get("openCost"),
        )
        if position_cost and position_cost > 0:
            entry_price = position_cost / (abs(size) * multiplier)
    current_price = _current_price(
        row,
        size,
        entry_price,
        multiplier,
        inverse_contract=inverse_contract,
    )
    calculated_entry_market_value = _position_notional(
        size,
        entry_price,
        multiplier,
        inverse_contract=inverse_contract,
    )
    calculated_market_value = _position_notional(
        size,
        current_price,
        multiplier,
        inverse_contract=inverse_contract,
    )
    explicit_market_value = _row_explicit_market_value(row)
    market_value = (
        explicit_market_value if explicit_market_value is not None else calculated_market_value
    )
    if (
        explicit_market_value is not None
        and not inverse_contract
        and current_price > EPSILON
        and entry_price > EPSILON
    ):
        entry_market_value = explicit_market_value * abs(entry_price / current_price)
    else:
        entry_market_value = calculated_entry_market_value
    margin_value = _row_margin_value(row, row_spec, market_value, margin_rate, size)
    direction = "long" if size > 0 else "short"

    explicit_net_pnl_key, explicit_net_pnl_value = _first_number_with_key(
        row,
        EXPLICIT_NET_PNL_FIELD_KEYS,
    )
    if explicit_net_pnl_value is None and _row_marks_pnl_as_net(row):
        explicit_net_pnl_key, explicit_net_pnl_value = _first_number_with_key(
            row,
            MARKABLE_NET_PNL_FIELD_KEYS,
        )
    explicit_net_pnl = (
        _normalized_pnl_amount(
            row,
            row_spec,
            field_key=explicit_net_pnl_key,
            value=explicit_net_pnl_value,
            current_price=current_price,
            inverse_contract=inverse_contract,
        )
        if explicit_net_pnl_value is not None
        else None
    )
    explicit_gross_pnl_key, explicit_gross_pnl_value = _first_number_with_key(
        row,
        (
            "gross_pnl",
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
            "position_pnl",
            "profit",
            "pnl",
        ),
    )
    explicit_gross_pnl = (
        _normalized_pnl_amount(
            row,
            row_spec,
            field_key=explicit_gross_pnl_key,
            value=explicit_gross_pnl_value,
            current_price=current_price,
            inverse_contract=inverse_contract,
        )
        if explicit_gross_pnl_value is not None
        else None
    )
    if explicit_net_pnl is not None and (
        explicit_net_pnl_key == explicit_gross_pnl_key
        or explicit_gross_pnl_key in MARKABLE_NET_PNL_FIELD_KEYS
    ):
        explicit_gross_pnl = None
    calculated_gross_pnl = _calculated_gross_pnl(
        size=size,
        entry_price=entry_price,
        current_price=current_price,
        multiplier=multiplier,
        inverse_contract=inverse_contract,
    )
    if _should_recalculate_generic_pnl(
        field_key=explicit_gross_pnl_key,
        explicit_net_pnl_value=explicit_net_pnl_value,
        size=size,
        entry_price=entry_price,
        current_price=current_price,
        multiplier=multiplier,
        has_multiplier=has_multiplier,
    ):
        explicit_gross_pnl = None
    if _should_recalculate_unscaled_exchange_pnl(
        field_key=explicit_gross_pnl_key,
        explicit_net_pnl_value=explicit_net_pnl_value,
        explicit_gross_pnl_value=explicit_gross_pnl_value,
        size=size,
        entry_price=entry_price,
        current_price=current_price,
        multiplier=multiplier,
        has_multiplier=has_multiplier,
        inverse_contract=inverse_contract,
    ):
        explicit_gross_pnl = None
    gross_pnl = explicit_gross_pnl if explicit_gross_pnl is not None else calculated_gross_pnl
    commission = _row_commission(
        row,
        row_spec,
        market_value,
        size,
        entry_market_value=entry_market_value,
        multiplier=multiplier,
        entry_price=entry_price,
        current_price=current_price,
        inverse_contract=inverse_contract,
    )
    swap = _sum_signed_amounts(row, CARRY_PNL_FIELD_KEYS)
    net_pnl = explicit_net_pnl if explicit_net_pnl is not None else gross_pnl + swap - commission

    return project_valued_position(
        ValuedPosition,
        data_name=data_name,
        size=size,
        direction=direction,
        entry_price=entry_price,
        current_price=current_price,
        multiplier=multiplier,
        margin_rate=margin_rate,
        market_value=market_value,
        margin_value=margin_value,
        commission=commission,
        gross_pnl=gross_pnl,
        pnl=net_pnl,
    )
