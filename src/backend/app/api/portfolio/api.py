"""
Portfolio management API routes.

Aggregates data across live trading strategy instances:
- Portfolio overview (total assets, PnL, strategy distribution)
- Aggregated positions (current positions per strategy)
- Aggregated trades (historical trades per strategy)
- Portfolio equity curve (stacked equity across strategies)
"""

import json
import logging
import math
import typing
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.portfolio.asset_spec_adapter import (
    _append_symbol_candidate as _append_symbol_candidate,
)
from app.api.portfolio.asset_spec_adapter import (
    _asset_spec_for_symbol,
    _merge_asset_spec_update,
    _merge_source_contract_metadata,
    _position_symbol_matches,
    _source_symbol_aliases,
)
from app.api.portfolio.asset_spec_adapter import (
    _asset_spec_has_any as _asset_spec_has_any,
)
from app.api.portfolio.asset_spec_adapter import (
    _can_merge_asset_spec_value as _can_merge_asset_spec_value,
)
from app.api.portfolio.asset_spec_adapter import (
    _combined_asset_spec_source as _combined_asset_spec_source,
)
from app.api.portfolio.asset_spec_adapter import (
    _is_asset_spec_core_key as _is_asset_spec_core_key,
)
from app.api.portfolio.asset_spec_adapter import (
    _is_asset_spec_primary_source_key as _is_asset_spec_primary_source_key,
)
from app.api.portfolio.asset_spec_adapter import (
    _merge_asset_spec_aliases as _merge_asset_spec_aliases,
)
from app.api.portfolio.asset_spec_adapter import (
    _metadata_from_config as _metadata_from_config,
)
from app.api.portfolio.asset_spec_adapter import (
    _position_spec_has_asset_metadata as _position_spec_has_asset_metadata,
)
from app.api.portfolio.asset_spec_adapter import (
    _row_can_use_local_asset_spec as _row_can_use_local_asset_spec,
)
from app.api.portfolio.instance_resolution import (
    _as_path,
    _coerce_int,
    _coerce_started_day,
    _current_user_id,
    _filter_rows_after_source_start,
    _infer_started_day_from_pid,
    _list_user_instances,
    _manager_instances_by_id,
    _trading_day,
    _trim_curve_by_source_start,
)
from app.api.portfolio.instance_resolution import (
    _row_date as _row_date,
)
from app.api.portfolio.portfolio_common import (
    _ACTIVE_TRADING_STATUSES,
    _append_unique,
    _first_number,
    _has_any,
    _PortfolioSource,
    _safe_dict,
    _safe_float,
    _safe_round,
    _unique_text,
)
from app.api.portfolio.portfolio_common import (
    _EXPLICIT_NET_PNL_FIELD_KEYS as _EXPLICIT_NET_PNL_FIELD_KEYS,
)
from app.api.portfolio.portfolio_common import (
    _GROSS_PNL_FIELD_KEYS as _GROSS_PNL_FIELD_KEYS,
)
from app.api.portfolio.portfolio_common import (
    _PORTFOLIO_TIMEZONE as _PORTFOLIO_TIMEZONE,
)
from app.api.portfolio.portfolio_common import (
    _is_float_input as _is_float_input,
)
from app.api.portfolio.portfolio_common import (
    _json_safe_value as _json_safe_value,
)
from app.api.portfolio.position_aggregation import (
    _allocation_asset_key,
    _build_position_summary,
    _latest_position_rows,
    _parse_query_ids,
    _position_data_time,
    _position_updated_at,
    _signed_market_value,
    _source_account_cash,
    _source_account_key,
    _source_account_time,
    _source_account_value,
    _source_has_confirmed_flat_positions,
    _source_snapshot_positions,
)
from app.api.portfolio.position_aggregation import (
    _empty_position_summary as _empty_position_summary,
)
from app.api.portfolio.position_aggregation import (
    _position_row_direction as _position_row_direction,
)
from app.api.portfolio.position_aggregation import (
    _snapshot_positions_for_portfolio as _snapshot_positions_for_portfolio,
)
from app.db.database import async_session_maker, get_db
from app.models.paper_runtime import PaperEquitySnapshot
from app.models.workspace import StrategyUnit, Workspace
from app.services import workspace_unit_runtime
from app.services.live_trading_manager import LiveTradingManager, get_live_trading_manager
from app.services.log_parser_service import (
    find_latest_log_dir,
    parse_current_position,
    parse_position_log,
    parse_run_info,
    parse_trade_log,
    parse_value_log,
)
from app.services.portfolio_composition import PortfolioCompositionService
from app.services.position_valuation import EPSILON, contract_spec_for, value_position
from app.services.strategy_service import get_strategy_dir
from app.services.trading_asset_info_service import (
    gateway_position_symbol,
    load_runtime_config,
    normalize_gateway_position,
    query_local_asset_spec,
    signed_gateway_size,
    split_bidirectional_position_row,
    symbol_aliases,
)
from app.services.workspace.units import is_server_owned_ai_research_unit

from . import asset_spec_adapter as _asset_spec_adapter
from . import instance_resolution as _instance_resolution
from . import portfolio_calculations as _portfolio_calculations

_COMMISSION_FIELD_KEYS = _portfolio_calculations._COMMISSION_FIELD_KEYS


def _infer_started_day_from_log_dir(
    log_dir: Path,
    *,
    allow_mtime_fallback: bool = True,
) -> str | None:
    return _instance_resolution._infer_started_day_from_log_dir(
        log_dir,
        allow_mtime_fallback=allow_mtime_fallback,
        parse_run_info_fn=parse_run_info,
        parse_value_log_fn=parse_value_log,
    )


def _source_started_day(source: _PortfolioSource) -> str | None:
    return _instance_resolution._source_started_day(
        source,
        infer_started_day_from_pid_fn=_infer_started_day_from_pid,
        infer_started_day_from_log_dir_fn=_infer_started_day_from_log_dir,
    )


def _resolve_instance_log_dir(inst: Mapping[str, object]) -> Path | None:
    return _instance_resolution._resolve_instance_log_dir(
        inst,
        find_latest_log_dir_fn=find_latest_log_dir,
        get_strategy_dir_fn=get_strategy_dir,
    )


def _contract_spec_for_position(
    symbol: str,
    row: dict[str, Any],
    source: _PortfolioSource,
) -> Any:
    return _asset_spec_adapter._contract_spec_for_position(
        symbol,
        row,
        source,
        contract_spec_for_fn=contract_spec_for,
        query_local_asset_spec_fn=query_local_asset_spec,
    )


