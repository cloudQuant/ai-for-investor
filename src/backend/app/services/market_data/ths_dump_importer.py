"""THS ``market-dumps`` Parquet 下载、解析与全市场回填落库。

用于迭代 199 的全市场历史回填：
- ``daily-k`` / ``daily-k-10d``：全市场日 K（一次下载覆盖全市场，避免逐标的 API 限流）。
- ``adjustment-factors``：全量复权因子事件流。

Parquet schema（实测）：
    日 K：thscode, currency, interval(1d), adjusted(none), date_ms,
          open_price, high_price, low_price, close_price, volume, turnover
    复权：thscode, ticker, ex_date_ms, dividend_per_share, per_share_bonus,
          allotment_ratio, allotment_price, currency

``date_ms`` 是交易日 T 的 Asia/Shanghai 零点（实测：连续工作日期序列），
中台 ``event_at`` 取该日期的 UTC midnight（与日线 provider 一致）。
"""

from __future__ import annotations

import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.schemas.asset_research import InstrumentIdentity
from app.services.market_data.access import MarketDataSourceAuthorization
from app.services.market_data.catalog import DataCatalogResolver
from app.services.market_data.coverage import QueryIdentity
from app.services.market_data.identity import ResolvedMarketDataIdentity
from app.services.market_data.providers import (
    MarketDataProviderRequest,
    ProviderFetchResult,
    ProviderMarketObservation,
)
from app.services.market_data.query_resolution import ResolvedMarketDataQueryContext
from app.services.market_data.store import MarketDataStore, PersistedProviderFetch

_UTC = timezone.utc
_SHANGHAI = ZoneInfo("Asia/Shanghai")

THS_DUMP_PROVIDER_ID = "ths"
THS_DAILY_K_DATASET_CODE = "market.bars"
THS_ADJUSTMENT_FACTORS_DATASET_CODE = "reference.stock_adjustment_factors"
THS_DAILY_K_SOURCE_POLICY_ID = "market-ths-dump-daily-k-v1"
THS_ADJUSTMENT_FACTORS_SOURCE_POLICY_ID = "market-ths-dump-adjustment-factors-v1"
THS_DAILY_K_SOURCE_REVISION = "ths.market-dumps:daily-k-v1"
THS_ADJUSTMENT_FACTORS_SOURCE_REVISION = "ths.market-dumps:adjustment-factors-v1"
THS_DAILY_K_REQUIRED_FIELDS = frozenset({"close"})
THS_ADJUSTMENT_FACTORS_REQUIRED_FIELDS = frozenset({"dividend_per_share", "per_share_bonus"})
THS_METADATA_VERSION = "iteration199-ths-dump-v1"

DEFAULT_MAX_DUMP_BYTES = 512 * 1024 * 1024
_MAX_PROVENANCE_BYTES = 10 * 1024 * 1024

# dump kind → 下载端点。
THS_DUMP_DOWNLOAD_PATHS: Mapping[str, str] = {
    "daily-k": "/api/dump/market-dumps/daily-k/download-url",
    "daily-k-10d": "/api/dump/market-dumps/daily-k-10d/download-url",
    "adjustment-factors": "/api/dump/market-dumps/adjustment-factors/download-url",
}


