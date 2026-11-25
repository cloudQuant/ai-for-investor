"""Database connection management."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import weakref
from collections.abc import AsyncGenerator
from typing import cast

from sqlalchemy import event, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings
from app.db.schema_compatibility import (
    _ensure_akshare_mgmt_schema_compatibility_sync as _ensure_akshare_mgmt_schema_compatibility_sync,
)
from app.db.schema_compatibility import run_all_schema_compatibility_sync
from app.middleware.metrics import record_db_query
from app.utils.username_identity import normalize_reserved_username

logger = logging.getLogger(__name__)

settings = get_settings()

# Engine / session-maker caches are keyed by the running event loop and guarded
# by ``_engine_lock`` so worker threads and async handlers never race or share a
# loop-bound MySQL pool across event loops.
_engine_lock = threading.RLock()
_engine: AsyncEngine | None = None  # fallback for callers outside a running loop
_async_session_maker: async_sessionmaker[AsyncSession] | None = None
_engines: weakref.WeakKeyDictionary[object, AsyncEngine] = weakref.WeakKeyDictionary()
_session_makers: weakref.WeakKeyDictionary[object, async_sessionmaker[AsyncSession]] = (
    weakref.WeakKeyDictionary()
)


def _register_db_metrics(target_engine: AsyncEngine) -> None:
    """Wire DB query metrics so db_query_total/duration reflect real DB activity."""

    @event.listens_for(target_engine.sync_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._db_query_start = time.perf_counter()

    @event.listens_for(target_engine.sync_engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        start = getattr(context, "_db_query_start", None)
        if start is None:
            return
        duration = time.perf_counter() - start
        operation = (statement.strip().split()[:1] or ["unknown"])[0].lower()
        table = _extract_table_name(statement)
        record_db_query(operation, table, duration)


def _extract_table_name(statement: str) -> str:
    """Best-effort table name extraction for low-cardinality metric labels."""
    stripped = statement.strip().lower()
    for prefix in ("insert into ", "update ", "delete from ", "from ", "into "):
        if stripped.startswith(prefix):
            rest = stripped[len(prefix) :]
            token = ""
            for ch in rest:
                if ch.isalnum() or ch in "_.":
                    token += ch
                else:
                    break
            return token or "unknown"
    return "unknown"


def _create_engine() -> AsyncEngine:
    """Build one async engine with pooling and pre-ping enabled."""

    extra_kwargs: dict[str, object] = {"pool_pre_ping": True}
    if settings.DATABASE_URL.startswith("mysql"):
        extra_kwargs.update(
            pool_size=5,
            max_overflow=10,
            pool_recycle=1800,
        )
    return create_async_engine(
        settings.DATABASE_URL,
        echo=settings.SQL_ECHO,
        **extra_kwargs,
    )


def _running_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _get_engine() -> AsyncEngine:
    global _engine
    loop = _running_loop()
    with _engine_lock:
        if loop is None:
            if _engine is None:
                _engine = _create_engine()
                _register_db_metrics(_engine)
            return _engine
        resolved = _engines.get(loop)
        if resolved is None:
            resolved = _create_engine()
            _engines[loop] = resolved
            _register_db_metrics(resolved)
        return resolved


def _get_session_maker() -> async_sessionmaker[AsyncSession]:
    global _async_session_maker
    loop = _running_loop()
    with _engine_lock:
        if loop is None:
            if _async_session_maker is None:
                _async_session_maker = async_sessionmaker(
                    _get_engine(),
                    class_=AsyncSession,
                    expire_on_commit=False,
                )
            return _async_session_maker
        maker = _session_makers.get(loop)
        if maker is None:
            maker = async_sessionmaker(
                _get_engine(),
                class_=AsyncSession,
                expire_on_commit=False,
            )
            _session_makers[loop] = maker
        return maker


async def dispose_current_loop_engine() -> None:
    """Dispose the already-created engine for the active loop without creating a new one."""
    global _engine, _async_session_maker
    loop = _running_loop()
    target: AsyncEngine | None
    with _engine_lock:
        if loop is None:
            target = _engine
            _engine = None
            _async_session_maker = None
        else:
            target = _engines.pop(loop, None)
            _session_makers.pop(loop, None)
    if target is not None:
        await target.dispose()


async def dispose_all_engines() -> None:
    """Dispose all cached per-loop and fallback engines cleanly."""
    global _engine, _async_session_maker
    targets: list[AsyncEngine] = []
    with _engine_lock:
        if _engine is not None:
            targets.append(_engine)
            _engine = None
        _async_session_maker = None
        targets.extend(_engines.values())
        _engines.clear()
        _session_makers.clear()
    for target in targets:
        try:
            await target.dispose()
        except Exception:
            logger.exception("Failed to dispose SQLAlchemy engine cleanly")


class _EngineProxy:
    """Proxy that lazily resolves the real engine on first use."""

    def __getattr__(self, name):
        return getattr(_get_engine(), name)

    def begin(self):
        return _get_engine().begin()

    async def dispose(self):
        return await dispose_current_loop_engine()


class _SessionMakerProxy:
    """Proxy that lazily resolves the real session maker on first use."""

    def __call__(self, *args, **kwargs):
        return _get_session_maker()(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(_get_session_maker(), name)


engine = _EngineProxy()
async_session_maker = _SessionMakerProxy()


class Base(DeclarativeBase):
    """ORM base class for all SQLAlchemy models."""

    pass


async def ensure_schema_compatibility() -> None:
    """Patch legacy databases with columns required by the current ORM schema."""
    async with engine.begin() as conn:
        await conn.run_sync(run_all_schema_compatibility_sync)


async def create_tables() -> None:
    """Create all ORM tables."""
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(run_all_schema_compatibility_sync)


async def init_db():
    """Initialize database tables (retained for test/script compatibility)."""
    await create_tables()


async def verify_database_connection() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))


async def verify_database_schema() -> None:
    """Verify database revision using read-only queries only."""
    from app.db.schema_readiness import verify_database_revision

    await verify_database_revision(cast(AsyncEngine, engine))


async def ensure_database_ready() -> None:
    """Prepare explicitly configured dev schema or verify deployed schema."""
    if settings.DB_AUTO_CREATE_SCHEMA:
        await create_tables()
    else:
        await verify_database_schema()
    if settings.DB_AUTO_CREATE_DEFAULT_ADMIN:
        logger.warning(
            "DB_AUTO_CREATE_DEFAULT_ADMIN is ignored during application startup; "
            "run `python -m app.db.bootstrap_admin` explicitly after migrations"
        )


async def create_default_admin() -> None:
    """Create the configured administrator only when its username is unused."""
    from app.models.permission import Role, user_roles
    from app.models.user import User
    from app.utils.security import get_password_hash

    local_settings = get_settings()

    async def find_existing_admin(session: AsyncSession) -> User | None:
        """Resolve configured username using the active database collation."""
        result = await session.execute(
            select(User).where(User.username == local_settings.ADMIN_USERNAME).limit(2)
        )
        matches = list(result.scalars().all())
        if not matches:
            configured_identity = normalize_reserved_username(local_settings.ADMIN_USERNAME)
            all_users = await session.execute(select(User))
            aliases = [
                user
                for user in all_users.scalars().all()
                if normalize_reserved_username(cast(str, user.username)) == configured_identity
            ]
            if aliases:
                raise RuntimeError(
                    "Default admin bootstrap refused: an existing account has a username "
                    "equivalent to the configured name under conservative normalization."
                )
            return None
        if len(matches) != 1:
            raise RuntimeError(
                "Default admin bootstrap refused: configured username matches multiple accounts."
            )

        existing_user = matches[0]
        if existing_user.username != local_settings.ADMIN_USERNAME:
            raise RuntimeError(
                "Default admin bootstrap refused: configured username resolves to a differently "
                "spelled account under the database collation."
            )

        role_result = await session.execute(
            select(user_roles.c.role).where(
                user_roles.c.user_id == existing_user.id,
                user_roles.c.role == Role.ADMIN.value,
            )
        )
        if role_result.scalar_one_or_none() is None:
            raise RuntimeError(
                "Default admin bootstrap refused: the existing configured account has no ADMIN "
                "role; verify ownership before granting privileges through a separate process."
            )
        return existing_user

    try:
        async with async_session_maker() as session:
            existing_user = await find_existing_admin(session)
            if existing_user is not None:
                return

            admin_user = User(
                username=local_settings.ADMIN_USERNAME,
                email=local_settings.ADMIN_EMAIL,
                hashed_password=get_password_hash(local_settings.ADMIN_PASSWORD),
                is_active=True,
            )
            session.add(admin_user)
            await session.flush()
            await session.execute(
                insert(user_roles).values(user_id=admin_user.id, role=Role.ADMIN.value)
            )
            await session.commit()
            logger.info("Default admin account created")
    except IntegrityError:
        async with async_session_maker() as retry_session:
            concurrent_admin = await find_existing_admin(retry_session)
            if concurrent_admin is not None:
                logger.info("Default admin bootstrap completed by a concurrent process")
                return
        raise RuntimeError(
            "Default admin bootstrap conflicted with an existing username or email."
        ) from None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
