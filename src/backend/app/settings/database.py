"""Relational, document, timeseries and cache connection settings.

Storage connections: the primary relational database, the akshare data
warehouse, the legacy migration targets, and the optional document,
timeseries and Redis caches.

Extracted verbatim from :class:`app.config.Settings`: same field names,
annotations, defaults, constraint metadata and validators. The composed
:class:`app.config.Settings` collects the sections in repository order, so a
field's env-var name is unchanged, and pydantic collects a ``field_validator``
declared on a section mixin and runs it on the composed model.

No behaviour lives here: these are settings declarations only.
"""

from pydantic import Field, field_validator

from app.settings.paths import DEFAULT_SQLITE_DATABASE_URL as _DEFAULT_SQLITE_DATABASE_URL


class DatabaseSettingsMixin:
    """Relational, document, timeseries and cache connection settings."""

    # Database settings
    DATABASE_TYPE: str = Field(
        default="sqlite", description="Database type: postgresql, mysql, mongodb, sqlite"
    )

    DATABASE_URL: str = Field(
        default=_DEFAULT_SQLITE_DATABASE_URL, description="Database connection URL"
    )

    AKSHARE_DATA_DATABASE_URL: str = Field(
        default="", description="Akshare data warehouse database connection URL"
    )

    LEGACY_SQLITE_DATABASE_URL: str = Field(
        default="", description="Legacy SQLite database connection URL used during migration"
    )

    LEGACY_AKSHARE_DATABASE_URL: str = Field(
        default="", description="Legacy akshare_web database connection URL used during migration"
    )

    DB_AUTO_CREATE_SCHEMA: bool = Field(default=False)

    DB_AUTO_CREATE_DEFAULT_ADMIN: bool = Field(default=False)

    # Optional: Document database
    DOCUMENT_DB_TYPE: str | None = Field(default=None, description="Document database type")

    DOCUMENT_DB_URL: str | None = Field(default=None, description="Document database URL")

    # Optional: Timeseries database
    TIMESERIES_DB_TYPE: str | None = Field(default=None, description="Timeseries database type")

    TIMESERIES_DB_URL: str | None = Field(default=None, description="Timeseries database URL")

    # Optional: Redis cache
    REDIS_URL: str | None = Field(default=None, description="Redis cache URL")

    # SQL logging (independent of DEBUG to avoid too much noise)
    SQL_ECHO: bool = Field(default=False, description="Enable SQLAlchemy query logging")

    SYNC_LOCAL_MYSQL_HOST: str = Field(
        default="127.0.0.1", description="Local MySQL host for data sync"
    )

    SYNC_LOCAL_MYSQL_PORT: int = Field(default=3306, description="Local MySQL port for data sync")

    SYNC_LOCAL_MYSQL_USER: str = Field(default="root", description="Local MySQL user for data sync")

    SYNC_LOCAL_MYSQL_PASSWORD: str = Field(
        default="", description="Local MySQL password for data sync"
    )

    @field_validator("DATABASE_TYPE")
    @classmethod
    def validate_database_type(cls, v: str) -> str:
        """Validate that database type is supported."""
        supported_databases = {"sqlite", "postgresql", "mysql"}
        if v.lower() not in supported_databases:
            raise ValueError(
                f"Unsupported DATABASE_TYPE: {v}. Supported types: {', '.join(supported_databases)}"
            )
        return v.lower()
