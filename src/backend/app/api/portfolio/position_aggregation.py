"""Position normalization and portfolio aggregation helpers."""

from typing import Any

from app.api.portfolio.portfolio_common import (
    _first_number,
    _PortfolioSource,
    _safe_float,
    _safe_round,
)
from app.services.position_valuation import EPSILON
from app.services.trading_asset_info_service import (
    gateway_position_symbol,
    signed_gateway_size,
    split_bidirectional_position_row,
    symbol_aliases,
)


def _source_snapshot_positions(source: _PortfolioSource) -> list[dict[str, Any]]:
    return _snapshot_positions_for_portfolio(source.snapshot)


def _position_row_direction(row: dict[str, Any], size: float) -> str:
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
        try:
            code = int(_safe_float(value, float("nan")))
        except (TypeError, ValueError):
            code = None
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


def _latest_position_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_key: dict[str, tuple[int, str, str, dict[str, Any]]] = {}
    latest_flat_by_key: dict[str, tuple[int, str, str, dict[str, Any]]] = {}
    latest_flat_by_symbol: dict[str, tuple[int, str, dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        symbol = str(row.get("data_name") or row.get("symbol") or "").strip()
        if not symbol:
            continue
        size = _safe_float(row.get("size"), 0.0)
        direction = _position_row_direction(row, size)
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
        direction = _position_row_direction(row, _safe_float(row.get("size"), 0.0))
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


def _snapshot_positions_for_portfolio(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = list((snapshot or {}).get("positions") or [])
    positions: list[dict[str, Any]] = []
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            continue
        for row in split_bidirectional_position_row(raw_row):
            size = signed_gateway_size(row)
            if abs(size) <= EPSILON:
                continue
            price = (
                _first_number(
                    row,
                    "price",
                    "avg_price",
                    "average_price",
                    "price_open",
                    "avgCost",
                    "avgPrice",
                    "entryPrice",
                    "ep",
                    "averageCost",
                    "Price",
                    "AveragePrice",
                )
                or 0.0
            )
            current_price = _first_number(
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
                "price_current",
                "marketPrice",
                "mktPrice",
                "mp",
                "PriceCurrent",
                "CurrentPrice",
                "SettlementPrice",
                "settlement_price",
            )
            explicit_market_value = _first_number(
                row,
                "market_value",
                "marketValue",
                "mktValue",
                "positionValue",
                "position_value",
                "value",
            )
            market_value = (
                explicit_market_value if explicit_market_value is not None else abs(size) * price
            )
            position = {
                **row,
                "data_name": gateway_position_symbol(row),
                "size": size,
                "price": price,
                "current_price": current_price,
                "market_value": market_value,
                "value": market_value,
                "position_pnl": row.get("position_pnl"),
                "pnl": row.get("pnl"),
                "pnlcomm": row.get("pnlcomm"),
                "gross_pnl": row.get("gross_pnl"),
                "commission": row.get("commission"),
                "commission_signed": row.get("commission_signed"),
                "multiplier": row.get("multiplier"),
                "margin_rate": row.get("margin_rate"),
                "margin": row.get("margin"),
                "margin_value": row.get("margin_value"),
                "use_margin": row.get("use_margin"),
                "initial_margin": row.get("initial_margin"),
                "maintain_margin": row.get("maintain_margin"),
                "updated_at": _position_updated_at(row),
                "data_time": _position_data_time(row),
                "source": row.get("source"),
                "position_source": row.get("position_source"),
                "asset_spec_source": row.get("asset_spec_source"),
                "valuation_status": row.get("valuation_status"),
                "valuation_warnings": list(row.get("valuation_warnings") or []),
            }
            if explicit_market_value is None:
                position["market_value_estimated"] = True
            positions.append(position)
    return positions


def _parse_query_ids(values: list[str] | None) -> set[str]:
    ids: set[str] = set()
    for value in values or []:
        ids.update(part.strip() for part in value.split(",") if part.strip())
    return ids


def _position_updated_at(row: dict[str, Any]) -> Any:
    return row.get("updated_at") or row.get("log_time") or row.get("datetime") or row.get("dt")


def _position_data_time(row: dict[str, Any]) -> Any:
    return row.get("data_time") or row.get("datetime") or row.get("dt")


def _empty_position_summary() -> dict[str, float | int]:
    return {
        "total_long_value": 0.0,
        "total_short_value": 0.0,
        "gross_market_value": 0.0,
        "net_market_value": 0.0,
        "total_pnl": 0.0,
        "long_count": 0,
        "short_count": 0,
        "flat_count": 0,
    }


def _build_position_summary(positions: list[dict[str, Any]]) -> dict[str, float | int]:
    summary = _empty_position_summary()

    for item in positions:
        size = float(item.get("size") or 0.0)
        if abs(size) <= EPSILON:
            continue
        market_value = abs(float(item.get("market_value") or 0.0))
        pnl = float(item.get("position_pnl") or item.get("pnl") or 0.0)

        if size > 0:
            summary["total_long_value"] += market_value
            summary["long_count"] += 1
        elif size < 0:
            summary["total_short_value"] += market_value
            summary["short_count"] += 1
        else:
            summary["flat_count"] += 1

        summary["total_pnl"] += pnl

    total_long = float(summary["total_long_value"])
    total_short = float(summary["total_short_value"])
    summary["total_long_value"] = _safe_round(total_long)
    summary["total_short_value"] = _safe_round(total_short)
    summary["gross_market_value"] = _safe_round(total_long + total_short)
    summary["net_market_value"] = _safe_round(total_long - total_short)
    summary["total_pnl"] = _safe_round(float(summary["total_pnl"]))
    return summary


def _source_has_confirmed_flat_positions(source: _PortfolioSource) -> bool:
    if source.live_positions is not None:
        return True
    snapshot = source.snapshot if isinstance(source.snapshot, dict) else {}
    return isinstance(snapshot.get("positions"), list)


def _source_account_key(source: _PortfolioSource) -> str:
    account = source.live_account or {}
    for value in (
        account.get("gateway_key"),
        account.get("account_id"),
        account.get("account"),
        account.get("login"),
        source.id,
    ):
        text = str(value or "").strip()
        if text:
            return text
    return source.id


def _source_account_value(source: _PortfolioSource) -> float | None:
    return _first_number(
        source.live_account,
        "value",
        "equity",
        "Equity",
        "eq",
        "total_eq",
        "totalEq",
        "total_equity",
        "totalEquity",
        "account_value",
        "accountValue",
        "net_liquidation",
        "NetLiquidation",
        "netliquidation",
        "NetLiquidationValue",
        "total_margin",
        "totalMargin",
        "total_margin_balance",
        "totalMarginBalance",
        "margin_balance",
        "marginBalance",
        "total_wallet_balance",
        "totalWalletBalance",
        "wallet_balance",
        "walletBalance",
        "balance",
        "Balance",
    )


def _source_account_cash(source: _PortfolioSource) -> float | None:
    account = source.live_account
    cash = _first_number(
        account,
        "cash",
        "available_cash",
        "available",
        "Available",
        "available_funds",
        "AvailableFunds",
        "availablefunds",
        "available_balance",
        "availableBalance",
        "available_bal",
        "availableBal",
        "available_equity",
        "availableEquity",
        "avail_eq",
        "availEq",
        "avail_bal",
        "availBal",
        "total_available_balance",
        "totalAvailableBalance",
        "total_available_margin",
        "totalAvailableMargin",
        "free_collateral",
        "freeCollateral",
        "free_margin",
        "freeMargin",
        "marginFree",
        "margin_free",
        "withdraw_available",
        "withdrawAvailable",
        "available_to_withdraw",
        "availableToWithdraw",
    )
    if cash is not None:
        return cash

    margin = _first_number(
        account,
        "margin",
        "used_margin",
        "usedMargin",
        "margin_used",
        "marginUsed",
        "curr_margin",
        "CurrMargin",
        "initial_margin",
        "initialMargin",
        "initial_margin_requirement",
        "initialMarginRequirement",
        "total_initial_margin",
        "totalInitialMargin",
        "total_used_margin",
        "totalUsedMargin",
        "total_position_initial_margin",
        "totalPositionInitialMargin",
        "total_open_order_initial_margin",
        "totalOpenOrderInitialMargin",
        "imr",
        "maintain_margin",
        "maintenance_margin",
        "maintMargin",
    )
    value = _source_account_value(source)
    if value is not None and margin is not None:
        return value - margin

    return _first_number(
        source.live_account,
        "balance",
        "Balance",
    )


def _source_account_time(source: _PortfolioSource) -> str:
    account = source.live_account or {}
    for key in ("updated_at", "data_time", "datetime", "dt", "time", "timestamp"):
        value = account.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return "live"


def _signed_market_value(size: float, market_value: float) -> float:
    gross_value = abs(market_value)
    if size > 0:
        return gross_value
    if size < 0:
        return -gross_value
    return 0.0


def _allocation_asset_key(symbol: Any) -> str:
    """Return a stable display key that groups equivalent broker symbol aliases."""
    raw_symbol = str(symbol or "").strip()
    if not raw_symbol:
        return ""
    candidates = [
        "".join(character for character in str(alias).upper() if character.isalnum())
        for alias in symbol_aliases(raw_symbol)
    ]
    candidates = [candidate for candidate in candidates if candidate]
    return min(candidates, key=len) if candidates else raw_symbol.upper()
