"""THS reference 数据域的 schedule-only collector 落库（除复权因子首例）。

THS 的财务、除复权、日历等是稀疏事件流，不是每日 bar 网格，也不属于 197 的
21 页面主题。按 DATA_SCOPE 它们登记为 reference_series / catalog_table，本模块
以 **schedule-only collector** 落库（复用 ``stock_valuation_collector`` 的
offline 落库模式），不注册 request-time route、不新增 public family、不触碰
ready 契约或 coverage 模型。

除复权因子（``adjustment-factors``）：
- 源事件时间为 ``ex_date_ms``（除权除息日），归一化为 UTC midnight 作为
  observation ``event_time``。
- 字段 ``dividend_per_share`` / ``per_share_bonus`` 进 ``fields_json``。
- 事件类型由两者隐式区分（THS 不返回 ``event_type``），保留该语义。

本 collector 只负责「已取数的数据落库」；取数由 ``ThsReferenceFetcher`` 完成，
两者分离以保持职责单一。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, time, timezone
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

from app.services.market_data.access import MarketDataSourceAuthorization
from app.services.market_data.providers import (
    MarketDataProviderRequest,
    ProviderFetchResult,
    ProviderMarketObservation,
)
from app.services.market_data.query_resolution import ResolvedMarketDataQueryContext
from app.services.market_data.store import MarketDataStore, PersistedProviderFetch
from app.services.market_data.ths_envelope import ThsEnvelope
from app.services.market_data.ths_reference import (
    normalize_adjustment_factors,
    normalize_financials,
)

_UTC = timezone.utc
THS_ADJUSTMENT_FACTORS_PROVIDER_ID = "ths"
THS_ADJUSTMENT_FACTORS_DATASET_CODE = "reference.stock_adjustment_factors"
THS_ADJUSTMENT_FACTORS_SOURCE_REVISION = "ths.adjustment-factors:reference-series-v1"
THS_ADJUSTMENT_FACTORS_REQUIRED_FIELDS = frozenset({"dividend_per_share", "per_share_bonus"})
THS_ADJUSTMENT_FACTORS_SOURCE_POLICY_ID = "market-ths-adjustment-factors-captured-v1"

# 财务三报表（schedule-only collector 落库，source_revision 区分报表）。
THS_FINANCIALS_PROVIDER_ID = "ths"
THS_FINANCIALS_SOURCE_POLICY_ID = "market-ths-financials-captured-v1"
THS_FINANCIALS_STATEMENTS: Mapping[str, str] = MappingProxyType(
    {
        "income": "market.stock_financials_income",
        "balance": "market.stock_financials_balance",
        "cashflow": "market.stock_financials_cashflow",
    }
)
THS_FINANCIALS_SOURCE_REVISIONS: Mapping[str, str] = MappingProxyType(
    {
        "income": "ths.income-statements:reference-series-v1",
        "balance": "ths.balance-sheets:reference-series-v1",
        "cashflow": "ths.cash-flow-statements:reference-series-v1",
    }
)


class ThsReferenceCollectorError(RuntimeError):
    """THS reference collector 稳定错误码。"""

    def __init__(self, code: str, *, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


def _millis_to_event_at(value: object) -> datetime:
    """把 ``ex_date_ms`` 归一化为除权日的 UTC midnight（与日线 event_at 对齐）。"""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ThsReferenceCollectorError("THS_EVENT_TIME_INVALID")
    instant = datetime.fromtimestamp(value / 1000.0, tz=_UTC)
    # 除权日 ex_date_ms 是「除权除息日的 Asia/Shanghai 零点」；转该日期 UTC midnight。
    shanghai_date = instant.astimezone(ZoneInfo("Asia/Shanghai")).date()
    return datetime.combine(shanghai_date, time.min, tzinfo=_UTC)


def adjustment_factor_observations(
    envelope: ThsEnvelope,
    *,
    request: MarketDataProviderRequest,
    retrieved_at: datetime,
) -> tuple[ProviderMarketObservation, ...]:
    """把除复权信封归一化为带真实事件时间的 observations。

    ``normalize_adjustment_factors`` 已按 ``ex_date_ms`` 降序排序；此处把每条
    事件映射为一个 ``ProviderMarketObservation``，``event_at`` 为除权日。
    """
    rows = normalize_adjustment_factors(envelope)
    observations: list[ProviderMarketObservation] = []
    for row in rows:
        event_at = _millis_to_event_at(row["ex_date_ms"])
        # 只落库请求窗口内的事件；更早/更晚历史由分批回填覆盖。
        if not request.start_at <= event_at < request.end_at:
            continue
        fields: dict[str, Any] = {
            "dividend_per_share": row.get("dividend_per_share"),
            "per_share_bonus": row.get("per_share_bonus"),
        }
        observations.append(
            ProviderMarketObservation(
                event_at=event_at,
                available_at=retrieved_at,
                fields=fields,
            )
        )
    return tuple(observations)


def financials_observations(
    envelope: ThsEnvelope,
    *,
    request: MarketDataProviderRequest,
    retrieved_at: datetime,
) -> tuple[ProviderMarketObservation, ...]:
    """把财务报表信封归一化为多期序列 observations。

    ``event_at`` 为报告期末（``period_end_ms`` 归一化为 UTC midnight）；
    ``fiscal_year`` / ``fiscal_period`` 作为维度字段保留在 ``fields``；
    ``null`` 表示「该期未披露」，透传不补零（AC-11）。报表金额字段原样
    透传（fields_json 为 JSON，允许超出 schema 声明的核心字段）。
    """
    rows = normalize_financials(envelope)
    observations: list[ProviderMarketObservation] = []
    seen_events: set[datetime] = set()
    for row in rows:
        period_end = row.get("period_end_ms")
        if period_end is None:
            raise ThsReferenceCollectorError("THS_FINANCIALS_PERIOD_END_MISSING")
        event_at = _millis_to_event_at(period_end)
        if not request.start_at <= event_at < request.end_at:
            continue
        if event_at in seen_events:
            raise ThsReferenceCollectorError("THS_FINANCIALS_DUPLICATE_PERIOD_END")
        seen_events.add(event_at)
        fields = {key: value for key, value in row.items() if key not in {"period_end_ms"}}
        observations.append(
            ProviderMarketObservation(
                event_at=event_at,
                available_at=retrieved_at,
                fields=fields,
            )
        )
    return tuple(observations)


class ThsReferenceCollector:
    """把已取数的 THS reference 数据落库为 reference_series。

    与 ``stock_valuation_collector`` 同构：不取数、不注册 route、不 resolve
    identity；调用方提供 unbound context、冻结 identity 与当前 source grant。
    """

    def __init__(self, *, store: MarketDataStore) -> None:
        if not isinstance(store, MarketDataStore):
            raise TypeError("store must be a MarketDataStore")
        self._store = store

    async def persist_adjustment_factors(
        self,
        *,
        context: ResolvedMarketDataQueryContext,
        source_authorization: MarketDataSourceAuthorization,
        request: MarketDataProviderRequest,
        envelope: ThsEnvelope,
        retrieved_at: datetime,
    ) -> PersistedProviderFetch:
        """落库一次除复权因子取数结果。"""
        if not isinstance(context, ResolvedMarketDataQueryContext):
            raise ThsReferenceCollectorError("THS_REFERENCE_CONTEXT_INVALID")
        if not isinstance(source_authorization, MarketDataSourceAuthorization):
            raise ThsReferenceCollectorError("THS_REFERENCE_AUTHORIZATION_INVALID")
        observations = adjustment_factor_observations(
            envelope,
            request=request,
            retrieved_at=retrieved_at,
        )
        result = ProviderFetchResult(
            provider_id=THS_ADJUSTMENT_FACTORS_PROVIDER_ID,
            source_revision=THS_ADJUSTMENT_FACTORS_SOURCE_REVISION,
            retrieved_at=retrieved_at,
            observations=observations,
            raw_payload=_raw_payload(request, envelope),
            request=request,
            warnings=("THS_ADJUSTMENT_FACTORS_OFFLINE_CAPTURED",),
        )
        receipt = await self._store.persist_provider_result(
            context,
            result,
            received_at=retrieved_at,
            source_authorization=source_authorization,
        )
        if not isinstance(receipt, PersistedProviderFetch):
            raise ThsReferenceCollectorError("THS_REFERENCE_PERSISTENCE_DEFERRED")
        return receipt

    async def persist_financials(
        self,
        *,
        statement: str,
        context: ResolvedMarketDataQueryContext,
        source_authorization: MarketDataSourceAuthorization,
        request: MarketDataProviderRequest,
        envelope: ThsEnvelope,
        retrieved_at: datetime,
    ) -> PersistedProviderFetch:
        """落库一次财务报表取数结果（income/balance/cashflow 三选一）。"""
        dataset_code = THS_FINANCIALS_STATEMENTS.get(statement)
        source_revision = THS_FINANCIALS_SOURCE_REVISIONS.get(statement)
        if dataset_code is None or source_revision is None:
            raise ThsReferenceCollectorError("THS_FINANCIALS_STATEMENT_UNSUPPORTED")
        if not isinstance(context, ResolvedMarketDataQueryContext):
            raise ThsReferenceCollectorError("THS_REFERENCE_CONTEXT_INVALID")
        if context.query.dataset_code != dataset_code:
            raise ThsReferenceCollectorError("THS_REFERENCE_CONTEXT_DATASET_MISMATCH")
        if not isinstance(source_authorization, MarketDataSourceAuthorization):
            raise ThsReferenceCollectorError("THS_REFERENCE_AUTHORIZATION_INVALID")
        observations = financials_observations(
            envelope,
            request=request,
            retrieved_at=retrieved_at,
        )
        result = ProviderFetchResult(
            provider_id=THS_FINANCIALS_PROVIDER_ID,
            source_revision=source_revision,
            retrieved_at=retrieved_at,
            observations=observations,
            raw_payload=_raw_payload(
                request,
                envelope,
                source_revision=source_revision,
                dataset_code=dataset_code,
            ),
            request=request,
            warnings=(f"THS_FINANCIALS_{statement.upper()}_OFFLINE_CAPTURED",),
        )
        receipt = await self._store.persist_provider_result(
            context,
            result,
            received_at=retrieved_at,
            source_authorization=source_authorization,
        )
        if not isinstance(receipt, PersistedProviderFetch):
            raise ThsReferenceCollectorError("THS_REFERENCE_PERSISTENCE_DEFERRED")
        return receipt


def _raw_payload(
    request: MarketDataProviderRequest,
    envelope: ThsEnvelope,
    *,
    source_revision: str = THS_ADJUSTMENT_FACTORS_SOURCE_REVISION,
    dataset_code: str = THS_ADJUSTMENT_FACTORS_DATASET_CODE,
) -> MappingProxyType[str, Any]:
    """构造紧凑的 provenance，含 request_id 与信封 request_id。"""
    payload: dict[str, Any] = {
        "collector": {
            "source_revision": source_revision,
            "dataset_code": dataset_code,
            "ths_request_id": envelope.request_id,
        },
        "request": request.dto_payload,
        "response_items": [list(envelope.data_item)],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > 10 * 1024 * 1024:
        raise ThsReferenceCollectorError("THS_REFERENCE_PROVENANCE_TOO_LARGE")
    return MappingProxyType(payload)
