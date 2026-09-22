"""Typed position views and pure helpers for paper trading."""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict, TypeVar

from app.models.paper_trading import Position


@dataclass(frozen=True)
class PositionSnapshot:
    """Typed in-memory view of a position after applying a fill update."""

    id: str
    account_id: str
    symbol: str
    size: float
    avg_price: float
    market_value: float
    margin_value: float
    multiplier: float
    margin_rate: float
    commission_rate: float
    commission_amount: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    entry_price: float
    entry_time: datetime | None
    updated_at: datetime | None


PositionView = Position | PositionSnapshot
PositionT = TypeVar("PositionT", Position, PositionSnapshot)
FloatConverter = Callable[[object, float], float]
SymbolAliasResolver = Callable[[str], Iterable[str]]
PositionAliasResolver = Callable[[object], set[str]]
OpenPositionPredicate = Callable[[PositionView], bool]


class PositionEvent(TypedDict, total=False):
    """Data passed from position accounting to the account update step."""

    cash_delta: float
    closed_size: float
    opening_size: float
    released_margin: float
    opening_margin: float
    realized_gross_pnl: float
    closing_commission: float
    opening_commission: float
    margin_accounting: bool
    position_snapshot: PositionView


def position_equity_component(position: PositionView, safe_float: FloatConverter) -> float:
    """Return the position's contribution to account equity."""
    market_value = safe_float(position.market_value, 0.0)
    margin_value = safe_float(position.margin_value, 0.0)
    unrealized_pnl = safe_float(position.unrealized_pnl, 0.0)
    multiplier = safe_float(position.multiplier, 1.0)
    margin_rate = safe_float(position.margin_rate, 1.0)
    uses_margin_accounting = margin_value > 0 and (
        abs(multiplier - 1.0) > 1e-12
        or margin_rate < 1.0
        or abs(margin_value - abs(market_value)) > 1e-9
    )
    if uses_margin_accounting:
        return margin_value + unrealized_pnl
    return market_value


def is_open_position(position: PositionView, safe_float: FloatConverter) -> bool:
    """Return whether a position has a non-zero size."""
    return abs(safe_float(position.size, 0.0)) > 1e-12


def first_open_position(
    positions: Sequence[PositionT], is_open: OpenPositionPredicate
) -> PositionT | None:
    """Return the first open position in the supplied sequence."""
    for position in positions:
        if is_open(position):
            return position
    return None


def position_aliases_for_symbol(
    symbol: object,
    resolve_aliases: SymbolAliasResolver,
) -> set[str]:
    """Return normalized aliases for a position symbol."""
    return {str(item).upper() for item in resolve_aliases(str(symbol or "")) if item}


def symbols_match(
    left: object,
    right: object,
    resolve_aliases: PositionAliasResolver,
) -> bool:
    """Return whether two position symbols share a normalized alias."""
    left_aliases = resolve_aliases(left)
    right_aliases = resolve_aliases(right)
    return bool(left_aliases and right_aliases and left_aliases & right_aliases)


def merge_position_snapshot(
    positions: Sequence[PositionView],
    snapshot: PositionView | None,
    is_open: OpenPositionPredicate,
) -> Sequence[PositionView]:
    """Replace stale positions with a fresh snapshot, or append an open one."""
    if snapshot is None:
        return positions

    snapshot_id = snapshot.id
    snapshot_account_id = snapshot.account_id
    snapshot_symbol = snapshot.symbol
    merged: list[PositionView] = []
    replaced = False
    for position in positions:
        same_id = (
            snapshot_id is not None
            and position.id is not None
            and str(position.id) == str(snapshot_id)
        )
        same_symbol = (
            snapshot_account_id is not None
            and snapshot_symbol is not None
            and position.account_id is not None
            and position.symbol is not None
            and str(position.account_id) == str(snapshot_account_id)
            and str(position.symbol) == str(snapshot_symbol)
        )
        if same_id or same_symbol:
            merged.append(snapshot)
            replaced = True
        else:
            merged.append(position)

    if not replaced and is_open(snapshot):
        merged.append(snapshot)
    return merged


def build_position_snapshot(
    position: Position,
    updates: Mapping[str, object],
    safe_float: FloatConverter,
) -> PositionSnapshot:
    """Normalize a position plus fill updates into an immutable typed view."""

    def number(name: str, current: float) -> float:
        return safe_float(updates.get(name, current), current)

    existing_entry_time = getattr(position, "entry_time", None)
    entry_time = updates.get(
        "entry_time",
        existing_entry_time if isinstance(existing_entry_time, datetime) else None,
    )
    if entry_time is not None and not isinstance(entry_time, datetime):
        raise TypeError("position entry_time must be a datetime or None")
    existing_updated_at = getattr(position, "updated_at", None)
    updated_at = updates.get(
        "updated_at",
        existing_updated_at if isinstance(existing_updated_at, datetime) else None,
    )
    if updated_at is not None and not isinstance(updated_at, datetime):
        raise TypeError("position updated_at must be a datetime or None")

    return PositionSnapshot(
        id=position.id,
        account_id=position.account_id,
        symbol=position.symbol,
        size=number("size", getattr(position, "size", 0.0)),
        avg_price=number("avg_price", getattr(position, "avg_price", 0.0)),
        market_value=number("market_value", getattr(position, "market_value", 0.0)),
        margin_value=number("margin_value", getattr(position, "margin_value", 0.0)),
        multiplier=number("multiplier", getattr(position, "multiplier", 1.0)),
        margin_rate=number("margin_rate", getattr(position, "margin_rate", 1.0)),
        commission_rate=number("commission_rate", getattr(position, "commission_rate", 0.0)),
        commission_amount=number("commission_amount", getattr(position, "commission_amount", 0.0)),
        unrealized_pnl=number("unrealized_pnl", getattr(position, "unrealized_pnl", 0.0)),
        unrealized_pnl_pct=number(
            "unrealized_pnl_pct", getattr(position, "unrealized_pnl_pct", 0.0)
        ),
        entry_price=number("entry_price", getattr(position, "entry_price", 0.0)),
        entry_time=entry_time,
        updated_at=updated_at,
    )
