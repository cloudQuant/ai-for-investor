"""Logging, audit, monitoring, orchestration and sandbox settings.

Operational plane: log format, level, directory and retention, audit-record
policy, monitoring check intervals, the Airflow orchestration integration
and the AI strategy sandbox.

Extracted verbatim from :class:`app.config.Settings`: same field names,
annotations, defaults, constraint metadata and validators. The composed
:class:`app.config.Settings` collects the sections in repository order, so a
field's env-var name is unchanged, and pydantic collects a ``field_validator``
declared on a section mixin and runs it on the composed model.

No behaviour lives here: these are settings declarations only.
"""

from pydantic import Field


class OperationsSettingsMixin:
    """Logging, audit, monitoring, orchestration and sandbox settings."""

    # Backtest subprocess timeout (seconds)
    BACKTEST_TIMEOUT: int = Field(default=300, description="Backtest subprocess timeout in seconds")

    AI_STRATEGY_SANDBOX_USE_DOCKER: bool = Field(
        default=True,
        description="Require Docker isolation for AI strategy draft validation in production",
    )

    AI_STRATEGY_SANDBOX_DOCKER_IMAGE: str = Field(
        default="backtrader-sandbox:latest",
        description="Docker image used for AI strategy draft validation",
    )

    # Monitoring check intervals (seconds)
    MONITORING_SYSTEM_INTERVAL: int = Field(
        default=300, description="System alert check interval in seconds"
    )

    MONITORING_ACCOUNT_INTERVAL: int = Field(
        default=30, description="Account/Position alert check interval in seconds"
    )

    MONITORING_STRATEGY_INTERVAL: int = Field(
        default=60, description="Strategy alert check interval in seconds"
    )

    MONITORING_DEFAULT_INTERVAL: int = Field(
        default=60, description="Default alert check interval in seconds"
    )

    # Logging format: "json" for structured JSON, "text" for plain text.
    # If unset, falls back to DEBUG-based default (DEBUG=true → colored text, DEBUG=false → JSON).
    LOG_FORMAT: str = Field(
        default="",
        description="Log output format: 'json' for structured JSON, 'text' for plain text, "
        "empty for auto-detection based on DEBUG flag",
    )

    # Log level override: when set, overrides the DEBUG-based default level.
    # Valid values: DEBUG, INFO, WARNING, ERROR, CRITICAL (case-insensitive).
    LOG_LEVEL: str = Field(
        default="",
        description="Explicit log level override. Empty = auto (DEBUG→DEBUG, prod→WARNING/INFO)",
    )

    # Log output directory
    LOG_DIR: str = Field(default="./logs", description="Log output directory path")

    # Log retention periods per category (days)
    LOG_RETENTION_APP_DAYS: int = Field(default=30, description="Application log retention in days")

    LOG_RETENTION_ERROR_DAYS: int = Field(default=90, description="Error log retention in days")

    LOG_RETENTION_AUDIT_DAYS: int = Field(default=365, description="Audit log retention in days")

    LOG_ROTATION_MAX_MB: int = Field(
        default=100,
        description="Maximum size in MB for each dated log file before rotation; 0 disables size cap",
    )

    # Audit settings
    AUDIT_RETENTION_DAYS: int = Field(
        default=90, description="Database audit record retention in days (7-365)"
    )

    AUDIT_CLEANUP_HOUR: int = Field(
        default=2, description="Hour of day to run audit cleanup (0-23)"
    )

    AUDIT_EVENT_MAX_SIZE_KB: int = Field(
        default=10, description="Maximum size of a single audit event_data in KB (1-100)"
    )

    # Airflow integration settings
    AIRFLOW_API_BASE_URL: str = Field(
        default="", description="Airflow REST API base URL (e.g. http://localhost:8080/api/v1)"
    )

    AIRFLOW_USERNAME: str = Field(default="admin", description="Airflow API username")

    AIRFLOW_PASSWORD: str = Field(default="", description="Airflow API password")

    ORCHESTRATION_BACKEND: str = Field(
        default="auto",
        description="Orchestration backend: airflow, apscheduler, auto (auto-detect)",
    )

    AIRFLOW_DAG_OUTPUT_DIR: str = Field(
        default="./dags", description="Directory for generated Airflow DAG files"
    )

    AIRFLOW_CALLBACK_BASE_URL: str = Field(
        default="http://localhost:8000",
        description="Base URL for Airflow task callbacks to ai-for-investor",
    )
