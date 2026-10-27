"""Tests for the environment-filtering process wrapper."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_WRAPPER_PATH = _BACKEND_ROOT / "scripts" / "ops" / "run_with_core_environment.py"
_SPEC = importlib.util.spec_from_file_location("run_with_core_environment", _WRAPPER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
wrapper = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wrapper)


def _install_settings_stub(
    monkeypatch: pytest.MonkeyPatch,
    fields: dict[str, Any],
    model_config: dict[str, Any],
) -> None:
    """Provide Settings metadata without importing application configuration or dotenv."""
    app_module = ModuleType("app")
    app_module.__path__ = []  # type: ignore[attr-defined]
    config_module = ModuleType("app.config")
    config_module.Settings = SimpleNamespace(  # type: ignore[attr-defined]
        model_fields=fields,
        model_config=model_config,
    )
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.config", config_module)


def test_static_environment_allowlists_match_the_recovered_contract() -> None:
    assert wrapper._BASE_ENV_KEYS == {"HOME", "PATH", "PYTHONUNBUFFERED", "TZ"}
    assert wrapper.CORE_RUNTIME_ENV_KEYS == {
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


def test_declared_setting_keys_include_prefix_alias_and_alias_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_settings_stub(
        monkeypatch,
        {
            "SERVICE_MODE": SimpleNamespace(
                alias="SERVICE_MODE_ALIAS",
                validation_alias=SimpleNamespace(choices=("SERVICE_MODE_LEGACY", 17)),
            ),
            "PORT": SimpleNamespace(alias=None, validation_alias=None),
        },
        {"env_prefix": "APP_"},
    )
    monkeypatch.setattr(wrapper.sys, "path", [])

    keys = wrapper.declared_setting_environment_keys()

    assert keys == {
        "SERVICE_MODE",
        "PORT",
        "APP_SERVICE_MODE",
        "APP_PORT",
        "SERVICE_MODE_ALIAS",
        "SERVICE_MODE_LEGACY",
    }
    assert wrapper.sys.path[0] == str(_BACKEND_ROOT)


def test_filtered_environment_keeps_allowed_values_and_drops_unknown_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        wrapper,
        "declared_setting_environment_keys",
        lambda: frozenset({"CUSTOM_ALIAS"}),
    )
    source = {
        "HOME": "home-sentinel",
        "DATABASE_URL": "dsn-sentinel",
        "CUSTOM_ALIAS": "alias-sentinel",
        "UNDECLARED_SDK_TOKEN": "untrusted-sentinel",
    }

    filtered = wrapper.filtered_environment(source)

    assert filtered == {
        "HOME": "home-sentinel",
        "DATABASE_URL": "dsn-sentinel",
        "CUSTOM_ALIAS": "alias-sentinel",
    }
    assert source["UNDECLARED_SDK_TOKEN"] == "untrusted-sentinel"


def test_main_execs_requested_command_with_only_filtered_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        wrapper,
        "declared_setting_environment_keys",
        lambda: frozenset({"CUSTOM_ALIAS"}),
    )
    monkeypatch.setattr(
        wrapper.os,
        "environ",
        {
            "PATH": "path-sentinel",
            "CUSTOM_ALIAS": "alias-sentinel",
            "UNDECLARED_SDK_TOKEN": "untrusted-sentinel",
        },
    )
    captured: dict[str, Any] = {}

    def capture_execvpe(
        file: str,
        args: list[str],
        env: dict[str, str],
    ) -> None:
        captured.update(file=file, args=args, env=env)

    monkeypatch.setattr(wrapper.os, "execvpe", capture_execvpe)

    wrapper.main(["python", "-c", "print('sentinel')"])

    assert captured == {
        "file": "python",
        "args": ["python", "-c", "print('sentinel')"],
        "env": {"PATH": "path-sentinel", "CUSTOM_ALIAS": "alias-sentinel"},
    }


def test_main_uses_sys_argv_when_argument_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wrapper, "declared_setting_environment_keys", lambda: frozenset())
    monkeypatch.setattr(wrapper.sys, "argv", ["wrapper.py", "python", "-V"])
    monkeypatch.setattr(wrapper.os, "environ", {"PATH": "path-sentinel"})
    captured: dict[str, Any] = {}

    def capture_execvpe(
        file: str,
        args: list[str],
        env: dict[str, str],
    ) -> None:
        captured.update(file=file, args=args, env=env)

    monkeypatch.setattr(wrapper.os, "execvpe", capture_execvpe)

    wrapper.main()

    assert captured == {
        "file": "python",
        "args": ["python", "-V"],
        "env": {"PATH": "path-sentinel"},
    }


def test_main_rejects_an_empty_command_without_executing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_execvpe(file: str, args: list[str], env: dict[str, str]) -> None:
        pytest.fail("execvpe must not be called for an empty command")

    monkeypatch.setattr(wrapper.os, "execvpe", unexpected_execvpe)

    with pytest.raises(SystemExit, match="usage: run_with_core_environment.py COMMAND"):
        wrapper.main([])
