"""JWT, rate-limit and bootstrap-admin credential settings.

Authentication credentials: the JWT signing key and lifetime, the slowapi
rate-limit strings, and the bootstrap admin account.

Extracted verbatim from :class:`app.config.Settings`: same field names,
annotations, defaults, constraint metadata and validators. The composed
:class:`app.config.Settings` collects the sections in repository order, so a
field's env-var name is unchanged, and pydantic collects a ``field_validator``
declared on a section mixin and runs it on the composed model.

No behaviour lives here: these are settings declarations only.
"""

from pydantic import Field, field_validator


class SecurityAuthSettingsMixin:
    """JWT, rate-limit and bootstrap-admin credential settings."""

    # JWT settings
    JWT_SECRET_KEY: str = Field(
        default="your-jwt-secret-change-in-production",
        description="JWT secret key (CHANGE IN PRODUCTION)",
    )

    JWT_ALGORITHM: str = Field(default="HS256", description="JWT encryption algorithm")

    JWT_EXPIRE_MINUTES: int = Field(
        default=60, description="JWT token expiration in minutes (default 1 hour)"
    )

    # Rate limiting (slowapi limit strings). E2E environments can raise these
    # quotas explicitly without weakening production brute-force protection.
    RATE_LIMIT_REGISTER: str = Field(
        default="5/hour", description="Rate limit for POST /auth/register (slowapi string)"
    )

    RATE_LIMIT_LOGIN: str = Field(
        default="10/minute", description="Rate limit for POST /auth/login (slowapi string)"
    )

    RATE_LIMIT_AUTH_ME: str = Field(
        default="60/minute", description="Rate limit for GET /auth/me (slowapi string)"
    )

    # Default admin account
    ADMIN_USERNAME: str = Field(default="admin", description="Default admin username")

    ADMIN_PASSWORD: str = Field(
        default="admin123", description="Default admin password (CHANGE IN PRODUCTION)"
    )

    ADMIN_EMAIL: str = Field(default="admin@example.com", description="Default admin email")

    @field_validator("JWT_EXPIRE_MINUTES")
    @classmethod
    def validate_jwt_expiration(cls, v: int) -> int:
        """Validate that JWT expiration is reasonable."""
        if not (5 <= v <= 10080):  # 5 minutes to 7 days
            raise ValueError(
                f"JWT_EXPIRE_MINUTES must be between 5 and 10080 (5 min to 7 days), got: {v}"
            )
        return v