class ThsDumpError(RuntimeError):
    """THS dump 下载/解析/落库稳定错误码。"""

    def __init__(self, code: str, *, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DumpDailyBar:
    """一条日 K Parquet 行。"""

    thscode: str
    event_at: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    turnover: float


@dataclass(frozen=True, slots=True)
class DumpAdjustmentFactor:
    """一条复权因子 Parquet 行。"""

    thscode: str
    event_at: datetime
    dividend_per_share: float | None
    per_share_bonus: float | None


def _millis_to_event_at(value: object) -> datetime:
    """date_ms（交易日上海零点）→ 交易日期的 UTC midnight。"""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ThsDumpError("THS_DUMP_TIMESTAMP_INVALID")
    instant = datetime.fromtimestamp(value / 1000.0, tz=_UTC)
    trading_date = instant.astimezone(_SHANGHAI).date()
    return datetime.combine(trading_date, time.min, tzinfo=_UTC)


def _require_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ThsDumpError("THS_DUMP_FIELD_INVALID", detail=field_name)
    return float(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return _require_float(value, field_name="optional")


def parse_daily_k_parquet(content: bytes) -> tuple[DumpDailyBar, ...]:
    """解析日 K Parquet，返回按 (thscode, date) 的 bar 元组。"""
    try:
        import pyarrow.parquet as pq  # noqa: PLC0415 - optional heavy dependency
    except ImportError as exc:  # pragma: no cover - environment provides pyarrow
        raise ThsDumpError("THS_DUMP_PYARROW_UNAVAILABLE") from exc
    try:
        table = pq.read_table(io.BytesIO(content))
    except Exception as exc:
        raise ThsDumpError("THS_DUMP_PARQUET_INVALID") from exc
    required = {"thscode", "date_ms", "open_price", "high_price", "low_price", "close_price"}
    if not required <= set(table.column_names):
        raise ThsDumpError("THS_DUMP_SCHEMA_MISMATCH")
    bars: list[DumpDailyBar] = []
    for row in table.to_pylist():
        thscode = row.get("thscode")
        if not isinstance(thscode, str) or not thscode:
            raise ThsDumpError("THS_DUMP_SYMBOL_INVALID")
        bars.append(
            DumpDailyBar(
                thscode=thscode,
                event_at=_millis_to_event_at(row.get("date_ms")),
                open_price=_require_float(row.get("open_price"), field_name="open_price"),
                high_price=_require_float(row.get("high_price"), field_name="high_price"),
                low_price=_require_float(row.get("low_price"), field_name="low_price"),
                close_price=_require_float(row.get("close_price"), field_name="close_price"),
                volume=_require_float(row.get("volume"), field_name="volume"),
                turnover=_require_float(row.get("turnover"), field_name="turnover"),
            )
        )
    return tuple(bars)


def parse_adjustment_factors_parquet(content: bytes) -> tuple[DumpAdjustmentFactor, ...]:
    """解析复权因子 Parquet，返回按 (thscode, ex_date) 的事件元组。"""
    try:
        import pyarrow.parquet as pq  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ThsDumpError("THS_DUMP_PYARROW_UNAVAILABLE") from exc
    try:
        table = pq.read_table(io.BytesIO(content))
    except Exception as exc:
        raise ThsDumpError("THS_DUMP_PARQUET_INVALID") from exc
    if not {"thscode", "ex_date_ms"} <= set(table.column_names):
        raise ThsDumpError("THS_DUMP_SCHEMA_MISMATCH")
    factors: list[DumpAdjustmentFactor] = []
    for row in table.to_pylist():
        thscode = row.get("thscode")
        if not isinstance(thscode, str) or not thscode:
            raise ThsDumpError("THS_DUMP_SYMBOL_INVALID")
        factors.append(
            DumpAdjustmentFactor(
                thscode=thscode,
                event_at=_millis_to_event_at(row.get("ex_date_ms")),
                dividend_per_share=_optional_float(row.get("dividend_per_share")),
                per_share_bonus=_optional_float(row.get("per_share_bonus")),
            )
        )
    return tuple(factors)


def group_by_symbol(
    items: Sequence[Any], *, symbol_attr: str = "thscode"
) -> dict[str, tuple[Any, ...]]:
    """按标的代码分组，保持组内顺序。"""
    grouped: dict[str, list[Any]] = {}
    for item in items:
        symbol = getattr(item, symbol_attr)
        grouped.setdefault(symbol, []).append(item)
    return {symbol: tuple(values) for symbol, values in grouped.items()}


def canonical_id_for_thscode(thscode: str) -> tuple[str, str]:
    """由 THS thscode 派生 (canonical_id, venue)。"""
    if "." not in thscode:
        raise ThsDumpError("THS_DUMP_SYMBOL_INVALID")
    ticker, _, suffix = thscode.partition(".")
    venue_by_suffix = {"SH": "CN-SSE", "SZ": "CN-SZSE", "BJ": "CN-BJSE"}
    venue = venue_by_suffix.get(suffix.upper())
    if venue is None or not ticker:
        raise ThsDumpError("THS_DUMP_SYMBOL_INVALID")
    return f"instrument:stock:{venue}:{ticker}", venue


def thscode_for_canonical_id(canonical_id: str) -> str | None:
    """由 canonical_id 反推 thscode（非股票或不合法返回 None）。"""
    parts = canonical_id.split(":")
    if len(parts) != 4 or parts[0] != "instrument" or parts[1] != "stock":
        return None
    _, _, venue, ticker = parts
    suffix_by_venue = {"CN-SSE": "SH", "CN-SZSE": "SZ", "CN-BJSE": "BJ"}
    suffix = suffix_by_venue.get(venue)
    if suffix is None or not ticker:
        return None
    return f"{ticker}.{suffix}"


class ThsDumpDownloader:
    """取预签名链接并即时下载 Parquet（5 分钟时效，不持久化链接）。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://fuyao.aicubes.cn",
        timeout_seconds: float = 60.0,
        max_bytes: int = DEFAULT_MAX_DUMP_BYTES,
    ) -> None:
        if not api_key:
            raise ThsDumpError("THS_DUMP_API_KEY_REQUIRED")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    def fetch_dump(self, kind: str, *, cache_path: str | None = None) -> bytes:
        """下载一个 dump 的 Parquet 字节（``cache_path`` 存在时复用本地文件）。"""
        if cache_path is not None:
            import os

            if os.path.isfile(cache_path):
                with open(cache_path, "rb") as handle:
                    return handle.read()
        path = THS_DUMP_DOWNLOAD_PATHS.get(kind)
        if path is None:
            raise ThsDumpError("THS_DUMP_KIND_UNREGISTERED")
        payload = self.fetch_ths_json(path)
        data = payload.get("data") if isinstance(payload, Mapping) else None
        presigned_url = data.get("presigned_url") if isinstance(data, Mapping) else None
        if not isinstance(presigned_url, str) or not presigned_url:
            raise ThsDumpError("THS_DUMP_URL_MISSING")
        # 即时下载，不持久化链接。
        download = httpx.get(presigned_url, timeout=self._timeout_seconds, trust_env=False)
        if download.status_code != 200:
            raise ThsDumpError("THS_DUMP_DOWNLOAD_HTTP_ERROR")
        if len(download.content) > self._max_bytes:
            raise ThsDumpError("THS_DUMP_TOO_LARGE")
        if cache_path is not None:
            with open(cache_path, "wb") as handle:
                handle.write(download.content)
        return download.content

    def fetch_ths_json(
        self, path: str, *, params: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        """带 ``X-api-key`` 请求一个 THS JSON 端点（瞬态网络错误自动重试）。"""
        response = self._get_with_retry(f"{self._base_url}{path}", params=params)
        if response.status_code != 200:
            raise ThsDumpError("THS_DUMP_URL_HTTP_ERROR")
        try:
            payload = json.loads(response.text)
        except ValueError as exc:
            raise ThsDumpError("THS_DUMP_URL_INVALID_JSON") from exc
        if not isinstance(payload, Mapping):
            raise ThsDumpError("THS_DUMP_URL_INVALID_JSON")
        return payload

    def _get_with_retry(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        attempts: int = 3,
    ) -> Any:
        """GET 一个 URL，对瞬态网络错误（连接重置/超时）做有界重试。"""
        import time

        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return httpx.get(
                    url,
                    params=dict(params) if params else None,
                    headers={"X-api-key": self._api_key} if self._api_key else None,
                    timeout=self._timeout_seconds,
                    trust_env=False,
                )
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(1.0 * (attempt + 1))
        assert last_error is not None
        raise ThsDumpError("THS_DUMP_NETWORK_ERROR", detail=type(last_error).__name__)


class ThsDumpImporter:
    """把已解析的 dump 数据按标的落库为规范 observation。

    与 198 的 schedule-only collector 同构：不取数、不注册 route；调用方提供
    当前 source grant，store 走既有 `persist_provider_result` 审计链路。
    """

    def __init__(self, *, store: MarketDataStore, catalog: DataCatalogResolver) -> None:
        if not isinstance(store, MarketDataStore):
            raise TypeError("store must be a MarketDataStore")
        if not isinstance(catalog, DataCatalogResolver):
            raise TypeError("catalog must be a DataCatalogResolver")
        self._store = store
        self._catalog = catalog

    async def import_daily_k(
        self,
        *,
        bars_by_symbol: Mapping[str, Sequence[DumpDailyBar]],
        source_authorization: MarketDataSourceAuthorization,
        retrieved_at: datetime,
        window_start: datetime,
        window_end: datetime,
    ) -> list[PersistedProviderFetch]:
        """按标的落库日 K bars；窗口外的 bar 被过滤。"""
        storage = await self._catalog.resolve_primary(THS_DAILY_K_DATASET_CODE)
        persisted: list[PersistedProviderFetch] = []
        for symbol in sorted(bars_by_symbol):
            bars = tuple(
                bar for bar in bars_by_symbol[symbol] if window_start <= bar.event_at < window_end
            )
            if not bars:
                continue
            canonical_id, venue = canonical_id_for_thscode(symbol)
            context = _build_context(
                dataset_code=THS_DAILY_K_DATASET_CODE,
                data_kind="bars",
                canonical_id=canonical_id,
                display_symbol=symbol,
                venue=venue,
                required_fields=THS_DAILY_K_REQUIRED_FIELDS,
                source_policy_id=THS_DAILY_K_SOURCE_POLICY_ID,
                storage=storage,
                window_start=window_start,
                window_end=window_end,
            )
            request = _provider_request(
                context=context,
                provider_symbol=symbol,
                data_kind="bars",
                required_fields=THS_DAILY_K_REQUIRED_FIELDS,
                source_policy_id=THS_DAILY_K_SOURCE_POLICY_ID,
                window_start=window_start,
                window_end=window_end,
            )
            observations = tuple(
                ProviderMarketObservation(
                    event_at=bar.event_at,
                    available_at=retrieved_at,
                    fields={
                        "open": bar.open_price,
                        "high": bar.high_price,
                        "low": bar.low_price,
                        "close": bar.close_price,
                        "volume": bar.volume,
                        "turnover": bar.turnover,
                    },
                )
                for bar in bars
            )
            result = ProviderFetchResult(
                provider_id=THS_DUMP_PROVIDER_ID,
                source_revision=THS_DAILY_K_SOURCE_REVISION,
                retrieved_at=retrieved_at,
                observations=observations,
                raw_payload=_raw_payload(
                    request, dataset_code=THS_DAILY_K_DATASET_CODE, observation_count=len(bars)
                ),
                request=request,
                warnings=("THS_DUMP_DAILY_K_OFFLINE_CAPTURED",),
            )
            receipt = await self._store.persist_provider_result(
                context,
                result,
                received_at=retrieved_at,
                source_authorization=source_authorization,
            )
            if not isinstance(receipt, PersistedProviderFetch):
                raise ThsDumpError("THS_DUMP_PERSISTENCE_DEFERRED")
            persisted.append(receipt)
        return persisted


def _build_context(
    *,
    dataset_code: str,
    data_kind: str,
    canonical_id: str,
    display_symbol: str,
    venue: str,
    required_fields: frozenset[str],
    source_policy_id: str,
    storage: Any,
    window_start: datetime,
    window_end: datetime,
) -> ResolvedMarketDataQueryContext:
    """构造一个 unbound（family_id=None）的落库上下文。"""
    from app.schemas.market_data_platform import MarketDataQueryRequest, ResolvedMarketDataQuery

    request = MarketDataQueryRequest.model_validate(
        {
            "identity": {"canonical_id": canonical_id},
            "dataset_code": dataset_code,
            "data_kind": data_kind,
            "frequency": "1d",
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "required_fields": sorted(required_fields),
            "adjustment": "unadjusted",
            "price_basis": "close",
            "currency": "CNY",
            "unit": "share",
            "source_policy_id": source_policy_id,
            "consistency": "display",
            "purpose": "display",
            "mode": "local_only",
        }
    )
    query = ResolvedMarketDataQuery.from_request(
        request,
        canonical_id=canonical_id,
        dataset_code=dataset_code,
        instrument_metadata_version=THS_METADATA_VERSION,
    )
    identity = InstrumentIdentity(
        asset_type="stock",
        identity_level="ASSET",
        canonical_id=canonical_id,
        display_symbol=display_symbol,
        name=display_symbol,
        venue=venue,
        currency="CNY",
        timezone="Asia/Shanghai",
        identifier_type="EXCHANGE_SYMBOL",
        identifier_value=display_symbol,
        product_type="EQUITY",
        metadata_version=THS_METADATA_VERSION,
        details={"kind": "STOCK", "exchange_symbol": display_symbol},
    )
    resolved_identity = ResolvedMarketDataIdentity(
        instrument_id=canonical_id,
        canonical_id=canonical_id,
        asset_type="stock",
        metadata_version=THS_METADATA_VERSION,
        venue=venue,
        identity=identity,
        valid_from=datetime(2000, 1, 1, tzinfo=_UTC),
        valid_to=None,
        known_at=datetime(2000, 1, 1, tzinfo=_UTC),
    )
    return ResolvedMarketDataQueryContext(
        query=query,
        identity=resolved_identity,
        storage=storage,
        coverage_identity=QueryIdentity(
            dataset_code=dataset_code,
            canonical_id=canonical_id,
            asset_type="stock",
            instrument_metadata_version=THS_METADATA_VERSION,
            data_kind=data_kind,
            market=venue,
            frequency="1d",
            source_policy_id=source_policy_id,
            adjustment="unadjusted",
            price_basis="close",
            currency="CNY",
            unit="share",
        ),
    )


def _provider_request(
    *,
    context: ResolvedMarketDataQueryContext,
    provider_symbol: str,
    data_kind: str,
    required_fields: frozenset[str],
    source_policy_id: str,
    window_start: datetime,
    window_end: datetime,
) -> MarketDataProviderRequest:
    return MarketDataProviderRequest(
        query_fingerprint=context.query.query_fingerprint,
        canonical_id=context.query.canonical_id,
        asset_type="stock",
        provider_symbol=provider_symbol,
        market=context.identity.venue or "",
        data_kind=data_kind,
        frequency="1d",
        start_at=window_start,
        end_at=window_end,
        required_fields=required_fields,
        provider=THS_DUMP_PROVIDER_ID,
        adjustment="unadjusted",
        price_basis="close",
        currency="CNY",
        unit="share",
        source_policy_id=source_policy_id,
    )


def _raw_payload(
    request: MarketDataProviderRequest,
    *,
    dataset_code: str,
    observation_count: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "collector": {
            "dataset_code": dataset_code,
            "provider_symbol": request.provider_symbol,
            "observation_count": observation_count,
        },
        "request": request.dto_payload,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > _MAX_PROVENANCE_BYTES:
        raise ThsDumpError("THS_DUMP_PROVENANCE_TOO_LARGE")
    return payload
