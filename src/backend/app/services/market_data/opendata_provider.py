"""opendata 进程内异步 provider adapter。

实现 ``MarketDataProvider.fetch``：纯 HTTP REST（自建数据中台），无隔离 SDK
子进程。复用 197 的契约选择、授权与 store/publication 链路；仅在 provider 层
新增 opendata 专属组件（HTTP、信封、错误码、分页）。

- 频率如实阻断：仅 ``1d``；分钟频 ``UNSUPPORTED``（中台分钟线走 Parquet 归档）。
- 鉴权经 ``OpendataCredentials`` 注入（``X-API-Key``），绝不落库明文/日志。
- 分页：``page`` / ``page_size`` 逐页拉取，直到短页或达到保护上限。
- 窗口：中台 REST 为闭区间日期，adapter 按平台半开窗口做客户端过滤。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time as _time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timezone
from email.utils import parsedate_to_datetime
from types import MappingProxyType
from typing import Any
from urllib.parse import quote

import httpx

from app.services.market_data.opendata_contracts import (
    OPENDATA_MAX_PAGE_SIZE,
    OPENDATA_MAX_ROWS,
    OPENDATA_PROVIDER_CONTRACT_REGISTRY,
    OPENDATA_SUPPORTED_FREQUENCIES,
    prepare_opendata_historical_request,
)
from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.market_data.opendata_snapshot_validators import (
    validate_index_coverage_payload,
    validate_index_snapshot_metadata,
    validate_index_snapshot_page,
    validate_index_snapshot_request,
    validate_next_snapshot_cursor,
    validate_stock_daily_snapshot_page,
    validate_stock_daily_snapshot_request,
)
from app.services.market_data.provider_contracts import (
    ProviderContract,
    ProviderContractError,
)
from app.services.market_data.providers import (
    MarketDataProviderRequest,
    ProviderFetchResult,
    ProviderMarketObservation,
)

_UTC = timezone.utc
_MAX_PROVENANCE_BYTES = 10 * 1024 * 1024
_MAX_RESPONSE_BYTES = 32 * 1024 * 1024
_MAX_TOTAL_RESPONSE_BYTES = 64 * 1024 * 1024
_DEFAULT_TOTAL_DEADLINE_SECONDS = 60.0
_DEFAULT_RETRY_BACKOFF_SECONDS = 0.25
_MAX_RETRIES = 2
_MAX_RETRY_DELAY_SECONDS = 2.0
_RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
_PUBLISHED_SNAPSHOT_PAGE_SIZE = 1000
_PUBLISHED_SNAPSHOT_MAX_PAGES = 100
_PUBLISHED_SNAPSHOT_MAX_ROWS = 50_000
_PUBLISHED_SNAPSHOT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES = 64 * 1024 * 1024
_PUBLISHED_SNAPSHOT_DEADLINE_SECONDS = 60.0
_PUBLISHED_STOCK_DAILY_DATASET_ID = "cn-equity-stock-daily"
_PUBLISHED_STOCK_DAILY_PATH = "/stock-daily/records"
_TRADE_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

#: 中台 REST 响应信封的成功标识字段。
_ENVELOPE_SUCCESS_FIELD = "success"
_ENVELOPE_DATA_FIELD = "data"
_ENVELOPE_MESSAGE_FIELD = "message"

# opendata 契约快照（导入时冻结，防运行时替换）。
_OPENDATA_REVIEWED_CONTRACTS: Mapping[tuple[str, str], ProviderContract] = MappingProxyType(
    {
        (contract.provider, contract.route_id): contract
        for contract in OPENDATA_PROVIDER_CONTRACT_REGISTRY.contracts
    }
)


class OpendataProviderError(RuntimeError):
    """opendata adapter 稳定错误码。"""

    def __init__(self, code: str, *, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OpendataPublishedSnapshotResult:
    """One fully paged result tied to a fixed published dataset snapshot."""

    snapshot: Mapping[str, Any]
    coverage: Mapping[str, Any]
    records: tuple[Mapping[str, Any], ...]
    page_count: int


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON object keys at the OpenData v2 trust boundary."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    """Reject non-standard NaN and infinity tokens in API JSON."""
    raise ValueError("non-standard JSON number")


def _reviewed_contract_for_request(request: MarketDataProviderRequest) -> ProviderContract:
    """选择唯一契约，绝不使用同形后备。"""
    if request.route_id is None:
        raise ProviderContractError("PROVIDER_CONTRACT_ROUTE_REQUIRED")
    contract = _OPENDATA_REVIEWED_CONTRACTS.get((request.provider, request.route_id))
    if contract is None:
        if any(route_id == request.route_id for _, route_id in _OPENDATA_REVIEWED_CONTRACTS):
            raise ProviderContractError("PROVIDER_CONTRACT_PROVIDER_MISMATCH")
        raise ProviderContractError("PROVIDER_CONTRACT_UNREGISTERED")
    contract.assert_request_matches(request)
    return contract


def _date_to_utc(value: object) -> datetime:
    """把中台 ``trade_date``（``YYYY-MM-DD``）归一化为交易日 UTC midnight。

    与 AkShare 契约一致：date-only 时间戳代表交易日，``event_at`` 取该日
    ``00:00 UTC``（日历表的 date-only → UTC midnight 口径相同）。
    """
    if not isinstance(value, str) or _TRADE_DATE_PATTERN.fullmatch(value) is None:
        raise OpendataProviderError("OPENDATA_TIMESTAMP_INVALID")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise OpendataProviderError("OPENDATA_TIMESTAMP_INVALID") from exc
    return datetime.combine(parsed, time.min, tzinfo=_UTC)


def _normalize_fields(row: Mapping[str, Any], *, contract: ProviderContract) -> dict[str, Any]:
    """映射已审查的源字段标签到中台字段，保留其它字段原样。"""
    excluded = {*contract.timestamp_columns, *contract.symbol_columns}
    fields: dict[str, Any] = {}
    for source_name, value in row.items():
        if source_name in excluded:
            continue
        normalized_name = contract.normalized_field_name(source_name)
        fields[normalized_name] = value
    return fields


def _normalize_observations(
    contract: ProviderContract,
    request: MarketDataProviderRequest,
    rows: Sequence[Mapping[str, Any]],
    retrieved_at: datetime,
) -> list[ProviderMarketObservation]:
    """把 ``data.rows`` 归一化为 persistence-ready observations。"""
    observations: list[ProviderMarketObservation] = []
    seen_events: set[datetime] = set()
    for row in rows:
        symbol = row.get("symbol")
        if not isinstance(symbol, str):
            raise OpendataProviderError("OPENDATA_RESPONSE_SYMBOL_INVALID")
        if symbol != request.provider_symbol:
            raise OpendataProviderError("OPENDATA_RESPONSE_SYMBOL_MISMATCH")
        event_at = _date_to_utc(row.get("trade_date"))
        if not request.start_at <= event_at < request.end_at:
            if contract.client_filters_window:
                continue
            raise OpendataProviderError("OPENDATA_RESPONSE_OUT_OF_WINDOW")
        if event_at in seen_events:
            raise OpendataProviderError("OPENDATA_RESPONSE_DUPLICATE_EVENT")
        seen_events.add(event_at)
        observations.append(
            ProviderMarketObservation(
                event_at=event_at,
                available_at=retrieved_at,
                fields=_normalize_fields(row, contract=contract),
            )
        )
    return observations


def _encode_json(payload: Any) -> bytes:
    """Serialize canonical JSON bytes used by provenance size accounting."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _monotonic() -> float:
    """Return monotonic time through a small seam for deterministic deadline tests."""
    return _time.monotonic()


