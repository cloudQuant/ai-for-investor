"""Snapshot projection helpers for workspace trading runtime state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from app.models.workspace import StrategyUnit

if TYPE_CHECKING:
    from app.services.position_valuation import PositionSpec, ValuedPosition
    from app.services.trading_workspace_service import TradingWorkspaceService


class SafeFloat(Protocol):
    def __call__(self, value: Any, default: float = 0.0) -> float: ...


class ParseLogDir(Protocol):
    def __call__(
        self,
        log_dir: Path,
        strategy_dir: Path | None = None,
    ) -> dict[str, Any] | None: ...


class AppendUnique(Protocol):
    def __call__(self, target: list[str], *values: Any) -> None: ...


class GatewayPositionSymbol(Protocol):
    def __call__(self, row: dict[str, Any], fallback: str = "") -> str: ...


class ValuePosition(Protocol):
    def __call__(
        self,
        row: dict[str, Any],
        *,
        spec: PositionSpec | None = None,
    ) -> ValuedPosition | None: ...


@dataclass(frozen=True)
class SnapshotDependencies:
    light_hydrate_preserve_keys: tuple[str, ...]
    safe_dict: Callable[[Any], dict[str, Any]]
    safe_float: SafeFloat
    safe_iso_text: Callable[[Any], str | None]
    instance_log_dir: Callable[[Mapping[str, object] | None], Path | None]
    parse_log_dir: ParseLogDir
    parse_position_log: Callable[[Path], list[dict[str, Any]]]
    parse_current_position: Callable[[Path], list[dict[str, Any]]]
    workspace_unit_dir: Callable[[str, str], Path]
    append_unique: AppendUnique
    round_quantity: Callable[[Any], float]
    leverage_from_margin_rate: Callable[[Any], float | None]
    unique_text: Callable[[list[Any]], str | None]
    gateway_position_symbol: GatewayPositionSymbol
    split_bidirectional_position_row: Callable[[dict[str, Any]], list[dict[str, Any]]]
    value_position: ValuePosition


def apply_position_rows_to_snapshot(
    cls: type[TradingWorkspaceService],
    snapshot: dict[str, Any],
    unit: StrategyUnit,
    instance: Mapping[str, object] | None,
    positions: list[dict[str, Any]],
    dependencies: SnapshotDependencies,
) -> float | None:
    _append_unique = dependencies.append_unique
    _leverage_from_margin_rate = dependencies.leverage_from_margin_rate
    _round_quantity = dependencies.round_quantity
    _safe_dict = dependencies.safe_dict
    _unique_text = dependencies.unique_text
    gateway_position_symbol = dependencies.gateway_position_symbol
    split_bidirectional_position_row = dependencies.split_bidirectional_position_row
    value_position = dependencies.value_position
    long_position = 0.0
    short_position = 0.0
    long_market_value = 0.0
    short_market_value = 0.0
    position_pnl = 0.0
    detail_positions: list[dict[str, Any]] = []
    latest_price: float | None = None
    latest_position_updated_at: str | None = None
    position_sources: list[str] = []
    asset_spec_sources: list[str] = []
    valuation_warnings = list(snapshot.get("valuation_warnings") or [])
    fallback_position_source = str(snapshot.get("position_source") or "").strip() or None

    fallback_symbol = str(unit.symbol or unit.symbol_name or unit.strategy_name or "")

    for raw_item in positions:
        for item in split_bidirectional_position_row(_safe_dict(raw_item)):
            data_name = gateway_position_symbol(item, fallback_symbol)
            spec = cls._contract_spec(
                unit,
                data_name,
                instance,
                cls._asset_spec_config_for_row(_safe_dict(item)),
            )
            position_source = cls._position_source_for_row(item, fallback_position_source)
            if (
                str(fallback_position_source or "").strip().lower() in {"log", "snapshot"}
                and position_source.lower() == "gateway"
            ):
                item = dict(item)
                item["force_recalculate_position_pnl"] = True
                position_source = str(fallback_position_source)
            valuation_item = cls._position_row_for_valuation(
                _safe_dict(item),
                spec,
                position_source=position_source,
            )
            valued = value_position(valuation_item, spec=spec)
            if valued is None:
                continue
            asset_spec_source = cls._asset_spec_source_for_row(item, spec)
            row_warnings = cls._position_valuation_warnings(
                unit,
                valuation_item,
                spec,
                position_source=position_source,
            )
            if valuation_item.get("recalculated_position_pnl"):
                row_warnings.append("本地/快照持仓盈亏已按最新资产乘数、保证金和手续费设置重新计算")
            _append_unique(valuation_warnings, row_warnings)
            position_sources.append(position_source)
            if asset_spec_source:
                asset_spec_sources.append(asset_spec_source)

            if valued.size > 0:
                long_position += abs(valued.size)
                long_market_value += valued.market_value
            else:
                short_position += abs(valued.size)
                short_market_value += valued.market_value

            position_pnl += valued.pnl
            latest_price = valued.current_price
            position_updated_at = cls._position_updated_at(item)
            position_data_time = cls._position_data_time(item)
            if position_updated_at and (
                latest_position_updated_at is None
                or position_updated_at > latest_position_updated_at
            ):
                latest_position_updated_at = position_updated_at
            detail_positions.append(
                {
                    "data_name": valued.data_name or data_name,
                    "direction": valued.direction,
                    "size": _round_quantity(abs(valued.size)),
                    "price": round(valued.entry_price, 4) if valued.entry_price else None,
                    "current_price": round(valued.current_price, 4)
                    if valued.current_price
                    else None,
                    "market_value": round(valued.market_value, 2),
                    "margin_value": round(valued.margin_value, 2),
                    "multiplier": round(valued.multiplier, 8),
                    "margin_rate": round(valued.margin_rate, 8),
                    "leverage": _leverage_from_margin_rate(valued.margin_rate),
                    "commission": round(valued.commission, 4),
                    "commission_source": valuation_item.get("commission_source")
                    or item.get("commission_source"),
                    "commission_signed": True,
                    "gross_pnl": round(valued.gross_pnl, 2),
                    "pnl": round(valued.pnl, 2),
                    "pnlcomm": round(valued.pnl, 2),
                    "position_pnl": round(valued.pnl, 2),
                    "updated_at": position_updated_at,
                    "data_time": position_data_time,
                    "source": position_source,
                    "position_source": position_source,
                    "asset_spec_source": asset_spec_source,
                    "valuation_status": "estimated" if row_warnings else "confirmed",
                    "valuation_warnings": row_warnings,
                }
            )
    snapshot["positions"] = detail_positions
    if not position_sources and fallback_position_source:
        position_sources.append(fallback_position_source)
    snapshot["position_source"] = _unique_text(position_sources)
    snapshot["asset_spec_source"] = _unique_text(asset_spec_sources)
    snapshot["valuation_warnings"] = valuation_warnings
    if valuation_warnings:
        snapshot["valuation_status"] = "estimated"
    elif snapshot.get("position_source") == "gateway":
        snapshot["valuation_status"] = "confirmed"
    else:
        snapshot["valuation_status"] = "empty" if not detail_positions else "estimated"
    if latest_position_updated_at:
        snapshot["updated_at"] = latest_position_updated_at
    snapshot["long_position"] = _round_quantity(long_position)
    snapshot["short_position"] = _round_quantity(short_position)
    snapshot["long_market_value"] = round(long_market_value, 2)
    snapshot["short_market_value"] = round(short_market_value, 2)
    snapshot["position_pnl"] = round(position_pnl, 2)
    return latest_price


def build_snapshot(
    cls: type[TradingWorkspaceService],
    unit: StrategyUnit,
    instance: Mapping[str, object] | None,
    *,
    full_log: bool = True,
    include_gateway_positions: bool = True,
    dependencies: SnapshotDependencies,
) -> tuple[dict[str, Any], dict[str, Any], int | None, float | None]:
    _LIGHT_HYDRATE_PRESERVE_KEYS = dependencies.light_hydrate_preserve_keys
    _append_unique = dependencies.append_unique
    _instance_log_dir = dependencies.instance_log_dir
    _safe_dict = dependencies.safe_dict
    _safe_float = dependencies.safe_float
    _safe_iso_text = dependencies.safe_iso_text
    parse_current_position = dependencies.parse_current_position
    parse_log_dir = dependencies.parse_log_dir
    parse_position_log = dependencies.parse_position_log
    workspace_unit_dir = dependencies.workspace_unit_dir
    instance_status = str((instance or {}).get("status") or "stopped").strip().lower()
    error = str((instance or {}).get("error") or "").strip() or None
    snapshot = cls.default_snapshot(
        unit=unit,
        instance_status="error" if error else (instance_status or "idle"),
        error=error,
    )
    if not full_log:
        current_snapshot = _safe_dict(getattr(unit, "trading_snapshot", None))
        for key in _LIGHT_HYDRATE_PRESERVE_KEYS:
            if key in current_snapshot:
                snapshot[key] = current_snapshot[key]
    snapshot["instance_id"] = (instance or {}).get("id") or unit.trading_instance_id
    snapshot["started_at"] = _safe_iso_text((instance or {}).get("started_at"))
    snapshot["stopped_at"] = _safe_iso_text((instance or {}).get("stopped_at"))

    metrics_snapshot: dict[str, Any] = {}
    bar_count: int | None = None
    elapsed_seconds: float | None = None
    latest_price: float | None = None

    log_result: dict[str, Any] | None = None
    position_rows: list[dict[str, Any]] = []
    position_rows_source = "none"
    log_dir = _instance_log_dir(instance)
    if log_dir is None:
        # The live-trading manager is process-local and is empty after an
        # API-server restart. Workspace runtimes persist their logs under
        # the unit directory, so use that durable source for historical
        # position and trade recovery.
        workspace_id = str(getattr(unit, "workspace_id", "") or "").strip()
        unit_id = str(getattr(unit, "id", "") or "").strip()
        if workspace_id and unit_id:
            persisted_log_dir = workspace_unit_dir(workspace_id, unit_id) / "logs"
            if persisted_log_dir.is_dir():
                log_dir = persisted_log_dir
    if log_dir and log_dir.is_dir():
        log_result = parse_log_dir(log_dir) if full_log else None
        position_rows = cls._latest_position_rows(parse_position_log(log_dir))
        if position_rows:
            position_rows_source = "log"
        if not position_rows:
            position_rows = parse_current_position(log_dir)
            if position_rows:
                position_rows_source = "snapshot"

    # Paper workspaces must display their own simulated state.  Their shared
    # market-data gateway is not an account for each strategy unit, and a
    # gateway request per unit makes the portfolio/risk page unresponsive.
    # Explicitly configured live units retain the broker-confirmed path.
    is_explicit_paper = str(getattr(unit, "trading_mode", "")).strip().lower() == "paper"
    gateway_position_rows = (
        None
        if is_explicit_paper or not include_gateway_positions
        else cls._gateway_position_rows(unit, instance)
    )
    if gateway_position_rows is not None:
        position_rows = gateway_position_rows
        position_rows_source = "gateway"
    elif (
        cls.normalize_trading_mode(getattr(unit, "trading_mode", None)) == "live"
        and instance_status == "running"
    ):
        snapshot["valuation_status"] = "stale_fallback"
        _append_unique(
            snapshot["valuation_warnings"],
            "运行中的实盘单元未能从交易所网关确认当前持仓，当前盈亏可能来自过期日志/快照",
        )

    if position_rows or gateway_position_rows is not None:
        snapshot["position_source"] = position_rows_source
        latest_price = cls._apply_position_rows_to_snapshot(
            snapshot,
            unit,
            instance,
            position_rows,
        )

    if log_result:
        snapshot["trades"] = cls._normalize_trade_rows(
            list(log_result.get("trades") or []),
            unit=unit,
        )

        kline = log_result.get("kline") or {}
        dates = list(kline.get("dates") or [])
        ohlc = list(kline.get("ohlc") or [])
        if dates:
            snapshot["trading_day"] = str(dates[-1])[:10]
            bar_count = len(dates)
        if len(ohlc) >= 1:
            last_close = _safe_float((ohlc[-1] or [None, None])[1], default=0.0)
            if last_close > 0:
                snapshot["latest_price"] = round(last_close, 4)
            if len(ohlc) >= 2:
                prev_close = _safe_float((ohlc[-2] or [None, None])[1], default=0.0)
                if prev_close > 0 and last_close > 0:
                    snapshot["change_pct"] = round((last_close - prev_close) / prev_close * 100, 2)

        equity_curve = list(log_result.get("equity_curve") or [])
        initial_cash = _safe_float(log_result.get("initial_cash"), 0.0)
        final_value = _safe_float(log_result.get("final_value"), 0.0)
        if len(equity_curve) >= 2:
            snapshot["today_pnl"] = round(equity_curve[-1] - equity_curve[-2], 2)
        snapshot["cumulative_pnl"] = round(final_value - initial_cash, 2)
        snapshot["max_drawdown_rate"] = round(_safe_float(log_result.get("max_drawdown")), 2)
        total_market_value = _safe_float(snapshot.get("long_market_value")) + _safe_float(
            snapshot.get("short_market_value")
        )
        if final_value > 0 and total_market_value > 0:
            snapshot["leverage"] = round(total_market_value / final_value, 4)
        if snapshot.get("latest_price") is None and latest_price is not None:
            snapshot["latest_price"] = round(latest_price, 4)

        metrics_snapshot = {
            "total_return": log_result.get("total_return"),
            "annual_return": log_result.get("annual_return"),
            "sharpe_ratio": log_result.get("sharpe_ratio"),
            "max_drawdown": log_result.get("max_drawdown"),
            "win_rate": log_result.get("win_rate"),
            "total_trades": log_result.get("total_trades"),
            "profitable_trades": log_result.get("profitable_trades"),
            "losing_trades": log_result.get("losing_trades"),
            "initial_cash": initial_cash,
            "final_value": final_value,
            "net_value": round(final_value / initial_cash, 6) if initial_cash > 0 else None,
            "net_profit": round(final_value - initial_cash, 2),
            "max_leverage": snapshot.get("leverage"),
            "trading_days": len(equity_curve),
        }

    if snapshot.get("latest_price") is None and latest_price is not None:
        snapshot["latest_price"] = round(latest_price, 4)

    started_at = snapshot.get("started_at")
    if started_at and snapshot.get("instance_status") == "running":
        try:
            started_dt = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            elapsed_seconds = None
        else:
            elapsed_seconds = round((datetime.now() - started_dt).total_seconds(), 2)

    return snapshot, metrics_snapshot, bar_count, elapsed_seconds
