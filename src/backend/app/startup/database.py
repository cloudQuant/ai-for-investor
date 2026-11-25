from typing import Any

from fastapi import FastAPI

from app.db.akshare_data_database import dispose_akshare_data_engine
from app.db.cache import close_cache
from app.db.database import dispose_all_engines, ensure_database_ready
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _get_logger(app: FastAPI):
    return getattr(app.state, "startup_logger", logger)


async def register(app: FastAPI, settings: Any) -> None:
    startup_logger = _get_logger(app)
    ensure_ready = getattr(app.state, "ensure_database_ready", ensure_database_ready)
    if settings.DB_AUTO_CREATE_SCHEMA:
        startup_logger.info("DB_AUTO_CREATE_SCHEMA=true: Creating database tables...")
        await ensure_ready()
        startup_logger.info("Database tables created/verified successfully")
    else:
        startup_logger.info("DB_AUTO_CREATE_SCHEMA=false: Verifying database migration revision...")
        await ensure_ready()
        startup_logger.info("Database migration revision verified (startup performed no DDL)")

    cache_type = "Redis" if settings.REDIS_URL else "Memory"
    startup_logger.info(f"Cache backend: {cache_type}")


async def shutdown(app: FastAPI, settings: Any) -> None:
    del app, settings
    await dispose_all_engines()
    await dispose_akshare_data_engine()
    await close_cache()
