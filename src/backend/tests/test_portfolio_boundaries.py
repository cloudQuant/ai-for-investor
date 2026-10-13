"""Focused tests for the extracted portfolio adapters."""

from app.api.portfolio.asset_spec_adapter import (
    _asset_spec_for_symbol,
    _merge_asset_spec_aliases,
)
from app.api.portfolio.instance_resolution import _list_user_instances
from app.api.portfolio.position_aggregation import _latest_position_rows


def test_asset_spec_adapter_preserves_contract_and_fills_missing_margin() -> None:
    specs = {"IF2610": {"multiplier": 300, "source": "gateway"}}

    _merge_asset_spec_aliases(
        specs,
        "CFFEX.IF2610",
        {"multiplier": 10, "margin_rate": 0.1, "source": "local"},
    )

    merged = _asset_spec_for_symbol(specs, "IF2610")
    assert merged["multiplier"] == 300
    assert merged["margin_rate"] == 0.1
    assert merged["source"] == "gateway+local"


def test_instance_resolution_filters_by_current_manager_status() -> None:
    class Manager:
        def list_instances(self, **_kwargs):
            return [{"id": "instance-1", "status": "running"}]

        def get_instance(self, _instance_id, **_kwargs):
            return {"id": "instance-1", "status": "stopped"}

    current_user = type("User", (), {"sub": "user-1"})()

    assert _list_user_instances(Manager(), current_user) == []
    assert _list_user_instances(Manager(), current_user, include_inactive=True) == [
        {"id": "instance-1", "status": "stopped"}
    ]


def test_position_aggregation_keeps_directional_flat_and_other_open_side() -> None:
    rows = [
        {"symbol": "IF2610", "size": 1, "side": "long", "datetime": "09:00"},
        {"symbol": "IF2610", "size": -1, "side": "short", "datetime": "09:15"},
        {"symbol": "IF2610", "size": 0, "side": "long", "datetime": "09:30"},
    ]

    latest = _latest_position_rows(rows)

    assert {(row["side"], row["size"]) for row in latest} == {
        ("long", 0),
        ("short", -1),
    }