def _retry_after_seconds(value: str | None) -> float | None:
    """Parse a Retry-After delay or HTTP date without trusting invalid values."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=_UTC)
            seconds = max(0.0, (retry_at - datetime.now(_UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _raw_payload_shell(
    request: MarketDataProviderRequest, contract: ProviderContract
) -> dict[str, Any]:
    """Return provenance with empty page arrays for incremental size checks."""
    return {
        "request": {**request.dto_payload, "request_id": request.request_id},
        "provider_contract": dict(contract.summary),
        "opendata_pages": [],
        "response_rows": [],
    }


def _page_provenance_metadata(response: Mapping[str, Any]) -> dict[str, Any]:
    """Select the page metadata retained in provider provenance."""
    return {
        "page": response.get("page"),
        "page_size": response.get("page_size"),
        "count": response.get("count"),
        "columns": list(response.get("columns") or ()),
    }


def _build_raw_payload(
    request: MarketDataProviderRequest,
    contract: ProviderContract,
    responses: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """构造 provenance，保留 request_id 与逐页响应（审计链）。"""
    payload = _raw_payload_shell(request, contract)
    payload["opendata_pages"] = [_page_provenance_metadata(response) for response in responses]
    payload["response_rows"] = [list(response.get("rows") or ()) for response in responses]
    encoded = _encode_json(payload)
    if len(encoded) > _MAX_PROVENANCE_BYTES:
        raise OpendataProviderError("OPENDATA_PROVENANCE_TOO_LARGE")
    return payload


class OpendataProvider:
    """进程内异步 opendata adapter，实现 ``MarketDataProvider.fetch``。

    生产构造用 ``from_environment``；测试可注入 httpx 客户端与凭据。
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        credentials: OpendataCredentials | None,
        timeout_seconds: float = 20.0,
        total_deadline_seconds: float = _DEFAULT_TOTAL_DEADLINE_SECONDS,
        max_retries: int = _MAX_RETRIES,
        retry_backoff_seconds: float = _DEFAULT_RETRY_BACKOFF_SECONDS,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        max_total_response_bytes: int = _MAX_TOTAL_RESPONSE_BYTES,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive number")
        if not math.isfinite(total_deadline_seconds) or total_deadline_seconds <= 0:
            raise ValueError("total_deadline_seconds must be a finite positive number")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or not 0 <= max_retries <= _MAX_RETRIES
        ):
            raise ValueError(f"max_retries must be between 0 and {_MAX_RETRIES}")
        if (
            not math.isfinite(retry_backoff_seconds)
            or retry_backoff_seconds < 0
            or retry_backoff_seconds > _MAX_RETRY_DELAY_SECONDS
        ):
            raise ValueError(
                f"retry_backoff_seconds must be between 0 and {_MAX_RETRY_DELAY_SECONDS}"
            )
        self._client = client
        self._credentials = credentials
        self._timeout_seconds = timeout_seconds
        self._total_deadline_seconds = total_deadline_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._max_response_bytes = max_response_bytes
        self._max_total_response_bytes = max_total_response_bytes

    @classmethod
    def from_environment(cls, *, require_config: bool = False) -> OpendataProvider | None:
        """构建环境适配器。

        默认保留旧调用方的 ``None`` 语义。策略选择器在 OpenData-only
        模式下传 ``require_config=True``，即使 Key 缺失也保留 OpenData
        adapter；真正 fetch 时返回明确配置错误，绝不因此切换其他数据源。
        """
        if not isinstance(require_config, bool):
            raise TypeError("require_config must be a bool")
        credentials = OpendataCredentials.from_environment()
        if credentials is None and not require_config:
            return None
        # trust_env=False：直连数据中台，不继承本地 HTTP(S) 代理配置。
        client = httpx.AsyncClient(trust_env=False)
        return cls(client=client, credentials=credentials)

    async def fetch(self, request: MarketDataProviderRequest) -> ProviderFetchResult:
        """取一个精确有界请求，不写存储。"""
        if request.provider != "opendata":
            raise OpendataProviderError("OPENDATA_PROVIDER_MISMATCH")
        if request.frequency not in OPENDATA_SUPPORTED_FREQUENCIES:
            raise OpendataProviderError("OPENDATA_FREQUENCY_UNSUPPORTED")
        if self._credentials is None:
            raise OpendataProviderError("OPENDATA_CREDENTIAL_MISSING")
        try:
            contract = _reviewed_contract_for_request(request)
            params = prepare_opendata_historical_request(contract, request)
        except ProviderContractError as exc:
            raise OpendataProviderError("OPENDATA_CONTRACT_INVALID", detail=exc.code) from exc
        endpoint = next(iter(contract.endpoints))
        responses: list[Mapping[str, Any]] = []
        rows: list[Mapping[str, Any]] = []
        seen_pages: set[bytes] = set()
        total_response_bytes = 0
        provenance_pages = 0
        provenance_bytes = len(_encode_json(_raw_payload_shell(request, contract)))
        if provenance_bytes > _MAX_PROVENANCE_BYTES:
            raise OpendataProviderError("OPENDATA_PROVENANCE_TOO_LARGE")
        deadline = _monotonic() + self._total_deadline_seconds
        page = 1
        while True:
            remaining_response_bytes = self._max_total_response_bytes - total_response_bytes
            if remaining_response_bytes <= 0:
                raise OpendataProviderError("OPENDATA_RESPONSE_TOO_LARGE")
            payload, page_response_bytes = await self._get_page(
                endpoint,
                {**params, "page": page},
                credentials=self._credentials,
                max_bytes=min(self._max_response_bytes, remaining_response_bytes),
                deadline=deadline,
                request_id=request.request_id,
            )
            total_response_bytes += page_response_bytes
            data = payload.get(_ENVELOPE_DATA_FIELD)
            if not isinstance(data, Mapping):
                raise OpendataProviderError("OPENDATA_ENVELOPE_INVALID")
            # AC03: each page must re-declare the adjustment basis the request named.
            if data.get("adjust") != params["adjust"]:
                raise OpendataProviderError("OPENDATA_ADJUSTMENT_BASIS_MISMATCH")
            page_rows = data.get("rows")
            if not isinstance(page_rows, list):
                raise OpendataProviderError("OPENDATA_ROWS_INVALID")

            response_page = data.get("page")
            if isinstance(response_page, bool) or not isinstance(response_page, int):
                raise OpendataProviderError("OPENDATA_PAGE_INVALID")
            if response_page != page:
                raise OpendataProviderError("OPENDATA_PAGE_MISMATCH")

            response_page_size = data.get("page_size")
            if isinstance(response_page_size, bool) or not isinstance(response_page_size, int):
                raise OpendataProviderError("OPENDATA_PAGE_SIZE_INVALID")
            if not 1 <= response_page_size <= OPENDATA_MAX_PAGE_SIZE:
                raise OpendataProviderError("OPENDATA_PAGE_SIZE_INVALID")
            if response_page_size != params["page_size"]:
                raise OpendataProviderError("OPENDATA_PAGE_SIZE_MISMATCH")

            response_count = data.get("count")
            if isinstance(response_count, bool) or not isinstance(response_count, int):
                raise OpendataProviderError("OPENDATA_COUNT_INVALID")
            if not 0 <= response_count <= response_page_size:
                raise OpendataProviderError("OPENDATA_COUNT_INVALID")
            if response_count != len(page_rows):
                raise OpendataProviderError("OPENDATA_COUNT_MISMATCH")

            if not all(isinstance(row, Mapping) for row in page_rows):
                raise OpendataProviderError("OPENDATA_ROW_NOT_MAPPING")

            try:
                page_metadata = _page_provenance_metadata(data)
                page_provenance_bytes = len(_encode_json(page_metadata)) + len(
                    _encode_json(page_rows)
                )
            except (TypeError, ValueError) as exc:
                raise OpendataProviderError(
                    "OPENDATA_RESPONSE_INVALID", detail=exc.__class__.__name__
                ) from exc
            if provenance_pages:
                page_provenance_bytes += 2  # comma in each of the two provenance arrays
            if provenance_bytes + page_provenance_bytes > _MAX_PROVENANCE_BYTES:
                raise OpendataProviderError("OPENDATA_PROVENANCE_TOO_LARGE")

            if page_rows:
                try:
                    canonical_rows = sorted(
                        json.dumps(
                            row,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                        for row in page_rows
                    )
                except (TypeError, ValueError) as exc:
                    raise OpendataProviderError("OPENDATA_ROWS_INVALID") from exc
                page_fingerprint = hashlib.sha256(
                    json.dumps(canonical_rows, ensure_ascii=False, separators=(",", ":")).encode(
                        "utf-8"
                    )
                ).digest()
                if page_fingerprint in seen_pages:
                    raise OpendataProviderError("OPENDATA_RESPONSE_DUPLICATE_PAGE")
                seen_pages.add(page_fingerprint)

            if len(rows) + len(page_rows) > OPENDATA_MAX_ROWS:
                raise OpendataProviderError("OPENDATA_RESPONSE_TOO_LARGE")
            rows.extend(page_rows)
            responses.append(data)
            provenance_bytes += page_provenance_bytes
            provenance_pages += 1
            if len(page_rows) < response_page_size or not page_rows:
                break
            page += 1

        self._remaining_seconds(deadline)
        retrieved_at = datetime.now(_UTC)
        try:
            observations = _normalize_observations(contract, request, rows, retrieved_at)
            raw_payload = _build_raw_payload(request, contract, responses)
        except OpendataProviderError:
            raise
        except Exception as exc:
            raise OpendataProviderError(
                "OPENDATA_RESPONSE_INVALID", detail=exc.__class__.__name__
            ) from exc

        self._remaining_seconds(deadline)
        return ProviderFetchResult(
            provider_id="opendata",
            source_revision="opendata-rest-v1",
            retrieved_at=retrieved_at,
            observations=tuple(observations),
            raw_payload=raw_payload,
            request=request,
            warnings=(("OPENDATA_IDENTITY_SOURCE_RESPONSE_BOUND",) if observations else ()),
        )

    async def fetch_published_index_snapshot(
        self,
        request: MarketDataProviderRequest,
        *,
        dataset_id: str,
    ) -> OpendataPublishedSnapshotResult:
        """Read one allowlisted index dataset through a fixed v2 snapshot.

        Snapshot creation is deliberately sent once because OpenData does not
        support an idempotency key. Coverage is checked against that exact
        publication before any records are fetched, and every records page is
        pinned to the returned ``snapshot_id`` and opaque cursor.
        """
        start_date, end_date = validate_index_snapshot_request(
            request, dataset_id, error_cls=OpendataProviderError
        )
        if self._credentials is None:
            raise OpendataProviderError("OPENDATA_CREDENTIAL_MISSING")

        deadline = _monotonic() + _PUBLISHED_SNAPSHOT_DEADLINE_SECONDS
        total_bytes = 0
        # Check coverage before creating a snapshot: snapshot creation has no
        # idempotency key and would otherwise leave orphan snapshots on a
        # missing grant or UNKNOWN coverage. Pin the resulting snapshot to the
        # exact publication and contract asserted by this response.
        coverage_payload, response_bytes = await self._published_json_request(
            "GET",
            f"/datasets/{quote(dataset_id, safe='')}/coverage",
            params={"start_date": start_date, "end_date": end_date},
            expected_status=200,
            request_id=request.request_id,
            deadline=deadline,
        )
        total_bytes += response_bytes
        publication_id, contract_sha256 = validate_index_coverage_payload(
            coverage_payload,
            dataset_id=dataset_id,
            start_date=start_date,
            end_date=end_date,
            error_cls=OpendataProviderError,
        )
        snapshot_payload, response_bytes = await self._published_json_request(
            "POST",
            "/snapshots",
            body={
                "dataset_id": dataset_id,
                "publication_id": publication_id,
                "start_date": start_date,
                "end_date": end_date,
                "page_size": _PUBLISHED_SNAPSHOT_PAGE_SIZE,
            },
            expected_status=201,
            request_id=request.request_id,
            deadline=deadline,
        )
        total_bytes += response_bytes
        snapshot, snapshot_id, record_count = validate_index_snapshot_metadata(
            snapshot_payload,
            dataset_id=dataset_id,
            publication_id=publication_id,
            contract_sha256=contract_sha256,
            start_date=start_date,
            end_date=end_date,
            page_size=_PUBLISHED_SNAPSHOT_PAGE_SIZE,
            max_rows=_PUBLISHED_SNAPSHOT_MAX_ROWS,
            error_cls=OpendataProviderError,
        )

        records: list[Mapping[str, Any]] = []
        seen_cursors: set[str] = set()
        cursor: str | None = None
        page_count = 0
        while True:
            if page_count >= _PUBLISHED_SNAPSHOT_MAX_PAGES:
                raise OpendataProviderError("OPENDATA_INDEX_SNAPSHOT_LIMIT_EXCEEDED")
            params = {"snapshot_id": snapshot_id}
            if cursor is not None:
                params["cursor"] = cursor
            page_payload, response_bytes = await self._published_json_request(
                "GET",
                f"/datasets/{quote(dataset_id, safe='')}/records",
                params=params,
                expected_status=200,
                request_id=request.request_id,
                deadline=deadline,
                max_response_bytes=min(
                    _PUBLISHED_SNAPSHOT_MAX_RESPONSE_BYTES,
                    _PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES - total_bytes,
                ),
            )
            total_bytes += response_bytes
            page_count += 1
            has_more, next_cursor = validate_index_snapshot_page(
                page_payload,
                snapshot=snapshot,
                record_count=record_count,
                total_bytes=total_bytes,
                records=records,
                page_size=_PUBLISHED_SNAPSHOT_PAGE_SIZE,
                max_rows=_PUBLISHED_SNAPSHOT_MAX_ROWS,
                max_total_bytes=_PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES,
                error_cls=OpendataProviderError,
            )
            if not has_more:
                break
            cursor = validate_next_snapshot_cursor(
                next_cursor=next_cursor,
                cursor=cursor,
                seen_cursors=seen_cursors,
                total_bytes=total_bytes,
                page_count=page_count,
                limit_code="OPENDATA_INDEX_SNAPSHOT_LIMIT_EXCEEDED",
                cursor_code="OPENDATA_INDEX_SNAPSHOT_CURSOR_INVALID",
                max_total_bytes=_PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES,
                max_pages=_PUBLISHED_SNAPSHOT_MAX_PAGES,
                error_cls=OpendataProviderError,
            )

        return OpendataPublishedSnapshotResult(
            snapshot=snapshot,
            coverage=dict(coverage_payload),
            records=tuple(records),
            page_count=page_count,
        )

    async def fetch_published_stock_daily_snapshot(
        self,
        request: MarketDataProviderRequest,
        *,
        publication_id: str,
    ) -> OpendataPublishedSnapshotResult:
        """Read one stock symbol from an explicitly pinned stock-daily publication.

        OpenData's dedicated endpoint creates a snapshot on the first request
        and returns that page. Further pages use only the returned snapshot ID
        and opaque cursor. The endpoint's coverage remains ``unknown`` until
        independent stock-history evidence is available; this method carries
        that value through without treating it as complete.
        """
        if self._credentials is None:
            if not isinstance(request, MarketDataProviderRequest):
                raise OpendataProviderError("OPENDATA_STOCK_DAILY_SNAPSHOT_REQUEST_INVALID")
            raise OpendataProviderError("OPENDATA_CREDENTIAL_MISSING")
        start_date, end_date = validate_stock_daily_snapshot_request(
            request,
            publication_id,
            reviewed_contract_fn=_reviewed_contract_for_request,
            error_cls=OpendataProviderError,
        )

        deadline = _monotonic() + _PUBLISHED_SNAPSHOT_DEADLINE_SECONDS
        total_bytes = 0
        records: list[Mapping[str, Any]] = []
        seen_cursors: set[str] = set()
        cursor: str | None = None
        page_count = 0
        snapshot: dict[str, Any] | None = None
        coverage: dict[str, Any] | None = None
        while True:
            if page_count >= _PUBLISHED_SNAPSHOT_MAX_PAGES:
                raise OpendataProviderError("OPENDATA_STOCK_DAILY_SNAPSHOT_LIMIT_EXCEEDED")
            if page_count == 0:
                params = {
                    "market": request.market,
                    "symbol": request.provider_symbol,
                    "publication_id": publication_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "page_size": str(_PUBLISHED_SNAPSHOT_PAGE_SIZE),
                }
            else:
                if snapshot is None:
                    raise OpendataProviderError("OPENDATA_STOCK_DAILY_SNAPSHOT_PAGE_INVALID")
                params = {
                    "market": request.market,
                    "symbol": request.provider_symbol,
                    "publication_id": publication_id,
                    "snapshot_id": str(snapshot["snapshot_id"]),
                }
                if cursor is not None:
                    params["cursor"] = cursor
            page_payload, response_bytes = await self._published_json_request(
                "GET",
                _PUBLISHED_STOCK_DAILY_PATH,
                params=params,
                expected_status=200,
                request_id=request.request_id,
                deadline=deadline,
                max_response_bytes=min(
                    _PUBLISHED_SNAPSHOT_MAX_RESPONSE_BYTES,
                    _PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES - total_bytes,
                ),
            )
            total_bytes += response_bytes
            page_count += 1
            snapshot, coverage, has_more, next_cursor = validate_stock_daily_snapshot_page(
                page_payload,
                request=request,
                publication_id=publication_id,
                snapshot=snapshot,
                coverage=coverage,
                total_bytes=total_bytes,
                records=records,
                page_size=_PUBLISHED_SNAPSHOT_PAGE_SIZE,
                max_rows=_PUBLISHED_SNAPSHOT_MAX_ROWS,
                max_total_bytes=_PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES,
                error_cls=OpendataProviderError,
            )
            if not has_more:
                break
            cursor = validate_next_snapshot_cursor(
                next_cursor=next_cursor,
                cursor=cursor,
                seen_cursors=seen_cursors,
                total_bytes=total_bytes,
                page_count=page_count,
                limit_code="OPENDATA_STOCK_DAILY_SNAPSHOT_LIMIT_EXCEEDED",
                cursor_code="OPENDATA_STOCK_DAILY_SNAPSHOT_CURSOR_INVALID",
                max_total_bytes=_PUBLISHED_SNAPSHOT_MAX_TOTAL_BYTES,
                max_pages=_PUBLISHED_SNAPSHOT_MAX_PAGES,
                error_cls=OpendataProviderError,
            )

        if snapshot is None or coverage is None:
            raise OpendataProviderError("OPENDATA_STOCK_DAILY_SNAPSHOT_PAGE_INVALID")
        return OpendataPublishedSnapshotResult(
            snapshot=snapshot,
            coverage=coverage,
            records=tuple(records),
            page_count=page_count,
        )

    async def _published_json_request(
        self,
        method: str,
        path: str,
        *,
        request_id: str,
        deadline: float,
        expected_status: int,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        max_response_bytes: int = _PUBLISHED_SNAPSHOT_MAX_RESPONSE_BYTES,
    ) -> tuple[Mapping[str, Any], int]:
        """Make one bounded v2 request without retrying snapshot creation."""
        if self._credentials is None:
            raise OpendataProviderError("OPENDATA_CREDENTIAL_MISSING")
        remaining = self._remaining_seconds(deadline)
        url = f"{self._credentials.base_url}/api/v2{path}"
        headers = {
            "X-API-Key": self._credentials.api_key,
            "X-Request-ID": request_id,
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            status_code, response_body = await asyncio.wait_for(
                self._read_published_attempt(
                    method,
                    url,
                    params=params,
                    body=body,
                    headers=headers,
                    timeout_seconds=min(self._timeout_seconds, remaining),
                    max_response_bytes=min(
                        max_response_bytes, _PUBLISHED_SNAPSHOT_MAX_RESPONSE_BYTES
                    ),
                ),
                timeout=remaining,
            )
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            raise OpendataProviderError("OPENDATA_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise OpendataProviderError(
                "OPENDATA_TRANSPORT_ERROR", detail=exc.__class__.__name__
            ) from exc
        if status_code != expected_status:
            if status_code == 401:
                code = "OPENDATA_UNAUTHORIZED"
            elif status_code == 403:
                code = "OPENDATA_FORBIDDEN"
            elif status_code == 410:
                code = "OPENDATA_SNAPSHOT_EXPIRED"
            elif status_code == 429:
                code = "OPENDATA_RATE_LIMITED"
            else:
                code = "OPENDATA_HTTP_ERROR"
            raise OpendataProviderError(code, detail=str(status_code))
        try:
            payload = json.loads(
                response_body,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise OpendataProviderError("OPENDATA_V2_RESPONSE_INVALID_JSON") from exc
        if not isinstance(payload, Mapping):
            raise OpendataProviderError("OPENDATA_V2_RESPONSE_INVALID")
        return payload, len(response_body)

    async def _read_published_attempt(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None,
        body: Mapping[str, Any] | None,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> tuple[int, bytes]:
        """Stream one v2 response under the caller's per-request size cap."""
        body_bytes = bytearray()
        async with self._client.stream(
            method,
            url,
            params=dict(params) if params is not None else None,
            json=dict(body) if body is not None else None,
            headers=dict(headers),
            timeout=timeout_seconds,
        ) as response:
            if response.status_code != 200 and response.status_code != 201:
                return response.status_code, b""
            content_type = response.headers.get("content-type", "")
            media_type = content_type.split(";", 1)[0].strip().casefold()
            if media_type != "application/json" and not media_type.endswith("+json"):
                raise OpendataProviderError("OPENDATA_V2_RESPONSE_CONTENT_TYPE_INVALID")
            declared_length = response.headers.get("content-length")
            if (
                declared_length is not None
                and declared_length.isascii()
                and declared_length.isdecimal()
                and int(declared_length) > max_response_bytes
            ):
                raise OpendataProviderError("OPENDATA_RESPONSE_TOO_LARGE")
            async for chunk in response.aiter_bytes():
                if len(body_bytes) + len(chunk) > max_response_bytes:
                    raise OpendataProviderError("OPENDATA_RESPONSE_TOO_LARGE")
                body_bytes.extend(chunk)
            return response.status_code, bytes(body_bytes)

    async def _get_page(
        self,
        endpoint: str,
        params: Mapping[str, Any],
        *,
        credentials: OpendataCredentials,
        max_bytes: int | None = None,
        deadline: float,
        request_id: str,
    ) -> tuple[Mapping[str, Any], int]:
        """流式读取一页，受 fetch 总 deadline 与有限重试共同约束。"""
        url = f"{credentials.base_url}{endpoint}"
        response_limit = self._max_response_bytes if max_bytes is None else max_bytes
        for retry_number in range(self._max_retries + 1):
            remaining = self._remaining_seconds(deadline)
            try:
                status_code, retry_after, body = await asyncio.wait_for(
                    self._read_page_attempt(
                        url,
                        params,
                        api_key=credentials.api_key,
                        request_id=request_id,
                        response_limit=response_limit,
                        timeout_seconds=min(self._timeout_seconds, remaining),
                    ),
                    timeout=remaining,
                )
            except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
                if retry_number < self._max_retries and await self._wait_for_retry(
                    retry_number, deadline=deadline
                ):
                    continue
                raise OpendataProviderError("OPENDATA_TIMEOUT") from exc
            except OpendataProviderError:
                raise
            except httpx.HTTPError as exc:
                if retry_number < self._max_retries and await self._wait_for_retry(
                    retry_number, deadline=deadline
                ):
                    continue
                raise OpendataProviderError(
                    "OPENDATA_TRANSPORT_ERROR", detail=exc.__class__.__name__
                ) from exc

            if status_code >= 400:
                if (
                    status_code in _RETRYABLE_HTTP_STATUSES
                    and retry_number < self._max_retries
                    and await self._wait_for_retry(
                        retry_number,
                        deadline=deadline,
                        retry_after=retry_after,
                    )
                ):
                    continue
                if status_code == 401:
                    raise OpendataProviderError("OPENDATA_UNAUTHORIZED")
                if status_code == 403:
                    raise OpendataProviderError("OPENDATA_FORBIDDEN")
                if status_code == 429:
                    raise OpendataProviderError("OPENDATA_RATE_LIMITED")
                raise OpendataProviderError("OPENDATA_HTTP_ERROR", detail=str(status_code))
            break

        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise OpendataProviderError("OPENDATA_ENVELOPE_INVALID_JSON") from exc
        if not isinstance(payload, Mapping):
            raise OpendataProviderError("OPENDATA_ENVELOPE_NOT_MAPPING")
        if payload.get(_ENVELOPE_SUCCESS_FIELD) is not True:
            message = payload.get(_ENVELOPE_MESSAGE_FIELD)
            raise OpendataProviderError(
                "OPENDATA_ENVELOPE_FAILURE",
                detail=message if isinstance(message, str) else None,
            )
        return payload, len(body)

    async def _read_page_attempt(
        self,
        url: str,
        params: Mapping[str, Any],
        *,
        api_key: str,
        request_id: str,
        response_limit: int,
        timeout_seconds: float,
    ) -> tuple[int, str | None, bytes]:
        """Read one response body; the caller applies a hard wall-clock deadline."""
        body = bytearray()
        async with self._client.stream(
            "GET",
            url,
            params=dict(params),
            headers={
                "X-API-Key": api_key,
                "X-Request-ID": request_id,
            },
            timeout=timeout_seconds,
        ) as response:
            if response.status_code >= 400:
                return response.status_code, response.headers.get("Retry-After"), b""
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > response_limit:
                    raise OpendataProviderError("OPENDATA_RESPONSE_TOO_LARGE")
                body.extend(chunk)
        return response.status_code, None, bytes(body)

    @staticmethod
    def _remaining_seconds(deadline: float) -> float:
        remaining = deadline - _monotonic()
        if remaining <= 0:
            raise OpendataProviderError("OPENDATA_TIMEOUT", detail="total deadline exceeded")
        return remaining

    def _retry_delay(self, retry_number: int, retry_after: str | None) -> float | None:
        """Return a bounded delay, declining excessive upstream Retry-After values."""
        requested_delay = _retry_after_seconds(retry_after)
        if requested_delay is not None:
            if requested_delay > _MAX_RETRY_DELAY_SECONDS:
                return None
            return requested_delay
        return min(
            self._retry_backoff_seconds * (2**retry_number),
            _MAX_RETRY_DELAY_SECONDS,
        )

    async def _wait_for_retry(
        self,
        retry_number: int,
        *,
        deadline: float,
        retry_after: str | None = None,
    ) -> bool:
        delay = self._retry_delay(retry_number, retry_after)
        if delay is None:
            return False
        remaining = self._remaining_seconds(deadline)
        if delay >= remaining:
            return False
        try:
            await asyncio.wait_for(asyncio.sleep(delay), timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise OpendataProviderError(
                "OPENDATA_TIMEOUT", detail="total deadline exceeded"
            ) from exc
        self._remaining_seconds(deadline)
        return True


__all__ = ["OpendataProvider", "OpendataProviderError"]
