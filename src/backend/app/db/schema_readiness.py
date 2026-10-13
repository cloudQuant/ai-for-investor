"""Read-only checks for the Alembic revision required by this application."""

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def get_alembic_heads() -> frozenset[str]:
    """Return current migration heads from the packaged Alembic graph."""
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


async def verify_database_revision(engine: AsyncEngine) -> None:
    """Check connectivity and exact Alembic head without issuing database DDL."""
    expected = get_alembic_heads()
    if not expected:
        raise RuntimeError("No Alembic migration heads are packaged with this application")

    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
        try:
            result = await connection.execute(text("SELECT version_num FROM alembic_version"))
        except SQLAlchemyError as exc:
            raise RuntimeError(
                "Database schema is not versioned; run the one-off `alembic upgrade head` "
                "migration job before starting application workers"
            ) from exc
        actual = frozenset(result.scalars().all())

    if actual != expected:
        raise RuntimeError(
            "Database migration revision mismatch: "
            f"expected heads {sorted(expected)}, found {sorted(actual)}; "
            "run the one-off `alembic upgrade head` migration job before starting "
            "application workers"
        )
