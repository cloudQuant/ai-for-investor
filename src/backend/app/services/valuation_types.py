"""Typed input specification shared by position valuation collaborators."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PositionSpec:
    multiplier: float = 1.0
    margin_rate: float = 1.0
    margin_amount: float = 0.0
    long_margin_rate: float | None = None
    short_margin_rate: float | None = None
    long_margin_amount: float | None = None
    short_margin_amount: float | None = None
    commission_rate: float = 0.0
    commission_amount: float = 0.0
    open_commission_rate: float | None = None
    close_commission_rate: float | None = None
    close_today_commission_rate: float | None = None
    close_yesterday_commission_rate: float | None = None
    maker_commission_rate: float | None = None
    taker_commission_rate: float | None = None
    open_commission_amount: float | None = None
    close_commission_amount: float | None = None
    close_today_commission_amount: float | None = None
    close_yesterday_commission_amount: float | None = None
    asset_type: str = ""
    contract_type: str = ""
    contract_value_currency: str = ""
    base_asset: str = ""
    quote_asset: str = ""
    settle_currency: str = ""
    fee_currency: str = ""
    source: str = ""
    is_inverse: bool | None = None
    has_multiplier: bool = False
    has_margin_rate: bool = False
    has_margin_amount: bool = False
    has_commission: bool = False
