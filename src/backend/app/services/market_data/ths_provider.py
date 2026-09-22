"""THS 进程内异步 provider adapter。

实现 ``MarketDataProvider.fetch``：纯 HTTP REST，无隔离 SDK 子进程。
复用 197 的契约选择、授权与 store/publication 链路；仅在 provider 层新增
THS 专属组件（HTTP、信封、错误码、限流）。

- 历史 K 线窗口跨度 ≤ 10 年：超限时在 adapter 内按 10 年切块逐块请求再合并。
- 频率如实阻断：仅 ``1d``；分钟频 ``UNSUPPORTED``。
- 鉴权经 ``ThsCredentials`` 注入，绝不落库明文/日志。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, time, timezone
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.services.market_data.provider_contracts import (
    ProviderContract,
    ProviderContractError,
)
from app.services.market_data.providers import (
    MarketDataProviderRequest,
    ProviderFetchResult,
    ProviderMarketObservation,
)
from app.services.market_data.ths_contracts import (
    THS_PROVIDER_CONTRACT_REGISTRY,
    THS_SUPPORTED_INTERVALS,
    prepare_ths_historical_request,
    split_window_into_chunks,
)
from app.services.market_data.ths_credentials import ThsCredentials
from app.services.market_data.ths_envelope import ThsEnvelope, ThsEnvelopeError, parse_ths_envelope
from app.services.market_data.ths_errors import ThsApiError
from app.services.market_data.ths_http import ThsHttpClient, ThsHttpError, ThsHttpResponse
from app.services.market_data.ths_rate_limiter import ThsRateLimiter, ThsRateLimitError

_UTC = timezone.utc
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_PROVENANCE_BYTES = 10 * 1024 * 1024

# THS 契约快照（导入时冻结，防运行时替换）。
_THS_REVIEWED_CONTRACTS: Mapping[tuple[str, str], ProviderContract] = MappingProxyType(
    {
        (contract.provider, contract.route_id): contract
        for contract in THS_PROVIDER_CONTRACT_REGISTRY.contracts
    }
)


class ThsProviderError(RuntimeError):
    """THS adapter 稳定错误码。"""

    def __init__(self, code: str, *, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


def _reviewed_contract_for_request(request: MarketDataProviderRequest) -> ProviderContract:
    """选择唯一契约，绝不使用同形后备。"""
    if request.route_id is None:
        raise ProviderContractError("PROVIDER_CONTRACT_ROUTE_REQUIRED")
    contract = _THS_REVIEWED_CONTRACTS.get((request.provider, request.route_id))
    if contract is None:
        if any(route_id == request.route_id for _, route_id in _THS_REVIEWED_CONTRACTS):
            raise ProviderContractError("PROVIDER_CONTRACT_PROVIDER_MISMATCH")
        raise ProviderContractError("PROVIDER_CONTRACT_UNREGISTERED")
    contract.assert_request_matches(request)
    return contract


def _millis_to_utc(value: object) -> datetime:
    """把 THS 交易日毫秒戳归一化为该交易日期的 UTC midnight。

    THS 的 ``date_ms`` 是「交易日 T 的 Asia/Shanghai 零点」（实测确认：
    2026-09-07 ~ 2026-09-18 的工作日序列，``date_ms`` 上海日期即交易日）。
    中台的日线 ``event_at`` 约定为「交易日期的 UTC midnight」（与 calendar 的
    date-only → UTC midnight 对齐），故取 ``date_ms`` 的上海日期再转 UTC midnight。
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise ThsProviderError("THS_TIMESTAMP_INVALID")
    instant = datetime.fromtimestamp(value / 1000.0, tz=_UTC)
    trading_date = instant.astimezone(_SHANGHAI).date()
    return datetime.combine(trading_date, time.min, tzinfo=_UTC)


