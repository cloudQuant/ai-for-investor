"""Stable result shape and projection for valued position rows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar


@dataclass(frozen=True)
class ValuedPosition:
    data_name: str
    size: float
    direction: str
    entry_price: float
    current_price: float
    multiplier: float
    margin_rate: float
    market_value: float
    margin_value: float
    commission: float
    gross_pnl: float
    pnl: float


ProjectedPosition = TypeVar("ProjectedPosition")


def project_valued_position(
    result_factory: Callable[..., ProjectedPosition],
    *,
    data_name: str,
    size: float,
    direction: str,
    entry_price: float,
    current_price: float,
    multiplier: float,
    margin_rate: float,
    market_value: float,
    margin_value: float,
    commission: float,
    gross_pnl: float,
    pnl: float,
) -> ProjectedPosition:
    """Project calculated amounts into the stable valuation result DTO."""
    return result_factory(
        data_name=data_name,
        size=size,
        direction=direction,
        entry_price=entry_price,
        current_price=current_price,
        multiplier=multiplier,
        margin_rate=margin_rate,
        market_value=market_value,
        margin_value=margin_value,
        commission=commission,
        gross_pnl=gross_pnl,
        pnl=pnl,
    )
