"""Static AkShare field and route definitions for provider contracts.

This module holds reviewed catalog data.  The core provider-contract module
supplies its constructors at import time so the data remains separate without
creating a dependency cycle back to the runtime contract implementation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Literal, Protocol, TypeVar

from app.services.market_data.dataset_contracts import (
    FAMILY_CONTRACT_VERSION,
    KLINE_LEGACY_CONTRACT_VERSION,
    KLINE_LEGACY_FAMILY_ID,
)


class _MappedFieldProfile(Protocol):
    """Structural contract required to build aliases for a field profile."""

    @property
    def mapped_fields(self) -> frozenset[str]: ...


_ProfileT = TypeVar("_ProfileT", bound=_MappedFieldProfile)
_ContractT = TypeVar("_ContractT")

AKSHARE_RESPONSE_FIELD_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "开盘": "open",
        "今开": "open",
        "open": "open",
        "收盘": "close",
        "最新价": "close",
        "close": "close",
        "最高": "high",
        "high": "high",
        "最低": "low",
        "low": "low",
        "成交量": "volume",
        "volume": "volume",
        "成交额": "turnover",
        "turnover": "turnover",
        "振幅": "amplitude",
        "涨跌幅": "change_pct",
        "涨跌额": "change",
        "换手率": "turnover_rate",
        "持仓量": "open_interest",
        "hold": "open_interest",
        "结算价": "settle",
        "settle": "settle",
        "单位净值": "nav",
        "累计净值": "cumulative_nav",
        "日增长率": "daily_growth_rate",
    }
)


def _aliases_for(mapped_fields: frozenset[str]) -> Mapping[str, str]:
    return MappingProxyType(
        {
            source_name: normalized_name
            for source_name, normalized_name in AKSHARE_RESPONSE_FIELD_ALIASES.items()
            if normalized_name in mapped_fields
        }
    )


_STOCK_MAPPED_FIELDS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "amplitude",
        "change_pct",
        "change",
        "turnover_rate",
        "settle",
    }
)
_FUTURES_MAPPED_FIELDS = frozenset(
    {"open", "high", "low", "close", "volume", "open_interest", "settle", "change"}
)
_BOND_MAPPED_FIELDS = frozenset(
    {"open", "high", "low", "close", "volume", "turnover", "change_pct"}
)
_FUND_NAV_MAPPED_FIELDS = frozenset({"nav", "cumulative_nav", "daily_growth_rate"})
_OPTION_MAPPED_FIELDS = frozenset(
    {"open", "high", "low", "close", "volume", "turnover", "open_interest", "change", "change_pct"}
)
_FX_MAPPED_FIELDS = frozenset({"open", "high", "low", "close", "change_pct"})


def build_akshare_contract_catalog(
    *,
    contract_factory: Callable[..., _ContractT],
    profile_factory: Callable[..., _ProfileT],
    contract_version: str,
) -> tuple[_ContractT, ...]:
    """Build the reviewed AkShare routes using core-owned contract classes."""

    def _profile(
        profile_id: str,
        required_fields: tuple[str, ...],
        *,
        optional_fields: tuple[str, ...] = (),
        mapped_fields: frozenset[str],
    ) -> _ProfileT:
        return profile_factory(
            profile_id=profile_id,
            required_fields=required_fields,
            optional_fields=optional_fields,
            mapped_fields=mapped_fields,
        )

    def _akshare_contract(
        *,
        contract_id: str,
        route_id: str,
        family_id: str,
        family_contract_version: str,
        asset_type: str,
        data_kind: str,
        frequencies: frozenset[str],
        markets: frozenset[str],
        supported_adjustments: frozenset[str],
        supported_price_bases: frozenset[str],
        supported_currencies: frozenset[str] | None,
        supported_units: frozenset[str] | None,
        field_profile: _ProfileT,
        timestamp_columns: tuple[str, ...],
        endpoints: frozenset[str],
        request_transform_id: str,
        endpoint_resolver_id: str = "akshare.static-endpoint-v1",
        symbol_columns: tuple[str, ...] = (),
        identity_proof: Literal["source_request_bound", "response_symbol"] = "source_request_bound",
        source_policy_required: bool = False,
        request_validator_id: str | None = None,
        supported_product_types: frozenset[str] | None = None,
        supported_fund_identity_kinds: frozenset[str] | None = None,
    ) -> _ContractT:
        return contract_factory(
            contract_id=contract_id,
            contract_version=contract_version,
            provider="akshare",
            route_id=route_id,
            family_id=family_id,
            family_contract_version=family_contract_version,
            asset_type=asset_type,
            data_kind=data_kind,
            frequencies=frequencies,
            markets=markets,
            supported_adjustments=supported_adjustments,
            supported_price_bases=supported_price_bases,
            supported_currencies=supported_currencies,
            supported_units=supported_units,
            field_profile=field_profile,
            response_field_aliases=_aliases_for(field_profile.mapped_fields),
            timestamp_columns=timestamp_columns,
            symbol_columns=symbol_columns,
            identity_proof=identity_proof,
            source_policy_required=source_policy_required,
            client_filters_window=True,
            request_transform_id=request_transform_id,
            endpoint_resolver_id=endpoint_resolver_id,
            endpoints=endpoints,
            request_validator_id=request_validator_id,
            supported_product_types=supported_product_types,
            supported_fund_identity_kinds=supported_fund_identity_kinds,
        )

    return (
        _akshare_contract(
            contract_id="akshare.stock.primary.contract-v1",
            route_id="akshare-stock-primary-v1",
            family_id="stock.realtime",
            family_contract_version=FAMILY_CONTRACT_VERSION,
            asset_type="stock",
            data_kind="bars",
            frequencies=frozenset({"1d", "1w", "1mo"}),
            markets=frozenset({"CN-SSE", "CN-SZSE"}),
            supported_adjustments=frozenset({"unadjusted", "qfq", "hfq"}),
            supported_price_bases=frozenset({"close"}),
            supported_currencies=frozenset({"CNY"}),
            supported_units=frozenset({"share"}),
            field_profile=_profile(
                "stock-bars-compatibility-v1",
                ("close",),
                optional_fields=(
                    "open",
                    "high",
                    "low",
                    "volume",
                    "turnover",
                    "change_pct",
                    "turnover_rate",
                ),
                mapped_fields=_STOCK_MAPPED_FIELDS,
            ),
            timestamp_columns=("日期", "date"),
            symbol_columns=("股票代码", "symbol", "code"),
            identity_proof="response_symbol",
            endpoints=frozenset({"stock_zh_a_hist"}),
            request_transform_id="akshare.historical-kline-request-v1",
            request_validator_id="akshare.cn-stock-symbol-v1",
        ),
        _akshare_contract(
            contract_id="akshare.stock.kline-legacy.contract-v1",
            route_id="akshare-stock-kline-legacy-v1",
            family_id=KLINE_LEGACY_FAMILY_ID,
            family_contract_version=KLINE_LEGACY_CONTRACT_VERSION,
            asset_type="stock",
            data_kind="bars",
            frequencies=frozenset({"1d", "1w", "1mo"}),
            markets=frozenset({"CN-SSE", "CN-SZSE"}),
            supported_adjustments=frozenset({"qfq"}),
            supported_price_bases=frozenset({"close"}),
            supported_currencies=frozenset({"CNY"}),
            supported_units=frozenset({"share"}),
            field_profile=_profile(
                "stock-kline-legacy-v1",
                ("open", "high", "low", "close", "volume", "change_pct"),
                mapped_fields=_STOCK_MAPPED_FIELDS,
            ),
            timestamp_columns=("日期", "date"),
            symbol_columns=("股票代码", "symbol", "code"),
            identity_proof="response_symbol",
            endpoints=frozenset({"stock_zh_a_hist"}),
            request_transform_id="akshare.historical-kline-request-v1",
            request_validator_id="akshare.cn-stock-symbol-v1",
        ),
        _akshare_contract(
            contract_id="akshare.stock.liquidity.contract-v1",
            route_id="akshare-stock-liquidity-primary-v1",
            family_id="stock.liquidity",
            family_contract_version=FAMILY_CONTRACT_VERSION,
            asset_type="stock",
            data_kind="reference_series",
            frequencies=frozenset({"1d"}),
            markets=frozenset({"CN-SSE", "CN-SZSE"}),
            supported_adjustments=frozenset({"unadjusted"}),
            supported_price_bases=frozenset({"close"}),
            supported_currencies=frozenset({"CNY"}),
            supported_units=frozenset({"share"}),
            field_profile=_profile(
                "stock-liquidity-v1",
                ("volume", "turnover", "turnover_rate"),
                mapped_fields=_STOCK_MAPPED_FIELDS,
            ),
            timestamp_columns=("日期", "date"),
            symbol_columns=("股票代码", "symbol", "code"),
            identity_proof="response_symbol",
            endpoints=frozenset({"stock_zh_a_hist"}),
            request_transform_id="akshare.historical-kline-request-v1",
            request_validator_id="akshare.cn-stock-symbol-v1",
        ),
        _akshare_contract(
            contract_id="akshare.futures.primary.contract-v1",
            route_id="akshare-futures-primary-v1",
            family_id="futures.realtime",
            family_contract_version=FAMILY_CONTRACT_VERSION,
            asset_type="futures",
            data_kind="bars",
            frequencies=frozenset({"1d"}),
            markets=frozenset({"CFFEX"}),
            supported_adjustments=frozenset({"unadjusted"}),
            supported_price_bases=frozenset({"close"}),
            supported_currencies=frozenset({"CNY"}),
            supported_units=frozenset({"contract"}),
            field_profile=_profile(
                "futures-bars-compatibility-v1",
                ("close",),
                optional_fields=(
                    "open",
                    "high",
                    "low",
                    "volume",
                    "open_interest",
                    "settle",
                    "change",
                ),
                mapped_fields=_FUTURES_MAPPED_FIELDS,
            ),
            timestamp_columns=("date", "日期"),
            endpoints=frozenset({"futures_zh_daily_sina"}),
            request_transform_id="akshare.symbol-only-request-v1",
            source_policy_required=True,
            request_validator_id="akshare.cffex-futures-symbol-v1",
        ),
        _akshare_contract(
            contract_id="akshare.bond.primary.contract-v1",
            route_id="akshare-bond-primary-v1",
            family_id="bond.realtime",
            family_contract_version=FAMILY_CONTRACT_VERSION,
            asset_type="bond",
            data_kind="bars",
            frequencies=frozenset({"1d"}),
            markets=frozenset({"SSE", "SZSE", "CN-SSE", "CN-SZSE"}),
            supported_adjustments=frozenset({"unadjusted"}),
            supported_price_bases=frozenset({"close"}),
            supported_currencies=frozenset({"CNY"}),
            supported_units=None,
            field_profile=_profile(
                "bond-bars-compatibility-v1",
                ("close",),
                optional_fields=("open", "high", "low", "volume", "turnover", "change_pct"),
                mapped_fields=_BOND_MAPPED_FIELDS,
            ),
            timestamp_columns=("date", "日期"),
            endpoints=frozenset({"bond_zh_hs_daily"}),
            request_transform_id="akshare.symbol-only-request-v1",
            source_policy_required=True,
            request_validator_id="akshare.cn-bond-symbol-v1",
        ),
        _akshare_contract(
            contract_id="akshare.fund.primary.contract-v1",
            route_id="akshare-fund-primary-v1",
            family_id="fund.realtime",
            family_contract_version=FAMILY_CONTRACT_VERSION,
            asset_type="fund",
            data_kind="bars",
            frequencies=frozenset({"1d", "1w", "1mo"}),
            markets=frozenset({"CN-SSE", "CN-SZSE"}),
            supported_adjustments=frozenset({"unadjusted", "qfq", "hfq"}),
            supported_price_bases=frozenset({"close"}),
            supported_currencies=frozenset({"CNY"}),
            supported_units=frozenset({"share"}),
            field_profile=_profile(
                "fund-bars-compatibility-v1",
                ("close",),
                optional_fields=("open", "high", "low", "volume", "turnover", "change_pct"),
                mapped_fields=_STOCK_MAPPED_FIELDS,
            ),
            timestamp_columns=("日期", "date"),
            endpoints=frozenset({"fund_etf_hist_em"}),
            request_transform_id="akshare.historical-kline-request-v1",
            source_policy_required=True,
            request_validator_id="akshare.cn-etf-symbol-v1",
        ),
        _akshare_contract(
            contract_id="akshare.fund.liquidity.contract-v1",
            route_id="akshare-fund-liquidity-primary-v1",
            family_id="fund.liquidity",
            family_contract_version=FAMILY_CONTRACT_VERSION,
            asset_type="fund",
            data_kind="reference_series",
            frequencies=frozenset({"1d"}),
            markets=frozenset({"CN-SSE", "CN-SZSE"}),
            supported_adjustments=frozenset({"unadjusted"}),
            supported_price_bases=frozenset({"close"}),
            supported_currencies=frozenset({"CNY"}),
            supported_units=frozenset({"share"}),
            field_profile=_profile(
                "fund-liquidity-v1",
                ("volume", "turnover"),
                mapped_fields=_STOCK_MAPPED_FIELDS,
            ),
            timestamp_columns=("日期", "date"),
            endpoints=frozenset({"fund_etf_hist_em"}),
            request_transform_id="akshare.historical-kline-request-v1",
            source_policy_required=True,
            request_validator_id="akshare.cn-etf-symbol-v1",
        ),
        _akshare_contract(
            contract_id="akshare.fund.nav.contract-v1",
            route_id="akshare-fund-nav-primary-v1",
            family_id="fund.nav",
            family_contract_version=FAMILY_CONTRACT_VERSION,
            asset_type="fund",
            data_kind="reference_series",
            frequencies=frozenset({"1d"}),
            markets=frozenset({"CN-SSE", "CN-SZSE"}),
            supported_adjustments=frozenset({"source_reported"}),
            supported_price_bases=frozenset({"nav"}),
            supported_currencies=frozenset({"CNY"}),
            supported_units=frozenset({"fund_share"}),
            field_profile=_profile(
                "fund-nav-v1",
                ("nav", "cumulative_nav", "daily_growth_rate"),
                mapped_fields=_FUND_NAV_MAPPED_FIELDS,
            ),
            timestamp_columns=("净值日期", "date"),
            endpoints=frozenset({"fund_etf_fund_info_em"}),
            request_transform_id="akshare.fund-nav-request-v1",
            source_policy_required=True,
            request_validator_id="akshare.cn-etf-symbol-v1",
            supported_product_types=frozenset({"ETF"}),
            supported_fund_identity_kinds=frozenset({"LISTING"}),
        ),
        _akshare_contract(
            contract_id="akshare.option.cffex.primary.contract-v1",
            route_id="akshare-cffex-option-primary-v1",
            family_id="option.realtime",
            family_contract_version=FAMILY_CONTRACT_VERSION,
            asset_type="option",
            data_kind="bars",
            frequencies=frozenset({"1d"}),
            markets=frozenset({"CFFEX"}),
            supported_adjustments=frozenset({"unadjusted"}),
            supported_price_bases=frozenset({"close"}),
            supported_currencies=frozenset({"CNY"}),
            supported_units=frozenset({"contract"}),
            field_profile=_profile(
                "option-bars-compatibility-v1",
                ("close",),
                optional_fields=("volume", "turnover", "open_interest", "change", "change_pct"),
                mapped_fields=_OPTION_MAPPED_FIELDS,
            ),
            timestamp_columns=("date", "日期"),
            endpoints=frozenset(
                {
                    "option_cffex_hs300_daily_sina",
                    "option_cffex_sz50_daily_sina",
                    "option_cffex_zz1000_daily_sina",
                }
            ),
            request_transform_id="akshare.symbol-only-request-v1",
            endpoint_resolver_id="akshare.cffex-option-prefix-v1",
            source_policy_required=True,
        ),
        _akshare_contract(
            contract_id="akshare.fx.primary.contract-v1",
            route_id="akshare-fx-primary-v1",
            family_id="fx.realtime",
            family_contract_version=FAMILY_CONTRACT_VERSION,
            asset_type="fx",
            data_kind="bars",
            frequencies=frozenset({"1d"}),
            markets=frozenset({"OTC", "CN-OTC"}),
            supported_adjustments=frozenset({"unadjusted"}),
            supported_price_bases=frozenset({"close"}),
            supported_currencies=None,
            supported_units=None,
            field_profile=_profile(
                "fx-bars-compatibility-v1",
                ("close",),
                optional_fields=("open", "high", "low", "change_pct"),
                mapped_fields=_FX_MAPPED_FIELDS,
            ),
            timestamp_columns=("日期", "date"),
            symbol_columns=("代码", "code", "symbol"),
            identity_proof="response_symbol",
            endpoints=frozenset({"forex_hist_em"}),
            request_transform_id="akshare.symbol-only-request-v1",
        ),
        _akshare_contract(
            contract_id="akshare.fx.range.contract-v1",
            route_id="akshare-fx-range-primary-v1",
            family_id="fx.range",
            family_contract_version=FAMILY_CONTRACT_VERSION,
            asset_type="fx",
            data_kind="bars",
            frequencies=frozenset({"1d"}),
            markets=frozenset({"OTC", "CN-OTC"}),
            supported_adjustments=frozenset({"unadjusted"}),
            supported_price_bases=frozenset({"close"}),
            supported_currencies=None,
            supported_units=None,
            field_profile=_profile(
                "fx-range-v1",
                ("open", "high", "low", "close"),
                mapped_fields=_FX_MAPPED_FIELDS,
            ),
            timestamp_columns=("日期", "date"),
            symbol_columns=("代码", "code", "symbol"),
            identity_proof="response_symbol",
            endpoints=frozenset({"forex_hist_em"}),
            request_transform_id="akshare.symbol-only-request-v1",
        ),
    )