def _normalize_observations(
    contract: ProviderContract,
    request: MarketDataProviderRequest,
    envelopes: Sequence[ThsEnvelope],
    retrieved_at: datetime,
) -> list[ProviderMarketObservation]:
    """把信封 ``data.item`` 归一化为 persistence-ready observations。

    THS 历史 K 线字段：``date_ms`` + open/high/low/close_price + volume/turnover。
    字段经 ``contract.response_field_aliases`` 映射到中台语义（open/close/...）。
    """
    observations: list[ProviderMarketObservation] = []
    seen_events: set[datetime] = set()
    for envelope in envelopes:
        for item in envelope.data_item:
            if not isinstance(item, Mapping):
                raise ThsProviderError("THS_ITEM_NOT_MAPPING")
            row = dict(item)
            event_at = _parse_event_at(row)
            if not request.start_at <= event_at < request.end_at:
                if contract.client_filters_window:
                    continue
                raise ThsProviderError("THS_RESPONSE_OUT_OF_WINDOW")
            if event_at in seen_events:
                raise ThsProviderError("THS_RESPONSE_DUPLICATE_EVENT")
            seen_events.add(event_at)
            fields = _normalize_fields(row, contract=contract)
            observations.append(
                ProviderMarketObservation(
                    event_at=event_at,
                    available_at=retrieved_at,
                    fields=fields,
                )
            )
    return observations


def _parse_event_at(row: Mapping[str, Any]) -> datetime:
    """从行中取 ``date_ms``（唯一时间戳列）并归一化。"""
    value = row.get("date_ms")
    if value is None:
        raise ThsProviderError("THS_TIMESTAMP_MISSING")
    return _millis_to_utc(value)


def _normalize_fields(row: Mapping[str, Any], *, contract: ProviderContract) -> dict[str, Any]:
    """映射已审查的源字段标签到中台字段，保留其它字段原样。"""
    excluded = {*contract.timestamp_columns, *contract.symbol_columns, "date_ms"}
    fields: dict[str, Any] = {}
    for source_name, value in row.items():
        if source_name in excluded:
            continue
        normalized_name = contract.normalized_field_name(source_name)
        fields[normalized_name] = value
    return fields


