"""Runtime identity checks for the legacy live trading manager import shim."""

from importlib import import_module

from app.services.live_trading import manager as canonical_manager


def test_legacy_live_trading_manager_aliases_canonical_exports() -> None:
    legacy_manager = import_module("app.services.live_trading_manager")

    assert legacy_manager is canonical_manager
    assert legacy_manager.LiveTradingManager is canonical_manager.LiveTradingManager
    assert legacy_manager.get_live_trading_manager is canonical_manager.get_live_trading_manager
