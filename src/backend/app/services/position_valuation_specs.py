"""Contract specification accumulator extracted from ``position_valuation``."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.services.valuation_numeric import (
    EPSILON,
    _as_dict,
    _commission_amount_from_keys,
    _commission_rate_from_config,
    _commission_rate_from_keys,
    _explicit_inverse_flag,
    _first_number,
    _first_text,
    _normalise_rate,
)
from app.services.valuation_types import PositionSpec

_INVERSE_MULTIPLIER_KEYS = (
    "contract_value",
    "contractValue",
    "contract_value_amount",
    "contractValueAmount",
    "contract_notional_value",
    "okx_contract_value",
    "ctVal",
    "multiplier",
    "mult",
    "contract_size",
    "trade_contract_size",
    "contract_multiplier",
    "ctMult",
    "VolumeMultiple",
    "CONTRACT_MULTIPLIER",
)
_LINEAR_MULTIPLIER_KEYS = (
    "multiplier",
    "mult",
    "contract_size",
    "trade_contract_size",
    "contract_notional_value",
    "okx_contract_value",
    "contract_multiplier",
    "ctVal",
    "ctMult",
    "VolumeMultiple",
    "CONTRACT_MULTIPLIER",
)
_MARGIN_RATE_KEYS = (
    "margin",
    "margin_rate",
    "margin_ratio",
    "required_margin_percent",
    "require_margin_percent",
    "maintain_margin_percent",
    "MARGIN_RATIO",
)
_MARGIN_AMOUNT_KEYS = (
    "margin_amount",
    "initial_margin_per_lot",
    "margin_initial",
    "initial_margin_amount",
    "SYMBOL_MARGIN_INITIAL",
    "MARGIN_PER_LOT",
    "LONG_MARGIN_AMOUNT",
    "LONG_MARGIN_PER_LOT",
)
_LONG_MARGIN_AMOUNT_KEYS = (
    "long_margin_amount",
    "LongMarginRatioByVolume",
    "LONG_MARGIN_AMOUNT",
    "LONG_MARGIN_PER_LOT",
)
_SHORT_MARGIN_AMOUNT_KEYS = (
    "short_margin_amount",
    "ShortMarginRatioByVolume",
    "SHORT_MARGIN_AMOUNT",
    "SHORT_MARGIN_PER_LOT",
)
_LONG_MARGIN_RATE_KEYS = (
    "long_margin_rate",
    "LongMarginRatio",
    "LongMarginRatioByMoney",
    "LONG_MARGIN_RATE",
    "MARGIN_BUY",
)
_SHORT_MARGIN_RATE_KEYS = (
    "short_margin_rate",
    "ShortMarginRatio",
    "ShortMarginRatioByMoney",
    "SHORT_MARGIN_RATE",
    "MARGIN_SELL",
)
_COMMISSION_RATE_FIELDS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    (
        "open_commission_rate",
        (
            "open_commission_rate",
            "open_fee_rate",
            "OpenRatioByMoney",
            "OPEN_FEE_RATE",
            "COMMISSION_OPEN_RATIO",
        ),
        False,
    ),
    (
        "close_commission_rate",
        (
            "close_commission_rate",
            "close_fee_rate",
            "CloseRatioByMoney",
            "CLOSE_FEE_RATE",
            "COMMISSION_CLOSE_RATIO",
        ),
        False,
    ),
    (
        "close_today_commission_rate",
        (
            "close_today_commission_rate",
            "close_today_fee_rate",
            "CloseTodayRatioByMoney",
            "CLOSETODAY_FEE_RATE",
            "CLOSE_TODAY_FEE_RATE",
            "COMMISSION_CLOSE_TODAY_RATIO",
        ),
        False,
    ),
    (
        "close_yesterday_commission_rate",
        (
            "close_yesterday_commission_rate",
            "close_yesterday_fee_rate",
            "CloseYesterdayRatioByMoney",
            "CLOSEYESTERDAY_FEE_RATE",
            "CLOSE_YESTERDAY_FEE_RATE",
            "COMMISSION_CLOSE_YESTERDAY_RATIO",
        ),
        False,
    ),
    ("maker_commission_rate", ("maker_commission_rate", "maker_fee_rate"), True),
    ("taker_commission_rate", ("taker_commission_rate", "taker_fee_rate"), True),
)
_COMMISSION_AMOUNT_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "open_commission_amount",
        (
            "open_commission_amount",
            "open_fee_amount",
            "OpenRatioByVolume",
            "OPEN_FEE_AMOUNT",
            "OPEN_FEE_PER_LOT",
            "COMMISSION_OPEN_AMOUNT",
        ),
    ),
    (
        "close_commission_amount",
        (
            "close_commission_amount",
            "close_fee_amount",
            "CloseRatioByVolume",
            "CLOSE_FEE_AMOUNT",
            "CLOSE_FEE_PER_LOT",
            "COMMISSION_CLOSE_AMOUNT",
        ),
    ),
    (
        "close_today_commission_amount",
        (
            "close_today_commission_amount",
            "close_today_fee_amount",
            "CloseTodayRatioByVolume",
            "CLOSETODAY_FEE_AMOUNT",
            "CLOSE_TODAY_FEE_AMOUNT",
            "CLOSE_TODAY_FEE_PER_LOT",
            "COMMISSION_CLOSE_TODAY_AMOUNT",
        ),
    ),
    (
        "close_yesterday_commission_amount",
        (
            "close_yesterday_commission_amount",
            "close_yesterday_fee_amount",
            "CloseYesterdayRatioByVolume",
            "CLOSEYESTERDAY_FEE_AMOUNT",
            "CLOSE_YESTERDAY_FEE_AMOUNT",
            "CLOSE_YESTERDAY_FEE_PER_LOT",
            "COMMISSION_CLOSE_YESTERDAY_AMOUNT",
        ),
    ),
)


@dataclass
class ContractSpecAccumulator:
    """Mutable precedence-ordered accumulator for ``contract_spec_for``."""

    multiplier: float | None = None
    margin_rate: float | None = None
    margin_amount: float | None = None
    long_margin_rate: float | None = None
    short_margin_rate: float | None = None
    long_margin_amount: float | None = None
    short_margin_amount: float | None = None
    commission_rate: float | None = None
    commission_amount: float | None = None
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
    allow_local_otc_default: bool = False

    def _record_source(self, subconfig_source: str) -> None:
        if subconfig_source and not self.source:
            self.source = subconfig_source

    def consume_metadata(self, subconfig: dict[str, Any]) -> None:
        """Populate missing contract currency and asset-type descriptors."""
        text_specs = (
            ("asset_type", ("asset_type", "instType")),
            ("contract_type", ("contract_type", "ctType")),
            (
                "contract_value_currency",
                (
                    "contract_value_currency",
                    "contract_value_ccy",
                    "ctValCcy",
                    "contractValueCurrency",
                ),
            ),
            ("base_asset", ("base_asset", "baseCcy")),
            ("quote_asset", ("quote_asset", "quoteCcy")),
            ("settle_currency", ("settle_currency", "settleCcy")),
            ("fee_currency", ("fee_currency", "feeCcy")),
        )
        for attr, keys in text_specs:
            if not getattr(self, attr):
                setattr(self, attr, _first_text(*(subconfig.get(key) for key in keys)))
        explicit_inverse = _explicit_inverse_flag(subconfig)
        if explicit_inverse is not None and self.is_inverse is None:
            self.is_inverse = explicit_inverse

    def consume_multiplier(
        self, subconfig: dict[str, Any], subconfig_source: str, is_inverse_fn: Any
    ) -> None:
        """Populate contract multiplier and implied inverse flag."""
        if self.multiplier is not None:
            return
        inverse_config = is_inverse_fn(
            subconfig,
            contract_type=self.contract_type,
            contract_value_currency=self.contract_value_currency,
            base_asset=self.base_asset,
            quote_asset=self.quote_asset,
            settle_currency=self.settle_currency,
            fee_currency=self.fee_currency,
        )
        if inverse_config and self.is_inverse is None:
            self.is_inverse = True
        keys = _INVERSE_MULTIPLIER_KEYS if inverse_config else _LINEAR_MULTIPLIER_KEYS
        self.multiplier = _first_number(*(subconfig.get(key) for key in keys))
        if self.multiplier is not None:
            self.has_multiplier = True
            self._record_source(subconfig_source)

    def consume_margin(self, subconfig: dict[str, Any], subconfig_source: str) -> None:
        """Populate margin rates and per-lot margin amounts."""
        if self.margin_rate is None:
            margin_value = _first_number(*(subconfig.get(k) for k in _MARGIN_RATE_KEYS))
            if margin_value is not None:
                self.margin_rate = _normalise_rate(margin_value, 1.0)
                self.has_margin_rate = True
                self._record_source(subconfig_source)
            else:
                leverage = _first_number(
                    subconfig.get("leverage"),
                    subconfig.get("lever"),
                    subconfig.get("max_leverage"),
                )
                if leverage and leverage > 0:
                    self.margin_rate = 1.0 / leverage
                    self.has_margin_rate = True
                    self._record_source(subconfig_source)
        for attr, keys, positive_only in (
            ("margin_amount", _MARGIN_AMOUNT_KEYS, True),
            ("long_margin_amount", _LONG_MARGIN_AMOUNT_KEYS, True),
            ("short_margin_amount", _SHORT_MARGIN_AMOUNT_KEYS, True),
        ):
            if getattr(self, attr) is None:
                val = _first_number(*(subconfig.get(k) for k in keys))
                if val is not None and (not positive_only or val > 0):
                    setattr(self, attr, val)
                    self.has_margin_amount = True
                    self._record_source(subconfig_source)
        rate_pairs: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("long_margin_rate", _LONG_MARGIN_RATE_KEYS),
            ("short_margin_rate", _SHORT_MARGIN_RATE_KEYS),
        )
        for attr, rate_keys in rate_pairs:
            if getattr(self, attr) is None:
                val = _first_number(*(subconfig.get(k) for k in rate_keys))
                if val is not None:
                    setattr(self, attr, _normalise_rate(val, 1.0))
                    self.has_margin_rate = True
                    self._record_source(subconfig_source)

    def consume_commissions(self, subconfig: dict[str, Any], subconfig_source: str) -> None:
        """Populate commission rate and per-lot fee schedules."""
        if self.commission_rate is None:
            commission_value = _commission_rate_from_config(subconfig)
            if commission_value is not None:
                self.commission_rate = commission_value
                self.has_commission = True
                self._record_source(subconfig_source)
        for attr, keys, signed in _COMMISSION_RATE_FIELDS:
            if getattr(self, attr) is None:
                val = _commission_rate_from_keys(subconfig, keys, signed=signed)
                if val is not None:
                    setattr(self, attr, val)
                    self.has_commission = True
                    self._record_source(subconfig_source)
        self._consume_base_commission_amount(subconfig, subconfig_source)
        for attr, keys in _COMMISSION_AMOUNT_FIELDS:
            if getattr(self, attr) is None:
                amount = _commission_amount_from_keys(subconfig, keys)
                if amount is not None:
                    setattr(self, attr, amount)
                    self.has_commission = True
                    self._record_source(subconfig_source)

    def _consume_base_commission_amount(
        self, subconfig: dict[str, Any], subconfig_source: str
    ) -> None:
        if self.commission_amount is not None:
            return
        if str(subconfig.get("commission_method") or "").lower() == "fixed_per_lot":
            self.commission_amount = _first_number(
                subconfig.get("open_commission_amount"),
                subconfig.get("open_fee_amount"),
                subconfig.get("open_commission_rate"),
                subconfig.get("OpenRatioByVolume"),
                subconfig.get("OPEN_FEE_AMOUNT"),
                subconfig.get("OPEN_FEE_PER_LOT"),
                subconfig.get("COMMISSION_OPEN_AMOUNT"),
            )
            if self.commission_amount is not None:
                self.has_commission = True
                self._record_source(subconfig_source)
        if self.commission_amount is None:
            self.commission_amount = _first_number(
                subconfig.get("commission_amount"),
                subconfig.get("fee_amount"),
                subconfig.get("commission_per_lot"),
                subconfig.get("open_fee_amount"),
                subconfig.get("open_commission_amount"),
                subconfig.get("OpenRatioByVolume"),
                subconfig.get("OPEN_FEE_AMOUNT"),
                subconfig.get("OPEN_FEE_PER_LOT"),
                subconfig.get("COMMISSION_OPEN_AMOUNT"),
            )
            if self.commission_amount is not None:
                self.has_commission = True
                self._record_source(subconfig_source)

    def finalize(self, symbol: str, local_default_fn: Any) -> PositionSpec:
        """Apply final defaults and return the normalized ``PositionSpec``."""
        if self.multiplier is None and self.allow_local_otc_default:
            local_default = local_default_fn(symbol)
            if local_default:
                self.multiplier = _first_number(local_default.get("multiplier"))
                self.has_multiplier = self.multiplier is not None
                if not self.asset_type:
                    self.asset_type = _first_text(local_default.get("asset_type"))
                if not self.source:
                    self.source = _first_text(local_default.get("source"))

        if self.commission_rate is None and self.taker_commission_rate is not None:
            self.commission_rate = self.taker_commission_rate
        if self.commission_rate is None and self.maker_commission_rate is not None:
            self.commission_rate = self.maker_commission_rate
        open_rate = self.open_commission_rate
        if open_rate is None:
            open_rate = self.commission_rate
        open_amount = self.open_commission_amount
        if open_amount is None:
            open_amount = self.commission_amount

        return PositionSpec(
            multiplier=max(self.multiplier or 1.0, EPSILON),
            margin_rate=max(self.margin_rate if self.margin_rate is not None else 1.0, 0.0),
            margin_amount=max(self.margin_amount or 0.0, 0.0),
            long_margin_rate=self.long_margin_rate,
            short_margin_rate=self.short_margin_rate,
            long_margin_amount=self.long_margin_amount,
            short_margin_amount=self.short_margin_amount,
            commission_rate=max(self.commission_rate or 0.0, 0.0),
            commission_amount=max(self.commission_amount or 0.0, 0.0),
            open_commission_rate=max(open_rate, 0.0) if open_rate is not None else None,
            close_commission_rate=(
                max(self.close_commission_rate, 0.0)
                if self.close_commission_rate is not None
                else None
            ),
            close_today_commission_rate=(
                max(self.close_today_commission_rate, 0.0)
                if self.close_today_commission_rate is not None
                else None
            ),
            close_yesterday_commission_rate=(
                max(self.close_yesterday_commission_rate, 0.0)
                if self.close_yesterday_commission_rate is not None
                else None
            ),
            maker_commission_rate=self.maker_commission_rate,
            taker_commission_rate=self.taker_commission_rate,
            open_commission_amount=open_amount,
            close_commission_amount=self.close_commission_amount,
            close_today_commission_amount=self.close_today_commission_amount,
            close_yesterday_commission_amount=self.close_yesterday_commission_amount,
            asset_type=self.asset_type,
            contract_type=self.contract_type,
            contract_value_currency=self.contract_value_currency,
            base_asset=self.base_asset,
            quote_asset=self.quote_asset,
            settle_currency=self.settle_currency,
            fee_currency=self.fee_currency,
            source=self.source,
            is_inverse=self.is_inverse,
            has_multiplier=self.has_multiplier,
            has_margin_rate=self.has_margin_rate,
            has_margin_amount=self.has_margin_amount,
            has_commission=self.has_commission,
        )


def collect_subconfigs(config: dict[str, Any], meta: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield ordered subconfig views from one config dictionary."""
    nested = [
        config,
        _as_dict(config.get("unit_settings")),
        _as_dict(config.get("params")),
        _as_dict(config.get("backtest")),
        _as_dict(config.get("simulate")),
        _as_dict(config.get("live")),
        _as_dict(config.get("gateway")),
        _as_dict(config.get("data")),
    ]
    if meta:
        nested.insert(0, meta)
    return (subconfig for subconfig in nested if subconfig)
