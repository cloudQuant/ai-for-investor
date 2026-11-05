from typing import Any

from fastapi import FastAPI

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Records which plane armed the AkShare APScheduler so the single-writer claim can be
# evidenced from the running process. Absent means nothing armed the scheduler.
SCHEDULER_START_SOURCE_ATTR = "akshare_scheduler_start_source"
SCHEDULER_START_SOURCE_ORCHESTRATION = "orchestration"
SCHEDULER_START_SOURCE_API_FALLBACK = "orchestration_fallback"

_API_FALLBACK_ALLOW = "allow"
_API_FALLBACK_FORBID = "forbid"
_API_FALLBACK_SETTING = "AKSHARE_SCHEDULER_API_FALLBACK"


def _get_logger(app: FastAPI):
    return getattr(app.state, "startup_logger", logger)


def _api_fallback_allowed(settings: Any, startup_logger: Any) -> bool:
    """Return whether this process may arm the AkShare scheduler as an API fallback.

    Fail-closed: only the exact value ``allow`` permits it. ``forbid`` and any
    unrecognised or unset value suppress the fallback, because a typo here decides
    which plane writes to the warehouse.
    """
    raw = getattr(settings, _API_FALLBACK_SETTING, None)
    value = raw.strip().lower() if isinstance(raw, str) else ""
    if value == _API_FALLBACK_ALLOW:
        return True
    if value == _API_FALLBACK_FORBID:
        startup_logger.error(
            f"Akshare APScheduler not started: {_API_FALLBACK_SETTING}=forbid suppresses the "
            "API-process fallback. A dedicated collector unit must own scheduling."
        )
        return False
    startup_logger.error(
        f"Akshare APScheduler not started (fail-closed): {_API_FALLBACK_SETTING}={raw!r} is "
        f"neither '{_API_FALLBACK_ALLOW}' nor '{_API_FALLBACK_FORBID}'; treating an "
        "unrecognised value as forbid."
    )
    return False


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
        app.state.akshare_scheduler_start_source = SCHEDULER_START_SOURCE_ORCHESTRATION
    except Exception as orchestration_error:
        startup_logger.exception("Failed to start orchestration backend")
        if not _api_fallback_allowed(settings, startup_logger):
            return
        try:
            from app.services.akshare.scheduler_service import get_akshare_scheduler_service

            akshare_scheduler_service = get_akshare_scheduler_service()
            app.state.akshare_scheduler_service = akshare_scheduler_service
            await akshare_scheduler_service.start()
            app.state.akshare_scheduler_start_source = SCHEDULER_START_SOURCE_API_FALLBACK
            startup_logger.warning(
                "Fallback: Akshare APScheduler started directly by the API process because the "
                f"orchestration backend failed: {orchestration_error!r}. Set "
                f"{_API_FALLBACK_SETTING}=forbid where a dedicated collector unit owns "
                "scheduling."
            )
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