def _build_raw_payload(
    request: MarketDataProviderRequest,
    contract: ProviderContract,
    envelopes: Sequence[ThsEnvelope],
) -> dict[str, Any]:
    """构造 provenance，保留 request_id 与信封 request_id（AC-25 审计链）。"""
    payload: dict[str, Any] = {
        "request": {**request.dto_payload, "request_id": request.request_id},
        "provider_contract": dict(contract.summary),
        "ths_request_ids": [envelope.request_id for envelope in envelopes],
        "response_items": [list(envelope.data_item) for envelope in envelopes],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    if len(encoded) > _MAX_PROVENANCE_BYTES:
        raise ThsProviderError("THS_PROVENANCE_TOO_LARGE")
    return payload


class ThsProvider:
    """进程内异步 THS adapter，实现 ``MarketDataProvider.fetch``。

    生产构造用 ``from_environment``；测试可注入 httpx 客户端与凭据。
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        credentials: ThsCredentials,
        rate_limiter: ThsRateLimiter,
        timeout_seconds: float = 20.0,
        max_response_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        self._http = ThsHttpClient(
            client=client,
            credentials=credentials,
            rate_limiter=rate_limiter,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
        )
        self._rate_limiter = rate_limiter

    @classmethod
    def from_environment(cls) -> ThsProvider | None:
        """从环境变量构建；未配置 Key 返回 ``None``（上层判失败关闭）。"""
        credentials = ThsCredentials.from_environment()
        if credentials is None:
            return None
        # trust_env=False：THS 直连目标域名，不继承本地 HTTP(S) 代理配置，
        # 避免代理劫持导致 Connection refused。
        client = httpx.AsyncClient(trust_env=False)
        rate_limiter = ThsRateLimiter()
        return cls(client=client, credentials=credentials, rate_limiter=rate_limiter)

    async def fetch(self, request: MarketDataProviderRequest) -> ProviderFetchResult:
        """取一个精确有界请求，不写存储。"""
        if request.provider != "ths":
            raise ThsProviderError("THS_PROVIDER_MISMATCH")
        # 频率如实阻断：仅 1d。前置检查，避免被契约层吞为 THS_CONTRACT_INVALID。
        if request.frequency not in THS_SUPPORTED_INTERVALS:
            raise ThsProviderError("THS_FREQUENCY_UNSUPPORTED")
        try:
            contract = _reviewed_contract_for_request(request)
        except ProviderContractError as exc:
            raise ThsProviderError("THS_CONTRACT_INVALID", detail=exc.code) from exc

        try:
            # 窗口切块：每块 ≤ 10 年（闭区间）。开放式窗口在上层已解析为具体窗口。
            chunks = split_window_into_chunks(request.start_at, request.end_at)
            envelopes: list[ThsEnvelope] = []
            endpoint = next(iter(contract.endpoints))
            for chunk_start, chunk_end in chunks:
                chunk_request = _chunk_request(request, chunk_start, chunk_end)
                call_kwargs = prepare_ths_historical_request(contract, chunk_request)
                response = await self._get(endpoint, call_kwargs)
                envelopes.append(self._parse_response(response))
        except ThsRateLimitError as exc:
            raise ThsProviderError("THS_RATE_LIMITED", detail=exc.detail) from exc
        except ThsHttpError as exc:
            raise ThsProviderError(exc.code, detail=exc.detail) from exc
        except ThsApiError as exc:
            raise ThsProviderError(exc.code, detail=exc.message) from exc
        except ThsEnvelopeError as exc:
            raise ThsProviderError(exc.code, detail=exc.detail) from exc

        retrieved_at = datetime.now(_UTC)
        try:
            observations = _normalize_observations(contract, request, envelopes, retrieved_at)
            raw_payload = _build_raw_payload(request, contract, envelopes)
        except ThsProviderError:
            raise
        except Exception as exc:
            raise ThsProviderError("THS_RESPONSE_INVALID", detail=exc.__class__.__name__) from exc

        return ProviderFetchResult(
            provider_id="ths",
            source_revision="ths-rest-v1",
            retrieved_at=retrieved_at,
            observations=tuple(observations),
            raw_payload=raw_payload,
            request=request,
            warnings=(("THS_IDENTITY_SOURCE_REQUEST_BOUND",) if observations else ()),
        )

    async def _get(self, endpoint: str, params: Mapping[str, Any]) -> ThsHttpResponse:
        """调用 GET 并记录限流/成功到限流器。"""
        try:
            response = await self._http.get(endpoint, params=params)
        except ThsRateLimitError:
            raise
        if response.status_code == 429:
            self._rate_limiter.record_rate_limit(retry_after_seconds=response.retry_after_seconds)
            raise ThsApiError(
                "THS_RATE_LIMITED",
                request_id=None,
                message="rate limited",
            )
        return response

    def _parse_response(self, response: ThsHttpResponse) -> ThsEnvelope:
        """解析信封，业务错误码/429 映射为结构化错误并同步限流器。"""
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ThsEnvelopeError("THS_ENVELOPE_INVALID_JSON") from exc
        if not isinstance(payload, Mapping):
            raise ThsEnvelopeError("THS_ENVELOPE_NOT_MAPPING")
        code = payload.get("code")
        if isinstance(code, int) and not isinstance(code, bool) and code == 4001:
            self._rate_limiter.record_rate_limit(retry_after_seconds=None)
            raise ThsApiError(
                "THS_RATE_LIMITED", ths_code=4001, request_id=payload.get("request_id")
            )
        return parse_ths_envelope(payload, http_status=response.status_code)


def _chunk_request(
    request: MarketDataProviderRequest,
    chunk_start: datetime,
    chunk_end: datetime,
) -> MarketDataProviderRequest:
    """构造窗口切块后的子请求（仅替换 start_at/end_at）。"""
    return MarketDataProviderRequest(
        query_fingerprint=request.query_fingerprint,
        canonical_id=request.canonical_id,
        asset_type=request.asset_type,
        provider_symbol=request.provider_symbol,
        market=request.market,
        data_kind=request.data_kind,
        frequency=request.frequency,
        start_at=chunk_start,
        end_at=chunk_end,
        required_fields=request.required_fields,
        provider=request.provider,
        adjustment=request.adjustment,
        price_basis=request.price_basis,
        currency=request.currency,
        unit=request.unit,
        source_policy_id=request.source_policy_id,
        route_id=request.route_id,
        family_id=request.family_id,
        family_contract_version=request.family_contract_version,
        provider_endpoint=request.provider_endpoint,
        product_type=request.product_type,
        fund_identity_kind=request.fund_identity_kind,
        policy_descriptor_hash=request.policy_descriptor_hash,
        access_grant_descriptor_hash=request.access_grant_descriptor_hash,
    )
