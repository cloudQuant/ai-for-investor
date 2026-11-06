"""Application identity, HTTP bind address, CORS and outbound proxy settings.

Server identity, the loopback-by-default HTTP bind address, the CORS
origin list and the outbound proxy knobs.

Extracted verbatim from :class:`app.config.Settings`: same field names,
annotations, defaults, constraint metadata and validators. The composed
:class:`app.config.Settings` collects the sections in repository order, so a
field's env-var name is unchanged, and pydantic collects a ``field_validator``
declared on a section mixin and runs it on the composed model.

No behaviour lives here: these are settings declarations only.
"""

from pydantic import Field, field_validator


class ApplicationSettingsMixin:
    """Application identity, HTTP bind address, CORS and outbound proxy settings."""

    # App settings
    APP_NAME: str = "ai-for-investor"

    DEBUG: bool = Field(default=False, description="Debug mode (must remain False in production)")

    SECRET_KEY: str = Field(
        default="your-secret-key-change-in-production",
        description="Secret key for encryption (CHANGE IN PRODUCTION)",
    )

    HTTP_PROXY: str = Field(default="", description="HTTP proxy URL")

    HTTPS_PROXY: str = Field(default="", description="HTTPS proxy URL")

    SOCKS_PROXY: str = Field(default="", description="SOCKS proxy URL")

    PROXY_HOST: str = Field(default="", description="Proxy host with optional scheme")

    NO_PROXY: str = Field(default="", description="No proxy hosts")

    # Service settings
    # NOTE: defaults to 127.0.0.1 (loopback) for safety. Production / docker
    # deployments should override via HOST=0.0.0.0 in their env files.
    HOST: str = Field(
        default="127.0.0.1",
        description="Server host address (override to 0.0.0.0 in containers/production)",
    )

    PORT: int = Field(default=8000, description="Server port")

    # Graceful shutdown timeout (seconds)
    SHUTDOWN_TIMEOUT: int = Field(
        default=30,
        description="Graceful shutdown timeout in seconds (range 1-300)",
    )

    # CORS allowed origins (comma-separated)
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000", description="Comma-separated list of allowed CORS origins"
    )

    @field_validator("PORT")
    @classmethod
    def validate_port_range(cls, v: int) -> int:
        """Validate that port is in valid range."""
        if not (1 <= v <= 65535):
            raise ValueError(f"PORT must be between 1 and 65535, got: {v}")
        return v

    @field_validator("SHUTDOWN_TIMEOUT")
    @classmethod
    def validate_shutdown_timeout(cls, v: int) -> int:
        """Validate that shutdown timeout is in valid range (1-300)."""
        if not (1 <= v <= 300):
            import logging

            logging.getLogger(__name__).warning(
                "SHUTDOWN_TIMEOUT=%d is out of range (1-300), using default 30s", v
            )
            return 30
        return v

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, v: str) -> str:
        """Validate that CORS origins are properly formatted."""
        if not v:
            raise ValueError("CORS_ORIGINS cannot be empty")

        origins = [o.strip() for o in v.split(",") if o.strip()]
        for origin in origins:
            if origin == "*":
                continue  # Wildcard is acceptable
            if not origin.startswith(("http://", "https://")):
                raise ValueError(
                    f"Invalid CORS origin: '{origin}'. Origins must start with http:// or https://"
                )

        return v