def _complete_asset_specs_from_local(
    specs: dict[str, dict[str, Any]],
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    return _asset_spec_adapter._complete_asset_specs_from_local(
        specs,
        symbols,
        query_local_asset_spec_fn=query_local_asset_spec,
    )


logger = logging.getLogger(__name__)
router = APIRouter()


def _get_manager() -> LiveTradingManager:
    """Get the live trading manager instance.

    Returns:
        LiveTradingManager: The live trading manager singleton instance.
    """
    return get_live_trading_manager()


def _leverage_from_margin_rate(value: Any) -> float | None:
    return _portfolio_calculations.leverage_from_margin_rate(
        value,
        safe_float_fn=_safe_float,
        epsilon=EPSILON,
    )


def _runtime_config_for_instance(inst: Mapping[str, object]) -> dict[str, Any]:
    runtime_dir = _as_path(inst.get("runtime_dir"))
    if runtime_dir is not None:
        config = load_runtime_config(runtime_dir)
        if config:
            return config
    try:
        strategy_id = inst["strategy_id"]
        if not isinstance(strategy_id, str):
            return {}
        strategy_dir = Path(get_strategy_dir(strategy_id))
    except ValueError:
        return {}
    return load_runtime_config(strategy_dir)


def _source_from_instance(inst: Mapping[str, object]) -> _PortfolioSource:
    raw_params = inst.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    runtime_config = _runtime_config_for_instance(inst)
    return _PortfolioSource(
        id=str(inst.get("id") or ""),
        strategy_id=str(inst.get("strategy_id") or ""),
        strategy_name=str(inst.get("strategy_name") or inst.get("strategy_id") or ""),
        status=str(inst.get("status") or "unknown"),
        symbol=str(params.get("symbol") or ""),
        trading_mode=str(params.get("trading_mode") or "paper"),
        workspace_id=str(inst.get("workspace_id") or "") or None,
        log_dir=_resolve_instance_log_dir(inst),
        snapshot={},
        valuation_configs=(
            _safe_dict(runtime_config),
            _safe_dict(params),
            _safe_dict(params.get("unit_settings")),
            _safe_dict(params.get("data_config")),
            _safe_dict(params.get("gateway")),
            _safe_dict(params.get("simulate")),
            _safe_dict(params.get("backtest")),
            _safe_dict(params.get("live")),
        ),
        started_at=str(inst.get("started_at") or "").strip() or None,
        updated_at=_coerce_started_day(inst.get("updated_at")),
        pid=_coerce_int(inst.get("pid")),
    )


def _workspace_unit_log_dir(unit: StrategyUnit) -> Path | None:
    runtime_dir = workspace_unit_runtime.unit_dir(str(unit.workspace_id), str(unit.id))
    latest = find_latest_log_dir(runtime_dir)
    return Path(latest) if latest else None


def _workspace_unit_runtime_config(unit: StrategyUnit) -> dict[str, Any]:
    runtime_dir = workspace_unit_runtime.unit_dir(str(unit.workspace_id), str(unit.id))
    return load_runtime_config(runtime_dir)


async def _active_workspace_sources(
    current_user: Any,
    mgr: LiveTradingManager,
    *,
    include_inactive: bool = False,
) -> list[_PortfolioSource]:
    """Load trading workspace units from the database.

    The live-trading manager is process-local. Stress supervisors and the API
    server can run in separate Python processes, so portfolio pages must be able
    to aggregate from persisted workspace unit state and runtime logs.
    """
    user_id = _current_user_id(current_user)
    if not user_id:
        return []

    async with async_session_maker() as session:
        query = (
            select(StrategyUnit, Workspace)
            .join(Workspace, StrategyUnit.workspace_id == Workspace.id)
            .where(Workspace.user_id == user_id)
            .where(Workspace.workspace_type == "trading")
            .order_by(Workspace.name, StrategyUnit.sort_order, StrategyUnit.strategy_name)
        )
        if not include_inactive:
            query = query.where(StrategyUnit.run_status.in_(_ACTIVE_TRADING_STATUSES))
        result = await session.execute(query)
        rows = result.all()

    instance_ids = [
        str(unit.trading_instance_id or "").strip()
        for unit, _workspace in rows
        if str(unit.trading_instance_id or "").strip()
    ]
    manager_instances = (
        _manager_instances_by_id(mgr, user_id, instance_ids)
        if not include_inactive and instance_ids
        else None
    )
    sources: list[_PortfolioSource] = []
    for unit, workspace in rows:
        snapshot = unit.trading_snapshot if isinstance(unit.trading_snapshot, dict) else {}
        gateway_config = unit.gateway_config if isinstance(unit.gateway_config, dict) else {}
        runtime_config = _workspace_unit_runtime_config(unit)
        unit_name = str(unit.strategy_name or unit.strategy_id or unit.id)
        db_status = str(unit.run_status or snapshot.get("instance_status") or "idle")
        status = db_status.strip().lower()
        instance_id = str(unit.trading_instance_id or "").strip()
        instance: Mapping[str, object] | None = None
        if (
            not include_inactive
            and status in _ACTIVE_TRADING_STATUSES
            and instance_id
            and hasattr(mgr, "get_instance")
        ):
            if manager_instances is not None:
                instance = manager_instances.get(instance_id)
            else:
                try:
                    instance = mgr.get_instance(instance_id, user_id=user_id)
                except Exception:
                    instance = None
            if isinstance(instance, dict):
                status = str(instance.get("status") or "idle").strip().lower()
            else:
                status = "idle"
            if status not in _ACTIVE_TRADING_STATUSES:
                continue
        elif not include_inactive and status in _ACTIVE_TRADING_STATUSES and not instance_id:
            # A workspace unit without a live instance handle should not be treated
            # as actively running, otherwise stale historical rows can leak old
            # equity curves into live portfolio views.
            continue
        started_at = (
            str(instance.get("started_at") if isinstance(instance, dict) else "").strip() or None
        )
        updated_at = (
            str(instance.get("updated_at") if isinstance(instance, dict) else "").strip() or None
        )
        if include_inactive and not started_at:
            started_at = (
                str(snapshot.get("started_at") or "")
                or str(snapshot.get("instance_started_at") or "")
                or str(snapshot.get("start_time") or "")
                or str(snapshot.get("startedAt") or "")
            ).strip() or None
        sources.append(
            _PortfolioSource(
                id=str(unit.trading_instance_id or unit.id),
                strategy_id=str(unit.strategy_id or unit.id),
                strategy_name=f"{workspace.name} / {unit_name}",
                status=status,
                symbol=str(unit.symbol or ""),
                unit_id=str(unit.id),
                trading_mode=str(unit.trading_mode or snapshot.get("mode") or "paper"),
                workspace_id=str(workspace.id),
                log_dir=_workspace_unit_log_dir(unit),
                snapshot=dict(snapshot),
                valuation_configs=(
                    _safe_dict(runtime_config),
                    _safe_dict(unit.unit_settings),
                    _safe_dict(unit.params),
                    _safe_dict(unit.data_config),
                    _safe_dict(gateway_config),
                    _safe_dict(gateway_config.get("params")),
                ),
                started_at=started_at,
                updated_at=updated_at,
                pid=_coerce_int(instance.get("pid") if isinstance(instance, dict) else None),
            )
        )
    return sources


async def _persisted_running_workspace_sources(current_user: Any) -> list[_PortfolioSource]:
    """Load first-screen sources from the workspace snapshots only.

    The workspace service persists these snapshots as it refreshes each unit.
    A portfolio landing page can therefore render from the durable state
    without constructing the live-trading manager, which may restore gateway
    sessions and enumerate every historical instance in the process.
    """
    user_id = _current_user_id(current_user)
    if not user_id:
        return []

    async with async_session_maker() as session:
        result = await session.execute(
            select(StrategyUnit, Workspace)
            .join(Workspace, StrategyUnit.workspace_id == Workspace.id)
            .where(Workspace.user_id == user_id)
            .where(Workspace.workspace_type == "trading")
            .where(StrategyUnit.run_status == "running")
            .order_by(Workspace.name, StrategyUnit.sort_order, StrategyUnit.strategy_name)
        )
        rows = result.all()

    sources: list[_PortfolioSource] = []
    for unit, workspace in rows:
        instance_id = str(unit.trading_instance_id or "").strip()
        if not instance_id:
            continue
        snapshot = unit.trading_snapshot if isinstance(unit.trading_snapshot, dict) else {}
        snapshot_status = str(snapshot.get("instance_status") or "running").strip().lower()
        if snapshot_status not in _ACTIVE_TRADING_STATUSES:
            continue
        unit_name = str(unit.strategy_name or unit.strategy_id or unit.id)
        started_at = (
            str(
                snapshot.get("started_at")
                or snapshot.get("instance_started_at")
                or snapshot.get("start_time")
                or snapshot.get("startedAt")
                or ""
            ).strip()
            or None
        )
        sources.append(
            _PortfolioSource(
                id=instance_id,
                strategy_id=str(unit.strategy_id or unit.id),
                strategy_name=f"{workspace.name} / {unit_name}",
                status="running",
                symbol=str(unit.symbol or ""),
                unit_id=str(unit.id),
                trading_mode=str(unit.trading_mode or snapshot.get("mode") or "paper"),
                workspace_id=str(workspace.id),
                log_dir=_workspace_unit_log_dir(unit),
                snapshot=dict(snapshot),
                started_at=started_at,
                updated_at=_coerce_started_day(unit.updated_at),
            )
        )
    return sources


def _live_positions_for_source(
    mgr: LiveTradingManager,
    source: _PortfolioSource,
) -> list[dict[str, Any]] | None:
    if str(source.status or "").strip().lower() != "running" or not source.id:
        return None

    is_live = str(source.trading_mode or "").strip().lower() == "live"
    has_gateway = getattr(mgr, "has_instance_gateway", None)
    if callable(has_gateway):
        try:
            if not has_gateway(source.id):
                if is_live:
                    _append_unique(
                        source.valuation_warnings,
                        "运行中的策略未绑定可查询的交易所网关，持仓/盈亏将回落到本地日志或快照",
                    )
                return None
        except Exception:
            if is_live:
                _append_unique(
                    source.valuation_warnings,
                    "检查策略网关绑定失败，持仓/盈亏将回落到本地日志或快照",
                )
            return None

    query_positions = getattr(mgr, "query_instance_gateway_positions", None)
    if not callable(query_positions):
        if is_live:
            _append_unique(
                source.valuation_warnings,
                "当前管理器不支持实时网关持仓查询，持仓/盈亏将回落到本地日志或快照",
            )
        return None
    try:
        raw_positions = query_positions(source.id)
    except Exception:
        if is_live:
            _append_unique(
                source.valuation_warnings,
                "交易所网关持仓查询失败，持仓/盈亏将回落到本地日志或快照",
            )
        return None
    if not isinstance(raw_positions, list):
        _append_unique(source.valuation_warnings, "交易所网关持仓返回格式异常")
        return None

    allowed_aliases = _source_symbol_aliases(source)
    matched_positions: list[dict[str, Any]] = []
    symbols: list[str] = []
    seen: set[str] = set()
    for item in raw_positions:
        if not isinstance(item, dict):
            continue
        symbol = gateway_position_symbol(item, source.symbol)
        if allowed_aliases and not _position_symbol_matches(symbol, allowed_aliases):
            continue
        matched_positions.append(item)
        if symbol and symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
    if source.symbol and source.symbol not in seen:
        symbols.append(source.symbol)

    asset_specs: dict[str, dict[str, Any]] = {}
    query_specs = getattr(mgr, "query_instance_asset_specs", None)
    if callable(query_specs) and symbols:
        try:
            raw_specs = query_specs(source.id, symbols)
        except Exception:
            _append_unique(
                source.valuation_warnings,
                "交易所资产规格查询失败，乘数/保证金/手续费可能使用本地配置或默认值",
            )
            raw_specs = {}
        if isinstance(raw_specs, dict):
            asset_specs = {
                str(key): dict(value) for key, value in raw_specs.items() if isinstance(value, dict)
            }
    asset_specs = _merge_source_contract_metadata(asset_specs, source, symbols)
    asset_specs = _complete_asset_specs_from_local(asset_specs, symbols)
    source.resolved_asset_specs = {
        str(key): dict(value) for key, value in asset_specs.items() if isinstance(value, dict)
    }

    recent_trades: list[dict[str, Any]] = []
    query_trades = getattr(mgr, "query_instance_gateway_trades", None)
    if callable(query_trades) and symbols:
        for symbol in symbols:
            try:
                raw_trades = query_trades(source.id, symbol=symbol, limit=500)
            except TypeError:
                raw_trades = query_trades(source.id)
            except Exception:
                raw_trades = []
            if isinstance(raw_trades, list):
                for item in raw_trades:
                    if not isinstance(item, dict):
                        continue
                    trade = dict(item)
                    trade.setdefault("__query_symbol", symbol)
                    recent_trades.append(trade)

    positions: list[dict[str, Any]] = []
    for item in matched_positions:
        for side_item in split_bidirectional_position_row(item):
            if abs(signed_gateway_size(side_item)) <= EPSILON:
                continue
            symbol = gateway_position_symbol(side_item, source.symbol)
            positions.append(
                normalize_gateway_position(
                    side_item,
                    fallback_symbol=source.symbol,
                    asset_spec=_asset_spec_for_symbol(asset_specs, symbol),
                    recent_trades=recent_trades,
                )
            )
    source.position_source = "gateway"
    return positions


def _live_account_for_source(
    mgr: LiveTradingManager,
    source: _PortfolioSource,
) -> dict[str, Any] | None:
    if str(source.status or "").strip().lower() != "running" or not source.id:
        return None

    is_live = str(source.trading_mode or "").strip().lower() == "live"
    has_gateway = getattr(mgr, "has_instance_gateway", None)
    if callable(has_gateway):
        try:
            if not has_gateway(source.id):
                return None
        except Exception:
            if is_live:
                _append_unique(
                    source.valuation_warnings, "检查策略网关绑定失败，账户权益将回落到日志"
                )
            return None

    query_account = getattr(mgr, "query_instance_gateway_account", None)
    if not callable(query_account):
        if is_live:
            _append_unique(
                source.valuation_warnings, "当前管理器不支持实时网关账户查询，账户权益将回落到日志"
            )
        return None
    try:
        account = query_account(source.id)
    except Exception:
        if is_live:
            _append_unique(
                source.valuation_warnings, "交易所网关账户查询失败，账户权益将回落到日志"
            )
        return None
    if not isinstance(account, dict):
        if is_live:
            _append_unique(
                source.valuation_warnings, "交易所网关账户返回格式异常，账户权益将回落到日志"
            )
        return None
    source.account_source = str(account.get("account_source") or "gateway").strip() or "gateway"
    return account


async def _persist_source_asset_specs(current_user: Any, source: _PortfolioSource) -> None:
    if not source.unit_id or not source.resolved_asset_specs:
        return
    user_id = _current_user_id(current_user)
    if not user_id:
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(StrategyUnit, Workspace)
            .join(Workspace, StrategyUnit.workspace_id == Workspace.id)
            .where(StrategyUnit.id == source.unit_id)
            .where(Workspace.user_id == user_id)
        )
        row = result.first()
        if row is None:
            return
        unit = row[0]
        if is_server_owned_ai_research_unit(unit):
            # This endpoint is user-triggered and can resolve remote/local
            # specs.  Do not use it as a write channel into an attested paper
            # unit's parameters; review reads server-signed handoff evidence.
            return
        params = _safe_dict(unit.params)
        raw_metadata = params.get("contract_metadata")
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        changed = False
        for key, value in source.resolved_asset_specs.items():
            if not isinstance(value, dict):
                continue
            existing_value = _asset_spec_for_symbol(metadata, str(key))
            merged_value = _merge_asset_spec_update(existing_value, value)
            if existing_value != merged_value:
                changed = True
            for alias in symbol_aliases(str(key)):
                alias_key = str(alias)
                if metadata.get(alias_key) != merged_value:
                    changed = True
                metadata[alias_key] = dict(merged_value)
        if not changed:
            return
        params["contract_metadata"] = metadata
        unit.params = params
        await session.commit()


