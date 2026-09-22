"""Static public interface for the legacy runtime service shim."""

from app.services.backtest.service import BacktestService as BacktestService

__all__ = ["BacktestService"]
