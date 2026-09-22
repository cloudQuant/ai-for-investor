"""THS reference 数据域的请求构造与响应归一化（财务/除复权/日历/检索/指数）。

这些数据域超出 197 的 21 页面主题，作为 ``reference_series`` / ``catalog_table``
数据集登记（见 DATA_SCOPE 第 3 节），不新增 provider route 契约、不强行塞进
OHLCV bars。本模块提供确定性的请求构造与响应归一化纯函数：

- 财务多期序列：保留 ``period``/``fiscal_period`` 维度，``null`` 透传不补零。
- 除复权事件流：``ex_date_ms`` 时间语义正确，按 ``ex_date_ms`` 降序，事件类型
  由 ``dividend_per_share``/``per_share_bonus`` 隐式区分。
- 交易日历：``date_ms`` + ``date``（``yyyyMMdd``）双字段。
- 标的检索/列表：中文名解析，``thscode`` 完整。

真实 HTTP 取数与落库（AC-18，G2/G3）由 T6 在获准真实 Key 下执行；本模块的
纯变换逻辑用 fixture 覆盖 AC-11/12/13（G1）。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.market_data.ths_envelope import ThsEnvelope

_UTC = timezone.utc

# THS reference 端点（路径以官方 llms-full.txt 实测为准，修正 RESEARCH 初稿）。
THS_FINANCIALS_INCOME_ENDPOINT = "/api/a-share/financials/income-statements"
THS_FINANCIALS_BALANCE_ENDPOINT = "/api/a-share/financials/balance-sheets"
THS_FINANCIALS_CASHFLOW_ENDPOINT = "/api/a-share/financials/cash-flow-statements"
THS_FINANCIALS_INDICATORS_ENDPOINT = "/api/a-share/financials/indicators"
THS_ADJUSTMENT_FACTORS_ENDPOINT = "/api/a-share/corporate-actions/adjustment-factors"
THS_CALENDAR_ENDPOINT = "/api/a-share/calendar/trading-days"
THS_TICKERS_SEARCH_ENDPOINT = "/api/meta/tickers/search"
THS_TICKERS_LIST_ENDPOINT = "/api/meta/tickers/list"
THS_INDEX_LIST_ENDPOINT = "/api/a-share-index/catalog/ths-index-list"
THS_INDEX_CONSTITUENTS_ENDPOINT = "/api/a-share-index/constituents/ths-stock-list"

# 财务接口共有响应元数据（多期序列保留这些维度）。
FINANCIALS_META_FIELDS = (
    "thscode",
    "ticker",
    "period",
    "fiscal_year",
    "fiscal_period",
    "report_date_ms",
    "period_end_ms",
    "currency",
)


class ThsReferenceError(RuntimeError):
    """THS reference 数据域归一化失败。"""

    def __init__(self, code: str, *, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


def _millis_to_utc(value: object) -> datetime:
    """校验 THS 毫秒戳合法并返回 UTC aware datetime（仅用于格式校验，返回值弃用）。"""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ThsReferenceError("THS_TIMESTAMP_INVALID")
    return datetime.fromtimestamp(value / 1000.0, tz=_UTC)


def build_financials_request(
    *,
    thscode: str,
    period: str = "annual",
    start_ms: int | None = None,
    end_ms: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """构造财务接口请求（最近 N 期或时间区间二选一）。

    取数模式二选一（互斥，见 RESEARCH 5.4）：
    - 最近 N 期：不传 start/end，返回最近 limit 期（默认 4，[1,20]）。
    - 时间区间：同时传 start+end（毫秒戳，闭区间，跨度 ≤ 10 年）。
    同时传 start/end 与 limit 或半开区间 → code=1004（应在调用前避免）。
    """
    if not isinstance(thscode, str) or not thscode.strip():
        raise ThsReferenceError("THS_SYMBOL_INVALID")
    params: dict[str, Any] = {"thscode": thscode.strip(), "period": period}
    if (start_ms is None) != (end_ms is None):
        raise ThsReferenceError("THS_FINANCIALS_WINDOW_HALF_OPEN")
    if start_ms is not None and end_ms is not None:
        if limit is not None:
            raise ThsReferenceError("THS_FINANCIALS_WINDOW_AND_LIMIT_CONFLICT")
        params["start"] = start_ms
        params["end"] = end_ms
    elif limit is not None:
        if not 1 <= limit <= 20:
            raise ThsReferenceError("THS_FINANCIALS_LIMIT_OUT_OF_RANGE")
        params["limit"] = limit
    return params


def normalize_financials(envelope: ThsEnvelope) -> tuple[dict[str, Any], ...]:
    """归一化财务多期序列：保留维度字段，``null`` 透传不补零。"""
    rows: list[dict[str, Any]] = []
    for item in envelope.data_item:
        if not isinstance(item, Mapping):
            raise ThsReferenceError("THS_ITEM_NOT_MAPPING")
        row: dict[str, Any] = {}
        for field in FINANCIALS_META_FIELDS:
            if field in item:
                row[field] = item[field]
        # 其余字段（金额、指标）原样透传，null 保留。
        for key, value in item.items():
            if key not in FINANCIALS_META_FIELDS:
                row[key] = value
        rows.append(row)
    return tuple(rows)


def build_adjustment_factors_request(
    *,
    thscode: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, Any]:
    """构造除复权请求（``from``/``to`` 为 ``YYYY-MM-DD``，可选）。"""
    if not isinstance(thscode, str) or not thscode.strip():
        raise ThsReferenceError("THS_SYMBOL_INVALID")
    params: dict[str, Any] = {"thscode": thscode.strip()}
    if from_date is not None:
        params["from"] = from_date
    if to_date is not None:
        params["to"] = to_date
    return params


def normalize_adjustment_factors(envelope: ThsEnvelope) -> tuple[dict[str, Any], ...]:
    """归一化除复权事件流：按 ``ex_date_ms`` 降序，事件类型隐式区分。

    THS 不返回 ``event_type``，事件类型由 ``dividend_per_share`` 与
    ``per_share_bonus`` 隐式区分（保留该语义，不伪造 event_type）。
    """
    rows: list[dict[str, Any]] = []
    for item in envelope.data_item:
        if not isinstance(item, Mapping):
            raise ThsReferenceError("THS_ITEM_NOT_MAPPING")
        if "ex_date_ms" not in item:
            raise ThsReferenceError("THS_ADJUSTMENT_EX_DATE_MISSING")
        # 校验时间语义，但不改值（保留毫秒戳语义）。
        _millis_to_utc(item["ex_date_ms"])
        rows.append(dict(item))
    rows.sort(key=lambda row: row["ex_date_ms"], reverse=True)
    return tuple(rows)


def normalize_calendar(envelope: ThsEnvelope) -> tuple[dict[str, Any], ...]:
    """归一化交易日历：``date_ms`` + ``date``（``yyyyMMdd``）双字段。"""
    rows: list[dict[str, Any]] = []
    for item in envelope.data_item:
        if not isinstance(item, Mapping):
            raise ThsReferenceError("THS_ITEM_NOT_MAPPING")
        if "date_ms" not in item or "date" not in item:
            raise ThsReferenceError("THS_CALENDAR_FIELD_MISSING")
        _millis_to_utc(item["date_ms"])
        date_value = item["date"]
        if not isinstance(date_value, str) or len(date_value) != 8 or not date_value.isdigit():
            raise ThsReferenceError("THS_CALENDAR_DATE_INVALID")
        rows.append({"date_ms": item["date_ms"], "date": date_value})
    rows.sort(key=lambda row: row["date_ms"])
    return tuple(rows)


def ths_calendar_to_manifest_payload(
    calendar_rows: tuple[Mapping[str, Any], ...],
    *,
    source_registry_id: str,
    calendar_code: str,
    calendar_version: str,
    approval_reference: str,
    evidence_uri: str,
    evidence_content_hash: str,
    coverage_data_kind: str = "bars",
    coverage_frequency: str = "1d",
) -> dict[str, Any]:
    """把 THS 交易日历（``normalize_calendar`` 输出）转为 CalendarImporter manifest。

    THS 日历的 ``date_ms`` 即交易日本身的 Asia/Shanghai 零点（与日线
    ``date_ms`` 的 T+1 语义不同），``date``（``yyyyMMdd``）为交易日。
    每个交易日生成一个 ``session`` 事件，``event_start/end`` 为该交易日的
    UTC midnight 半开窗口（与中台日线 ``event_at`` 约定对齐）。
    """
    if not calendar_rows:
        raise ThsReferenceError("THS_CALENDAR_EMPTY")
    events: list[dict[str, Any]] = []
    first_day = last_day = ""
    for row in calendar_rows:
        yyyymmdd = str(row["date"])
        trading_date = f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
        if not first_day:
            first_day = trading_date
        last_day = trading_date
        day_start = datetime.fromisoformat(f"{trading_date}T00:00:00+00:00")
        # CalendarImporter 要求 event_end 严格小于 coverage_end；沿用 197 的
        # 微秒级收尾（event_end = day_end - 1µs）。
        day_end = day_start + timedelta(days=1) - timedelta(microseconds=1)
        events.append(
            {
                "trading_date": trading_date,
                "event_type": "session",
                "session_code": "daily-bar-close",
                "is_trading_day": True,
                "event_start": day_start.isoformat(),
                "event_end": day_end.isoformat(),
                "coverage": {"data_kind": coverage_data_kind, "frequency": coverage_frequency},
                "event_payload": {"provider_observation_key": "daily-close"},
            }
        )
    coverage_end_exclusive = (
        datetime.fromisoformat(f"{last_day}T00:00:00+00:00") + timedelta(days=1)
    ).isoformat()
    return {
        "manifest_version": "market-data-calendar-v1",
        "approval_reference": approval_reference,
        "evidence_uri": evidence_uri,
        "evidence_content_hash": evidence_content_hash,
        "source_registry_id": source_registry_id,
        "calendar_code": calendar_code,
        "calendar_version": calendar_version,
        "timezone_name": "Asia/Shanghai",
        "coverage_start_at": f"{first_day}T00:00:00+00:00",
        "coverage_end_at": coverage_end_exclusive,
        "events": events,
    }


def build_tickers_search_request(
    *,
    q: str,
    exchange: str | None = None,
    asset_type: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """构造标的检索请求（``q`` 必填，``limit`` 默认 10 最大 50）。"""
    if not isinstance(q, str) or not q.strip():
        raise ThsReferenceError("THS_SEARCH_QUERY_INVALID")
    if limit > 50 or limit < 1:
        raise ThsReferenceError("THS_SEARCH_LIMIT_OUT_OF_RANGE")
    params: dict[str, Any] = {"q": q.strip(), "limit": limit}
    if exchange is not None:
        params["exchange"] = exchange
    if asset_type is not None:
        params["asset_type"] = asset_type
    return params


def normalize_tickers(envelope: ThsEnvelope) -> tuple[dict[str, Any], ...]:
    """归一化标的检索/列表：``thscode`` 完整，``name`` 为中文名（可为 None）。"""
    rows: list[dict[str, Any]] = []
    for item in envelope.data_item:
        if not isinstance(item, Mapping):
            raise ThsReferenceError("THS_ITEM_NOT_MAPPING")
        if "thscode" not in item:
            raise ThsReferenceError("THS_TICKER_THSCODE_MISSING")
        rows.append(dict(item))
    return tuple(rows)


def build_tickers_list_request(
    *,
    asset_type: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> dict[str, Any]:
    """构造标的列表请求（``limit`` 默认 1000 最大 10000）。"""
    if limit > 10000 or limit < 1:
        raise ThsReferenceError("THS_LIST_LIMIT_OUT_OF_RANGE")
    if offset < 0:
        raise ThsReferenceError("THS_LIST_OFFSET_INVALID")
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if asset_type is not None:
        params["asset_type"] = asset_type
    return params


def normalize_index_constituents(envelope: ThsEnvelope) -> tuple[dict[str, Any], ...]:
    """归一化指数列表与成分股（catalog_table）。"""
    rows: list[dict[str, Any]] = []
    for item in envelope.data_item:
        if not isinstance(item, Mapping):
            raise ThsReferenceError("THS_ITEM_NOT_MAPPING")
        rows.append(dict(item))
    return tuple(rows)


def build_index_list_request(*, tag: str = "cn_concept") -> dict[str, Any]:
    """构造同花顺指数列表请求（``tag`` 单值白名单，默认 cn_concept）。"""
    allowed_tags = {"cn_concept", "region", "tszs", "industry"}
    if tag not in allowed_tags:
        raise ThsReferenceError("THS_INDEX_TAG_INVALID")
    return {"tag": tag}


def build_index_constituents_request(*, thscode: str) -> dict[str, Any]:
    """构造指数成分股请求（``thscode`` 单指数，不接受逗号）。"""
    if not isinstance(thscode, str) or not thscode.strip():
        raise ThsReferenceError("THS_SYMBOL_INVALID")
    return {"thscode": thscode.strip().upper()}
