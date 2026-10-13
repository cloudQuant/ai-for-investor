"""Direct tests for the shared position-valuation numeric normalization helper."""

import pytest

from app.services import position_valuation as valuation_facade
from app.services.position_valuation import safe_float
from app.services.valuation_numeric import safe_float as numeric_safe_float
from app.services.valuation_position import _current_price, _row_explicit_market_value
from app.services.valuation_projection import project_valued_position
from app.services.valuation_types import PositionSpec


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


def test_numeric_collaborator_preserves_facade_fallback_behavior() -> None:
    assert numeric_safe_float is valuation_facade.safe_float
    assert numeric_safe_float({"amount": "invalid"}, None) is None
    assert numeric_safe_float("invalid", 4.5) == 4.5


def test_price_collaborator_falls_back_to_market_value_then_entry_price() -> None:
    assert (
        _current_price(
            {"last_price": 0, "market_value": "20"},
            size=2.0,
            entry_price=8.0,
            multiplier=1.0,
        )
        == 10.0
    )
    assert (
        _current_price(
            {"last_price": "invalid"},
            size=2.0,
            entry_price=8.0,
            multiplier=1.0,
        )
        == 8.0
    )


def test_position_collaborator_rejects_estimated_explicit_market_value() -> None:
    row = {"marketValue": "250", "market_value_estimated": True}

    assert _row_explicit_market_value(row) is None


def test_zero_size_position_still_returns_none_through_facade() -> None:
    assert valuation_facade.value_position({"symbol": "IF2609", "size": 0}) is None


def test_result_projection_keeps_the_facade_result_type_and_field_shape() -> None:
    projected = project_valued_position(
        valuation_facade.ValuedPosition,
        data_name="IF2609",
        size=2.0,
        direction="long",
        entry_price=10.0,
        current_price=12.0,
        multiplier=300.0,
        margin_rate=0.1,
        market_value=7200.0,
        margin_value=720.0,
        commission=1.5,
        gross_pnl=1200.0,
        pnl=1198.5,
    )

    assert isinstance(projected, valuation_facade.ValuedPosition)
    assert isinstance(valuation_facade.PositionSpec(), PositionSpec)
    assert projected.pnl == 1198.5
    assert projected.market_value == 7200.0


def test_facade_result_factory_remains_monkeypatchable(monkeypatch: pytest.MonkeyPatch) -> None:
    class ProjectedResult:
        def __init__(self, **values: object) -> None:
            self.values = values

    monkeypatch.setattr(valuation_facade, "ValuedPosition", ProjectedResult)

    projected = valuation_facade.value_position(
        {"symbol": "IF2609", "size": 1, "price": 10, "current_price": 11}
    )

    assert isinstance(projected, ProjectedResult)
    assert projected.values["data_name"] == "IF2609"
