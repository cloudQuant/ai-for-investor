from typing import Any

from fastapi import FastAPI

from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _get_logger(app: FastAPI):
    return getattr(app.state, "startup_logger", logger)


async def register(app: FastAPI, settings: Any) -> None:
    startup_logger = _get_logger(app)

    # Iteration 199: independent THS history scheduler (main database, not the
    # AkShare warehouse). Fail-closed and disabled unless explicitly enabled.
    try:
        from app.services.market_data.ths_scheduler import ThsMarketDataScheduler

        ths_scheduler = ThsMarketDataScheduler.from_settings(settings)
        await ths_scheduler.start()
        app.state.ths_market_data_scheduler = ths_scheduler
        startup_logger.info(f"THS market-data scheduler: {ths_scheduler.describe()}")
    except Exception:
        startup_logger.exception("Failed to start THS market-data scheduler")

    if not settings.AKSHARE_DATA_DATABASE_URL:
        return

    try:
        from app.api.airflow_dags import set_orchestration_backend
        from app.services.orchestration.detector import BackendDetector

        detector = BackendDetector()
        orchestration_backend = await detector.detect()
        await orchestration_backend.start()
        set_orchestration_backend(orchestration_backend)
        app.state.orchestration_backend = orchestration_backend

        backend_status = await orchestration_backend.get_backend_status()
        startup_logger.info(
            f"Orchestration backend started: {backend_status.get('type', 'unknown')}"
        )
    except Exception:
        startup_logger.exception("Failed to start orchestration backend")
        try:
            from app.services.akshare.scheduler_service import get_akshare_scheduler_service

            akshare_scheduler_service = get_akshare_scheduler_service()
            app.state.akshare_scheduler_service = akshare_scheduler_service
            await akshare_scheduler_service.start()
            startup_logger.info("Fallback: Akshare APScheduler started directly")
        except Exception:
            startup_logger.exception("Failed to start fallback APScheduler")


async def shutdown(app: FastAPI, settings: Any) -> None:
    startup_logger = _get_logger(app)
    try:
        from app.api.airflow_dags import _orchestration_backend

        if _orchestration_backend is not None:
            await _orchestration_backend.shutdown()
            startup_logger.info("Orchestration backend shut down")
    except Exception:
        startup_logger.exception("Failed to shutdown orchestration backend")

    akshare_scheduler_service = getattr(app.state, "akshare_scheduler_service", None)
    if akshare_scheduler_service is not None:
        try:
            await akshare_scheduler_service.shutdown()
        except Exception:
            startup_logger.exception("Failed to shutdown akshare scheduler")

    ths_scheduler = getattr(app.state, "ths_market_data_scheduler", None)
    if ths_scheduler is not None:
        try:
            await ths_scheduler.shutdown()
        except Exception:
            startup_logger.exception("Failed to shutdown THS market-data scheduler")
