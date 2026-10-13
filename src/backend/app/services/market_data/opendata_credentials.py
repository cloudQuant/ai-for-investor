"""opendata 凭据引用解析（``X-API-Key``）。

API Key 通过 credential ref（环境变量 ``OPENDATA_API_KEY``）注入，绝不落库明文、
不进日志、不进异常消息、不进浏览器响应。异常信息一律用脱敏占位。

与 THS 的差异：中台 REST 用 ``X-API-Key`` 头，base URL 指向自建数据中台。
"""

from __future__ import annotations

from collections.abc import Mapping

# 凭据引用的环境变量名。
OPENDATA_API_KEY_ENV = "OPENDATA_API_KEY"
# 可选覆盖：数据中台 base URL（默认本机开发端口）。
OPENDATA_BASE_URL_ENV = "OPENDATA_BASE_URL"
DEFAULT_OPENDATA_BASE_URL = "http://127.0.0.1:8000"

# 脱敏占位：任何异常/日志/响应路径都不允许出现 Key 明文。
_CREDENTIAL_MASK = "<redacted>"


class OpendataCredentialsError(RuntimeError):
    """凭据解析失败（缺配置或非法），绝不携带 Key 明文。"""

    def __init__(self, code: str, *, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


class OpendataCredentials:
    """从 credential ref 解析的 opendata API Key 持有者。

    仅暴露 ``api_key`` 用于注入 HTTP 请求头，绝不实现会泄漏明文的
    ``__repr__`` / ``__str__``。
    """

    def __init__(self, api_key: str, *, base_url: str = DEFAULT_OPENDATA_BASE_URL) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise OpendataCredentialsError("OPENDATA_CREDENTIAL_INVALID")
        if not isinstance(base_url, str) or not base_url.strip():
            raise OpendataCredentialsError("OPENDATA_BASE_URL_INVALID")
        self._api_key = api_key.strip()
        self.base_url = base_url.strip().rstrip("/")
        if not base_url.strip().lower().startswith(("http://", "https://")):
            raise OpendataCredentialsError("OPENDATA_BASE_URL_INVALID")

    @property
    def api_key(self) -> str:
        """返回 Key 用于构造请求头；调用方不得将其写入日志。"""
        return self._api_key

    def __repr__(self) -> str:
        return f"OpendataCredentials(api_key={_CREDENTIAL_MASK})"

    def __str__(self) -> str:
        return f"OpendataCredentials(api_key={_CREDENTIAL_MASK})"

    @classmethod
    def from_environment(
        cls,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> OpendataCredentials | None:
        """从环境变量解析凭据；未配置返回 ``None``（上层判失败关闭）。"""
        import os

        source = os.environ if environment is None else environment
        raw_key = source.get(OPENDATA_API_KEY_ENV, "").strip()
        if not raw_key:
            return None
        base_url = source.get(OPENDATA_BASE_URL_ENV, DEFAULT_OPENDATA_BASE_URL).strip()
        return cls(raw_key, base_url=base_url or DEFAULT_OPENDATA_BASE_URL)


__all__ = [
    "DEFAULT_OPENDATA_BASE_URL",
    "OPENDATA_API_KEY_ENV",
    "OPENDATA_BASE_URL_ENV",
    "OpendataCredentials",
    "OpendataCredentialsError",
]
