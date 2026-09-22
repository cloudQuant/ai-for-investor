"""Workspace report generation.

Aggregates per-unit ``metrics_snapshot`` rows into a workspace-level report
with weighted averages and configurable date / cash / annualization rules.

Extracted from the original ``WorkspaceService`` so the god-class shrinks
without breaking its public surface; the facade in
:mod:`app.services.workspace_service` still exposes ``get_workspace_report``
and ``delete_workspace_report`` as thin async methods that delegate here.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeGuard

from app.db.database import async_session_maker
from app.models.workspace import (
    StrategyUnit,
    Workspace,
    WorkspaceJSONMapping,
    WorkspaceJSONValue,
)

logger = logging.getLogger(__name__)


# Extended metric keys for Iteration 124 report columns.
_EXT_METRIC_KEYS: tuple[str, ...] = (
    "total_return",
    "annual_return",
    "sharpe_ratio",
    "max_drawdown",
    "win_rate",
    "total_trades",
    "profitable_trades",
    "losing_trades",
    "initial_cash",
    "final_value",
    "net_value",
    "net_profit",
    "max_leverage",
    "max_market_value",
    "max_drawdown_value",
    "adjusted_return_risk",
    "avg_profit",
    "avg_profit_rate",
    "total_win_amount",
    "total_loss_amount",
    "profit_loss_ratio",
    "profit_factor",
    "profit_rate_factor",
    "profit_loss_rate_ratio",
    "odds",
    "daily_avg_return",
    "daily_max_loss",
    "daily_max_profit",
    "weekly_avg_return",
    "weekly_max_loss",
    "weekly_max_profit",
    "monthly_avg_return",
    "monthly_max_loss",
    "monthly_max_profit",
    "trading_cost",
    "trading_days",
)


# Type alias for the workspace loader injected by the facade.
# Mirrors :meth:`WorkspaceService._load_workspace` so callers can pass it
# directly without an adapter.
WorkspaceLoader = Callable[..., Awaitable[Workspace | None]]


def _is_workspace_json_value(value: object) -> TypeGuard[WorkspaceJSONValue]:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_workspace_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_workspace_json_value(item) for key, item in value.items()
        )
    return False


def _is_workspace_json_mapping(value: object) -> TypeGuard[WorkspaceJSONMapping]:
    return isinstance(value, dict) and _is_workspace_json_value(value)


def _safe_workspace_json_mapping(value: object) -> WorkspaceJSONMapping:
    if _is_workspace_json_mapping(value):
        return dict(value)
    return {}


def _numeric_metric(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _numeric_metric_float(value: object) -> float | None:
    metric = _numeric_metric(value)
    if metric is None:
        return None
    try:
        return float(metric)
    except OverflowError:
        return None


def _metric_float_or_default(value: object, default: float) -> float:
    metric = _numeric_metric_float(value)
    return default if metric is None else metric


def _date_metric(metrics: Mapping[str, object], key: str) -> str | None:
    value = metrics.get(key)
    return value if isinstance(value, str) else None


def _unit_in_range(unit: StrategyUnit, start_date: str | None, end_date: str | None) -> bool:
    """Return ``True`` if a unit's data window overlaps the requested range."""
    dc = _safe_workspace_json_mapping(unit.data_config)
    u_start = _date_metric(dc, "start_date")
    u_end = _date_metric(dc, "end_date")
    if start_date and u_end and u_end < start_date:
        return False
    if end_date and u_start and u_start > end_date:
        return False
    return True


def _recalc_annual(
    metrics: Mapping[str, object], *, calc_method: str, annual_days: int
) -> int | float | None:
    """Recompute ``annual_return`` from ``total_return`` + ``trading_days``."""
    total_return = _numeric_metric_float(metrics.get("total_return"))
    trading_days = _numeric_metric_float(metrics.get("trading_days"))
    if total_return is None or trading_days is None or trading_days <= 0:
        return _numeric_metric(metrics.get("annual_return"))

    if calc_method == "compound":
        try:
            return round(((1 + total_return) ** (annual_days / trading_days) - 1), 6)
        except (OverflowError, ValueError):
            return _numeric_metric(metrics.get("annual_return"))
    return round(total_return * (annual_days / trading_days), 6)


