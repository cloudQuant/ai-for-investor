"""Local contracts for gateway runtime specification validation helpers."""

import pytest

from app.services.gateway.runtime import _positive_spec_number


@pytest.mark.parametrize(
    ("spec", "keys", "expected"),
    [
        pytest.param(
            {"first": None, "second": ""},
            ("first", "second"),
            False,
            id="none-and-empty-are-skipped",
        ),
        pytest.param(
            {"first": None, "second": "", "third": 2},
            ("first", "second", "third"),
            True,
            id="later-positive-value",
        ),
        pytest.param(
            {"first": object(), "second": 2},
            ("first", "second"),
            True,
            id="type-error-continues",
        ),
        pytest.param(
            {"first": "not-a-number", "second": 2},
            ("first", "second"),
            True,
            id="value-error-continues",
        ),
        pytest.param(
            {"first": 0, "second": -1},
            ("first", "second"),
            False,
            id="non-positive-values",
        ),
    ],
)
def test_positive_spec_number_preserves_candidate_fallbacks(
    spec: dict[str, object],
    keys: tuple[str, ...],
    expected: bool,
) -> None:
    """Only a positive numeric candidate succeeds; unusable candidates are skipped."""

    assert _positive_spec_number(spec, *keys) is expected
