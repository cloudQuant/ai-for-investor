"""Numeric input compatibility checks for paper-trading helpers."""

from array import array

import pytest

from app.services.paper_trading_service import PaperTradingService


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(memoryview(b"1.25"), 1.25, id="memoryview-ascii"),
        pytest.param(array("b", b"12"), 12.0, id="signed-byte-array-ascii"),
    ],
)
def test_numeric_helpers_accept_values_supported_by_float(
    value: object,
    expected: float,
) -> None:
    assert PaperTradingService._safe_float(value, 7.25) == expected
    assert PaperTradingService._positive_finite(value, "size") == expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(True, id="boolean-true"),
        pytest.param(False, id="boolean-false"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(1 << 4096, id="float-overflow"),
        pytest.param("not-a-number", id="invalid-text"),
        pytest.param(None, id="none"),
        pytest.param(complex(1, 0), id="complex"),
        pytest.param(object(), id="unsupported-object"),
        pytest.param(memoryview(b"12.5")[::2], id="non-contiguous-memoryview"),
        pytest.param(array("d", [1.0]), id="binary-float-array"),
    ],
)
def test_numeric_helpers_reject_invalid_or_non_finite_values(value: object) -> None:
    assert PaperTradingService._safe_float(value, 7.25) == 7.25

    with pytest.raises(ValueError, match="size must be a positive finite number"):
        PaperTradingService._positive_finite(value, "size")