def _serialize_unit_reference(unit: StrategyUnit, value_metric_key: str) -> dict[str, Any]:
    """Render a compact unit reference suitable for the summary block."""
    data_config = _safe_workspace_json_mapping(unit.data_config)
    metrics = _safe_workspace_json_mapping(unit.metrics_snapshot)
    return {
        "id": unit.id,
        "strategy_name": unit.strategy_name or unit.strategy_id or "",
        "symbol": unit.symbol or "",
        "symbol_name": unit.symbol_name or "",
        "timeframe": unit.timeframe or "",
        "group_name": unit.group_name or "",
        "category": unit.category or "",
        "run_status": unit.run_status or "idle",
        "run_count": unit.run_count or 0,
        "last_run_time": unit.last_run_time,
        "last_task_id": unit.last_task_id,
        "start_date": _date_metric(data_config, "start_date"),
        "data_source": f"{unit.symbol or ''}_{unit.timeframe or ''}",
        "value": _numeric_metric(metrics.get(value_metric_key)),
    }


async def get_workspace_report(
    *,
    workspace_id: str,
    user_id: str,
    load_workspace: WorkspaceLoader,
    start_date: str | None = None,
    end_date: str | None = None,
    max_cash: float | None = None,
    calc_method: str = "simple",
    annual_days: int = 252,
    weight_mode: str = "equal",
    weights: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """Generate a combined report aggregating metrics across all units.

    Args:
        workspace_id: Target workspace id.
        user_id: Owner; used by ``load_workspace`` for tenancy enforcement.
        load_workspace: Callable that resolves a ``Workspace`` row with
            ``strategy_units`` eagerly loaded; injected so this module does
            not back-import :mod:`app.services.workspace_service`.
        start_date / end_date: Optional ISO dates to filter units whose data
            window overlaps the requested range.
        max_cash: Optional override for ``initial_cash`` per unit row.
        calc_method: ``"simple"`` (default) or ``"compound"``.
        annual_days: Trading days per year used for annualization.
        weight_mode: ``"equal"`` (default) or ``"custom"``. Custom mode uses
            ``weights`` if provided, otherwise auto-derives from each unit's
            ``initial_cash`` proportion.
        weights: Optional explicit per-unit weights keyed by unit id.

    Returns:
        Report dict, or ``None`` if the workspace does not exist or is not
        owned by ``user_id``.
    """
    async with async_session_maker() as session:
        ws = await load_workspace(session, workspace_id, user_id, load_units=True)
        if ws is None:
            return None

        units = ws.strategy_units or []
        filtered_units = [u for u in units if _unit_in_range(u, start_date, end_date)]
        metrics_by_unit_id = {
            unit.id: _safe_workspace_json_mapping(unit.metrics_snapshot) for unit in filtered_units
        }
        data_config_by_unit_id = {
            unit.id: _safe_workspace_json_mapping(unit.data_config) for unit in filtered_units
        }
        completed_units = [u for u in filtered_units if metrics_by_unit_id[u.id]]

        # Build weight map. Custom mode without explicit weights auto-derives
        # from each completed unit's initial_cash proportion.
        resolved_weights = weights or {}
        if weight_mode == "custom" and not resolved_weights and completed_units:
            total_cash = sum(
                (
                    _numeric_metric_float(metrics_by_unit_id[u.id].get("initial_cash")) or 0.0
                    for u in completed_units
                ),
                start=0.0,
            )
            if total_cash > 0:
                resolved_weights = {
                    u.id: (
                        _numeric_metric_float(metrics_by_unit_id[u.id].get("initial_cash")) or 0.0
                    )
                    / total_cash
                    for u in completed_units
                }

        rows: list[dict[str, Any]] = []
        for u in filtered_units:
            m = metrics_by_unit_id[u.id]
            dc = data_config_by_unit_id[u.id]
            row: dict[str, Any] = {
                "id": u.id,
                "strategy_name": u.strategy_name or u.strategy_id or "",
                "symbol": u.symbol or "",
                "symbol_name": u.symbol_name or "",
                "timeframe": u.timeframe or "",
                "group_name": u.group_name or "",
                "category": u.category or "",
                "run_status": u.run_status or "idle",
                "run_count": u.run_count or 0,
                "last_run_time": u.last_run_time,
                "last_task_id": u.last_task_id,
                "start_date": _date_metric(dc, "start_date"),
                "data_source": f"{u.symbol or ''}_{u.timeframe or ''}",
            }

            row["initial_cash"] = (
                max_cash if (max_cash is not None and m) else _numeric_metric(m.get("initial_cash"))
            )

            for key in _EXT_METRIC_KEYS:
                if key == "initial_cash":
                    continue
                row[key] = _numeric_metric(m.get(key))

            if m:
                row["annual_return"] = _recalc_annual(
                    m, calc_method=calc_method, annual_days=annual_days
                )

            rows.append(row)

        def _weighted_avg(metric_key: str) -> float | None:
            vals: list[tuple[float, float]] = []
            for u in completed_units:
                m = metrics_by_unit_id[u.id]
                raw_metric = (
                    _recalc_annual(m, calc_method=calc_method, annual_days=annual_days)
                    if metric_key == "annual_return"
                    else m.get(metric_key)
                )
                metric_value = _numeric_metric_float(raw_metric)
                if metric_value is None:
                    continue
                w = (
                    resolved_weights.get(u.id, 1.0)
                    if weight_mode == "custom" and resolved_weights
                    else 1.0
                )
                vals.append((metric_value, w))
            if not vals:
                return None
            total_w = sum(w for _, w in vals)
            if total_w == 0:
                return None
            return round(sum(v * w for v, w in vals) / total_w, 4)

        def _safe_sum(metric_key: str) -> int | float | None:
            vals = [
                value
                for u in completed_units
                if (value := _numeric_metric(metrics_by_unit_id[u.id].get(metric_key))) is not None
            ]
            return sum(vals, start=0) if vals else None

        summary: dict[str, Any] = {
            "total_units": len(units),
            "completed_units": len(completed_units),
            "avg_total_return": _weighted_avg("total_return"),
            "avg_annual_return": _weighted_avg("annual_return"),
            "avg_sharpe_ratio": _weighted_avg("sharpe_ratio"),
            "avg_max_drawdown": _weighted_avg("max_drawdown"),
            "avg_win_rate": _weighted_avg("win_rate"),
            "total_trades": _safe_sum("total_trades"),
            "best_return_unit": max(
                completed_units,
                key=lambda u: _metric_float_or_default(
                    metrics_by_unit_id[u.id].get("total_return"), float("-inf")
                ),
                default=None,
            ),
            "worst_drawdown_unit": max(
                completed_units,
                key=lambda u: abs(
                    _metric_float_or_default(metrics_by_unit_id[u.id].get("max_drawdown"), 0.0)
                ),
                default=None,
            ),
            "config": {
                "start_date": start_date,
                "end_date": end_date,
                "max_cash": max_cash,
                "calc_method": calc_method,
                "annual_days": annual_days,
                "weight_mode": weight_mode,
            },
        }

        for key, value_metric in (
            ("best_return_unit", "total_return"),
            ("worst_drawdown_unit", "max_drawdown"),
        ):
            unit_obj = summary[key]
            if unit_obj is not None:
                summary[key] = _serialize_unit_reference(unit_obj, value_metric)

        return {
            "workspace_id": workspace_id,
            "workspace_name": ws.name,
            "summary": summary,
            "units": rows,
        }


async def delete_workspace_report(
    *,
    workspace_id: str,
    user_id: str,
    load_workspace: WorkspaceLoader,
) -> dict[str, Any] | None:
    """Clear the cached report config on a workspace.

    Only resets ``workspace.settings.report_config``; never touches
    per-unit ``metrics_snapshot`` (those are run results, not report
    artefacts).

    Returns:
        Confirmation dict, or ``None`` if the workspace does not exist.
    """
    async with async_session_maker() as session:
        ws = await load_workspace(session, workspace_id, user_id, load_units=False)
        if ws is None:
            return None
        settings = _safe_workspace_json_mapping(ws.settings)
        had_config = "report_config" in settings
        settings.pop("report_config", None)
        ws.settings = settings
        await session.commit()
        return {
            "workspace_id": workspace_id,
            "cleared": had_config,
            "message": "报告缓存配置已清除，单元运行指标未受影响",
        }
