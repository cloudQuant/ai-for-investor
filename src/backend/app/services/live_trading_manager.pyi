"""Static exports for the legacy live-trading-manager module alias."""

from app.services.live_trading.manager import LiveTradingManager as LiveTradingManager
from app.services.live_trading.manager import (
    get_live_trading_manager as get_live_trading_manager,
)

__all__ = ["LiveTradingManager", "get_live_trading_manager"]
