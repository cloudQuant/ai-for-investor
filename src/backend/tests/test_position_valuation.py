"""Direct tests for the shared position-valuation numeric normalization helper."""

from app.services.position_valuation import safe_float


def test_safe_float_uses_float_defaults_and_preserves_none_fallback() -> None:
    assert safe_float("12.5") == 12.5
    assert safe_float(None) == 0.0
    assert safe_float("invalid", 3.25) == 3.25
    assert safe_float(None, 3.25) == 3.25
    assert safe_float("invalid", None) is None
    assert safe_float(None, None) is None


def test_safe_float_recursively_reads_nested_dict_values() -> None:
    assert safe_float({"cost": {"amount": "2,500.5"}}, 0.0) == 2500.5


def test_safe_float_aggregates_valid_numbers_in_nested_lists() -> None:
    value = [1, {"amount": "2.5"}, "invalid", [4, None]]

    assert safe_float(value, None) == 7.5
    assert safe_float(["invalid", None], None) is None
