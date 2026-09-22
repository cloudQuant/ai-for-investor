"""THS 限流与熔断的 fixture 测试（AC-04、NFR-02）。"""

from __future__ import annotations

import pytest

from app.services.market_data.ths_rate_limiter import (
    ThsRateLimiter,
    ThsRateLimitError,
    parse_retry_after,
)


class TestRetryAfterParsing:
    def test_parse_valid_seconds(self) -> None:
        assert parse_retry_after("30") == 30.0

    def test_parse_missing_or_invalid(self) -> None:
        assert parse_retry_after(None) is None
        assert parse_retry_after("abc") is None
        assert parse_retry_after("-5") is None


class TestBackoffBranches:
    def test_retry_after_present_obeyed(self) -> None:
        """AC-04 分支 A：携带 Retry-After 时遵守该头。"""
        limiter = ThsRateLimiter()
        decision = limiter.record_rate_limit(retry_after_seconds=42.0)
        assert decision.use_retry_after
        assert decision.retry_after_seconds == 42.0
        assert decision.delay_seconds == 42.0

    def test_retry_after_absent_exponential_backoff(self) -> None:
        """AC-04 分支 B：不携带时指数退避。"""
        limiter = ThsRateLimiter()
        first = limiter.record_rate_limit(retry_after_seconds=None)
        second = limiter.record_rate_limit(retry_after_seconds=None)
        assert not first.use_retry_after
        assert not second.use_retry_after
        assert first.delay_seconds < second.delay_seconds  # 指数递增


class TestCircuitBreaker:
    def test_injected_clock_controls_circuit_cooldown(self) -> None:
        now = [10.0]
        limiter = ThsRateLimiter(
            failure_threshold=1,
            cooldown_seconds=5.0,
            clock=lambda: now[0],
        )

        limiter.record_transient_failure()
        assert limiter.circuit_open
        with pytest.raises(ThsRateLimitError):
            limiter.before_request()

        now[0] = 15.0
        assert not limiter.circuit_open

    def test_circuit_opens_after_threshold(self) -> None:
        """AC-04/NFR-02：连续 5 次暂时失败触发熔断。"""
        limiter = ThsRateLimiter(failure_threshold=3, cooldown_seconds=60.0)
        for _ in range(3):
            limiter.record_transient_failure()
        assert limiter.circuit_open
        with pytest.raises(ThsRateLimitError):
            limiter.before_request()

    def test_success_resets_circuit(self) -> None:
        limiter = ThsRateLimiter(failure_threshold=2, cooldown_seconds=60.0)
        limiter.record_transient_failure()
        limiter.record_success()
        limiter.record_transient_failure()
        assert not limiter.circuit_open

    def test_rate_limit_counts_toward_breaker(self) -> None:
        """限流也计入连续失败（触发熔断）。"""
        limiter = ThsRateLimiter(failure_threshold=2, cooldown_seconds=60.0)
        limiter.record_rate_limit(retry_after_seconds=None)
        limiter.record_rate_limit(retry_after_seconds=None)
        assert limiter.circuit_open
