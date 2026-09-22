"""THS ``ApiResponse`` 统一信封的解析与归一化。

THS API 所有业务结果（含业务错误）通常返回 HTTP 200，业务结果经信封
``code`` 表达；触发限流时可能返回 HTTP 429。客户端须同时检查 HTTP 状态码
与信封 ``code``。

信封结构（见 RESEARCH 第 2 节）：:

    {
      "code": 0,
      "message": "success",
      "request_id": "a1b2c3d4e5f6789012345678abcdef01",
      "data": {"timestamp": 1716105600000, "item": []}
    }

``data`` 错误时可能为 ``null``。``data.item`` 为业务数据列表。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.market_data.ths_errors import ThsApiError, map_ths_error_code

# 信封顶层必需字段。
_ENVELOPE_KEYS = frozenset({"code", "message", "request_id"})


class ThsEnvelopeError(RuntimeError):
    """信封解析失败（非 THS 业务错误，而是响应结构不符契约）。"""

    def __init__(self, code: str, *, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ThsEnvelope:
    """归一化后的 THS 成功信封。

    ``data_item`` 为 ``data.item`` 列表（可能为空）；``data_timestamp_ms`` 为
    ``data.timestamp`` 毫秒戳（可能为 ``None``）。``request_id`` 进入来源证据，
    可用于审计链路检索（AC-25）。
    """

    code: int
    message: str
    request_id: str
    data_item: tuple[Any, ...]
    data_timestamp_ms: int | None
    raw: Mapping[str, Any]

    @property
    def item_count(self) -> int:
        """``data.item`` 的条目数。"""
        return len(self.data_item)


def parse_ths_envelope(
    payload: Mapping[str, Any],
    *,
    http_status: int = 200,
    response_headers: Mapping[str, str] | None = None,
) -> ThsEnvelope:
    """解析并归一化 THS 信封，失败时抛出结构化错误。

    ``http_status`` 供调用方传入真实 HTTP 状态码：429 无论信封如何都按限流
    处理（由调用方在更上层依据状态码先行拦截，本函数仅在此兜底校验）。
    ``response_headers`` 仅用于观测（如 ``Retry-After``），不参与归一化决策。
    """
    if not isinstance(payload, Mapping):
        raise ThsEnvelopeError("THS_ENVELOPE_NOT_MAPPING")

    # 顶层 code 为必填整数。
    code = payload.get("code")
    if not isinstance(code, int) or isinstance(code, bool):
        raise ThsEnvelopeError("THS_ENVELOPE_CODE_INVALID")

    message = payload.get("message")
    if message is not None and not isinstance(message, str):
        raise ThsEnvelopeError("THS_ENVELOPE_MESSAGE_INVALID")

    request_id = payload.get("request_id")
    if request_id is not None and not isinstance(request_id, str):
        raise ThsEnvelopeError("THS_ENVELOPE_REQUEST_ID_INVALID")

    # 业务错误：映射为结构化错误。HTTP 429 无论 code 如何都按限流处理。
    if http_status == 429 or code in _rate_limit_codes():
        raise ThsApiError(
            "THS_RATE_LIMITED",
            ths_code=code if code != 0 else None,
            request_id=request_id,
            message=message,
        )

    if code != 0:
        raise ThsApiError(
            map_ths_error_code(code),
            ths_code=code,
            request_id=request_id,
            message=message,
        )

    data = payload.get("data")
    data_item: tuple[Any, ...] = ()
    data_timestamp_ms: int | None = None
    if data is not None:
        if not isinstance(data, Mapping):
            raise ThsEnvelopeError("THS_ENVELOPE_DATA_INVALID")
        raw_item = data.get("item")
        if raw_item is None:
            data_item = ()
        elif isinstance(raw_item, (list, tuple)):
            data_item = tuple(raw_item)
        else:
            raise ThsEnvelopeError("THS_ENVELOPE_ITEM_INVALID")
        raw_timestamp = data.get("timestamp")
        if raw_timestamp is not None:
            if not isinstance(raw_timestamp, int) or isinstance(raw_timestamp, bool):
                raise ThsEnvelopeError("THS_ENVELOPE_TIMESTAMP_INVALID")
            data_timestamp_ms = raw_timestamp

    return ThsEnvelope(
        code=0,
        message=message or "success",
        request_id=request_id or "",
        data_item=data_item,
        data_timestamp_ms=data_timestamp_ms,
        raw=payload,
    )


def _rate_limit_codes() -> frozenset[int]:
    from app.services.market_data.ths_errors import THS_RATE_LIMIT_CODES

    return THS_RATE_LIMIT_CODES
