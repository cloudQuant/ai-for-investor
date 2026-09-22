"""THS 信封、错误码与鉴权契约的 fixture 测试（AC-01~08）。"""

from __future__ import annotations

import pytest

from app.services.market_data.ths_envelope import (
    ThsEnvelopeError,
    parse_ths_envelope,
)
from app.services.market_data.ths_errors import (
    ThsApiError,
    map_ths_error_code,
    severity_for,
)


def _success_payload(
    *, code: int = 0, item: list | None = None, request_id: str = "req-123"
) -> dict:
    return {
        "code": code,
        "message": "success" if code == 0 else "error",
        "request_id": request_id,
        "data": {"timestamp": 1716105600000, "item": item if item is not None else []},
    }


class TestEnvelopeSuccess:
    def test_code_zero_normalizes_item_and_request_id(self) -> None:
        """AC-01：code=0 信封含 data.item，观察正确归一化，request_id 进来源证据。"""
        envelope = parse_ths_envelope(
            _success_payload(item=[{"date_ms": 1716105600000, "close_price": 10.5}])
        )
        assert envelope.code == 0
        assert envelope.request_id == "req-123"
        assert envelope.data_timestamp_ms == 1716105600000
        assert len(envelope.data_item) == 1
        assert envelope.data_item[0]["close_price"] == 10.5

    def test_empty_item_is_valid(self) -> None:
        envelope = parse_ths_envelope(_success_payload(item=[]))
        assert envelope.item_count == 0

    def test_null_data_is_valid(self) -> None:
        payload = {"code": 0, "message": "success", "request_id": "req-1", "data": None}
        envelope = parse_ths_envelope(payload)
        assert envelope.item_count == 0


class TestErrorCodes:
    @pytest.mark.parametrize(
        "code,expected", [(2001, "THS_AUTH_DENIED"), (2003, "THS_PERMISSION_DENIED")]
    )
    def test_auth_errors_not_retryable(self, code: int, expected: str) -> None:
        """AC-02：code=2001/2003 不可重试错误，立即失败。"""
        with pytest.raises(ThsApiError) as exc:
            parse_ths_envelope(_success_payload(code=code))
        assert exc.value.code == expected
        assert not exc.value.retryable

    @pytest.mark.parametrize(
        "code,expected",
        [(3001, "EMPTY_CONFIRMED"), (3002, "DATA_NOT_READY"), (3004, "UNSUPPORTED_IDENTITY")],
    )
    def test_domain_errors(self, code: int, expected: str) -> None:
        """AC-03：code=3001/3002/3004 映射 EMPTY_CONFIRMED/DATA_NOT_READY/UNSUPPORTED_IDENTITY。"""
        with pytest.raises(ThsApiError) as exc:
            parse_ths_envelope(_success_payload(code=code))
        assert exc.value.code == expected

    def test_rate_limit_code_4001(self) -> None:
        """AC-04 部分：code=4001 按限流。"""
        with pytest.raises(ThsApiError) as exc:
            parse_ths_envelope(_success_payload(code=4001))
        assert exc.value.code == "THS_RATE_LIMITED"
        assert exc.value.retryable

    def test_http_429_treated_as_rate_limit(self) -> None:
        """AC-04：HTTP 429 无论信封如何都按限流。"""
        with pytest.raises(ThsApiError) as exc:
            parse_ths_envelope(_success_payload(code=0), http_status=429)
        assert exc.value.code == "THS_RATE_LIMITED"

    @pytest.mark.parametrize("code", [5001, 5002, 5003])
    def test_transient_errors_retryable(self, code: int) -> None:
        """AC-05：code=5001/5002/5003 暂时性错误，可限次重试。"""
        with pytest.raises(ThsApiError) as exc:
            parse_ths_envelope(_success_payload(code=code))
        assert exc.value.retryable

    @pytest.mark.parametrize("code", [1001, 1002, 1003, 1004])
    def test_validation_codes_mapped(self, code: int) -> None:
        """AC-06 相关：1001~1004 为请求构造错误，应在请求变换层前置拦截。"""
        assert severity_for(code) == "validation"

    def test_unknown_code_maps_to_unknown_error(self) -> None:
        assert map_ths_error_code(9999) == "THS_UNKNOWN_ERROR"


class TestEnvelopeValidation:
    def test_non_mapping_rejected(self) -> None:
        with pytest.raises(ThsEnvelopeError) as exc:
            parse_ths_envelope("not a mapping")  # type: ignore[arg-type]
        assert exc.value.code == "THS_ENVELOPE_NOT_MAPPING"

    def test_missing_code_rejected(self) -> None:
        with pytest.raises(ThsEnvelopeError) as exc:
            parse_ths_envelope({"message": "x", "request_id": "r"})
        assert exc.value.code == "THS_ENVELOPE_CODE_INVALID"

    def test_invalid_item_rejected(self) -> None:
        with pytest.raises(ThsEnvelopeError) as exc:
            parse_ths_envelope({"code": 0, "message": "s", "request_id": "r", "data": {"item": 5}})
        assert exc.value.code == "THS_ENVELOPE_ITEM_INVALID"
