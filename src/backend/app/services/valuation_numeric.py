"""Numeric normalization and shared valuation field constants."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, overload

EPSILON = 1e-12
COMMISSION_FIELD_KEYS = (
    "commission",
    "comm",
    "commissionAmount",
    "fee",
    "fees",
    "feeAmount",
    "execFee",
    "exec_fee",
    "execFeeV2",
    "exec_fee_v2",
    "execCommission",
    "exec_commission",
    "open_fee",
    "openFee",
    "open_commission",
    "openCommission",
    "positionCommission",
    "position_fee",
    "position_commission",
    "tradeFee",
    "trade_fee",
    "trade_commission",
    "broker_commission",
    "brokerCommission",
    "commission_amount",
    "Commission",
    "fillFee",
    "fill_fee",
)
CARRY_PNL_FIELD_KEYS = (
    "swap",
    "storage",
    "funding",
    "funding_fee",
    "fundingFee",
    "funding_fee_amount",
    "fundingFeeAmount",
    "interest",
    "borrow_interest",
    "borrowInterest",
    "financing_fee",
    "financingFee",
)
OKX_SIGNED_FEE_FIELD_KEYS = frozenset(
    {
        "fee",
        "position_fee",
        "position_commission",
        "trade_fee",
        "trade_commission",
        "fillFee",
        "fill_fee",
    }
)
EXPLICIT_NET_PNL_FIELD_KEYS = (
    "pnlcomm",
    "net_pnl",
    "netPnl",
    "netPNL",
    "net_position_pnl",
    "netPositionPnl",
    "netPositionPNL",
    "net_unrealized_pnl",
    "netUnrealizedPnl",
    "netUnrealizedPNL",
    "unrealized_pnl_after_fee",
    "unrealizedPnlAfterFee",
    "position_pnl_after_fee",
    "positionPnlAfterFee",
)
MARKABLE_NET_PNL_FIELD_KEYS = ("position_pnl", "pnl", "profit")
NET_PNL_FLAG_KEYS = (
    "position_pnl_is_net",
    "positionPnlIsNet",
    "pnl_is_net",
    "pnlIsNet",
    "profit_is_net",
    "profitIsNet",
    "position_pnl_includes_fee",
    "positionPnlIncludesFee",
    "pnl_includes_fee",
    "pnlIncludesFee",
    "profit_includes_fee",
    "profitIncludesFee",
    "position_pnl_includes_commission",
    "positionPnlIncludesCommission",
    "pnl_includes_commission",
    "pnlIncludesCommission",
    "profit_includes_commission",
    "profitIncludesCommission",
    "is_net_pnl",
    "isNetPnl",
)
INVERSE_CONTRACT_FLAG_KEYS = (
    "inverse",
    "is_inverse",
    "isInverse",
    "inverse_contract",
    "inverseContract",
)
_COMMON_QUOTE_SUFFIXES = (
    "USDT",
    "USDC",
    "USD",
    "CNH",
    "CNY",
    "EUR",
    "JPY",
    "BTC",
    "ETH",
)
_FIAT_CURRENCIES = frozenset(
    {
        "AUD",
        "CAD",
        "CHF",
        "CNH",
        "CNY",
        "EUR",
        "GBP",
        "HKD",
        "JPY",
        "MXN",
        "NOK",
        "NZD",
        "SEK",
        "SGD",
        "TRY",
        "USD",
        "ZAR",
    }
)
_MT5_METAL_CONTRACT_SIZES = {
    "XAUUSD": 100.0,
    "XAGUSD": 5000.0,
    "XPTUSD": 100.0,
    "XPDUSD": 100.0,
}
_MT5_FOREX_CONTRACT_SIZE = 100000.0


@overload
def safe_float(value: object, default: None) -> float | None: ...


@overload
def safe_float(value: object, default: float = 0.0) -> float: ...


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    if value in (None, ""):
        return default
    if isinstance(value, dict):
        for key in ("cost", "amount", "value", "balance", "total", "commission", "fee"):
            item = value.get(key)
            if item not in (None, ""):
                if default is None:
                    return safe_float(item, None)
                return safe_float(item, default)
        return default
    if isinstance(value, (list, tuple)):
        numbers = [safe_float(item, None) for item in value]
        valid_numbers = [number for number in numbers if number is not None]
        return sum(valid_numbers) if valid_numbers else default
    if isinstance(value, str):
        value = value.strip().replace(",", "")
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_number(*values: Any, default: float | None = None) -> float | None:
    for value in values:
        if value in (None, ""):
            continue
        number = safe_float(value, None)
        if number is not None:
            return number
    return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "signed"}


def _row_marks_pnl_as_net(row: dict[str, Any]) -> bool:
    return any(_truthy(row.get(key)) for key in NET_PNL_FLAG_KEYS)


def _explicit_inverse_flag(config: dict[str, Any]) -> bool | None:
    for key in INVERSE_CONTRACT_FLAG_KEYS:
        value = config.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "inverse", "coin_margined"}:
            return True
        if text in {"0", "false", "no", "n", "linear"}:
            return False
    return None


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _uses_okx_fee_sign(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "").strip().lower()
        for key in (
            "source",
            "asset_spec_source",
            "exchange",
            "exchange_id",
            "exchange_name",
            "exchange_nae",
            "gateway",
            "broker",
        )
    )
    return "okx" in text


def _first_number_with_key(
    row: dict[str, Any],
    keys: Iterable[str],
) -> tuple[str | None, float | None]:
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            continue
        number = safe_float(value, None)
        if number is not None:
            return key, number
    return None, None


def _sum_signed_amounts(row: dict[str, Any], keys: Iterable[str]) -> float:
    total = 0.0
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        value = row.get(key)
        if value in (None, ""):
            continue
        amount = safe_float(value, None)
        if amount is not None:
            total += amount
    return total


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _normalise_rate(value: Any, default: float = 0.0) -> float:
    number = safe_float(value, default)
    if number > 1.0:
        return number / 100.0
    return max(number, 0.0)


def _normalise_ctp_commission_rate(value: Any, default: float = 0.0) -> float:
    number = safe_float(value, default)
    if number > 0.01:
        return number / 10000.0
    return max(number, 0.0)


def _normalise_signed_rate(value: Any, default: float = 0.0) -> float:
    number = safe_float(value, default)
    if abs(number) > 1.0:
        return number / 100.0
    return number


def _commission_rate_from_keys(
    config: dict[str, Any],
    keys: Iterable[str],
    *,
    signed: bool = False,
) -> float | None:
    method = str(config.get("commission_method") or "").strip().lower()
    for key in keys:
        value = _first_number(config.get(key))
        if value is None:
            continue
        if signed:
            return _normalise_signed_rate(value)
        if (
            method == "percent_10k"
            or key.startswith("COMMISSION_")
            or key.endswith("RatioByMoney")
            and value > 0.01
        ):
            return _normalise_ctp_commission_rate(value)
        return _normalise_rate(value, 0.0)
    return None


def _commission_amount_from_keys(
    config: dict[str, Any],
    keys: Iterable[str],
) -> float | None:
    for key in keys:
        value = _first_number(config.get(key))
        if value is not None:
            return max(value, 0.0)
    return None


def _commission_rate_from_config(config: dict[str, Any]) -> float | None:
    method = str(config.get("commission_method") or "").strip().lower()
    for key in (
        "commission",
        "commission_rate",
        "fee_rate",
        "open_fee_rate",
        "open_commission_rate",
        "taker_commission_rate",
        "taker_fee_rate",
        "maker_commission_rate",
        "maker_fee_rate",
        "OPEN_FEE_RATE",
        "OpenRatioByMoney",
        "COMMISSION_OPEN_RATIO",
    ):
        value = _first_number(config.get(key))
        if value is None:
            continue
        if (
            method == "percent_10k"
            or key == "COMMISSION_OPEN_RATIO"
            or (key == "OpenRatioByMoney" and value > 0.01)
        ):
            return _normalise_ctp_commission_rate(value)
        return _normalise_rate(value, 0.0)
    return None
