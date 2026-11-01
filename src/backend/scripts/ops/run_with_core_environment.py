"""Run a child command with only declared application settings in its environment."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

CORE_RUNTIME_ENV_KEYS: frozenset[str] = frozenset(
    {
        "AI_RESEARCH_PROTOCOL_V2_ENABLED",
        "AI_RESEARCH_PROTOCOL_V2_HOLDOUT_WORKER_ENABLED",
        "AI_RESEARCH_PROTOCOL_V2_WORKER_ENABLED",
        "AKSHARE_DATA_DATABASE_URL",
        "AKSHARE_INTERFACE_BOOTSTRAP_MODE",
        "AKSHARE_SCHEDULER_LEASE_SECONDS",
        "AKSHARE_SCHEDULER_MAX_CONCURRENT_TASKS",
        "AKSHARE_SCHEDULER_PER_SOURCE_CONCURRENT_TASKS",
        "AKSHARE_SCHEDULER_RETRY_BASE_SECONDS",
        "AKSHARE_SCHEDULER_RETRY_MAX_SECONDS",
        "AKSHARE_SCHEDULER_SOURCE_MIN_INTERVAL_SECONDS",
        "AKSHARE_SCHEDULER_TIMEZONE",
        "AKSHARE_SCRIPT_ROOT",
        "ASSET_RESEARCH_OUTCOME_EVALUATOR_ENABLED",
        "ASSET_RESEARCH_SCHEDULE_ENABLED",
        "ASSET_RESEARCH_TASK_RUNNER_ENABLED",
        "DATABASE_TYPE",
        "DATABASE_URL",
        "DB_AUTO_CREATE_DEFAULT_ADMIN",
        "DB_AUTO_CREATE_SCHEMA",
        "DEBUG",
        "HOST",
        "JWT_SECRET_KEY",
        "MARKET_DATA_ONLINE_FETCH_ENABLED",
        "MARKET_DATA_OPENDATA_ENABLED",
        "MARKET_DATA_QUERY_V2_ENABLED",
        "MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED",
        "MARKET_DATA_RESEARCH_CACHE_FILL_ENABLED",
        "MARKET_DATA_THS_ENABLED",
        "MARKET_DATA_THS_SCHEDULER_ENABLED",
        "MARKET_DATA_THS_SCHEDULER_HOUR",
        "MARKET_DATA_THS_SCHEDULER_MINUTE",
        "MARKET_DATA_THS_SCHEDULER_TIMEZONE",
        "ORCHESTRATION_BACKEND",
        "PORT",
        "SECRET_KEY",
        "SQL_ECHO",
        "STOCK_SIGNAL_SCHEDULE_CRON",
        "STOCK_SIGNAL_SCHEDULE_ENABLED",
        "STOCK_SIGNAL_SCHEDULE_TIMEZONE",
        "SYNC_LOCAL_MYSQL_HOST",
        "SYNC_LOCAL_MYSQL_PASSWORD",
        "SYNC_LOCAL_MYSQL_PORT",
        "SYNC_LOCAL_MYSQL_USER",
    }
)

_BASE_ENV_KEYS: frozenset[str] = frozenset(
    {
        "HOME",
        "PATH",
        "PYTHONUNBUFFERED",
        "TZ",
    }
)


def declared_setting_environment_keys() -> frozenset[str]:
    """Include declared project settings without forwarding arbitrary SDK credentials."""
    backend_root = Path(__file__).resolve().parents[2]
    backend_root_text = str(backend_root)
    if backend_root_text not in sys.path:
        sys.path.insert(0, backend_root_text)

    from app.config import Settings

    names = set(Settings.model_fields)
    prefix = str(Settings.model_config.get("env_prefix") or "")
    for name, field in Settings.model_fields.items():
        names.add(prefix + name)
        for alias in (field.alias, field.validation_alias):
            if isinstance(alias, str):
                names.add(alias)
            for choice in getattr(alias, "choices", ()):
                if isinstance(choice, str):
                    names.add(choice)
    return frozenset(names)


def filtered_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Keep only process basics and reviewed app/database/scheduler settings."""
    allowed = _BASE_ENV_KEYS | CORE_RUNTIME_ENV_KEYS | declared_setting_environment_keys()
    return {key: value for key, value in source.items() if key in allowed}


def main(argv: Sequence[str] | None = None) -> None:
    """Replace this wrapper with the requested child command."""
    command = list(sys.argv[1:] if argv is None else argv)
    if not command:
        raise SystemExit("usage: run_with_core_environment.py COMMAND [ARG ...]")
    os.execvpe(command[0], command, filtered_environment(dict(os.environ)))


if __name__ == "__main__":
    main()
