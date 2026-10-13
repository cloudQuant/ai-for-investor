"""Shared portfolio API types and small value-conversion helpers."""

import math
from array import array
from ctypes import Array
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, SupportsFloat, SupportsIndex, TypeGuard
from zoneinfo import ZoneInfo

_ACTIVE_TRADING_STATUSES = {"queued", "running"}
_PORTFOLIO_TIMEZONE = ZoneInfo("Asia/Shanghai")
_GROSS_PNL_FIELD_KEYS = (
    "gross_pnl",
    "position_unrealized_pnl",
    "position_unrealised_pnl",
    "position_profit",
    "PositionProfit",
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
    "position_pnl",
    "profit",
    "upl",
    "up",
)
_EXPLICIT_NET_PNL_FIELD_KEYS = (
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


@dataclass
class _PortfolioSource:
    id: str
    strategy_id: str
    strategy_name: str
    status: str
    symbol: str = ""
    unit_id: str | None = None
    workspace_id: str | None = None
    trading_mode: str = "paper"
    log_dir: Path | None = None
    snapshot: dict[str, Any] | None = None
    live_positions: list[dict[str, Any]] | None = None
    live_account: dict[str, Any] | None = None
    resolved_asset_specs: dict[str, dict[str, Any]] = field(default_factory=dict)
    valuation_configs: tuple[dict[str, Any], ...] = ()
    position_source: str | None = None
    account_source: str | None = None
    asset_spec_source: str | None = None
    valuation_status: str = "empty"
    valuation_warnings: list[str] = field(default_factory=list)
    pid: int | None = None
    started_at: str | None = None
    updated_at: str | None = None


def _safe_round(v: float, n: int = 2) -> float:
    """Round finite values and convert NaN or infinity to zero."""
    if math.isnan(v) or math.isinf(v):
        return 0.0
    return round(v, n)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]
    return value


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _unique_text(values: list[Any]) -> str | None:
    texts = [str(value or "").strip() for value in values]
    unique = sorted({text for text in texts if text})
    if not unique:
        return None
    if len(unique) == 1:
        return unique[0]
    return "mixed"


def _append_unique(target: list[str], *values: Any) -> None:
    seen = set(target)
    for value in values:
        if isinstance(value, (list, tuple, set)):
            _append_unique(target, *value)
            seen = set(target)
            continue
        text = str(value or "").strip()
        if text and text not in seen:
            target.append(text)
            seen.add(text)


def _has_any(row: dict[str, Any], *keys: str) -> bool:
    return any(row.get(key) not in (None, "") for key in keys)


class _SupportsBuffer(Protocol):
    def __buffer__(self, flags: int, /) -> memoryview: ...


def _is_float_input(
    value: object,
) -> TypeGuard[
    str | bytes | bytearray | memoryview | _SupportsBuffer | SupportsFloat | SupportsIndex
]:
    """Report whether the built-in float() accepts the value's input protocol."""
    return (
        isinstance(value, (str, bytes, bytearray, memoryview))
        or isinstance(value, (array, Array))
        or hasattr(value, "__float__")
        or hasattr(value, "__index__")
        or hasattr(value, "__buffer__")
    )


def _first_number(row: dict[str, Any] | None, *keys: str) -> float | None:
    if not isinstance(row, dict):
        return None
    for key in keys:
        value: object = row.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, dict):
            nested_value: object | None = None
            for nested_key in ("amount", "value", "balance", "total"):
                candidate = value.get(nested_key)
                if candidate not in (None, ""):
                    nested_value = candidate
                    break
            if nested_value in (None, ""):
                continue
            value = nested_value
        if isinstance(value, str):
            value = value.strip().replace(",", "")
        try:
            if not _is_float_input(value):
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
