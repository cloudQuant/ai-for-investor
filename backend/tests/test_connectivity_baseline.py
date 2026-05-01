import importlib

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.db import mongodb, redis
from app.db.mysql import engine


def test_required_database_and_secret_settings_fail_fast() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            SECRET_KEY="",
            MYSQL_USER="",
            MYSQL_PASSWORD="",
            MYSQL_DATABASE="",
        )

    errors = {".".join(str(part) for part in error["loc"]): error["type"] for error in exc_info.value.errors()}
    assert errors["SECRET_KEY"] == "string_too_short"
    assert errors["MYSQL_USER"] == "string_too_short"
    assert errors["MYSQL_PASSWORD"] == "string_too_short"
    assert errors["MYSQL_DATABASE"] == "string_too_short"


def test_mysql_engine_uses_async_driver_and_configured_database() -> None:
    url = str(engine.url)

    assert engine.dialect.name == "mysql"
    assert engine.dialect.driver == "asyncmy"
    assert settings.MYSQL_DATABASE in url


@pytest.mark.asyncio
async def test_mongodb_connect_and_close_use_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    created = {}

    class FakeMongoClient:
        def __init__(self, url: str) -> None:
            self.url = url
            self.closed = False
            created["client"] = self

        def __getitem__(self, database: str) -> str:
            created["database"] = database
            return f"db:{database}"

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(mongodb, "AsyncIOMotorClient", FakeMongoClient)
    mongodb._client = None
    mongodb._db = None

    await mongodb.connect_mongodb()

    assert created["client"].url == settings.MONGODB_URL
    assert created["database"] == settings.MONGODB_DATABASE
    assert mongodb.get_mongodb() == f"db:{settings.MONGODB_DATABASE}"

    await mongodb.close_mongodb()

    assert created["client"].closed is True
    assert mongodb._client is None
    assert mongodb._db is None


@pytest.mark.asyncio
async def test_redis_connect_and_close_use_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    created = {}

    class FakeRedis:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.closed = False
            created["client"] = self

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(redis.redis, "Redis", FakeRedis)
    redis._redis = None

    await redis.connect_redis()

    assert created["client"].kwargs == {
        "host": settings.REDIS_HOST,
        "port": settings.REDIS_PORT,
        "password": settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
        "db": settings.REDIS_DB,
        "decode_responses": True,
    }
    assert redis.get_redis() is created["client"]

    await redis.close_redis()

    assert created["client"].closed is True
    assert redis._redis is None
