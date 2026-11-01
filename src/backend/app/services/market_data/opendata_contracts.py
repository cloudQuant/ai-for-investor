"""opendata（自建数据中台）provider 契约与请求变换。

复用迭代 197 的 ``ProviderContract`` 数据类，登记自建数据中台的静态控制面：
请求变换（REST 查询参数）、响应字段映射、日期归一化、复权映射。

与 AkShare / THS 的关键差异：
- 传输：中台 REST（``GET /api/v1/data/{asset_class}/{domain}``），API Key 鉴权；
- 返回：``data.rows`` 为 dwd 合并层行，字段名已是中台字段名
  （``symbol`` / ``trade_date`` / ``open`` / ``high`` / ``low`` / ``close`` /
  ``volume`` / ``amount``），故别名表只需把 ``amount`` 映射为 ``turnover``；
- 时间戳：``trade_date``（``YYYY-MM-DD``，date-only）→ 交易日 UTC midnight；
- 窗口：中台 REST 为闭区间日期；平台内部为半开 UTC 窗口，故 end 需 -1 天；
- 股票分页：``page`` / ``page_size`` 逐页拉取，直到短页。
- 风险指数只使用 OpenData v2 固定 publication snapshot 与 opaque cursor；
  三个 benchmark 分别绑定独立 dataset，覆盖状态未知时不生成指标。

本模块是控制面，不含网络客户端、数据库句柄或运行时开关。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from types import MappingProxyType
from typing import Any

from app.services.market_data.dataset_contracts import FAMILY_CONTRACT_VERSION
from app.services.market_data.provider_contracts import (
    AKSHARE_ROW_NORMALIZER_ID,
    AKSHARE_UTC_DATE_NORMALIZER_ID,
    OPENDATA_HISTORICAL_KLINE_REQUEST_TRANSFORM_ID,
    OPENDATA_PROVIDER_CONTRACT_VERSION,
    OPENDATA_STATIC_ENDPOINT_RESOLVER_ID,
    THS_CLOSED_WINDOW_SEMANTICS,
    ProviderContract,
    ProviderContractError,
    ProviderContractRegistry,
    ProviderResponseFieldProfile,
)
from app.services.market_data.providers import MarketDataProviderRequest

#: 中台 dwd 日线端点（唯一已审查端点）。
OPENDATA_STOCK_DAILY_ENDPOINT = "/api/v1/data/equity/stock_daily"
OPENDATA_INDEX_BENCHMARK_FAMILY_ID = "risk.index_benchmark"
OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION = "risk-index-benchmark-published-v2"
OPENDATA_INDEX_BENCHMARK_ROUTE_ID = "opendata-index-benchmark-published-v2"
OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT = (
    "GET /api/v2/datasets/{dataset_id}/coverage; "
    "POST /api/v2/snapshots; GET /api/v2/datasets/{dataset_id}/records"
)
OPENDATA_INDEX_BENCHMARK_DATASETS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "hs300": ("000300.SH", "cn.csi300.index.daily"),
        "csi500": ("000905.SH", "cn.csi500.index.daily"),
        "csi800": ("000906.SH", "cn.csi800.index.daily"),
    }
)
OPENDATA_INDEX_BENCHMARK_DATASET_IDS = frozenset(
    dataset_id for _symbol, dataset_id in OPENDATA_INDEX_BENCHMARK_DATASETS.values()
)


def has_complete_business_history_coverage(
    coverage: Mapping[str, Any],
    *,
    requested_start: str,
    requested_end: str,
) -> bool:
    """Validate exact requested bounds and an evidence-backed observed subrange.

    OpenData reports observed business dates as a half-open range from its first
    through last observation. Non-trading days at the requested window edges may
    therefore make this range narrower than the request without reducing
    completeness. The observed range must still be nonempty and fully bounded by
    the exact requested window.
    """
    try:
        request_start = date.fromisoformat(requested_start)
        request_end = date.fromisoformat(requested_end)
    except (TypeError, ValueError):
        return False
    if (
        request_start.isoformat() != requested_start
        or request_end.isoformat() != requested_end
        or request_start >= request_end
        or coverage.get("status") != "complete"
        or coverage.get("scope") != "business_history"
        or coverage.get("requested") != {"start": requested_start, "end": requested_end}
        or coverage.get("missing_ranges") != []
        or coverage.get("limitation") is not None
    ):
        return False

    observed = coverage.get("observed")
    evidence_refs = coverage.get("evidence_refs")
    if (
        not isinstance(observed, Mapping)
        or set(observed) != {"start", "end"}
        or not isinstance(evidence_refs, list)
        or not evidence_refs
        or any(not isinstance(item, str) or not item.strip() for item in evidence_refs)
    ):
        return False
    observed_start_text = observed.get("start")
    observed_end_text = observed.get("end")
    if not isinstance(observed_start_text, str) or not isinstance(observed_end_text, str):
        return False
    try:
        observed_start = date.fromisoformat(observed_start_text)
        observed_end = date.fromisoformat(observed_end_text)
    except ValueError:
        return False
    return (
        observed_start.isoformat() == observed_start_text
        and observed_end.isoformat() == observed_end_text
        and request_start <= observed_start < observed_end <= request_end
    )


#: opendata provider 支持的频率：当前仅日线（分钟线走 Parquet 归档，未开放 REST）。
OPENDATA_SUPPORTED_FREQUENCIES = frozenset({"1d"})

#: 单次请求最大页大小：与中台 REST 的 ``MAX_PAGE_SIZE`` 一致（超出返回 422）。
OPENDATA_MAX_PAGE_SIZE = 1000

#: 整体分页保护上限：超过即失败，避免无限翻页。
OPENDATA_MAX_ROWS = 50_000

#: 中台复权语义 → opendata ``adjust`` 原生值。
_ADJUSTMENT_MAP: Mapping[str, str] = MappingProxyType(
    {
        "unadjusted": "none",
        "qfq": "qfq",
        "hfq": "hfq",
    }
)

#: 中台 dwd 行字段别名：源字段 → 中台归一化字段。
#: 日线 dwd 已使用中台字段名，只有成交额在中台契约里叫 ``turnover``。
OPENDATA_RESPONSE_FIELD_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "amount": "turnover",
        "turnover": "turnover",
        "change_pct": "change_pct",
        "change": "change",
        "turnover_rate": "turnover_rate",
        "previous_close": "previous_close",
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
        "change_pct",
        "change",
        "turnover_rate",
        "previous_close",
    }
)


def opendata_adjustment(request: MarketDataProviderRequest) -> str:
    """把中台复权语义映射为 opendata ``adjust`` 参数值，绝不猜测新基准。

    ``None`` 与 ``unadjusted`` 均映射为 ``none``。
    """
    adjustment = request.adjustment or "unadjusted"
    try:
        return _ADJUSTMENT_MAP[adjustment]
    except KeyError as exc:
        raise ProviderContractError("PROVIDER_CONTRACT_ADJUSTMENT_UNSUPPORTED") from exc


def _aliases(mapped_fields: frozenset[str]) -> Mapping[str, str]:
    return MappingProxyType(
        {
            source_name: normalized_name
            for source_name, normalized_name in OPENDATA_RESPONSE_FIELD_ALIASES.items()
            if normalized_name in mapped_fields
        }
    )


#: opendata provider 契约。route_id 与 source policy 中的 opendata 路由一一对应。
OPENDATA_PROVIDER_CONTRACTS: tuple[ProviderContract, ...] = (
    ProviderContract(
        contract_id="opendata.stock.daily.contract-v1",
        contract_version=OPENDATA_PROVIDER_CONTRACT_VERSION,
        provider="opendata",
        route_id="opendata-stock-daily-v1",
        family_id="stock.realtime",
        family_contract_version=FAMILY_CONTRACT_VERSION,
        asset_type="stock",
        data_kind="bars",
        frequencies=OPENDATA_SUPPORTED_FREQUENCIES,
        markets=frozenset({"CN-SSE", "CN-SZSE"}),
        supported_adjustments=frozenset({"unadjusted", "qfq", "hfq"}),
        supported_price_bases=frozenset({"close"}),
        supported_currencies=frozenset({"CNY"}),
        supported_units=frozenset({"share"}),
        field_profile=ProviderResponseFieldProfile(
            profile_id="stock-bars-opendata-v1",
            required_fields=("close",),
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
        response_field_aliases=_aliases(_STOCK_MAPPED_FIELDS),
        timestamp_columns=("trade_date",),
        symbol_columns=("symbol",),
        identity_proof="response_symbol",
        source_policy_required=True,
        client_filters_window=True,
        request_transform_id=OPENDATA_HISTORICAL_KLINE_REQUEST_TRANSFORM_ID,
        endpoint_resolver_id=OPENDATA_STATIC_ENDPOINT_RESOLVER_ID,
        endpoints=frozenset({OPENDATA_STOCK_DAILY_ENDPOINT}),
        # 与 AkShare 一致：date-only 时间戳 → 交易日 UTC midnight。
        normalizer_id=AKSHARE_ROW_NORMALIZER_ID,
        timestamp_normalizer_id=AKSHARE_UTC_DATE_NORMALIZER_ID,
        # 平台内部半开窗口；provider 侧的闭区间语义在请求变换里处理。
        window_semantics=THS_CLOSED_WINDOW_SEMANTICS,
    ),
)

OPENDATA_PROVIDER_CONTRACT_REGISTRY = ProviderContractRegistry(OPENDATA_PROVIDER_CONTRACTS)


def prepare_opendata_historical_request(
    contract: ProviderContract,
    request: MarketDataProviderRequest,
) -> Mapping[str, Any]:
    """执行 opendata 日线的请求变换（Query Transform）。

    平台内部窗口为半开 ``[start, end)``；中台 REST 的 ``start``/``end`` 为
    闭区间日期，故 ``end`` 取 ``end - 1 天``（与 AkShare 的 inclusive end 口径一致）。
    """
    if request.frequency not in OPENDATA_SUPPORTED_FREQUENCIES:
        raise ProviderContractError("PROVIDER_CONTRACT_FREQUENCY_UNSUPPORTED")
    if request.start_at >= request.end_at:
        raise ProviderContractError("PROVIDER_CONTRACT_WINDOW_INVALID")
    if contract.contract_id != "opendata.stock.daily.contract-v1":
        raise ProviderContractError("PROVIDER_CONTRACT_UNREGISTERED")
    return {
        "symbols": request.provider_symbol,
        "start": request.start_at.date().isoformat(),
        "end": (request.end_at - timedelta(days=1)).date().isoformat(),
        "adjust": opendata_adjustment(request),
        "layer": "dwd",
        "source": "auto",
        "page_size": OPENDATA_MAX_PAGE_SIZE,
    }


__all__ = [
    "OPENDATA_INDEX_BENCHMARK_DATASETS",
    "OPENDATA_INDEX_BENCHMARK_DATASET_IDS",
    "OPENDATA_INDEX_BENCHMARK_FAMILY_ID",
    "OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION",
    "OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT",
    "OPENDATA_INDEX_BENCHMARK_ROUTE_ID",
    "OPENDATA_MAX_PAGE_SIZE",
    "OPENDATA_MAX_ROWS",
    "OPENDATA_PROVIDER_CONTRACT_REGISTRY",
    "OPENDATA_PROVIDER_CONTRACTS",
    "OPENDATA_RESPONSE_FIELD_ALIASES",
    "OPENDATA_STOCK_DAILY_ENDPOINT",
    "OPENDATA_SUPPORTED_FREQUENCIES",
    "opendata_adjustment",
    "prepare_opendata_historical_request",
]
