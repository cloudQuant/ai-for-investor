from contextlib import asynccontextmanager
import logging
from time import perf_counter
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from app.core.config import settings
from app.core.observability import record_api_exception, record_api_request
from app.db.mongodb import connect_mongodb, close_mongodb
from app.db.redis import connect_redis, close_redis

def configure_logging(log_level: str = settings.LOG_LEVEL) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(level=level)
    logging.getLogger().setLevel(level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


configure_logging()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("application_startup", app_name=settings.APP_NAME)
    await connect_mongodb()
    await connect_redis()
    yield
    await close_mongodb()
    await close_redis()
    logger.info("application_shutdown", app_name=settings.APP_NAME)


async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    started_at = perf_counter()
    request.state.request_id = request_id
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    logger.info("request_started", method=request.method, path=request.url.path, request_id=request_id)
    try:
        response = await call_next(request)
    except Exception as exc:
        record_api_exception((perf_counter() - started_at) * 1000)
        logger.error("request_failed", method=request.method, path=request.url.path, error=str(exc), request_id=request_id)
        raise
    latency_ms = (perf_counter() - started_at) * 1000
    record_api_request(response.status_code, latency_ms)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=round(latency_ms, 2),
        request_id=request_id,
    )
    return response


async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "unhandled_exception",
        error=str(exc),
        path=request.url.path,
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred",
            },
            "request_id": getattr(request.state, "request_id", None),
        },
    )


async def health_check():
    return {"status": "healthy", "app": settings.APP_NAME, "version": settings.APP_VERSION}


from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.blog import router as blog_router
from app.api.v1.forum import router as forum_router
from app.api.v1.tools import router as tools_router
from app.api.v1.open_source import router as open_source_router
from app.api.v1.admin import router as admin_router
from app.api.v1.preferences import router as preferences_router


def create_app(include_lifespan: bool = True) -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan if include_lifespan else None,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_CREDENTIALS,
        allow_methods=settings.CORS_METHODS,
        allow_headers=settings.CORS_HEADERS,
    )

    application.middleware("http")(add_request_id)
    application.add_exception_handler(Exception, global_exception_handler)
    application.get("/health")(health_check)
    application.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    application.include_router(users_router, prefix="/api/v1/users", tags=["users"])
    application.include_router(blog_router, prefix="/api/v1/blog", tags=["blog"])
    application.include_router(forum_router, prefix="/api/v1/forum", tags=["forum"])
    application.include_router(tools_router, prefix="/api/v1/tools", tags=["tools"])
    application.include_router(open_source_router, prefix="/api/v1/open-source", tags=["open-source"])
    application.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])
    application.include_router(preferences_router, prefix="/api/v1/preferences", tags=["preferences"])
    return application


app = create_app()
