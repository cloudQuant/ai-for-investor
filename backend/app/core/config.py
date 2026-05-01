from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    APP_NAME: str = "ai-for-investor"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    SITE_URL: str = "http://localhost:3000"

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: list[str] = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    CORS_HEADERS: list[str] = ["Authorization", "Content-Type", "X-CSRF-Token"]

    SECRET_KEY: str = Field(min_length=1)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    IDLE_TIMEOUT_MINUTES: int = 30
    ABSOLUTE_TIMEOUT_HOURS: int = 24

    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_REQUIRE_UPPERCASE: bool = True
    PASSWORD_REQUIRE_LOWERCASE: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_SPECIAL: bool = False

    ARGON2_MEMORY_COST: int = 65536
    ARGON2_TIME_COST: int = 3
    ARGON2_PARALLELISM: int = 4

    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_TOKEN_EXPIRE_HOURS: int = 1

    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = Field(min_length=1)
    MYSQL_PASSWORD: str = Field(min_length=1)
    MYSQL_DATABASE: str = Field(min_length=1)

    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DATABASE: str = "ai_for_investor"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    GITHUB_TOKEN: str = ""

    TENCENT_COS_SECRET_ID: str = ""
    TENCENT_COS_SECRET_KEY: str = ""
    TENCENT_COS_BUCKET: str = ""
    TENCENT_COS_REGION: str = ""

    SENTRY_DSN: str = ""

    RATE_LIMIT_LOGIN_MAX: int = 5
    RATE_LIMIT_LOGIN_WINDOW_MINUTES: int = 15
    RATE_LIMIT_REGISTER_MAX: int = 3
    RATE_LIMIT_REGISTER_WINDOW_MINUTES: int = 60
    RATE_LIMIT_API_MAX: int = 100
    RATE_LIMIT_API_WINDOW_MINUTES: int = 1

    TOOL_CONTAINER_CPU_LIMIT: int = 1
    TOOL_CONTAINER_MEMORY_MB: int = 1024
    TOOL_CONTAINER_TIMEOUT_SECONDS: int = 120

    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