async def _portfolio_sources(
    current_user: Any,
    mgr: LiveTradingManager,
    *,
    include_inactive: bool = False,
) -> list[_PortfolioSource]:
    workspace_sources = await _active_workspace_sources(
        current_user,
        mgr,
        include_inactive=include_inactive,
    )
    sources = (
        workspace_sources
        if workspace_sources
        else [
            _source_from_instance(inst)
            for inst in _list_user_instances(mgr, current_user, include_inactive=include_inactive)
        ]
    )
    for source in sources:
        # A paper workspace is a collection of independent simulated portfolios.
        # Its gateway is only used to feed the running strategy, not to represent
        # the account/positions of every unit.  Querying that shared gateway here
        # once per unit both duplicates broker data and makes the risk page block
        # behind dozens of synchronous requests.  Use each unit's own logs and
        # persisted snapshot instead.  Keep the legacy instance fallback intact
        # for callers that do not originate from a workspace unit.
        if source.unit_id and str(source.trading_mode or "").strip().lower() == "paper":
            continue
        live_positions = _live_positions_for_source(mgr, source)
        if live_positions is not None:
            source.live_positions = live_positions
            await _persist_source_asset_specs(current_user, source)
        live_account = _live_account_for_source(mgr, source)
        if live_account is not None:
            source.live_account = live_account
    return sources


def _parse_positions_for_portfolio(log_dir: Path) -> list[dict[str, Any]]:
    position_log_rows = parse_position_log(log_dir)
    if position_log_rows:
        return [
            row
            for row in _latest_position_rows(position_log_rows)
            if abs(_safe_float(row.get("size"), 0.0)) > EPSILON
        ]
    return [
        row
        for row in parse_current_position(log_dir)
        if abs(_safe_float(row.get("size"), 0.0)) > EPSILON
    ]


