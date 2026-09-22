"""THS 凭据引用解析（``X-api-key``）。

API Key 通过 credential ref（环境变量 ``THS_API_KEY``）注入，绝不落库明文、
不进日志、不进异常消息、不进浏览器响应。异常信息一律用脱敏占位。
"""

from __future__ import annotations

from collections.abc import Mapping

# 凭据引用的环境变量名。
THS_API_KEY_ENV = "THS_API_KEY"
# 可选覆盖：THS API base URL（默认 https://fuyao.aicubes.cn）。
THS_API_BASE_URL_ENV = "THS_API_BASE_URL"
DEFAULT_THS_API_BASE_URL = "https://fuyao.aicubes.cn"

# 脱敏占位：任何异常/日志/响应路径都不允许出现 Key 明文。
_CREDENTIAL_MASK = "<redacted>"


class ThsCredentialsError(RuntimeError):
    """凭据解析失败（缺配置或非法），绝不携带 Key 明文。"""

    def __init__(self, code: str, *, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


class ThsCredentials:
    """从 credential ref 解析的 THS API Key 持有者。

    仅暴露 ``api_key`` 用于注入 HTTP 请求头，绝不实现 ``__repr__`` 或 ``str``
    泄漏明文。
    """

    def __init__(self, api_key: str, *, base_url: str = DEFAULT_THS_API_BASE_URL) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ThsCredentialsError("THS_CREDENTIAL_INVALID")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ThsCredentialsError("THS_BASE_URL_INVALID")
        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")

    @property
    def api_key(self) -> str:
        """返回 Key 用于构造请求头；调用方不得将其写入日志。"""
        return self._api_key

    @property
    def authorization_header(self) -> str:
        """直接可用的鉴权头值（``X-api-key: <key>``）。"""
        return self._api_key

    def __repr__(self) -> str:
        return f"ThsCredentials(api_key={_CREDENTIAL_MASK})"

    def __str__(self) -> str:
        return f"ThsCredentials(api_key={_CREDENTIAL_MASK})"

    @classmethod
    def from_environment(
        cls,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> ThsCredentials | None:
        """从环境变量解析凭据；未配置返回 ``None``（上层判失败关闭）。"""
        import os

        source = os.environ if environment is None else environment
        raw_key = source.get(THS_API_KEY_ENV, "").strip()
        if not raw_key:
            return None
        base_url = source.get(THS_API_BASE_URL_ENV, DEFAULT_THS_API_BASE_URL).strip()
        return cls(raw_key, base_url=base_url or DEFAULT_THS_API_BASE_URL)
