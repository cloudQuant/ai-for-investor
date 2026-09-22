"""同花顺（THS）API 错误码到中台语义的映射与结构化错误。

THS API 使用统一信封 ``ApiResponse``，业务结果经 ``code`` 表达；触发限流时
可能返回 HTTP 429。本模块把 THS 业务错误码映射为稳定、可重试策略明确的
结构化错误，供 ``ThsEnvelopeCodec`` 与 ``ThsProvider`` 使用。

错误码来源见迭代 198 RESEARCH.md 第 3 节。
"""

from __future__ import annotations

from typing import Literal

# THS 业务错误码 → 中台语义（stable code）。
# 语义分类：
#   不可重试（auth/permission）：立即失败，不浪费重试预算。
#   领域结果（标的问题）：EMPTY_CONFIRMED / DATA_NOT_READY / UNSUPPORTED_IDENTITY。
#   限流：与 HTTP 429 等效，指数退避 + 熔断。
#   暂时性（服务端/上游）：可限次重试。
#   请求构造错误：应在请求变换层前置校验，不应发送到上游。
THS_ERROR_CODE_MAP: dict[int, str] = {
    2001: "THS_AUTH_DENIED",
    2003: "THS_PERMISSION_DENIED",
    3001: "EMPTY_CONFIRMED",
    3002: "DATA_NOT_READY",
    3004: "UNSUPPORTED_IDENTITY",
    4001: "THS_RATE_LIMITED",
    5001: "THS_SERVER_ERROR",
    5002: "THS_UPSTREAM_TIMEOUT",
    5003: "THS_UPSTREAM_UNAVAILABLE",
}

# 请求构造错误码：应在本地前置拦截，不应发送到上游。
THS_REQUEST_VALIDATION_CODES: frozenset[int] = frozenset({1001, 1002, 1003, 1004})

# 不可重试错误码（鉴权/权限）。
THS_NON_RETRYABLE_CODES: frozenset[int] = frozenset({2001, 2003})

# 限流错误码（与 HTTP 429 等效）。
THS_RATE_LIMIT_CODES: frozenset[int] = frozenset({4001})

# 暂时性错误码（服务端/上游，可限次重试）。
THS_TRANSIENT_CODES: frozenset[int] = frozenset({5001, 5002, 5003})

ErrorSeverity = Literal[
    "auth",
    "permission",
    "empty",
    "not_ready",
    "unsupported",
    "rate_limit",
    "transient",
    "validation",
]


class ThsApiError(RuntimeError):
    """THS 业务错误，携带稳定错误码、THS 业务码与脱敏后的 request_id。

    ``detail`` 仅用于安全诊断，绝不包含 API Key 明文。
    """

    def __init__(
        self,
        code: str,
        *,
        ths_code: int | None = None,
        request_id: str | None = None,
        message: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.code = code
        self.ths_code = ths_code
        self.request_id = request_id
        self.message = message
        self.detail = detail
        super().__init__(code)

    @property
    def retryable(self) -> bool:
        """是否可重试：限流与暂时性错误可重试，其余不可重试。"""
        return self.code in {
            "THS_RATE_LIMITED",
            "THS_SERVER_ERROR",
            "THS_UPSTREAM_TIMEOUT",
            "THS_UPSTREAM_UNAVAILABLE",
        }


def map_ths_error_code(ths_code: int) -> str:
    """把 THS 业务错误码映射为稳定中台错误码。

    未识别的业务码归为暂时性服务端错误（保守可重试），避免把未知业务码
    误判为数据缺失或权限失败。
    """
    if not isinstance(ths_code, int):
        raise TypeError("ths_code must be an int")
    if ths_code == 0:
        raise ValueError("ths_code 0 is success, not an error")
    if ths_code in THS_ERROR_CODE_MAP:
        return THS_ERROR_CODE_MAP[ths_code]
    return "THS_UNKNOWN_ERROR"


def severity_for(ths_code: int) -> ErrorSeverity:
    """返回 THS 业务码的错误严重度分类，用于审计与限流决策。"""
    if ths_code in THS_REQUEST_VALIDATION_CODES:
        return "validation"
    if ths_code in THS_NON_RETRYABLE_CODES:
        return "permission" if ths_code == 2003 else "auth"
    if ths_code in THS_RATE_LIMIT_CODES:
        return "rate_limit"
    if ths_code in THS_TRANSIENT_CODES:
        return "transient"
    if ths_code == 3001:
        return "empty"
    if ths_code == 3002:
        return "not_ready"
    if ths_code == 3004:
        return "unsupported"
    return "transient"