def _source_positions(source: _PortfolioSource) -> list[dict[str, Any]]:
    if source.live_positions is not None:
        source.position_source = "gateway"
        return source.live_positions
    snapshot_positions = _source_snapshot_positions(source)
    if snapshot_positions:
        source.position_source = "snapshot"
        return snapshot_positions
    if source.log_dir:
        source.position_source = "log"
        return _parse_positions_for_portfolio(source.log_dir)
    source.position_source = None
    return []


def _position_valuation_warnings(
    source: _PortfolioSource,
    row: dict[str, Any],
    spec: Any,
    *,
    position_source: str,
) -> list[str]:
    return _portfolio_calculations.position_valuation_warnings(
        source,
        row,
        spec,
        position_source=position_source,
        has_any_fn=_has_any,
    )


def _position_row_should_recalculate_local_pnl(
    row: dict[str, Any],
    spec: Any,
    *,
    position_source: str,
    force: bool = False,
) -> bool:
    return _portfolio_calculations.position_row_should_recalculate_local_pnl(
        row,
        spec,
        position_source=position_source,
        force=force,
        has_any_fn=_has_any,
    )


def _position_row_for_valuation(
    row: dict[str, Any],
    spec: Any,
    *,
    position_source: str,
) -> dict[str, Any]:
    return _portfolio_calculations.position_row_for_valuation(
        row,
        spec,
        position_source=position_source,
        should_recalculate_fn=_position_row_should_recalculate_local_pnl,
    )


def _valued_source_positions(source: _PortfolioSource) -> list[dict[str, Any]]:
    return _portfolio_calculations.valued_source_positions(
        source,
        source_positions_fn=_source_positions,
        split_bidirectional_position_row_fn=split_bidirectional_position_row,
        contract_spec_for_position_fn=_contract_spec_for_position,
        position_row_for_valuation_fn=_position_row_for_valuation,
        value_position_fn=value_position,
        position_valuation_warnings_fn=_position_valuation_warnings,
        append_unique_fn=_append_unique,
        unique_text_fn=_unique_text,
        signed_market_value_fn=_signed_market_value,
        leverage_from_margin_rate_fn=_leverage_from_margin_rate,
        position_updated_at_fn=_position_updated_at,
        position_data_time_fn=_position_data_time,
    )


def _source_trades(
    source: _PortfolioSource,
    *,
    started_day: str | None = None,
) -> list[dict[str, Any]]:
    if source.log_dir:
        trades = parse_trade_log(source.log_dir)
    else:
        trades = [
            dict(item)
            for item in (source.snapshot or {}).get("trades") or []
            if isinstance(item, dict)
        ]
    return _filter_rows_after_source_start(
        trades,
        source_started_day=started_day,
        keys=("log_time", "event_time", "time", "dtclose", "datetime", "dtopen"),
    )


# ---------- Portfolio Overview ----------

# NOTE:
# The "simulation" variants below currently reuse the same aggregation logic as the
# live trading endpoints. If simulation instances are later stored separately from
# live instances, the underlying data source can be adjusted while keeping the
# API surface stable.


