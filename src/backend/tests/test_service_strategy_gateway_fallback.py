"""The live strategy builder must not fall back to legacy GatewayRuntime."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.gateway import runtime as gateway_runtime_service
from app.services.live_trading import manager as manager_module
from app.services.live_trading.service_execution_launch import (
    SERVICE_EXECUTION_PROFILE_MAP_ENV,
    ServiceStrategyProfileError,
)


def test_unconfigured_live_strategy_fails_before_legacy_gateway_builder(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    manager = object.__new__(manager_module.LiveTradingManager)
    instance = {
        "id": "instance-live",
        "strategy_id": "strategy-live",
        "user_id": "subject-live",
        "_server_execution_mode": "live",
        "_server_allow_service_strategy_execution": True,
    }
    monkeypatch.delenv(SERVICE_EXECUTION_PROFILE_MAP_ENV, raising=False)

    def old_gateway_path_must_not_run(*_args, **_kwargs):
        pytest.fail("unconfigured live strategy entered the legacy gateway path")

    monkeypatch.setattr(
        gateway_runtime_service, "build_subprocess_env", old_gateway_path_must_not_run
    )
    monkeypatch.setattr(manager, "_load_strategy_config", old_gateway_path_must_not_run)
    monkeypatch.setattr(manager, "_import_gateway_runtime_classes", old_gateway_path_must_not_run)

    with pytest.raises(ServiceStrategyProfileError) as raised:
        manager._build_subprocess_env("instance-live", instance, tmp_path)

    assert raised.value.code == "SERVICE_EXECUTION_PROFILE_REQUIRED"
    assert "ServiceExecutionSession" in str(raised.value)
    assert "service-v2 owner grant" in str(raised.value)

    with pytest.raises(ServiceStrategyProfileError) as builder_error:
        manager._build_gateway_launch(instance, tmp_path, {})

    assert builder_error.value.code == "SERVICE_EXECUTION_PROFILE_REQUIRED"


def test_simulation_without_gateway_keeps_research_environment_without_runtime_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    manager = object.__new__(manager_module.LiveTradingManager)
    manager._acquire_gateway_for_instance = lambda *_args, **_kwargs: None
    instance = {
        "id": "instance-simulation",
        "strategy_id": "strategy-research",
        "_server_execution_mode": "simulation",
        "_server_allow_service_strategy_execution": False,
    }
    monkeypatch.setattr(
        gateway_runtime_service,
        "get_settings",
        lambda: SimpleNamespace(DEBUG=False),
    )
    monkeypatch.setattr(
        gateway_runtime_service, "_refresh_runtime_asset_specs", lambda *_args: None
    )

    def old_runtime_import_must_not_run(*_args, **_kwargs):
        pytest.fail("a simulation without a gateway imported the optional legacy runtime")

    monkeypatch.setattr(manager, "_import_gateway_runtime_classes", old_runtime_import_must_not_run)

    environment = manager._build_subprocess_env(
        "instance-simulation",
        instance,
        tmp_path,
    )

    assert environment["BT_TRADING_INSTANCE_ID"] == "instance-simulation"
    assert environment["DEBUG"] == "false"
    assert "BT_STORE_PROVIDER" not in environment
