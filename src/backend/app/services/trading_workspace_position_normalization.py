"""Normalization and gateway-row preparation for workspace trading positions."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Any, Protocol

from app.models.workspace import StrategyUnit
from app.services.trading_asset_info_service import (
    LONG_POSITION_FIELD_KEYS,
    SHORT_POSITION_FIELD_KEYS,
)

if TYPE_CHECKING:
    from app.services.live_trading.manager import LiveTradingManager
    from app.services.trading_workspace_service import TradingWorkspaceService


class SafeFloat(Protocol):
    def __call__(self, value: Any, default: float = 0.0) -> float: ...


class SafeInt(Protocol):
    def __call__(self, value: Any, default: int = 0) -> int: ...


class FirstRowNumber(Protocol):
    def __call__(self, row: dict[str, Any], *keys: str) -> float | None: ...


class NormalizeGatewayPosition(Protocol):
    def __call__(
        self,
        row: dict[str, Any],
        *,
        fallback_symbol: str = "",
        asset_spec: dict[str, Any] | None = None,
        recent_trades: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...


class GatewayPositionSymbol(Protocol):
    def __call__(self, row: dict[str, Any], fallback: str = "") -> str: ...


@dataclass(frozen=True)
class PositionNormalizationDependencies:
    safe_float: SafeFloat
    safe_iso_text: Callable[[Any], str | None]
    safe_int: SafeInt
    round_quantity: Callable[[Any], float]
    epsilon: float
    position_log_row_direction: Callable[[dict[str, Any], float], str]
    get_live_trading_manager: Callable[[], LiveTradingManager]
    normalize_gateway_position: NormalizeGatewayPosition
    asset_spec_for_symbol: Callable[[dict[str, dict[str, Any]], str], dict[str, Any]]
    complete_asset_specs_from_local: Callable[
        [dict[str, dict[str, Any]], list[str]], dict[str, dict[str, Any]]
    ]
    merge_unit_contract_metadata: Callable[
        [dict[str, dict[str, Any]], StrategyUnit, Mapping[str, object] | None, list[str]],
        dict[str, dict[str, Any]],
    ]
    gateway_position_symbol: GatewayPositionSymbol
    signed_gateway_size: Callable[[dict[str, Any]], float]
    split_bidirectional_position_row: Callable[[dict[str, Any]], list[dict[str, Any]]]
    safe_dict: Callable[[Any], dict[str, Any]]
    is_server_owned_ai_research_unit: Callable[[StrategyUnit], bool]


def _normalize_trade_direction(value: Any, size: float) -> str:
    text = str(value or "").strip().lower()
    if text in {"buy", "long", "多", "多头"}:
        return "long"
    if text in {"sell", "short", "空", "空头"}:
        return "short"
    return "long" if size >= 0 else "short"


def _position_row_direction(
    row: dict[str, Any],
    *,
    dependencies: PositionNormalizationDependencies,
) -> str:
    direction = str(row.get("direction") or row.get("side") or "").strip().lower()
    if direction in {"short", "sell", "sold"}:
        return "short"
    raw_size = dependencies.safe_float(row.get("size"))
    return "short" if raw_size < 0 else "long"


def _position_row_open_size(
    cls: type[TradingWorkspaceService],
    row: dict[str, Any],
    *,
    dependencies: PositionNormalizationDependencies,
) -> float:
    size_value = row.get("size")
    size = abs(dependencies.safe_float(size_value))
    if size > dependencies.epsilon:
        return size
    if size_value not in (None, ""):
        return 0.0
    long_position = cls._first_row_number(row, *LONG_POSITION_FIELD_KEYS)
    short_position = cls._first_row_number(row, *SHORT_POSITION_FIELD_KEYS)
    return max(long_position or 0.0, 0.0) + max(short_position or 0.0, 0.0)


def _position_row_directional_sizes(
    row: dict[str, Any],
    size: float,
    *,
    first_row_number: FirstRowNumber,
    dependencies: PositionNormalizationDependencies,
) -> tuple[float, float] | None:
    long_size = first_row_number(row, *LONG_POSITION_FIELD_KEYS)
    short_size = first_row_number(row, *SHORT_POSITION_FIELD_KEYS)
    if size <= dependencies.epsilon and (
        (long_size or 0.0) > dependencies.epsilon or (short_size or 0.0) > dependencies.epsilon
    ):
        return max(long_size or 0.0, 0.0), max(short_size or 0.0, 0.0)
    return None


def _normalize_trade_rows(
    cls: type[TradingWorkspaceService],
    raw_trades: list[Any],
    *,
    unit: StrategyUnit,
    dependencies: PositionNormalizationDependencies,
) -> list[dict[str, Any]]:
    _safe_float = dependencies.safe_float
    _safe_iso_text = dependencies.safe_iso_text
    _safe_int = dependencies.safe_int
    _round_quantity = dependencies.round_quantity
    symbol = str(unit.symbol or unit.symbol_name or unit.strategy_name or "")
    trades: list[dict[str, Any]] = []

    for index, payload in enumerate(raw_trades):
        if not isinstance(payload, dict):
            continue

        raw_size = _safe_float(payload.get("size"), 0.0)
        size = abs(raw_size)
        pnl = _safe_float(payload.get("pnl"), 0.0)
        pnlcomm = _safe_float(payload.get("pnlcomm"), pnl)
        price = _safe_float(payload.get("price"), 0.0)
        value = _safe_float(payload.get("value"), 0.0)
        commission = _safe_float(payload.get("commission"), 0.0)
        row_id = str(payload.get("id") or payload.get("ref") or index + 1)

        trades.append(
            {
                "id": row_id,
                "datetime": _safe_iso_text(payload.get("datetime")),
                "dtopen": _safe_iso_text(payload.get("dtopen") or payload.get("open_time")),
                "dtclose": _safe_iso_text(
                    payload.get("dtclose") or payload.get("close_time") or payload.get("datetime")
                ),
                "data_name": str(payload.get("data_name") or payload.get("symbol") or symbol),
                "direction": cls._normalize_trade_direction(payload.get("direction"), raw_size),
                "size": _round_quantity(size),
                "price": round(price, 4) if price else None,
                "value": round(value, 2) if value else None,
                "commission": round(commission, 4),
                "pnl": round(pnl, 2),
                "pnlcomm": round(pnlcomm, 2),
                "barlen": (
                    _safe_int(payload.get("barlen")) if payload.get("barlen") is not None else None
                ),
            }
        )

    return trades[-200:]


def _position_log_row_direction(
    row: dict[str, Any],
    size: float,
    dependencies: PositionNormalizationDependencies,
) -> str:
    EPSILON = dependencies.epsilon
    _safe_float = dependencies.safe_float
    for key in (
        "direction",
        "side",
        "position_side",
        "positionSide",
        "PositionSide",
        "positionIdx",
        "position_idx",
        "posSide",
        "trade_action",
        "position_type",
        "type",
        "PosiDirection",
        "posi_direction",
        "position_direction",
    ):
        value = row.get(key)
        if value in (None, ""):
            continue
        text = str(value).strip().lower()
        if text in {"long", "buy", "bought", "position_type_buy", "deal_type_buy"}:
            return "long"
        if text in {"short", "sell", "sold", "position_type_sell", "deal_type_sell"}:
            return "short"
        if text == "flat":
            return "flat"
        numeric_code = _safe_float(value, float("nan"))
        code = int(numeric_code) if isfinite(numeric_code) else None
        key_text = key.lower()
        if key_text in {"trade_action", "position_type", "type"}:
            if code == 0:
                return "long"
            if code == 1:
                return "short"
        if key_text in {"posidirection", "posi_direction", "position_direction"}:
            if code == 2:
                return "long"
            if code == 3:
                return "short"
        if key_text in {"positionidx", "position_idx"}:
            if code == 1:
                return "long"
            if code == 2:
                return "short"
    if abs(size) <= EPSILON:
        return "flat"
    return "short" if size < 0 else "long"


def _latest_position_rows(
    rows: list[dict[str, Any]],
    dependencies: PositionNormalizationDependencies,
) -> list[dict[str, Any]]:
    EPSILON = dependencies.epsilon
    _safe_float = dependencies.safe_float
    latest_by_key: dict[str, tuple[int, str, str, dict[str, Any]]] = {}
    latest_flat_by_key: dict[str, tuple[int, str, str, dict[str, Any]]] = {}
    latest_flat_by_symbol: dict[str, tuple[int, str, dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        symbol = str(row.get("data_name") or row.get("symbol") or "").strip()
        if not symbol:
            continue
        size = _safe_float(row.get("size"), 0.0)
        direction = dependencies.position_log_row_direction(row, size)
        timestamp = str(row.get("datetime") or row.get("dt") or "")
        if abs(size) <= EPSILON:
            if direction in {"long", "short"}:
                key = f"{symbol}:{direction}"
                current_flat_by_key = latest_flat_by_key.get(key)
                if current_flat_by_key is None or (timestamp, index) >= (
                    current_flat_by_key[1],
                    current_flat_by_key[0],
                ):
                    latest_flat_by_key[key] = (index, timestamp, symbol, row)
                continue
            current_flat_by_symbol = latest_flat_by_symbol.get(symbol)
            if current_flat_by_symbol is None or (timestamp, index) >= (
                current_flat_by_symbol[1],
                current_flat_by_symbol[0],
            ):
                latest_flat_by_symbol[symbol] = (index, timestamp, row)
            continue
        key = f"{symbol}:{direction}"
        current_position_by_key = latest_by_key.get(key)
        if current_position_by_key is None or (timestamp, index) >= (
            current_position_by_key[1],
            current_position_by_key[0],
        ):
            latest_by_key[key] = (index, timestamp, symbol, row)

    latest_nonflat_by_symbol: dict[str, tuple[int, str]] = {}
    for index, timestamp, symbol, _row in latest_by_key.values():
        current_nonflat_by_symbol = latest_nonflat_by_symbol.get(symbol)
        if current_nonflat_by_symbol is None or (timestamp, index) >= (
            current_nonflat_by_symbol[1],
            current_nonflat_by_symbol[0],
        ):
            latest_nonflat_by_symbol[symbol] = (index, timestamp)

    selected: list[tuple[int, dict[str, Any]]] = []
    for index, timestamp, symbol, row in latest_by_key.values():
        direction = dependencies.position_log_row_direction(row, _safe_float(row.get("size"), 0.0))
        key = f"{symbol}:{direction}"
        flat = latest_flat_by_symbol.get(symbol)
        if flat is not None and (flat[1], flat[0]) >= (timestamp, index):
            continue
        directional_flat = latest_flat_by_key.get(key)
        if directional_flat is not None and (directional_flat[1], directional_flat[0]) >= (
            timestamp,
            index,
        ):
            continue
        selected.append((index, row))
    for symbol, (index, timestamp, row) in latest_flat_by_symbol.items():
        latest_nonflat_for_symbol = latest_nonflat_by_symbol.get(symbol)
        if latest_nonflat_for_symbol is None or (timestamp, index) >= (
            latest_nonflat_for_symbol[1],
            latest_nonflat_for_symbol[0],
        ):
            selected.append((index, row))
    for key, (index, timestamp, _symbol, row) in latest_flat_by_key.items():
        latest_nonflat_for_key = latest_by_key.get(key)
        if latest_nonflat_for_key is None or (timestamp, index) >= (
            latest_nonflat_for_key[1],
            latest_nonflat_for_key[0],
        ):
            selected.append((index, row))
    return [row for _index, row in sorted(selected, key=lambda item: item[0])]


def _position_updated_at(
    row: dict[str, Any],
    dependencies: PositionNormalizationDependencies,
) -> str | None:
    _safe_iso_text = dependencies.safe_iso_text
    return _safe_iso_text(
        row.get("updated_at") or row.get("log_time") or row.get("datetime") or row.get("dt")
    )


def _position_data_time(
    row: dict[str, Any],
    dependencies: PositionNormalizationDependencies,
) -> str | None:
    _safe_iso_text = dependencies.safe_iso_text
    return _safe_iso_text(row.get("data_time") or row.get("datetime") or row.get("dt"))


def _latest_position_updated_at(
    cls: type[TradingWorkspaceService], rows: list[dict[str, Any]]
) -> str | None:
    latest: str | None = None
    for row in rows:
        timestamp = cls._position_updated_at(row)
        if timestamp and (latest is None or timestamp > latest):
            latest = timestamp
    return latest


def _latest_position_data_time(
    cls: type[TradingWorkspaceService], rows: list[dict[str, Any]]
) -> str | None:
    latest: str | None = None
    for row in rows:
        timestamp = cls._position_data_time(row)
        if timestamp and (latest is None or timestamp > latest):
            latest = timestamp
    return latest


def _gateway_position_rows(
    cls: type[TradingWorkspaceService],
    unit: StrategyUnit,
    instance: Mapping[str, object] | None,
    dependencies: PositionNormalizationDependencies,
) -> list[dict[str, Any]] | None:
    EPSILON = dependencies.epsilon
    _asset_spec_for_symbol = dependencies.asset_spec_for_symbol
    _complete_asset_specs_from_local = dependencies.complete_asset_specs_from_local
    _merge_unit_contract_metadata = dependencies.merge_unit_contract_metadata
    is_server_owned_ai_research_unit = dependencies.is_server_owned_ai_research_unit
    get_live_trading_manager = dependencies.get_live_trading_manager
    normalize_gateway_position = dependencies.normalize_gateway_position
    gateway_position_symbol = dependencies.gateway_position_symbol
    signed_gateway_size = dependencies.signed_gateway_size
    split_bidirectional_position_row = dependencies.split_bidirectional_position_row
    instance_id = str((instance or {}).get("id") or unit.trading_instance_id or "").strip()
    if not instance_id:
        return None

    try:
        manager = get_live_trading_manager()
    except Exception:
        return None

    has_gateway = getattr(manager, "has_instance_gateway", None)
    if callable(has_gateway):
        try:
            if not has_gateway(instance_id):
                return None
        except Exception:
            return None

    query_positions = getattr(manager, "query_instance_gateway_positions", None)
    if not callable(query_positions):
        return None
    try:
        raw_positions = query_positions(instance_id)
    except Exception:
        return None
    if not isinstance(raw_positions, list):
        return None

    fallback_symbol = str(unit.symbol or unit.symbol_name or unit.strategy_name or "")
    allowed_aliases = cls._unit_position_symbol_aliases(unit, instance)
    matched_positions: list[dict[str, Any]] = []
    symbols: list[str] = []
    seen: set[str] = set()
    for item in raw_positions:
        if not isinstance(item, dict):
            continue
        row_symbol = gateway_position_symbol(item)
        if allowed_aliases and not cls._position_symbol_matches(row_symbol, allowed_aliases):
            continue
        matched_positions.append(item)
        symbol = row_symbol or fallback_symbol
        if symbol and symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
    if fallback_symbol and fallback_symbol not in seen:
        symbols.append(fallback_symbol)

    asset_specs: dict[str, dict[str, Any]] = {}
    query_specs = getattr(manager, "query_instance_asset_specs", None)
    if callable(query_specs) and symbols and not is_server_owned_ai_research_unit(unit):
        try:
            raw_specs = query_specs(instance_id, symbols)
        except Exception:
            raw_specs = {}
        if isinstance(raw_specs, dict):
            asset_specs = {
                str(key): dict(value) for key, value in raw_specs.items() if isinstance(value, dict)
            }
    asset_specs = _merge_unit_contract_metadata(asset_specs, unit, instance, symbols)
    asset_specs = _complete_asset_specs_from_local(asset_specs, symbols)
    if asset_specs:
        cls._sync_unit_contract_metadata_from_specs(unit, asset_specs)

    recent_trades: list[dict[str, Any]] = []
    query_trades = getattr(manager, "query_instance_gateway_trades", None)
    if callable(query_trades) and symbols:
        for symbol in symbols:
            try:
                raw_trades = query_trades(instance_id, symbol=symbol, limit=500)
            except TypeError:
                raw_trades = query_trades(instance_id)
            except Exception:
                raw_trades = []
            if isinstance(raw_trades, list):
                for item in raw_trades:
                    if not isinstance(item, dict):
                        continue
                    trade = dict(item)
                    trade.setdefault("__query_symbol", symbol)
                    recent_trades.append(trade)

    rows: list[dict[str, Any]] = []
    for item in matched_positions:
        for side_item in split_bidirectional_position_row(item):
            if abs(signed_gateway_size(side_item)) <= EPSILON:
                continue
            symbol = gateway_position_symbol(side_item, fallback_symbol)
            rows.append(
                normalize_gateway_position(
                    side_item,
                    fallback_symbol=fallback_symbol,
                    asset_spec=_asset_spec_for_symbol(asset_specs, symbol),
                    recent_trades=recent_trades,
                )
            )
    return rows


normalize_trade_direction = _normalize_trade_direction
position_row_direction = _position_row_direction
position_row_open_size = _position_row_open_size
position_row_directional_sizes = _position_row_directional_sizes
normalize_trade_rows = _normalize_trade_rows
position_log_row_direction = _position_log_row_direction
latest_position_rows = _latest_position_rows
position_updated_at = _position_updated_at
position_data_time = _position_data_time
latest_position_updated_at = _latest_position_updated_at
latest_position_data_time = _latest_position_data_time
gateway_position_rows = _gateway_position_rows
