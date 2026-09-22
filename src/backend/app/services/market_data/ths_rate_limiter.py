"""THS 限流与熔断（429 / code=4001）。

退避策略不依赖 ``Retry-After``（THS 官方未承诺该头；若响应实际携带则遵守）。
连续暂时失败达阈值触发熔断（60s），期间快速失败不发起请求。

本模块是进程内状态机，与 AkShare/OpenBB 的限流额度相互独立（THS 是独立来源）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


class ThsRateLimitError(RuntimeError):
    """限流触发熔断时抛出的结构化错误。"""

    def __init__(self, code: str = "THS_CIRCUIT_OPEN", *, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ThsBackoffDecision:
    """一次限流后的退避决策。"""

    delay_seconds: float
    use_retry_after: bool
    retry_after_seconds: float | None


class ThsRateLimiter:
    """指数退避 + 熔断的进程内限流器。

    - 429/4001 视为限流，指数退避。
    - 携带 ``Retry-After`` 时遵守该头（分支 A）；否则按指数退避（分支 B）。
    - 连续 ``failure_threshold`` 次暂时失败触发 ``cooldown_seconds`` 熔断。
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if cooldown_seconds <= 0 or base_delay_seconds <= 0 or max_delay_seconds <= 0:
            raise ValueError("durations must be positive")
        if max_delay_seconds < base_delay_seconds:
            raise ValueError("max_delay_seconds must be >= base_delay_seconds")
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._base_delay_seconds = base_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._attempt = 0

    @property
    def circuit_open(self) -> bool:
        """是否处于熔断状态（应快速失败，不发起请求）。"""
        return self._clock() < self._circuit_open_until

    def before_request(self) -> None:
        """在出站前调用；熔断期间抛错快速失败。"""
        if self.circuit_open:
            remaining = self._circuit_open_until - self._clock()
            raise ThsRateLimitError(
                "THS_CIRCUIT_OPEN",
                detail=f"circuit open for {remaining:.1f}s",
            )

    def record_rate_limit(self, *, retry_after_seconds: float | None) -> ThsBackoffDecision:
        """记录一次限流并返回退避决策。

        ``retry_after_seconds`` 为 ``Retry-After`` 头解析值（可能为 ``None``）。
        分支 A：携带时遵守该头（不叠加指数）；分支 B：不携带时指数退避。
        """
        self._attempt += 1
        if retry_after_seconds is not None and retry_after_seconds > 0:
            delay = min(retry_after_seconds, self._max_delay_seconds)
            self._note_failure()
            return ThsBackoffDecision(delay, True, retry_after_seconds)
        # 分支 B：指数退避。
        delay = min(self._base_delay_seconds * (2 ** (self._attempt - 1)), self._max_delay_seconds)
        self._note_failure()
        return ThsBackoffDecision(delay, False, None)

    def record_transient_failure(self) -> None:
        """记录一次暂时性失败（5001/5002/5003），累积到熔断阈值。"""
        self._note_failure()

    def record_success(self) -> None:
        """成功请求重置连续失败计数与退避指数。"""
        self._consecutive_failures = 0
        self._attempt = 0
        self._circuit_open_until = 0.0

    def _note_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._circuit_open_until = self._clock() + self._cooldown_seconds
            self._consecutive_failures = 0


def parse_retry_after(value: str | None) -> float | None:
    """解析 ``Retry-After`` 头（秒数，非负）；缺失/非法返回 ``None``。"""
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return seconds
