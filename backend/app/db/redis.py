import redis.asyncio as redis
from app.core.config import settings

_redis: redis.Redis | None = None


async def connect_redis():
    global _redis
    _redis = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
        db=settings.REDIS_DB,
        decode_responses=True,
    )


async def close_redis():
    global _redis
    if _redis:
        await _redis.close()
    _redis = None


def get_redis() -> redis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialized")
    return _redis
