"""THS 有界异步 HTTP 客户端。

封装 ``httpx.AsyncClient``：单请求超时默认 20s、响应体大小上限、可取消。
不解析业务语义——只负责收发字节与状态码/头，业务归一化在 ``ths_envelope``。

凭据由 ``ThsCredentials`` 注入，本模块绝不把 API Key 写入日志或异常。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.services.market_data.ths_credentials import ThsCredentials
from app.services.market_data.ths_rate_limiter import ThsRateLimiter

DEFAULT_TIMEOUT_SECONDS = 20.0
# 响应体大小上限，防止全市场导出误走即时路径导致 OOM。
DEFAULT_MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class ThsHttpError(RuntimeError):
    """HTTP 传输层错误（超时/取消/超限/连接失败），不含业务语义。"""

    def __init__(self, code: str, *, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


class ThsHttpResponse:
    """一次 THS HTTP 响应的最小承载（状态码、头、字节体）。"""

    def __init__(
        self,
        *,
        status_code: int,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        self.status_code = status_code
        self.headers = dict(headers)
        self.body = body

    @property
    def retry_after_seconds(self) -> float | None:
        """解析 ``Retry-After`` 头（可能为 ``None``）。"""
        from app.services.market_data.ths_rate_limiter import parse_retry_after

        return parse_retry_after(self.headers.get("Retry-After") or self.headers.get("retry-after"))


class ThsHttpClient:
    """有界异步 HTTP 客户端，复用调用方传入的 ``httpx.AsyncClient``。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        credentials: ThsCredentials,
        rate_limiter: ThsRateLimiter,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if not isinstance(client, httpx.AsyncClient):
            raise TypeError("client must be an httpx.AsyncClient")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._client = client
        self._credentials = credentials
        self._rate_limiter = rate_limiter
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    @property
    def base_url(self) -> str:
        return self._credentials.base_url

    async def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> ThsHttpResponse:
        """执行一次 GET，熔断期间快速失败，返回有界响应。

        参数键/值不包含凭据；鉴权经请求头注入。
        """
        self._rate_limiter.before_request()
        url = f"{self._credentials.base_url}{path}"
        headers = {"X-api-key": self._credentials.authorization_header}
        try:
            async with self._client.stream(
                "GET",
                url,
                params=dict(params) if params else None,
                headers=headers,
                timeout=self._timeout_seconds,
            ) as response:
                body = await self._read_bounded(response)
                return ThsHttpResponse(
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    body=body,
                )
        except httpx.TimeoutException as exc:
            raise ThsHttpError("THS_HTTP_TIMEOUT", detail="request timed out") from exc
        except httpx.HTTPError as exc:
            raise ThsHttpError("THS_HTTP_TRANSPORT", detail=_safe_detail(exc)) from exc

    async def _read_bounded(self, response: httpx.Response) -> bytes:
        """读取响应体并施加大小上限，超限立即中断，不 OOM。"""
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._max_response_bytes:
                await response.aclose()
                raise ThsHttpError("THS_HTTP_RESPONSE_TOO_LARGE")
            chunks.append(chunk)
        return b"".join(chunks)


def _safe_detail(exc: BaseException) -> str:
    """脱敏诊断：只保留异常类名，绝不拼入 URL（可能含查询参数）。"""
    return exc.__class__.__name__
