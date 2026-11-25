"""Portfolio runtime configuration resolution."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.api.portfolio.instance_resolution import _as_path
from app.services.strategy_service import get_strategy_dir
from app.services.trading_asset_info_service import load_runtime_config


def runtime_config_for_instance(inst: Mapping[str, object]) -> dict[str, Any]:
    runtime_dir = _as_path(inst.get("runtime_dir"))
    if runtime_dir is not None:
        config = load_runtime_config(runtime_dir)
        if config:
            return config
    try:
        strategy_id = inst["strategy_id"]
        if not isinstance(strategy_id, str):
            return {}
        strategy_dir = Path(get_strategy_dir(strategy_id))
    except ValueError:
        return {}
    return load_runtime_config(strategy_dir)