def _value_log_edge_rows(path: Path) -> tuple[list[str], list[str]]:
    """Read bounded head/tail samples from a value log without parsing its curve."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            head = [handle.readline().strip() for _ in range(32)]
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(size - 65536, 0))
            tail = handle.read().decode("utf-8", errors="ignore").splitlines()
    except OSError:
        return [], []
    return [line for line in head if line], [line.strip() for line in tail if line.strip()]


def _parse_value_log_edge_row(
    line: str,
    *,
    log_format: str,
    headers: list[str] | None = None,
) -> dict[str, Any]:
    """Parse one supported value-log row for the compact portfolio summary."""
    if log_format == "json":
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    if log_format == "tsv" and headers:
        values = line.split("\t")
        return {
            header: values[index] if index < len(values) else ""
            for index, header in enumerate(headers)
        }
    if log_format == "pipe":
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2:
            return {}
        row: dict[str, Any] = {}
        for part in parts[1:]:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            row[key.strip()] = value.strip()
        return row
    return {}


def _compact_value_log_summary(
    log_dir: Path | None,
    *,
    started_day: str | None = None,
) -> tuple[float, float, float] | None:
    """Return initial equity, latest equity and latest cash from a value log.

    Full portfolio analytics need every point in the curve. The first-screen
    cards only need its two endpoints, so scanning a bounded head/tail window
    avoids decoding thousands of JSON rows across a large workspace.
    """
    path = (log_dir / "value.log") if log_dir is not None else None
    if path is None or not path.is_file():
        return None
    if started_day:
        parsed = parse_value_log(path.parent, prefer_log_time=True)
        dates = list(parsed.get("dates") or [])
        equity = list(parsed.get("equity_curve") or [])
        cash = list(parsed.get("cash_curve") or [])
        if not dates or not equity:
            return None
        started = _trading_day(started_day)
        if started:
            dates, equity, cash = _trim_curve_by_source_start(dates, equity, cash, started)
        if not dates:
            return None
        if not cash:
            cash = [0.0 for _ in dates]
        return (equity[0], equity[-1], cash[-1])

    head, tail = _value_log_edge_rows(path)
    if not head:
        return None

    first = head[0]
    if first.startswith("{"):
        log_format, headers = "json", None
        head_rows = head
    elif "\t" in first:
        log_format, headers = "tsv", first.split("\t")
        head_rows = head[1:]
    elif "|" in first:
        log_format, headers = "pipe", None
        head_rows = head
    else:
        return None

    def extract(lines: list[str], *, reverse: bool = False) -> tuple[float, float] | None:
        candidates = reversed(lines) if reverse else lines
        for line in candidates:
            row = _parse_value_log_edge_row(line, log_format=log_format, headers=headers)
            value = _first_number(row, "value", "broker_value")
            if value is None or not math.isfinite(value) or abs(value) > 1e15:
                continue
            cash = _first_number(row, "cash", "broker_cash")
            if cash is None or not math.isfinite(cash) or abs(cash) > 1e15:
                cash = 0.0
            if cash and abs(value) > abs(cash) * 1000:
                continue
            return value, cash
        return None

    initial = extract(head_rows)
    latest = extract(tail, reverse=True)
    if initial is None or latest is None:
        return None
    return initial[0], latest[0], latest[1]


def _workspace_unit_value_log_summary(
    unit: StrategyUnit,
    *,
    started_day: str | None = None,
) -> tuple[float, float, float] | None:
    return _compact_value_log_summary(_workspace_unit_log_dir(unit), started_day=started_day)


def _is_running_portfolio_source(source: _PortfolioSource) -> bool:
    """Return whether a source belongs to a currently running workspace unit.

    ``_portfolio_sources`` obtains workspace instances through the live manager,
    which has already verified the process state before exposing ``running``.
    A PID is useful metadata, but not every compatible manager implementation
    exposes it; requiring it here silently removed valid portfolio sources.
    """
    return str(source.status or "").strip().lower() == "running"


def _compact_workspace_overview(rows: list[_PortfolioSource]) -> dict[str, Any]:
    """Build a first-screen portfolio summary from persisted workspace snapshots.

    The detailed portfolio view reads strategy logs and, for legacy instances,
    can query a gateway. That is appropriate for drill-down views but becomes
    prohibitively expensive when hundreds of paper units are running. The
    workspace snapshot is refreshed by the trading service, so it is the right
    source for the page's initial metric cards.
    """

    def safe_round(value: float, digits: int | None = None) -> float:
        if digits is None:
            return _safe_round(value)
        return _safe_round(value, digits)

    return _portfolio_calculations.compact_workspace_overview(
        rows,
        safe_dict_fn=_safe_dict,
        source_started_day_fn=_source_started_day,
        compact_value_log_summary_fn=_compact_value_log_summary,
        first_number_fn=_first_number,
        safe_round_fn=safe_round,
        epsilon=EPSILON,
    )


async def _compact_portfolio_overview(
    current_user: Any,
    mgr: LiveTradingManager,
) -> dict[str, Any] | None:
    sources = await _active_workspace_sources(current_user, mgr, include_inactive=False)
    if any(str(source.trading_mode or "").strip().lower() == "live" for source in sources):
        # Live workspaces may require a broker account query to remain accurate.
        # Retain the detailed path for that safety-sensitive case.
        return None
    return _compact_workspace_overview(sources)


async def _persisted_compact_portfolio_overview(current_user: Any) -> dict[str, Any]:
    """Build a first-screen overview without initializing the live manager."""
    return _compact_workspace_overview(await _persisted_running_workspace_sources(current_user))


@router.get(
    "/overview/summary",
    summary="Portfolio overview (persisted first-screen summary)",
    response_model=None,
)
async def get_portfolio_overview_summary(
    current_user: typing.Any = Depends(get_current_user),
) -> dict[str, Any]:
    """Return fast first-screen totals from persisted workspace snapshots.

    Detailed portfolio routes continue to validate live processes and gateways.
    This endpoint intentionally avoids that work so navigating to the portfolio
    page remains responsive when many historical instances exist.
    """
    return await _persisted_compact_portfolio_overview(current_user)


@router.get("/overview", summary="Portfolio overview (live trading)", response_model=None)
async def get_portfolio_overview(
    summary_only: bool = False,
    include_inactive: bool = False,
    portfolio_ref: str | None = Query(default=None, min_length=1, max_length=128),
    membership_version: int | None = Query(default=None, ge=1),
    current_user: typing.Any = Depends(get_current_user),
    mgr: LiveTradingManager = Depends(_get_manager),
    db: AsyncSession = Depends(get_db),
) -> typing.Any:
    """Return portfolio-level aggregated metrics.

    Aggregates data across all live trading instances including total assets,
    cash, PnL, and per-strategy summaries.

    Args:
        current_user: The authenticated user.
        mgr: The live trading manager.

    Returns:
        A dictionary containing portfolio overview metrics including:
            - total_assets: Total portfolio value
            - total_cash: Total cash across all strategies
            - total_position_value: Total value of open positions
            - total_initial_capital: Total initial capital
            - total_pnl: Total profit/loss
            - total_pnl_pct: Total PnL percentage
            - strategy_count: Number of strategies
            - running_count: Number of running strategies
            - strategies: List of per-strategy summaries
    """
    if (portfolio_ref is None) != (membership_version is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "COMPOSITION_VERSION_REQUIRED"},
        )
    if portfolio_ref is not None and membership_version is not None:
        composition_service = PortfolioCompositionService(db)
        composition = await composition_service.get_version(
            current_user.sub, portfolio_ref, membership_version
        )
        return await composition_service.project(current_user, composition)

    if summary_only:
        compact_overview = await _compact_portfolio_overview(current_user, mgr)
        if compact_overview is not None:
            return compact_overview

    sources = await _portfolio_sources(current_user, mgr, include_inactive=include_inactive)
    if not include_inactive:
        sources = [source for source in sources if _is_running_portfolio_source(source)]

    total_assets = 0.0
    total_cash = 0.0
    total_initial = 0.0
    total_position_gross = 0.0
    total_position_net = 0.0
    has_position_data = False
    strategy_summaries = []
    counted_account_keys: set[str] = set()

    for source in sources:
        log_dir = source.log_dir
        started_day = _source_started_day(source) if not include_inactive else None
        valued_positions = _valued_source_positions(source)
        position_summary = _build_position_summary(valued_positions)
        has_source_positions = bool(
            position_summary["long_count"]
            or position_summary["short_count"]
            or position_summary["flat_count"]
        )
        has_source_position_data = has_source_positions or _source_has_confirmed_flat_positions(
            source
        )
        account_value = _source_account_value(source)
        account_cash = _source_account_cash(source)
        account_key = _source_account_key(source) if account_value is not None else ""
        account_counted = False
        if not log_dir:
            if account_value is not None and account_key not in counted_account_keys:
                total_assets += account_value
                total_cash += account_cash if account_cash is not None else 0.0
                total_initial += account_value
                counted_account_keys.add(account_key)
                account_counted = True
            if has_source_positions:
                has_position_data = True
                total_position_gross += float(position_summary["gross_market_value"])
                total_position_net += float(position_summary["net_market_value"])
            elif has_source_position_data:
                has_position_data = True
            strategy_summaries.append(
                {
                    "id": source.id,
                    "strategy_id": source.strategy_id,
                    "strategy_name": source.strategy_name,
                    "status": source.status,
                    "position_source": source.position_source,
                    "account_source": source.account_source,
                    "account_counted_in_totals": account_counted,
                    "asset_spec_source": source.asset_spec_source,
                    "valuation_status": source.valuation_status,
                    "valuation_warnings": list(source.valuation_warnings),
                    "total_assets": _safe_round(account_value or 0.0),
                    "initial_capital": _safe_round(account_value or 0.0),
                    "pnl": 0,
                    "pnl_pct": 0,
                    "total_trades": 0,
                    "win_rate": 0,
                }
            )
            continue

        value_data = parse_value_log(log_dir, prefer_log_time=True)
        equity = value_data.get("equity_curve", [])
        cash = value_data.get("cash_curve", [])
        if started_day:
            dates = value_data.get("dates", [])
            if dates and equity:
                dates, equity, cash = _trim_curve_by_source_start(
                    dates=dates,
                    equity=equity,
                    cash=cash,
                    source_started_day=started_day,
                )
            value_data["equity_curve"] = equity
            value_data["cash_curve"] = cash

        trades = _source_trades(source, started_day=started_day)

        initial = equity[0] if equity else 0
        final = equity[-1] if equity else 0
        final_cash = cash[-1] if cash else 0
        pnl = final - initial
        pnl_pct = (pnl / initial * 100) if initial > 0 else 0

        if account_value is not None:
            if account_key not in counted_account_keys:
                total_assets += account_value
                total_cash += account_cash if account_cash is not None else final_cash
                total_initial += initial if initial > 0 else account_value
                counted_account_keys.add(account_key)
                account_counted = True
        else:
            total_assets += final
            total_cash += final_cash
            total_initial += initial
        if has_source_positions:
            has_position_data = True
            total_position_gross += float(position_summary["gross_market_value"])
            total_position_net += float(position_summary["net_market_value"])
        elif has_source_position_data:
            has_position_data = True

        total_t = len(trades)
        win_t = len([t for t in trades if t.get("pnlcomm", 0) > 0])

        strategy_summaries.append(
            {
                "id": source.id,
                "strategy_id": source.strategy_id,
                "strategy_name": source.strategy_name,
                "status": source.status,
                "position_source": source.position_source,
                "account_source": source.account_source,
                "account_counted_in_totals": account_counted,
                "asset_spec_source": source.asset_spec_source,
                "valuation_status": source.valuation_status,
                "valuation_warnings": list(source.valuation_warnings),
                "total_assets": _safe_round(account_value if account_value is not None else final),
                "initial_capital": _safe_round(initial),
                "pnl": _safe_round(
                    (account_value - initial) if account_value is not None and initial > 0 else pnl
                ),
                "pnl_pct": _safe_round(
                    (
                        (account_value - initial) / initial * 100
                        if account_value is not None and initial > 0
                        else pnl_pct
                    ),
                    2,
                ),
                "total_trades": total_t,
                "win_rate": _safe_round(win_t / total_t * 100 if total_t > 0 else 0, 1),
            }
        )

    total_pnl = total_assets - total_initial
    total_pnl_pct = (total_pnl / total_initial * 100) if total_initial > 0 else 0
    running_count = sum(1 for source in sources if source.status == "running")
    fallback_net_position = total_assets - total_cash
    if not has_position_data:
        total_position_gross = abs(fallback_net_position)
        total_position_net = fallback_net_position

    return {
        "total_assets": _safe_round(total_assets),
        "total_cash": _safe_round(total_cash),
        "total_position_value": _safe_round(total_position_gross),
        "net_position_value": _safe_round(total_position_net),
        "total_initial_capital": _safe_round(total_initial),
        "total_pnl": _safe_round(total_pnl),
        "total_pnl_pct": _safe_round(total_pnl_pct, 2),
        "strategy_count": len(sources),
        "running_count": running_count,
        "strategies": strategy_summaries,
    }


# ---------- Aggregated Positions ----------


@router.get("/positions", summary="Aggregated positions (live trading)", response_model=None)
async def get_portfolio_positions(
    include_inactive: bool = False,
    current_user: typing.Any = Depends(get_current_user),
    mgr: LiveTradingManager = Depends(_get_manager),
) -> typing.Any:
    """Return current positions across strategies (from current_position.json).

    Args:
        current_user: The authenticated user.
        mgr: The live trading manager.

    Returns:
        A dictionary containing total count and list of positions with:
            - strategy_id: The strategy identifier
            - strategy_name: The strategy display name
            - instance_id: The instance identifier
            - data_name: The symbol/instrument name
            - size: Position size (positive for long, negative for short)
            - price: Average entry price
            - market_value: Current market value
            - direction: Position direction ("long", "short", or "flat")
    """
    sources = await _portfolio_sources(current_user, mgr, include_inactive=include_inactive)
    positions = []

    for source in sources:
        cur_pos = _valued_source_positions(source)
        for p in cur_pos:
            size = float(p.get("size") or 0.0)
            if abs(size) <= EPSILON:
                continue
            price = float(p.get("price") or 0.0)
            market_value = float(p.get("market_value") or 0.0)
            latest_price = float(p.get("latest_price") or price)
            position_pnl = float(p.get("position_pnl") or 0.0)
            positions.append(
                {
                    "strategy_id": source.strategy_id,
                    "strategy_name": source.strategy_name,
                    "instance_id": source.id,
                    "data_name": str(p.get("data_name") or ""),
                    "size": size,
                    "price": price,
                    "latest_price": _safe_round(latest_price, 4),
                    "market_value": _safe_round(abs(market_value), 6),
                    "signed_market_value": _safe_round(
                        float(p.get("signed_market_value") or 0.0), 6
                    ),
                    "position_pnl": _safe_round(position_pnl),
                    "gross_pnl": _safe_round(float(p.get("gross_pnl") or 0.0)),
                    "commission": _safe_round(float(p.get("commission") or 0.0), 4),
                    "commission_source": p.get("commission_source"),
                    "multiplier": _safe_round(float(p.get("multiplier") or 1.0), 8),
                    "margin_rate": _safe_round(float(p.get("margin_rate") or 0.0), 8),
                    "leverage": p.get("leverage"),
                    "margin_value": _safe_round(float(p.get("margin_value") or 0.0)),
                    "updated_at": _position_updated_at(p),
                    "data_time": _position_data_time(p),
                    "direction": "long" if size > 0 else ("short" if size < 0 else "flat"),
                    "position_source": p.get("position_source"),
                    "asset_spec_source": p.get("asset_spec_source"),
                    "valuation_status": p.get("valuation_status"),
                    "valuation_warnings": list(p.get("valuation_warnings") or []),
                }
            )

    response = {
        "total": len(positions),
        "positions": positions,
        "summary": _build_position_summary(positions),
    }
    warnings = [
        warning for source in sources for warning in list(source.valuation_warnings) if warning
    ]
    if warnings:
        response["warnings"] = warnings
    return response


# ---------- Aggregated Trades ----------


@router.get("/trades", summary="Aggregated trade records (live trading)", response_model=None)
async def get_portfolio_trades(
    limit: int = 200,
    workspace_ids: Annotated[list[str] | None, Query()] = None,
    include_inactive: bool = Query(default=False),
    current_user: typing.Any = Depends(get_current_user),
    mgr: LiveTradingManager = Depends(_get_manager),
) -> typing.Any:
    """Return historical trades across strategies (from trade.log), sorted by close time.

    Args:
        limit: Maximum number of trades to return.
        current_user: The authenticated user.
        mgr: The live trading manager.

    Returns:
        A dictionary containing total count and list of trades, sorted by
        close date in descending order (most recent first).
    """
    workspace_id_set = _parse_query_ids(workspace_ids)
    include_inactive_sources = include_inactive
    sources = await _portfolio_sources(
        current_user,
        mgr,
        include_inactive=include_inactive_sources,
    )
    if workspace_id_set:
        sources = [source for source in sources if source.workspace_id in workspace_id_set]
    if not include_inactive:
        sources = [
            source
            for source in sources
            if str(source.status or "").strip().lower() in _ACTIVE_TRADING_STATUSES
        ]
    all_trades = []

    for source in sources:
        started_day = None if include_inactive else _source_started_day(source)
        trades = _source_trades(source, started_day=started_day)
        for t in trades:
            item = dict(t)
            item["strategy_id"] = source.strategy_id
            item["strategy_name"] = source.strategy_name
            item["instance_id"] = source.id
            item["workspace_id"] = source.workspace_id
            all_trades.append(item)

    # Sort by close date descending
    all_trades.sort(key=lambda x: x.get("dtclose", ""), reverse=True)

    return {"total": len(all_trades), "trades": all_trades[:limit]}


# ---------- Portfolio Equity Curve ----------


_PAPER_RUNTIME_MODES = frozenset({"paper", "simulation", "simulated"})
_MAX_PORTFOLIO_EQUITY_POINTS = 1_500


def _is_paper_runtime_source(source: _PortfolioSource) -> bool:
    """Return whether a source represents a simulated trading runtime."""
    return str(source.trading_mode or "paper").strip().lower() in _PAPER_RUNTIME_MODES


def _sample_indexes(length: int, max_points: int = _MAX_PORTFOLIO_EQUITY_POINTS) -> list[int]:
    """Return shared sample indexes so every portfolio series stays aligned."""
    if length <= max_points:
        return list(range(length))
    step = (length - 1) / (max_points - 1)
    return [round(index * step) for index in range(max_points)]


async def _paper_equity_points(
    current_user: typing.Any,
    sources: list[_PortfolioSource],
) -> dict[str, list[tuple[str, float, float, float]]]:
    """Load canonical equity snapshots for the current run of each paper instance."""
    instance_ids = sorted({source.id for source in sources if _is_paper_runtime_source(source)})
    user_id = _current_user_id(current_user)
    if not instance_ids or not user_id:
        return {}

    async with async_session_maker() as session:
        result = await session.execute(
            select(PaperEquitySnapshot)
            .where(
                PaperEquitySnapshot.user_id == user_id,
                PaperEquitySnapshot.instance_id.in_(instance_ids),
            )
            .order_by(
                PaperEquitySnapshot.instance_id,
                PaperEquitySnapshot.observed_at,
                PaperEquitySnapshot.id,
            )
        )
        snapshots = result.scalars().all()

    points_by_instance: dict[str, list[tuple[str, float, float, float]]] = {}
    for snapshot in snapshots:
        observed_at = snapshot.observed_at.replace(second=0, microsecond=0)
        point = (
            observed_at.isoformat(),
            float(snapshot.total_equity),
            float(snapshot.cash),
            float(snapshot.realized_pnl) + float(snapshot.unrealized_pnl),
        )
        # A paper instance id is deliberately reused when a workspace unit is
        # restarted. ``initial`` marks the beginning of the new runtime, so
        # prior snapshots must not be joined to its current equity curve.
        if str(snapshot.source or "").strip().lower() == "initial":
            points_by_instance[snapshot.instance_id] = []
        instance_points = points_by_instance.setdefault(snapshot.instance_id, [])
        if instance_points and instance_points[-1][0] == point[0]:
            instance_points[-1] = point
        else:
            instance_points.append(point)

    return points_by_instance


def _paper_runtime_value_data(
    source: _PortfolioSource,
    paper_points: list[tuple[str, float, float, float]],
) -> dict[str, list[Any]]:
    """Prepend current-runtime log history that predates paper snapshots."""
    snapshot_dates = [point[0] for point in paper_points]
    snapshot_equity = [point[1] for point in paper_points]
    snapshot_cash = [point[2] for point in paper_points]
    snapshot_pnl = [point[3] for point in paper_points]

    # ``parse_value_log`` already handles a missing or empty log directory.
    # Do not pre-filter with ``Path.is_dir``: compatibility adapters may hand
    # us a path-like runtime log location whose existence is resolved by the
    # parser itself, and an empty snapshot history must still fall back to it.
    log_data = parse_value_log(source.log_dir, prefer_log_time=False) if source.log_dir else {}
    log_dates = list(log_data.get("datetimes") or log_data.get("dates", []))
    log_equity = list(log_data.get("equity_curve", []))
    log_cash = list(log_data.get("cash_curve", []))
    first_snapshot_day = _trading_day(snapshot_dates[0]) if snapshot_dates else ""

    history_dates: list[str] = []
    history_equity: list[float] = []
    history_cash: list[float] = []
    history_pnl: list[float] = []
    initial_log_equity = _safe_float(log_equity[0]) if log_equity else 0.0
    initial_log_cash = _safe_float(log_cash[0]) if log_cash else initial_log_equity
    base_equity = snapshot_equity[0] if snapshot_equity else initial_log_equity
    base_cash = snapshot_cash[0] if snapshot_cash else initial_log_cash
    base_pnl = snapshot_pnl[0] if snapshot_pnl else 0.0
    for index, dt in enumerate(log_dates):
        if index >= len(log_equity):
            break
        if first_snapshot_day and _trading_day(dt) >= first_snapshot_day:
            continue
        equity_delta = _safe_float(log_equity[index]) - initial_log_equity
        cash_delta = (
            _safe_float(log_cash[index]) - initial_log_cash
            if index < len(log_cash)
            else equity_delta
        )
        history_dates.append(str(dt))
        history_equity.append(base_equity + equity_delta)
        history_cash.append(base_cash + cash_delta)
        history_pnl.append(base_pnl + equity_delta)

    return {
        "datetimes": [*history_dates, *snapshot_dates],
        "equity_curve": [*history_equity, *snapshot_equity],
        "cash_curve": [*history_cash, *snapshot_cash],
        "pnl_curve": [*history_pnl, *snapshot_pnl],
    }


@router.get("/equity", summary="Portfolio equity curve (live trading)", response_model=None)
async def get_portfolio_equity(
    workspace_ids: Annotated[list[str] | None, Query()] = None,
    include_inactive: bool = Query(default=False),
    current_user: typing.Any = Depends(get_current_user),
    mgr: LiveTradingManager = Depends(_get_manager),
) -> typing.Any:
    """Return portfolio-level equity curve - aligning and stacking strategy equity by date.

    Also returns individual strategy equity curves so the client can switch
    between the whole portfolio and a strategy unit.

    Args:
        current_user: The authenticated user.
        mgr: The live trading manager.

    Returns:
        A dictionary containing:
            - dates: List of all dates across strategies
            - total_equity: Portfolio total equity per date
            - total_drawdown: Portfolio drawdown per date
            - strategies: List of per-strategy equity curves
    """
    workspace_id_set = _parse_query_ids(workspace_ids)
    include_inactive_sources = include_inactive
    sources = await _portfolio_sources(
        current_user,
        mgr,
        include_inactive=include_inactive_sources,
    )
    if workspace_id_set:
        sources = [source for source in sources if source.workspace_id in workspace_id_set]
    if not include_inactive:
        sources = [source for source in sources if _is_running_portfolio_source(source)]

    paper_points_by_source = await _paper_equity_points(current_user, sources)

    # Each strategy's date -> value mapping
    strategy_curves: list[dict[str, Any]] = []
    unavailable_strategies: list[dict[str, Any]] = []
    all_dates_set: set = set()
    counted_account_keys: set[str] = set()

    for source in sources:
        paper_runtime_source = _is_paper_runtime_source(source)
        if paper_runtime_source:
            paper_points = paper_points_by_source.get(source.id, [])
            value_data = _paper_runtime_value_data(source, paper_points)
        else:
            log_dir = source.log_dir
            value_data = parse_value_log(log_dir, prefer_log_time=True) if log_dir else {}
        dates = value_data.get("datetimes") or value_data.get("dates", [])
        equity = value_data.get("equity_curve", [])
        cash = value_data.get("cash_curve", [])
        pnl = value_data.get("pnl_curve", [])
        # A canonical paper snapshot is already scoped to the active runtime.
        # When it is not available we are reading a regular runtime log, so the
        # same start-time guard used by live strategies must apply.
        has_paper_snapshot = paper_runtime_source and bool(paper_points)
        if not include_inactive and not has_paper_snapshot:
            started_day = _source_started_day(source)
            if dates and equity:
                dates, equity, cash = _trim_curve_by_source_start(
                    dates=dates,
                    equity=equity,
                    cash=cash,
                    source_started_day=started_day,
                )

        if not pnl and equity:
            initial_equity = float(equity[0])
            pnl = [float(value) - initial_equity for value in equity]

        if not dates:
            # Paper snapshots belong to workspace units. Legacy manager
            # instances without a workspace must still be able to show their
            # gateway account when no local curve has been written yet.
            if paper_runtime_source and source.unit_id:
                unavailable_strategies.append(
                    {
                        "strategy_id": source.strategy_id,
                        "strategy_name": source.strategy_name,
                        "instance_id": source.id,
                        "values": [],
                        "value_source": "paper_snapshot_unavailable",
                    }
                )
                continue
            account_value = _source_account_value(source)
            if account_value is None:
                unavailable_strategies.append(
                    {
                        "strategy_id": source.strategy_id,
                        "strategy_name": source.strategy_name,
                        "instance_id": source.id,
                        "values": [],
                        "value_source": "unavailable",
                    }
                )
                continue
            account_key = _source_account_key(source)
            if account_key in counted_account_keys:
                unavailable_strategies.append(
                    {
                        "strategy_id": source.strategy_id,
                        "strategy_name": source.strategy_name,
                        "instance_id": source.id,
                        "values": [],
                        "value_source": "shared_account",
                    }
                )
                continue
            counted_account_keys.add(account_key)
            live_date = _source_account_time(source)
            dates = [live_date]
            equity = [account_value]
            cash = [_source_account_cash(source) or 0.0]
            pnl = [0.0]
            value_source = source.account_source or "gateway"
        else:
            value_source = "paper_snapshot_with_runtime_log" if has_paper_snapshot else "log"

        date_map = {}
        for i, dt in enumerate(dates):
            date_map[dt] = {
                "equity": equity[i] if i < len(equity) else 0,
                "cash": cash[i] if i < len(cash) else 0,
                "pnl": pnl[i] if i < len(pnl) else 0,
            }
        all_dates_set.update(dates)

        strategy_curves.append(
            {
                "strategy_id": source.strategy_id,
                "strategy_name": source.strategy_name,
                "instance_id": source.id,
                "date_map": date_map,
                "initial": equity[0] if equity else 0,
                "first_trading_day": _trading_day(dates[0]) if dates else "",
                "value_source": value_source,
            }
        )

    if not all_dates_set:
        return {
            "dates": [],
            "total_equity": [],
            "cumulative_pnl": [],
            "total_drawdown": [],
            "strategies": unavailable_strategies,
        }

    sorted_dates = sorted(all_dates_set)

    # Aggregate
    total_equity = []
    cumulative_pnl = []
    strategy_series: dict[str, list[float]] = {sc["instance_id"]: [] for sc in strategy_curves}
    strategy_pnl_series: dict[str, list[float]] = {sc["instance_id"]: [] for sc in strategy_curves}

    for dt in sorted_dates:
        day_total = 0.0
        day_pnl = 0.0
        for sc in strategy_curves:
            dm = sc["date_map"]
            if dt in dm:
                val = dm[dt]["equity"]
                sc["_seen"] = True
                series_val = val
                pnl_val = dm[dt]["pnl"]
                sc["_pnl_seen"] = True
            elif sc.get("_seen"):
                val = sc.get("_last", sc.get("initial", 0.0))
                series_val = val
                pnl_val = sc.get("_last_pnl", 0.0)
            else:
                # A process that first reports later in the *same* trading day
                # already had its initial capital at market open. Seed it only
                # within that day so an intraday startup does not create a
                # false portfolio jump. Earlier trading days must remain zero:
                # the runtime did not exist yet and should not rewrite history.
                starts_today = _trading_day(dt) == sc.get("first_trading_day")
                val = sc.get("initial", 0.0) if starts_today else 0.0
                series_val = val
                pnl_val = 0.0
            sc["_last"] = val
            sc["_last_pnl"] = pnl_val
            day_total += val
            day_pnl += pnl_val
            strategy_series[sc["instance_id"]].append(_safe_round(series_val))
            strategy_pnl_series[sc["instance_id"]].append(_safe_round(pnl_val))
        total_equity.append(_safe_round(day_total))
        cumulative_pnl.append(_safe_round(day_pnl))

    # Drawdown must use the same high-water mark as the total-equity curve
    # rendered by the client.  A cumulative-PnL peak with fixed initial capital
    # becomes inaccurate when the portfolio's capital or strategy mix changes.
    total_drawdown = []
    equity_peak = 0.0
    for equity_value in total_equity:
        equity_peak = max(equity_peak, equity_value)
        drawdown = (equity_value - equity_peak) / equity_peak if equity_peak > EPSILON else 0.0
        total_drawdown.append(_safe_round(drawdown, 6))

    # Sampling only after aggregation keeps every strategy on the same time
    # axis. Per-instance sampling creates staggered gaps and visible sawtooth
    # jumps when hundreds of runtimes are combined.
    sample_indexes = _sample_indexes(len(sorted_dates))
    sorted_dates = [sorted_dates[index] for index in sample_indexes]
    total_equity = [total_equity[index] for index in sample_indexes]
    cumulative_pnl = [cumulative_pnl[index] for index in sample_indexes]
    total_drawdown = [total_drawdown[index] for index in sample_indexes]
    strategy_series = {
        instance_id: [values[index] for index in sample_indexes]
        for instance_id, values in strategy_series.items()
    }
    strategy_pnl_series = {
        instance_id: [values[index] for index in sample_indexes]
        for instance_id, values in strategy_pnl_series.items()
    }

    strategies_out = []
    for sc in strategy_curves:
        strategies_out.append(
            {
                "strategy_id": sc["strategy_id"],
                "strategy_name": sc["strategy_name"],
                "instance_id": sc["instance_id"],
                "values": strategy_series[sc["instance_id"]],
                "pnl_values": strategy_pnl_series[sc["instance_id"]],
                "value_source": sc.get("value_source"),
            }
        )

    return {
        "dates": sorted_dates,
        "total_equity": total_equity,
        "cumulative_pnl": cumulative_pnl,
        "total_drawdown": total_drawdown,
        "strategies": [*strategies_out, *unavailable_strategies],
    }


# ---------- Asset Allocation ----------


@router.get(
    "/allocation", summary="Asset allocation by open positions (live trading)", response_model=None
)
async def get_portfolio_allocation(
    workspace_ids: Annotated[list[str] | None, Query()] = None,
    include_inactive: bool = Query(default=False),
    current_user: typing.Any = Depends(get_current_user),
    mgr: LiveTradingManager = Depends(_get_manager),
) -> typing.Any:
    """Return the open-position allocation of each traded asset in the portfolio.

    Positions from the same asset are merged across strategies and workspaces.
    Allocation weights use gross market exposure, so long and short legs both
    contribute to an asset's share of the portfolio.

    Args:
        workspace_ids: Optional trading workspace IDs to include.
        current_user: The authenticated user.
        mgr: The live trading manager.

    Returns:
        A dictionary containing:
            - total: Total gross market exposure of open positions
            - items: One merged allocation item per traded asset
    """
    workspace_id_set = _parse_query_ids(workspace_ids)
    include_inactive_sources = include_inactive
    sources = await _portfolio_sources(
        current_user,
        mgr,
        include_inactive=include_inactive_sources,
    )
    if workspace_id_set:
        sources = [source for source in sources if source.workspace_id in workspace_id_set]
        if not include_inactive:
            sources = [
                source
                for source in sources
                if str(source.status or "").strip().lower() in _ACTIVE_TRADING_STATUSES
            ]

    allocations: dict[str, dict[str, Any]] = {}
    total = 0.0

    for source in sources:
        for position in _valued_source_positions(source):
            size = _safe_float(position.get("size"), 0.0)
            market_value = abs(_safe_float(position.get("market_value"), 0.0))
            asset = _allocation_asset_key(position.get("data_name"))
            if not asset or abs(size) <= EPSILON or market_value <= EPSILON:
                continue
            item = allocations.setdefault(
                asset,
                {
                    "asset": asset,
                    "value": 0.0,
                    "long_value": 0.0,
                    "short_value": 0.0,
                    "net_value": 0.0,
                    "position_count": 0,
                },
            )
            item["value"] += market_value
            if size > 0:
                item["long_value"] += market_value
                item["net_value"] += market_value
            else:
                item["short_value"] += market_value
                item["net_value"] -= market_value
            item["position_count"] += 1
            total += market_value

    items = sorted(allocations.values(), key=lambda item: (-item["value"], item["asset"]))
    for item in items:
        item["value"] = _safe_round(item["value"])
        item["long_value"] = _safe_round(item["long_value"])
        item["short_value"] = _safe_round(item["short_value"])
        item["net_value"] = _safe_round(item["net_value"])
        item["weight"] = _safe_round(item["value"] / total * 100, 2) if total > 0 else 0

    return {"total": _safe_round(total), "items": items}


# =====================================================================
# Simulation trading variants
# =====================================================================


@router.get(
    "/simulation/overview", summary="Portfolio overview (simulation trading)", response_model=None
)
async def get_simulation_portfolio_overview(
    current_user: typing.Any = Depends(get_current_user),
    mgr: LiveTradingManager = Depends(_get_manager),
) -> typing.Any:
    """Simulation portfolio overview.

    Currently reuses the same aggregation logic as live trading. This keeps the
    API stable for the frontend while allowing the underlying data source to be
    customized later if simulation instances are stored separately.
    """
    # Reuse the same logic as get_portfolio_overview for now
    return await get_portfolio_overview(current_user=current_user, mgr=mgr)


@router.get(
    "/simulation/positions",
    summary="Aggregated positions (simulation trading)",
    response_model=None,
)
async def get_simulation_portfolio_positions(
    current_user: typing.Any = Depends(get_current_user),
    mgr: LiveTradingManager = Depends(_get_manager),
) -> typing.Any:
    """Simulation current positions across strategies.

    See `get_portfolio_positions` for field details.
    """
    return await get_portfolio_positions(current_user=current_user, mgr=mgr)


@router.get(
    "/simulation/trades",
    summary="Aggregated trade records (simulation trading)",
    response_model=None,
)
async def get_simulation_portfolio_trades(
    limit: int = 200,
    workspace_ids: Annotated[list[str] | None, Query()] = None,
    current_user: typing.Any = Depends(get_current_user),
    mgr: LiveTradingManager = Depends(_get_manager),
) -> typing.Any:
    """Simulation historical trades across strategies.

    See `get_portfolio_trades` for field details.
    """
    return await get_portfolio_trades(
        limit=limit,
        workspace_ids=workspace_ids,
        current_user=current_user,
        mgr=mgr,
    )


@router.get(
    "/simulation/equity", summary="Portfolio equity curve (simulation trading)", response_model=None
)
async def get_simulation_portfolio_equity(
    current_user: typing.Any = Depends(get_current_user),
    mgr: LiveTradingManager = Depends(_get_manager),
) -> typing.Any:
    """Simulation portfolio-level equity curve.

    See `get_portfolio_equity` for field details.
    """
    return await get_portfolio_equity(current_user=current_user, mgr=mgr)


@router.get(
    "/simulation/allocation",
    summary="Asset allocation by open positions (simulation trading)",
    response_model=None,
)
async def get_simulation_portfolio_allocation(
    workspace_ids: Annotated[list[str] | None, Query()] = None,
    current_user: typing.Any = Depends(get_current_user),
    mgr: LiveTradingManager = Depends(_get_manager),
) -> typing.Any:
    """Simulation allocation across traded assets.

    See `get_portfolio_allocation` for field details.
    """
    return await get_portfolio_allocation(
        workspace_ids=workspace_ids,
        current_user=current_user,
        mgr=mgr,
    )
