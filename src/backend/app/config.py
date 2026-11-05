"""
Configuration management - Load configuration from environment variables.

The settings fields live in cohesive section modules under ``app.settings`` and
are composed into the single :class:`Settings` model below. This module remains
the import surface of the whole configuration: ``from app.config import Settings,
get_settings, production_security_mode`` and every ``settings.<FIELD>`` access work
exactly as before the split, and the env-file, validation and singleton behaviour
are unchanged.
"""

import os
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.settings.ai_assistant import AiAssistantSettingsMixin
from app.settings.ai_research_v2 import AiResearchV2SettingsMixin
from app.settings.application import ApplicationSettingsMixin
from app.settings.asset_research import AssetResearchSettingsMixin
from app.settings.broker_accounts import BrokerAccountSettingsMixin
from app.settings.database import DatabaseSettingsMixin
from app.settings.market_data import MarketDataSettingsMixin
from app.settings.operations import OperationsSettingsMixin
from app.settings.paths import REPO_ROOT as _REPO_ROOT
from app.settings.security_auth import SecurityAuthSettingsMixin
from app.settings.service_deployments import ServiceDeploymentSecretsMixin

_DEFAULT_SECRETS = frozenset(
    {
        "your-secret-key-change-in-production",
        "your-jwt-secret-change-in-production",
        # Public Docker/repository example values are equally predictable and
        # must never satisfy a server-owned provenance or production-secret
        # check merely because their wording happens to exceed 32 characters.
        "replace-with-a-random-secret-key-at-least-32-chars",
        "replace-with-a-random-jwt-secret-at-least-32-chars",
    }
)

_DEFAULT_PASSWORDS = frozenset({"admin123", "password", "12345678"})


def _coerce_bool(value: object) -> bool | None:
    """Coerce common boolean-like values from settings inputs or env vars."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


def _is_production(debug: object | None = None, *, debug_was_explicit: bool = False) -> bool:
    """Check if the application should apply production-only safeguards."""
    normalized_debug = _coerce_bool(debug)
    if debug_was_explicit and normalized_debug is not None:
        return not normalized_debug
    env_debug = _coerce_bool(os.environ.get("DEBUG"))
    if env_debug is not None:
        return not env_debug
    return False


def production_security_mode(settings: "Settings") -> bool:
    """Return whether production-only runtime security guards apply."""
    return _is_production(
        settings.DEBUG,
        debug_was_explicit="DEBUG" in settings.model_fields_set,
    )


class Settings(
    BrokerAccountSettingsMixin,
    OperationsSettingsMixin,
    ServiceDeploymentSecretsMixin,
    AiAssistantSettingsMixin,
    AiResearchV2SettingsMixin,
    AssetResearchSettingsMixin,
    MarketDataSettingsMixin,
    DatabaseSettingsMixin,
    SecurityAuthSettingsMixin,
    ApplicationSettingsMixin,
    BaseSettings,
):
    """Application settings.

    Attributes:
        APP_NAME: Application name.
        DEBUG: Debug mode flag.
        SECRET_KEY: Secret key for encryption.
        DATABASE_TYPE: Database type (postgresql, mysql, mongodb, sqlite).
        DATABASE_URL: Database connection URL.
        DOCUMENT_DB_TYPE: Optional document database type.
        DOCUMENT_DB_URL: Optional document database URL.
        TIMESERIES_DB_TYPE: Optional timeseries database type.
        TIMESERIES_DB_URL: Optional timeseries database URL.
        REDIS_URL: Optional Redis cache URL.
        JWT_SECRET_KEY: JWT secret key.
        JWT_ALGORITHM: JWT encryption algorithm.
        JWT_EXPIRE_MINUTES: JWT token expiration time in minutes.
        HOST: Server host address.
        PORT: Server port.
        BACKTEST_TIMEOUT: Backtest subprocess timeout in seconds.
        CORS_ORIGINS: Comma-separated list of allowed CORS origins.
        SQL_ECHO: Whether to echo SQL statements.
        ADMIN_USERNAME: Default admin username.
        ADMIN_PASSWORD: Default admin password.
        ADMIN_EMAIL: Default admin email.
    """

    model_config = SettingsConfigDict(
        env_file=(
            ".env",
            str(_REPO_ROOT / ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_runtime_security_guards(self) -> "Settings":
        """Validate production-only secret and admin-password guards."""
        if self.MARKET_DATA_QUERY_V2_ENABLED and not self.MARKET_DATA_CURSOR_SIGNING_KEY:
            raise ValueError(
                "MARKET_DATA_CURSOR_SIGNING_KEY is required when MARKET_DATA_QUERY_V2_ENABLED=true"
            )
        if self.MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED:
            if not self.MARKET_DATA_QUERY_V2_ENABLED:
                raise ValueError(
                    "MARKET_DATA_QUERY_V2_ENABLED is required when "
                    "MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED=true"
                )
            if len(self.MARKET_DATA_RESEARCH_ARTIFACT_SIGNING_KEY.encode("utf-8")) < 32:
                raise ValueError(
                    "MARKET_DATA_RESEARCH_ARTIFACT_SIGNING_KEY must be at least 32 bytes when "
                    "MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED=true"
                )
            artifact_root = Path(self.MARKET_DATA_RESEARCH_ARTIFACT_ROOT).expanduser()
            if not artifact_root.is_absolute():
                raise ValueError(
                    "MARKET_DATA_RESEARCH_ARTIFACT_ROOT must be an absolute path when "
                    "MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED=true"
                )
        if production_security_mode(self):
            cors_origins = {
                origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
            }
            if "*" in cors_origins:
                raise ValueError(
                    "Wildcard CORS origin is not allowed in production when credentials are enabled. "
                    "Set CORS_ORIGINS to explicit http:// or https:// origins."
                )
            for field_name in ("SECRET_KEY", "JWT_SECRET_KEY"):
                if getattr(self, field_name) in _DEFAULT_SECRETS:
                    raise ValueError(
                        f"Default secret key detected (ENV: {field_name}). "
                        "Please set a secure random key via environment variable in production."
                    )
            if self.ADMIN_PASSWORD.lower() in _DEFAULT_PASSWORDS:
                raise ValueError(
                    "Default admin password detected. Set ADMIN_PASSWORD to a secure password in production."
                )
            for field_name in (
                "IB_VERIFY_SSL",
                "IB_WEB_VERIFY_SSL",
                "IB_PAPER_VERIFY_SSL",
                "IB_LIVE_VERIFY_SSL",
            ):
                if not getattr(self, field_name):
                    raise ValueError(
                        f"{field_name}=False is not allowed in production. "
                        "Install the gateway CA certificate and enable TLS verification."
                    )
            if not self.AI_STRATEGY_SANDBOX_USE_DOCKER:
                raise ValueError(
                    "AI_STRATEGY_SANDBOX_USE_DOCKER must be enabled in production. "
                    "AI-generated strategy code cannot run in the application process."
                )
        return self

    @field_validator("SECRET_KEY", "JWT_SECRET_KEY")
    @classmethod
    def validate_secrets_length(cls, v: str, info) -> str:
        """Validate that secret keys have sufficient length."""
        min_length = 32
        if len(v) < min_length:
            raise ValueError(
                f"{info.field_name} must be at least {min_length} characters long "
                f"for security. Current length: {len(v)}"
            )
        return v


# Use simple cache to avoid lru_cache issues in pydantic-settings v2
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the configuration singleton.

    Returns:
        The Settings instance.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
