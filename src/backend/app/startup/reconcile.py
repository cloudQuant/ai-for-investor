from typing import Any

from fastapi import FastAPI

from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _get_logger(app: FastAPI):
    return getattr(app.state, "startup_logger", logger)


async def register(app: FastAPI, settings: Any) -> None:
    startup_logger = _get_logger(app)
    try:
        from app.services.backtest.manager import BacktestExecutionManager
        from app.services.overfitting.service import OverfittingService
        from app.services.stock_analysis.tasks import StockAnalysisTaskService
        from app.services.workspace_service import WorkspaceService

        workspace_service = WorkspaceService()
        reconciled_tasks = await BacktestExecutionManager().reconcile_orphaned_tasks()
        reconciled_stock_analysis_tasks = await StockAnalysisTaskService.reconcile_orphaned_tasks()
        reconciled_overfitting_tasks = await OverfittingService.reconcile_orphaned_tasks()
        reconciled_units = await workspace_service.reconcile_orphaned_run_statuses()
        reconciled_bar_counts = await workspace_service.reconcile_completed_bar_counts()
        if (
            reconciled_tasks
            or reconciled_stock_analysis_tasks
            or reconciled_overfitting_tasks
            or reconciled_units
            or reconciled_bar_counts
        ):
            startup_logger.warning(
                "Recovered stale runtime state on startup: backtest_tasks=%s, stock_analysis_tasks=%s, overfitting_tasks=%s, workspace_units=%s, unit_bar_counts=%s",
                reconciled_tasks,
                reconciled_stock_analysis_tasks,
                reconciled_overfitting_tasks,
                reconciled_units,
                reconciled_bar_counts,
            )
    except Exception:
        startup_logger.exception("Failed to reconcile stale runtime state during startup")


async def shutdown(app: FastAPI, settings: Any) -> None:
    startup_logger = _get_logger(app)
    try:
        from app.services.backtest.manager import BacktestExecutionManager
        from app.services.backtest.runner import get_default_backtest_runner
        from app.services.overfitting.service import OverfittingService
        from app.services.stock_analysis.tasks import StockAnalysisTaskService
        from app.utils.async_tasks import cancel_tracked_tasks

        cancelled_tracked = await cancel_tracked_tasks()
        cancelled_local = get_default_backtest_runner().cancel_all()
        mgr = BacktestExecutionManager()
        interrupted_backtests = await mgr.interrupt_active_tasks()
        interrupted_stock_analysis = await StockAnalysisTaskService.interrupt_active_tasks()
        interrupted_overfitting = await OverfittingService.interrupt_active_tasks()
        if (
            cancelled_tracked
            or cancelled_local
            or interrupted_backtests
            or interrupted_stock_analysis
            or interrupted_overfitting
        ):
            startup_logger.warning(
                "Interrupted active tasks during shutdown: cancelled_tracked=%s, cancelled_local=%s, backtest_tasks=%s, stock_analysis_tasks=%s, overfitting_tasks=%s",
                cancelled_tracked,
                cancelled_local,
                interrupted_backtests,
                interrupted_stock_analysis,
                interrupted_overfitting,
            )
    except Exception:
        startup_logger.exception("Failed to interrupt active tasks during shutdown")
