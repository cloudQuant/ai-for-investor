"""Paper equity snapshot query and runtime curve helpers for portfolio routes."""

from __future__ import annotations

import typing
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from app.api.portfolio.instance_resolution import _current_user_id, _trading_day
from app.api.portfolio.portfolio_common import _PortfolioSource, _safe_float
from app.models.paper_runtime import PaperEquitySnapshot
from app.services.log_parser_service import parse_value_log

_PAPER_RUNTIME_MODES = frozenset({"paper", "simulation", "simulated"})
_MAX_PORTFOLIO_EQUITY_POINTS = 1_500
_MAX_PAPER_EQUITY_SNAPSHOTS = 200_000
_MIN_PER_INSTANCE_SNAPSHOTS = 2_000


def _is_paper_runtime_source(source: _PortfolioSource) -> bool:
    """Return whether a source represents a simulated trading runtime."""
    return str(source.trading_mode or "paper").strip().lower() in _PAPER_RUNTIME_MODES


def _sample_indexes(length: int, max_points: int = _MAX_PORTFOLIO_EQUITY_POINTS) -> list[int]:
    """Return shared sample indexes so every portfolio series stays aligned."""
    if length <= max_points:
        return list(range(length))
    step = (length - 1) / (max_points - 1)
    return [round(index * step) for index in range(max_points)]


async def load_paper_equity_points(
    current_user: typing.Any,
    sources: list[_PortfolioSource],
    *,
    session_maker: Any,
    max_total_snapshots: int = _MAX_PAPER_EQUITY_SNAPSHOTS,
) -> dict[str, list[tuple[str, float, float, float]]]:
    """Load recent canonical equity snapshots per paper instance without starving others."""
    instance_ids = sorted({source.id for source in sources if _is_paper_runtime_source(source)})
    user_id = _current_user_id(current_user)
    if not instance_ids or not user_id:
        return {}

    per_instance_limit = max(
        _MIN_PER_INSTANCE_SNAPSHOTS,
        max_total_snapshots // max(len(instance_ids), 1),
    )

    ranked = (
        select(
            PaperEquitySnapshot.id.label("id"),
            sa.func.row_number()
            .over(
                partition_by=PaperEquitySnapshot.instance_id,
                order_by=(
                    PaperEquitySnapshot.observed_at.desc(),
                    PaperEquitySnapshot.id.desc(),
                ),
            )
            .label("rn"),
        )
        .where(
            PaperEquitySnapshot.user_id == user_id,
            PaperEquitySnapshot.instance_id.in_(instance_ids),
        )
        .subquery()
    )
    query = (
        select(PaperEquitySnapshot)
        .join(ranked, PaperEquitySnapshot.id == ranked.c.id)
        .where(ranked.c.rn <= per_instance_limit)
        .order_by(
            PaperEquitySnapshot.instance_id,
            PaperEquitySnapshot.observed_at,
            PaperEquitySnapshot.id,
        )
    )

    async with session_maker() as session:
        result = await session.execute(query)
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
    parse_value_log_fn: Any = parse_value_log,
) -> dict[str, list[Any]]:
    """Prepend current-runtime log history that predates paper snapshots."""
    snapshot_dates = [point[0] for point in paper_points]
    snapshot_equity = [point[1] for point in paper_points]
    snapshot_cash = [point[2] for point in paper_points]
    snapshot_pnl = [point[3] for point in paper_points]

    log_data = parse_value_log_fn(source.log_dir, prefer_log_time=False) if source.log_dir else {}
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
