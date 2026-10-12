"""Portfolio position valuation and compact overview calculations."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from app.api.portfolio.portfolio_common import (
    _EXPLICIT_NET_PNL_FIELD_KEYS,
    _GROSS_PNL_FIELD_KEYS,
    _PortfolioSource,
)
from app.services.position_valuation import EPSILON
from app.services.valuation_projection import ValuedPosition
from app.services.valuation_types import PositionSpec

_COMMISSION_FIELD_KEYS = (
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
)


class _HasAny(Protocol):
    def __call__(self, row: dict[str, Any], *keys: str) -> bool: ...


class _ValuePosition(Protocol):
    def __call__(
        self,
        row: dict[str, Any],
        *,
        spec: PositionSpec | None = None,
    ) -> ValuedPosition | None: ...


class _PositionRowBuilder(Protocol):
    def __call__(
        self,
        row: dict[str, Any],
        spec: object,
        *,
        position_source: str,
    ) -> dict[str, Any]: ...


class _ShouldRecalculateLocalPnl(Protocol):
    def __call__(
        self,
        row: dict[str, Any],
        spec: object,
        *,
        position_source: str,
        force: bool = False,
    ) -> bool: ...


class _PositionWarnings(Protocol):
    def __call__(
        self,
        source: _PortfolioSource,
        row: dict[str, Any],
        spec: object,
        *,
        position_source: str,
    ) -> list[str]: ...


class _SplitBidirectional(Protocol):
    def __call__(self, row: dict[str, Any]) -> list[dict[str, Any]]: ...


class _ContractSpec(Protocol):
    def __call__(
        self,
        symbol: str,
        row: dict[str, Any],
        source: _PortfolioSource,
    ) -> PositionSpec: ...


class _AppendUnique(Protocol):
    def __call__(self, target: list[str], *values: object) -> None: ...


class _StartedDay(Protocol):
    def __call__(self, source: _PortfolioSource) -> str | None: ...


class _CompactValueLogSummary(Protocol):
    def __call__(
        self,
        log_dir: Path | None,
        *,
        started_day: str | None = None,
    ) -> tuple[float, float, float] | None: ...


class _FirstNumber(Protocol):
    def __call__(self, row: dict[str, Any] | None, *keys: str) -> float | None: ...


class _SafeRound(Protocol):
    def __call__(self, value: float, digits: int | None = None) -> float: ...


def leverage_from_margin_rate(
    value: object,
    *,
    safe_float_fn: Callable[[object], float],
    epsilon: float = EPSILON,
) -> float | None:
    margin_rate = safe_float_fn(value)
    if margin_rate <= epsilon:
        return None
    return round(1.0 / margin_rate, 8)


def position_valuation_warnings(
    source: _PortfolioSource,
    row: dict[str, Any],
    spec: object,
    *,
    position_source: str,
    has_any_fn: _HasAny,
) -> list[str]:
    warnings: list[str] = []
    if (
        str(source.trading_mode or "").strip().lower() == "live"
        and str(source.status or "").strip().lower() == "running"
        and position_source != "gateway"
    ):
        warnings.append("未能从交易所网关确认当前持仓，当前数据来自本地日志/快照")
    if not getattr(spec, "has_multiplier", False) and not has_any_fn(
        row, "multiplier", "mult", "contract_multiplier", "contract_size"
    ):
        warnings.append("合约乘数未从交易所或本地资产信息确认，按 1 估算")
    if (
        not getattr(spec, "has_margin_rate", False)
        and not getattr(spec, "has_margin_amount", False)
        and not has_any_fn(
            row,
            "margin",
            "margin_rate",
            "margin_ratio",
            "leverage",
            "lever",
            "margin_value",
            "use_margin",
            "initial_margin",
            "imr",
            "margin_amount",
            "initial_margin_per_lot",
            "margin_initial",
            "maintain_margin",
            "mmr",
            "long_margin_amount",
            "short_margin_amount",
            "MARGIN_PER_LOT",
            "LONG_MARGIN_AMOUNT",
            "SHORT_MARGIN_AMOUNT",
        )
    ):
        warnings.append("保证金率未确认，按全额保证金估算")
    has_real_commission = has_any_fn(row, *_COMMISSION_FIELD_KEYS)
    if row.get("commission_currency_mismatch"):
        warnings.append("成交手续费币种与盈亏计价币种不一致，当前按资产费率估算手续费")
    if not getattr(spec, "has_commission", False) and not has_real_commission:
        warnings.append("手续费未确认，持仓盈亏未扣除真实手续费")
    elif (
        getattr(spec, "has_commission", False)
        and not has_real_commission
        and (row.get("generic_pnl_recalculated") or has_any_fn(row, *_GROSS_PNL_FIELD_KEYS))
    ):
        warnings.append("持仓手续费未从交易所成交/持仓回报确认，当前按资产费率估算")
    return warnings


def position_row_should_recalculate_local_pnl(
    row: dict[str, Any],
    spec: object,
    *,
    position_source: str,
    force: bool = False,
    has_any_fn: _HasAny,
) -> bool:
    if not force and str(position_source or "").strip().lower() == "gateway":
        return False
    if not (
        getattr(spec, "has_multiplier", False)
        or getattr(spec, "has_commission", False)
        or getattr(spec, "has_margin_rate", False)
        or getattr(spec, "has_margin_amount", False)
    ):
        return False
    if not has_any_fn(
        row,
        "price",
        "avg_price",
        "average_price",
        "price_open",
        "entry_price",
        "avgCost",
        "avgPrice",
        "avgPx",
        "avg_entry_price",
        "avgEntryPrice",
        "entryPrice",
        "open_avg_price",
        "openAvgPrice",
        "Price",
        "AveragePrice",
    ):
        return False
    if not has_any_fn(
        row,
        "current_price",
        "latest_price",
        "last_price",
        "mark_price",
        "markPrice",
        "markPx",
        "market_price",
        "lastPrice",
        "LastPrice",
        "market_value",
        "marketValue",
        "positionValue",
        "position_value",
        "value",
    ):
        return False
    return has_any_fn(row, *_EXPLICIT_NET_PNL_FIELD_KEYS, *_GROSS_PNL_FIELD_KEYS, "pnl")


def position_row_for_valuation(
    row: dict[str, Any],
    spec: object,
    *,
    position_source: str,
    should_recalculate_fn: _ShouldRecalculateLocalPnl,
) -> dict[str, Any]:
    item = dict(row)
    force_recalculate = bool(item.pop("force_recalculate_position_pnl", False))
    if not should_recalculate_fn(
        item,
        spec,
        position_source=position_source,
        force=force_recalculate,
    ):
        return item
    for key in (*_EXPLICIT_NET_PNL_FIELD_KEYS, *_GROSS_PNL_FIELD_KEYS, "pnl"):
        item.pop(key, None)
    if force_recalculate:
        item["market_value_estimated"] = True
    item["recalculated_position_pnl"] = True
    return item


def valued_source_positions(
    source: _PortfolioSource,
    *,
    source_positions_fn: Callable[[_PortfolioSource], list[dict[str, Any]]],
    split_bidirectional_position_row_fn: _SplitBidirectional,
    contract_spec_for_position_fn: _ContractSpec,
    position_row_for_valuation_fn: _PositionRowBuilder,
    value_position_fn: _ValuePosition,
    position_valuation_warnings_fn: _PositionWarnings,
    append_unique_fn: _AppendUnique,
    unique_text_fn: Callable[[list[object]], str | None],
    signed_market_value_fn: Callable[[float, float], float],
    leverage_from_margin_rate_fn: Callable[[object], float | None],
    position_updated_at_fn: Callable[[dict[str, Any]], object],
    position_data_time_fn: Callable[[dict[str, Any]], object],
) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for raw_row in source_positions_fn(source):
        for row in split_bidirectional_position_row_fn(raw_row):
            symbol = str(row.get("data_name") or row.get("symbol") or "")
            spec = contract_spec_for_position_fn(symbol, row, source)
            position_source = str(
                row.get("position_source") or row.get("source") or source.position_source or "local"
            ).strip()
            if (
                source.live_positions is None
                and str(source.position_source or "").strip().lower() in {"log", "snapshot"}
                and position_source.lower() == "gateway"
            ):
                position_source = str(source.position_source)
                row = dict(row)
                row["force_recalculate_position_pnl"] = True
            valuation_row = position_row_for_valuation_fn(
                row,
                spec,
                position_source=position_source,
            )
            valued = value_position_fn(valuation_row, spec=spec)
            if valued is None:
                continue
            asset_spec_source = str(
                row.get("asset_spec_source") or getattr(spec, "source", "") or ""
            ).strip()
            row_warnings = position_valuation_warnings_fn(
                source,
                valuation_row,
                spec,
                position_source=position_source,
            )
            if valuation_row.get("recalculated_position_pnl"):
                row_warnings.append("本地/快照持仓盈亏已按最新资产乘数、保证金和手续费设置重新计算")
            append_unique_fn(source.valuation_warnings, row_warnings)
            if asset_spec_source:
                source.asset_spec_source = unique_text_fn(
                    [source.asset_spec_source, asset_spec_source]
                )
            source.valuation_status = "estimated" if source.valuation_warnings else "confirmed"
            positions.append(
                {
                    "data_name": valued.data_name or symbol,
                    "size": valued.size,
                    "price": valued.entry_price,
                    "latest_price": valued.current_price,
                    "market_value": valued.market_value,
                    "signed_market_value": signed_market_value_fn(valued.size, valued.market_value),
                    "position_pnl": valued.pnl,
                    "gross_pnl": valued.gross_pnl,
                    "commission": valued.commission,
                    "commission_source": valuation_row.get("commission_source")
                    or row.get("commission_source"),
                    "multiplier": valued.multiplier,
                    "margin_rate": valued.margin_rate,
                    "leverage": leverage_from_margin_rate_fn(valued.margin_rate),
                    "margin_value": valued.margin_value,
                    "updated_at": position_updated_at_fn(row),
                    "data_time": position_data_time_fn(row),
                    "direction": valued.direction,
                    "position_source": position_source,
                    "asset_spec_source": asset_spec_source or None,
                    "valuation_status": "estimated" if row_warnings else "confirmed",
                    "valuation_warnings": row_warnings,
                }
            )
    if not positions and source.position_source == "gateway":
        source.valuation_status = "confirmed"
    elif not positions and source.valuation_warnings:
        source.valuation_status = "stale_fallback"
    return positions


def compact_workspace_overview(
    rows: list[_PortfolioSource],
    *,
    safe_dict_fn: Callable[[object], dict[str, Any]],
    source_started_day_fn: _StartedDay,
    compact_value_log_summary_fn: _CompactValueLogSummary,
    first_number_fn: _FirstNumber,
    safe_round_fn: _SafeRound,
    epsilon: float = EPSILON,
) -> dict[str, Any]:
    total_assets = 0.0
    total_cash = 0.0
    total_initial = 0.0
    total_position_gross = 0.0
    total_position_net = 0.0
    running_count = 0
    has_position_data = False

    # Sources from the live-manager path have already passed process validation,
    # while the fast landing-page path contains only persisted running units.
    # Requiring a process PID here would make the snapshot-only path discard all
    # valid first-screen data after an API-server restart.
    running_sources = [
        source for source in rows if str(source.status or "").strip().lower() == "running"
    ]

    for source in running_sources:
        snapshot = safe_dict_fn(source.snapshot)
        started_day = source_started_day_fn(source)
        long_value = max(
            first_number_fn(snapshot, "long_market_value", "long_value", "longMarketValue") or 0.0,
            0.0,
        )
        short_value = max(
            first_number_fn(snapshot, "short_market_value", "short_value", "shortMarketValue")
            or 0.0,
            0.0,
        )
        net_position_value = long_value - short_value
        value_summary = compact_value_log_summary_fn(source.log_dir, started_day=started_day)
        initial, assets, cash = value_summary if value_summary is not None else (0.0, 0.0, 0.0)

        total_initial += initial
        total_assets += assets
        total_cash += cash
        total_position_gross += long_value + short_value
        total_position_net += net_position_value
        if (
            isinstance(snapshot.get("positions"), list)
            or long_value > epsilon
            or short_value > epsilon
        ):
            has_position_data = True
        running_count += 1

    total_pnl = total_assets - total_initial
    total_pnl_pct = total_pnl / total_initial * 100 if total_initial > 0 else 0.0
    if not has_position_data:
        total_position_net = total_assets - total_cash
        total_position_gross = abs(total_position_net)
    return {
        "total_assets": safe_round_fn(total_assets),
        "total_cash": safe_round_fn(total_cash),
        "total_position_value": safe_round_fn(total_position_gross),
        "net_position_value": safe_round_fn(total_position_net),
        "total_initial_capital": safe_round_fn(total_initial),
        "total_pnl": safe_round_fn(total_pnl),
        "total_pnl_pct": safe_round_fn(total_pnl_pct, 2),
        "strategy_count": len(running_sources),
        "running_count": running_count,
        # Per-strategy metrics require scanning every value and trade log. They
        # are not rendered in the first screen and are intentionally omitted in
        # compact mode to keep the route DB-only.
        "strategies": [],
    }
