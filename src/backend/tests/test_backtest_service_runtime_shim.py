"""Runtime identity checks for the legacy backtest service import shim."""

from app.services import backtest_service as legacy_service
from app.services.backtest import service as canonical_service


def test_legacy_backtest_service_import_preserves_module_and_class_identity() -> None:
    assert legacy_service is canonical_service
    assert legacy_service.BacktestService is canonical_service.BacktestService
