"""THS（同花顺）provider 契约与请求变换。

复用迭代 197 的 ``ProviderContract`` 数据类，登记 THS 的静态控制面：
请求变换、响应字段映射、时间戳归一化、闭区间窗口语义、复权映射。

与 AkShare 的关键差异（见 DESIGN D2.2）：
- 请求变换：毫秒戳、``thscode``、``interval``、``adjust`` 映射
- 时间戳列：``date_ms`` / ``period_end_ms`` 毫秒戳
- 身份证明：``source_request_bound``（thscode 入参）+ 响应 ``thscode``
- 复权：``adjust=none/forward/backward``
- 信封：``ApiResponse``

本模块是控制面，不含网络客户端、数据库句柄或运行时开关。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any

from app.services.market_data.dataset_contracts import FAMILY_CONTRACT_VERSION
from app.services.market_data.provider_contracts import (
    AKSHARE_ROW_NORMALIZER_ID,
    THS_CLOSED_WINDOW_SEMANTICS,
    THS_MILLIS_TIMESTAMP_NORMALIZER_ID,
    THS_PROVIDER_CONTRACT_VERSION,
    THS_STATIC_ENDPOINT_RESOLVER_ID,
    ProviderContract,
    ProviderContractError,
    ProviderContractRegistry,
    ProviderResponseFieldProfile,
)
from app.services.market_data.providers import MarketDataProviderRequest

_UTC = timezone.utc

# 历史/财务区间最大跨度：10 年（THS 硬约束，超过返回 code=1003）。
THS_MAX_WINDOW = timedelta(days=365 * 10)

# 批量快照/估值接口单次 thscodes 上限：100 原始 token。
THS_MAX_BATCH_TOKENS = 100

# THS adjust 原生值（THS 原生值，非中台语义）。
THS_ADJUST_NONE = "none"
THS_ADJUST_FORWARD = "forward"
THS_ADJUST_BACKWARD = "backward"

# 中台复权语义 → THS adjust 原生值映射（见 DESIGN D2.3）。
_ADJUSTMENT_MAP: Mapping[str, str] = MappingProxyType(
    {
        "unadjusted": THS_ADJUST_NONE,
        "qfq": THS_ADJUST_FORWARD,
        "hfq": THS_ADJUST_BACKWARD,
    }
)

# THS 历史 K 线支持的 interval（文档当前仅 1d）。
THS_SUPPORTED_INTERVALS = frozenset({"1d"})

# THS ``date_ms`` 是交易日的 Asia/Shanghai 零点；中台 ``event_at`` 是同一交易日的
# UTC midnight。两者相差固定 8 小时（上海无夏令时），请求窗口须整体位移。
THS_SHANGHAI_UTC_OFFSET = timedelta(hours=8)

# THS 字段别名：snake_case 源字段 → 中台归一化字段。
# 历史 K 线：date_ms / open_price / high_price / low_price / close_price /
#             volume / turnover。
THS_RESPONSE_FIELD_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "open_price": "open",
        "high_price": "high",
        "low_price": "low",
        "close_price": "close",
        "last_price": "close",
        "volume": "volume",
        "turnover": "turnover",
        "price_change": "change",
        "price_change_ratio_pct": "change_pct",
        "turnover_rate": "turnover_rate",
        "prev_price": "previous_close",
    }
)

# stock bars 中台字段（与 AkShare stock 契约对齐）。
_STOCK_MAPPED_FIELDS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "change_pct",
        "change",
        "turnover_rate",
    }
)


def ths_adjustment(request: MarketDataProviderRequest) -> str:
    """把中台复权语义映射为 THS adjust 原生值，绝不猜测新基准。

    ``None`` 与 ``unadjusted`` 均映射为 ``none``。
    """
    adjustment = request.adjustment or "unadjusted"
    try:
        return _ADJUSTMENT_MAP[adjustment]
    except KeyError as exc:
        raise ProviderContractError("PROVIDER_CONTRACT_ADJUSTMENT_UNSUPPORTED") from exc


def _millis(value: datetime) -> int:
    """把已归一化的 UTC 时刻转为 THS 毫秒戳（Asia/Shanghai 语义由上游处理）。"""
    return int(value.timestamp() * 1000)


def _inclusive_end_millis(end_at: datetime) -> int:
    """把中台半开 ``[start, end)`` 的 end 转为 THS 闭区间 end（end-1ms）。"""
    return _millis(end_at - timedelta(milliseconds=1))


def split_window_into_chunks(
    start_at: datetime,
    end_at: datetime,
    *,
    max_span: timedelta = THS_MAX_WINDOW,
) -> tuple[tuple[datetime, datetime], ...]:
    """把请求窗口切成每块跨度 ≤ max_span 的连续块（保证 ≤ 10 年）。

    中台内部为半开 ``[start, end)``；切块结果同样为半开区间，请求变换时
    再逐块转为 THS 闭区间。单块直接返回原窗口。
    """
    if start_at >= end_at:
        raise ProviderContractError("PROVIDER_CONTRACT_WINDOW_INVALID")
    if end_at - start_at <= max_span:
        return ((start_at, end_at),)
    chunks: list[tuple[datetime, datetime]] = []
    cursor = start_at
    while cursor < end_at:
        chunk_end = min(cursor + max_span, end_at)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end
    return tuple(chunks)


def split_thscodes_batch(
    thscodes: tuple[str, ...], *, limit: int = THS_MAX_BATCH_TOKENS
) -> tuple[tuple[str, ...], ...]:
    """把多标的清单按单批上限切批（去重前校验，本地前置拦截越界）。"""
    if not isinstance(thscodes, tuple):
        raise TypeError("thscodes must be a tuple")
    if any(not isinstance(item, str) or not item.strip() for item in thscodes):
        raise ProviderContractError("PROVIDER_CONTRACT_SYMBOL_INVALID")
    if not thscodes:
        return ()
    batches: list[tuple[str, ...]] = []
    for index in range(0, len(thscodes), limit):
        batches.append(thscodes[index : index + limit])
    return tuple(batches)


def _profile(
    profile_id: str,
    required_fields: tuple[str, ...],
    *,
    optional_fields: tuple[str, ...] = (),
    mapped_fields: frozenset[str],
) -> ProviderResponseFieldProfile:
    return ProviderResponseFieldProfile(
        profile_id=profile_id,
        required_fields=required_fields,
        optional_fields=optional_fields,
        mapped_fields=mapped_fields,
    )


def _aliases_for(mapped_fields: frozenset[str]) -> Mapping[str, str]:
    return MappingProxyType(
        {
            source_name: normalized_name
            for source_name, normalized_name in THS_RESPONSE_FIELD_ALIASES.items()
            if normalized_name in mapped_fields
        }
    )


def _ths_contract(
    *,
    contract_id: str,
    route_id: str,
    family_id: str,
    asset_type: str,
    data_kind: str,
    frequencies: frozenset[str],
    markets: frozenset[str],
    supported_adjustments: frozenset[str],
    supported_price_bases: frozenset[str],
    supported_currencies: frozenset[str] | None,
    supported_units: frozenset[str] | None,
    field_profile: ProviderResponseFieldProfile,
    endpoints: frozenset[str],
    request_transform_id: str,
    source_policy_required: bool = False,
) -> ProviderContract:
    return ProviderContract(
        contract_id=contract_id,
        contract_version=THS_PROVIDER_CONTRACT_VERSION,
        provider="ths",
        route_id=route_id,
        family_id=family_id,
        family_contract_version=FAMILY_CONTRACT_VERSION,
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
        timestamp_columns=("date_ms",),
        symbol_columns=("thscode",),
        identity_proof="source_request_bound",
        source_policy_required=source_policy_required,
        client_filters_window=True,
        request_transform_id=request_transform_id,
        endpoint_resolver_id=THS_STATIC_ENDPOINT_RESOLVER_ID,
        endpoints=endpoints,
        normalizer_id=AKSHARE_ROW_NORMALIZER_ID,
        timestamp_normalizer_id=THS_MILLIS_TIMESTAMP_NORMALIZER_ID,
        window_semantics=THS_CLOSED_WINDOW_SEMANTICS,
    )


# THS provider 契约。route_id 与 source policy 中的 THS 路由一一对应。
THS_PROVIDER_CONTRACTS: tuple[ProviderContract, ...] = (
    _ths_contract(
        contract_id="ths.stock.primary.contract-v1",
        route_id="ths-stock-primary-v1",
        family_id="stock.realtime",
        asset_type="stock",
        data_kind="bars",
        frequencies=frozenset({"1d"}),
        markets=frozenset({"CN-SSE", "CN-SZSE"}),
        supported_adjustments=frozenset({"unadjusted", "qfq", "hfq"}),
        supported_price_bases=frozenset({"close"}),
        supported_currencies=frozenset({"CNY"}),
        supported_units=frozenset({"share"}),
        field_profile=_profile(
            "stock-bars-ths-v1",
            ("close",),
            optional_fields=("open", "high", "low", "volume", "turnover"),
            mapped_fields=_STOCK_MAPPED_FIELDS,
        ),
        endpoints=frozenset({"/api/a-share/prices/historical"}),
        request_transform_id="ths.historical-kline-request-v1",
        source_policy_required=True,
    ),
    _ths_contract(
        contract_id="ths.stock.liquidity.contract-v1",
        route_id="ths-stock-liquidity-v1",
        family_id="stock.liquidity",
        asset_type="stock",
        data_kind="reference_series",
        frequencies=frozenset({"1d"}),
        markets=frozenset({"CN-SSE", "CN-SZSE"}),
        supported_adjustments=frozenset({"unadjusted"}),
        supported_price_bases=frozenset({"close"}),
        supported_currencies=frozenset({"CNY"}),
        supported_units=frozenset({"share"}),
        field_profile=_profile(
            "stock-liquidity-ths-v1",
            ("volume", "turnover", "turnover_rate"),
            mapped_fields=_STOCK_MAPPED_FIELDS,
        ),
        endpoints=frozenset({"/api/a-share/prices/historical"}),
        request_transform_id="ths.historical-kline-request-v1",
        source_policy_required=True,
    ),
    # 指数（a-share-index）历史 K 线在中台现有七类资产模型中无对应 asset_type
    # （dataset_contracts._ASSET_TYPES 仅 stock/futures/bond/fund/option/fx/crypto）。
    # 按 DATA_SCOPE 第 3 节，指数成分股与指数列表作为 catalog_table / reference
    # 数据集登记（见 ths_reference.py），不新增 provider route 契约。
)

THS_PROVIDER_CONTRACT_REGISTRY = ProviderContractRegistry(THS_PROVIDER_CONTRACTS)


def prepare_ths_historical_request(
    contract: ProviderContract,
    request: MarketDataProviderRequest,
) -> Mapping[str, Any]:
    """执行 THS 历史 K 线的请求变换（Query Transform）。

    时区语义（实测确认，2026-09-19）：
    - 中台日线 ``event_at`` = 交易日 T 的 UTC midnight（``T 00:00 UTC``）。
    - THS ``date_ms`` = 交易日 T 的 Asia/Shanghai 零点（``T 00:00+08:00``
      = ``(T-1) 16:00 UTC``），且 THS 按其毫秒数值过滤。
    因此 THS 查询窗口须相对中台 UTC 窗口整体 **-8 小时**，否则交易日 T 的
    bar（``date_ms`` 落在 T-1 日 16:00 UTC）会被排除。

    历史 K 线仅单标的单请求；``start``/``end`` 均必填（毫秒戳，闭区间）。
    """
    if request.frequency not in THS_SUPPORTED_INTERVALS:
        raise ProviderContractError("PROVIDER_CONTRACT_FREQUENCY_UNSUPPORTED")
    ths_start = request.start_at - THS_SHANGHAI_UTC_OFFSET
    ths_end = request.end_at - THS_SHANGHAI_UTC_OFFSET
    return {
        "thscode": request.provider_symbol,
        "interval": "1d",
        "start": _millis(ths_start),
        "end": _inclusive_end_millis(ths_end),
        "adjust": ths_adjustment(request),
    }


__all__ = [
    "THS_ADJUST_BACKWARD",
    "THS_ADJUST_FORWARD",
    "THS_ADJUST_NONE",
    "THS_MAX_BATCH_TOKENS",
    "THS_MAX_WINDOW",
    "THS_PROVIDER_CONTRACT_REGISTRY",
    "THS_PROVIDER_CONTRACTS",
    "THS_RESPONSE_FIELD_ALIASES",
    "THS_SUPPORTED_INTERVALS",
    "prepare_ths_historical_request",
    "split_thscodes_batch",
    "split_window_into_chunks",
    "ths_adjustment",
]
