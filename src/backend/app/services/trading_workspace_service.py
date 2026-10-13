"""
Trading workspace service.

Provides strategy-unit level trading orchestration by reusing the existing
live trading manager/runtime while persisting state on workspace units.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Any

from app.models.workspace import StrategyUnit
from app.schemas.trading import PositionManagerResponse, TradingDailySummaryResponse
from app.schemas.workspace import UnitStatusResponse
from app.services import trading_workspace_contract_specs as _contract_specs
from app.services import trading_workspace_position_normalization as _position_normalization
from app.services import trading_workspace_snapshot as _workspace_snapshot
from app.services import trading_workspace_startup as _workspace_startup
from app.services import workspace_unit_runtime
from app.services.ai_research_provenance import (
    AI_RESEARCH_PAPER_RUNTIME_ANCHOR_FIELD,
    AI_RESEARCH_PAPER_RUNTIME_METRICS_OBSERVATION_FIELD,
    issue_ai_research_paper_runtime_anchor,
    issue_ai_research_paper_runtime_metrics_observation,
    verify_ai_research_paper_runtime_anchor_for_unit,
)
from app.services.asset_info.gateway_specs import persist_asset_specs, query_local_asset_spec
from app.services.asset_info.positions import normalize_gateway_position
from app.services.auto_trading_scheduler import get_auto_trading_scheduler
from app.services.live_trading.metadata import SERVER_RUNTIME_LAUNCH_ID_FIELD
from app.services.live_trading_manager import get_live_trading_manager
from app.services.log_parser_service import (
    parse_current_position,
    parse_log_dir,
    parse_position_log,
)
from app.services.position_valuation import EPSILON, PositionSpec, contract_spec_for, value_position
from app.services.risk_gate_service import RiskGateService
from app.services.trading_asset_info_service import (
    LONG_POSITION_FIELD_KEYS,
    POSITION_SIZE_FIELD_KEYS,
    SHORT_POSITION_FIELD_KEYS,
    gateway_position_symbol,
    signed_gateway_size,
    split_bidirectional_position_row,
    symbol_aliases,
)
from app.services.workspace.units import (
    assert_ai_research_live_handoff_runtime_start_allowed,
    is_server_owned_ai_research_live_handoff_unit,
    is_server_owned_ai_research_paper_runtime,
    is_server_owned_ai_research_unit,
)

logger = logging.getLogger(__name__)

_ASSET_SPEC_CONTRACT_KEYS = _contract_specs._ASSET_SPEC_CONTRACT_KEYS
_ASSET_SPEC_MARGIN_KEYS = _contract_specs._ASSET_SPEC_MARGIN_KEYS
_ASSET_SPEC_FEE_KEYS = _contract_specs._ASSET_SPEC_FEE_KEYS
_ASSET_SPEC_AUX_KEYS = _contract_specs._ASSET_SPEC_AUX_KEYS
_json_safe_value = _contract_specs._json_safe_value
_asset_spec_for_symbol = _contract_specs._asset_spec_for_symbol
_metadata_from_config = _contract_specs._metadata_from_config
_merge_asset_spec_aliases = _contract_specs._merge_asset_spec_aliases
_combined_asset_spec_source = _contract_specs._combined_asset_spec_source
_can_merge_asset_spec_value = _contract_specs._can_merge_asset_spec_value
_is_asset_spec_core_key = _contract_specs._is_asset_spec_core_key
_is_asset_spec_primary_source_key = _contract_specs._is_asset_spec_primary_source_key
_asset_spec_has_any = _contract_specs._asset_spec_has_any
_merge_asset_spec_update = _contract_specs._merge_asset_spec_update
_append_symbol_candidate = _contract_specs._append_symbol_candidate
_append_config_symbols = _contract_specs._append_config_symbols


def _position_normalization_dependencies() -> (
    _position_normalization.PositionNormalizationDependencies
):
    return _position_normalization.PositionNormalizationDependencies(
        safe_float=_safe_float,
        safe_iso_text=_safe_iso_text,
        safe_int=_safe_int,
        round_quantity=_round_quantity,
        epsilon=EPSILON,
        position_log_row_direction=TradingWorkspaceService._position_log_row_direction,
        get_live_trading_manager=get_live_trading_manager,
        normalize_gateway_position=normalize_gateway_position,
        asset_spec_for_symbol=_asset_spec_for_symbol,
        complete_asset_specs_from_local=_complete_asset_specs_from_local,
        merge_unit_contract_metadata=_merge_unit_contract_metadata,
        gateway_position_symbol=gateway_position_symbol,
        signed_gateway_size=signed_gateway_size,
        split_bidirectional_position_row=split_bidirectional_position_row,
        safe_dict=_safe_dict,
        is_server_owned_ai_research_unit=is_server_owned_ai_research_unit,
    )


def _snapshot_dependencies() -> _workspace_snapshot.SnapshotDependencies:
    return _workspace_snapshot.SnapshotDependencies(
        light_hydrate_preserve_keys=_LIGHT_HYDRATE_PRESERVE_KEYS,
        safe_dict=_safe_dict,
        safe_float=_safe_float,
        safe_iso_text=_safe_iso_text,
        instance_log_dir=_instance_log_dir,
        parse_log_dir=parse_log_dir,
        parse_position_log=parse_position_log,
        parse_current_position=parse_current_position,
        workspace_unit_dir=workspace_unit_runtime.unit_dir,
        append_unique=_append_unique,
        round_quantity=_round_quantity,
        leverage_from_margin_rate=_leverage_from_margin_rate,
        unique_text=_unique_text,
        gateway_position_symbol=gateway_position_symbol,
        split_bidirectional_position_row=split_bidirectional_position_row,
        value_position=value_position,
    )


def _startup_dependencies() -> _workspace_startup.StartupDependencies:
    return _workspace_startup.StartupDependencies(
        get_live_trading_manager=get_live_trading_manager,
        risk_gate_service_factory=RiskGateService,
        logger=logger,
        is_server_owned_ai_research_paper_runtime=is_server_owned_ai_research_paper_runtime,
        is_server_owned_ai_research_live_handoff_unit=is_server_owned_ai_research_live_handoff_unit,
        verify_ai_research_paper_runtime_anchor_for_unit=(
            verify_ai_research_paper_runtime_anchor_for_unit
        ),
        issue_ai_research_paper_runtime_anchor=issue_ai_research_paper_runtime_anchor,
        assert_ai_research_live_handoff_runtime_start_allowed=(
            assert_ai_research_live_handoff_runtime_start_allowed
        ),
        paper_runtime_anchor_field=AI_RESEARCH_PAPER_RUNTIME_ANCHOR_FIELD,
        sync_trading_unit_runtime=workspace_unit_runtime.sync_trading_unit_runtime,
        clear_runtime_logs_before_start=_clear_runtime_logs_before_start,
    )


_LIGHT_HYDRATE_PRESERVE_KEYS = (
    "today_pnl",
    "change_pct",
    "leverage",
    "cumulative_pnl",
    "max_drawdown_rate",
    "trading_day",
    "detail_route",
    "trades",
)
_COMMISSION_FIELD_KEYS = (
    "commission",
    "comm",
    "commissionAmount",
    "fee",
    "fees",
    "feeAmount",
    "execFee",
    "exec_fee",
    "execFeeV2",
    "exec_fee_v2",
    "execCommission",
    "exec_commission",
    "open_fee",
    "openFee",
    "open_commission",
    "openCommission",
    "positionCommission",
    "position_fee",
    "position_commission",
    "tradeFee",
    "trade_fee",
    "trade_commission",
    "broker_commission",
    "brokerCommission",
    "commission_amount",
    "Commission",
)
_EXPLICIT_NET_PNL_FIELD_KEYS = (
    "pnlcomm",
    "net_pnl",
    "netPnl",
    "netPNL",
    "net_position_pnl",
    "netPositionPnl",
    "netPositionPNL",
    "net_unrealized_pnl",
    "netUnrealizedPnl",
    "netUnrealizedPNL",
    "unrealized_pnl_after_fee",
    "unrealizedPnlAfterFee",
    "position_pnl_after_fee",
    "positionPnlAfterFee",
)
_PNL_FIELD_KEYS = (*_EXPLICIT_NET_PNL_FIELD_KEYS, "position_pnl", "pnl")
_GROSS_PNL_FIELD_KEYS = (
    "gross_pnl",
    "position_unrealized_pnl",
    "position_unrealised_pnl",
    "position_profit",
    "PositionProfit",
    "unrealized_profit",
    "unrealised_profit",
    "unrealizedProfit",
    "unrealisedProfit",
    "unRealizedProfit",
    "UnrealizedPnL",
    "unrealizedPnl",
    "unrealisedPnl",
    "unrealized_pnl",
    "unrealised_pnl",
    "unrealizedPNL",
    "unrealisedPNL",
    "unrealizedpnl",
    "unrealisedpnl",
    "floating_pnl",
    "position_pnl",
    "profit",
    "upl",
    "up",
)
_POSITION_SIZE_ALIAS_KEYS = (
    *POSITION_SIZE_FIELD_KEYS,
    *LONG_POSITION_FIELD_KEYS,
    *SHORT_POSITION_FIELD_KEYS,
)
_POSITION_RESPONSE_REVALUE_KEYS = (
    "instrument",
    "InstrumentID",
    "instId",
    "contract",
    "side",
    "positionIdx",
    "pos",
    "posSide",
    "Position",
    "Volume",
    "Qty",
    "Quantity",
    "PosiDirection",
    "posi_direction",
    "position_direction",
    "price_open",
    "entry_price",
    "avgPx",
    "avg_entry_price",
    "avgEntryPrice",
    "open_avg_price",
    "openAvgPrice",
    "last_price",
    "lastPrice",
    "markPx",
    "markPrice",
    "LastPrice",
    "Price",
    "AveragePrice",
    "PositionCost",
    "position_cost",
    "positionValue",
    "VolumeMultiple",
    "CONTRACT_MULTIPLIER",
    "LongMarginRatioByMoney",
    "ShortMarginRatioByMoney",
    "LongMarginRatioByVolume",
    "ShortMarginRatioByVolume",
    "MARGIN_BUY",
    "MARGIN_SELL",
    "MARGIN_PER_LOT",
    "imr",
    "mmr",
    "positionIM",
    "positionIMByMp",
    "lever",
    "mgnMode",
    "OpenRatioByMoney",
    "OpenRatioByVolume",
    "OPEN_FEE_RATE",
    "OPEN_FEE_AMOUNT",
    "COMMISSION_OPEN_RATIO",
    "COMMISSION_OPEN_AMOUNT",
)
_CURRENT_PRICE_FIELD_KEYS = (
    "current_price",
    "latest_price",
    "last_price",
    "mark_price",
    "markPrice",
    "market_price",
    "lastPrice",
    "LastPrice",
    "price_current",
    "marketPrice",
    "mktPrice",
    "mp",
    "PriceCurrent",
    "CurrentPrice",
    "SettlementPrice",
    "settlement_price",
)


def _now_local_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError):
        return default
    return result if isfinite(result) else default


def _safe_iso_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _round_quantity(value: Any) -> float:
    number = _safe_float(value, 0.0)
    rounded = round(number, 4)
    if abs(number) > EPSILON and abs(rounded) <= EPSILON:
        rounded = round(number, 8)
        if abs(rounded) <= EPSILON:
            return number
    return rounded


def _safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _unique_text(values: list[Any]) -> str | None:
    texts = [str(value or "").strip() for value in values]
    unique = sorted({text for text in texts if text})
    if not unique:
        return None
    if len(unique) == 1:
        return unique[0]
    return "mixed"


def _unique_number(values: list[Any]) -> float | None:
    numbers: list[float] = []
    for value in values:
        if value in (None, ""):
            continue
        number = _safe_float(value)
        numbers.append(number)
    if not numbers:
        return None
    first = numbers[0]
    if all(abs(item - first) <= EPSILON for item in numbers):
        return first
    return None


def _leverage_from_margin_rate(value: Any) -> float | None:
    margin_rate = _safe_float(value)
    if margin_rate <= EPSILON:
        return None
    return round(1.0 / margin_rate, 8)


def _append_unique(target: list[str], *values: Any) -> None:
    seen = set(target)
    for value in values:
        if isinstance(value, (list, tuple, set)):
            _append_unique(target, *value)
            seen = set(target)
            continue
        text = str(value or "").strip()
        if text and text not in seen:
            target.append(text)
            seen.add(text)


def _merge_unit_contract_metadata(
    specs: dict[str, dict[str, Any]],
    unit: StrategyUnit,
    instance: Mapping[str, object] | None,
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    return _contract_specs._merge_unit_contract_metadata(specs, unit, instance, symbols)


def _complete_asset_specs_from_local(
    specs: dict[str, dict[str, Any]],
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    return _contract_specs.complete_asset_specs_from_local(
        specs, symbols, query_local_asset_spec=query_local_asset_spec
    )


def _clear_runtime_logs_before_start(runtime_dir: Path) -> None:
    logs_dir = runtime_dir / "logs"
    if logs_dir.is_symlink() or logs_dir.is_file():
        logs_dir.unlink()
    elif logs_dir.is_dir():
        shutil.rmtree(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)


def _instance_log_dir(instance: Mapping[str, object] | None) -> Path | None:
    if not instance:
        return None

    log_dir_text = str(instance.get("log_dir") or "").strip()
    if log_dir_text:
        log_dir = Path(log_dir_text)
        if log_dir.is_dir():
            return log_dir

    runtime_dir_text = str(instance.get("runtime_dir") or "").strip()
    if runtime_dir_text:
        log_dir = Path(runtime_dir_text) / "logs"
        if log_dir.is_dir():
            return log_dir

    return None


class TradingWorkspaceService:
    """Trading orchestration for workspace strategy units."""

    @staticmethod
    def normalize_trading_mode(value: Any) -> str:
        text = str(value or "").strip().lower()
        return "live" if text == "live" else "paper"

    @staticmethod
    def normalize_gateway_config(config: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(config, dict):
            return {}
        params = config.get("params")
        normalized = {
            "preset_id": str(config.get("preset_id") or "").strip() or None,
            "name": str(config.get("name") or "").strip() or None,
            "params": params if isinstance(params, dict) else {},
        }
        return {key: value for key, value in normalized.items() if value not in (None, "", {})}

    @classmethod
    def default_snapshot(
        cls,
        *,
        unit: StrategyUnit,
        instance_status: str = "idle",
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "instance_id": unit.trading_instance_id,
            "instance_status": instance_status,
            "mode": cls.normalize_trading_mode(unit.trading_mode),
            "error": error,
            "started_at": None,
            "stopped_at": None,
            "gateway_summary": cls.gateway_summary(
                unit.gateway_config if isinstance(unit.gateway_config, dict) else {}
            ),
            "long_position": 0.0,
            "short_position": 0.0,
            "today_pnl": None,
            "position_pnl": None,
            "latest_price": None,
            "change_pct": None,
            "long_market_value": 0.0,
            "short_market_value": 0.0,
            "leverage": None,
            "cumulative_pnl": None,
            "max_drawdown_rate": None,
            "trading_day": None,
            "updated_at": _now_local_text(),
            "detail_route": None,
            "position_source": None,
            "asset_spec_source": None,
            "valuation_status": "empty",
            "valuation_warnings": [],
            "positions": [],
            "trades": [],
        }

    @staticmethod
    def gateway_summary(gateway_config: dict[str, Any] | None) -> str | None:
        params = (gateway_config or {}).get("params")
        gateway = params.get("gateway") if isinstance(params, dict) else None
        if not isinstance(gateway, dict):
            return None
        parts = [
            str(gateway.get("exchange_type") or "").strip(),
            str(gateway.get("asset_type") or "").strip(),
            str(gateway.get("account_id") or "").strip(),
        ]
        summary = " / ".join(part for part in parts if part)
        return summary or None

    @staticmethod
    def _map_run_status(instance_status: str, error: str | None = None) -> str:
        text = str(instance_status or "").strip().lower()
        if text == "running":
            return "running"
        if text == "error" or error:
            return "failed"
        return "idle"

    @staticmethod
    def _normalize_trade_direction(value: Any, size: float) -> str:
        return _position_normalization.normalize_trade_direction(value, size)

    @classmethod
    def _normalize_trade_rows(
        cls,
        raw_trades: list[Any],
        *,
        unit: StrategyUnit,
    ) -> list[dict[str, Any]]:
        return _position_normalization.normalize_trade_rows(
            cls, raw_trades, unit=unit, dependencies=_position_normalization_dependencies()
        )

    @staticmethod
    def _position_log_row_direction(row: dict[str, Any], size: float) -> str:
        return _position_normalization.position_log_row_direction(
            row, size, dependencies=_position_normalization_dependencies()
        )

    @staticmethod
    def _latest_position_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _position_normalization.latest_position_rows(
            rows, dependencies=_position_normalization_dependencies()
        )

    @staticmethod
    def _position_updated_at(row: dict[str, Any]) -> str | None:
        return _position_normalization.position_updated_at(
            row, dependencies=_position_normalization_dependencies()
        )

    @staticmethod
    def _position_data_time(row: dict[str, Any]) -> str | None:
        return _position_normalization.position_data_time(
            row, dependencies=_position_normalization_dependencies()
        )

    @classmethod
    def _latest_position_updated_at(cls, rows: list[dict[str, Any]]) -> str | None:
        return _position_normalization.latest_position_updated_at(cls, rows)

    @classmethod
    def _latest_position_data_time(cls, rows: list[dict[str, Any]]) -> str | None:
        return _position_normalization.latest_position_data_time(cls, rows)

    @classmethod
    def _contract_spec(
        cls,
        unit: StrategyUnit,
        symbol: str,
        instance: Mapping[str, object] | None = None,
        *extra_configs: dict[str, Any],
    ) -> PositionSpec:
        return _contract_specs.resolve_contract_spec(
            cls,
            unit,
            symbol,
            instance,
            *extra_configs,
            contract_spec_for=contract_spec_for,
            query_local_asset_spec=query_local_asset_spec,
        )

    @staticmethod
    def _position_spec_has_asset_metadata(spec: Any) -> bool:
        return bool(
            getattr(spec, "has_multiplier", False)
            or getattr(spec, "has_margin_rate", False)
            or getattr(spec, "has_margin_amount", False)
            or getattr(spec, "has_commission", False)
        )

    @classmethod
    def _config_can_use_local_asset_spec(cls, config: dict[str, Any]) -> bool:
        if not isinstance(config, dict):
            return False
        if cls._has_any(config, *_EXPLICIT_NET_PNL_FIELD_KEYS, *_GROSS_PNL_FIELD_KEYS, "pnl"):
            return True
        return cls._has_any(
            config,
            "price",
            "avg_price",
            "average_price",
            "price_open",
            "entry_price",
            "avgCost",
            "avgPrice",
            "avgPx",
            "avg_entry_price",
            "avgEntryPrice",
            "entryPrice",
            "open_avg_price",
            "openAvgPrice",
            "Price",
            "AveragePrice",
        ) and cls._has_any(config, *_CURRENT_PRICE_FIELD_KEYS)

    @staticmethod
    def _position_source_for_row(row: dict[str, Any], fallback: str | None = None) -> str:
        return str(row.get("position_source") or row.get("source") or fallback or "local").strip()

    @staticmethod
    def _asset_spec_source_for_row(row: dict[str, Any], spec: Any) -> str | None:
        return (
            str(row.get("asset_spec_source") or getattr(spec, "source", "") or "").strip() or None
        )

    @staticmethod
    def _asset_spec_config_for_row(row: dict[str, Any]) -> dict[str, Any]:
        config = dict(row)
        config.pop("position_source", None)
        if config.get("asset_spec_source"):
            config["source"] = config.get("asset_spec_source")
        else:
            config.pop("source", None)
        return config

    @staticmethod
    def _has_any(row: dict[str, Any], *keys: str) -> bool:
        return any(row.get(key) not in (None, "") for key in keys)

    @staticmethod
    def _unit_contract_metadata(unit: StrategyUnit) -> dict[str, Any]:
        params = _safe_dict(getattr(unit, "params", None))
        metadata = params.get("contract_metadata")
        return dict(metadata) if isinstance(metadata, dict) else {}

    @classmethod
    def _unit_has_asset_valuation_config(cls, unit: StrategyUnit) -> bool:
        if cls._unit_contract_metadata(unit):
            return True
        for config in (
            _safe_dict(getattr(unit, "unit_settings", None)),
            _safe_dict(getattr(unit, "params", None)),
            _safe_dict(getattr(unit, "data_config", None)),
            _safe_dict(getattr(unit, "gateway_config", None)),
        ):
            if cls._has_any(
                config,
                "multiplier",
                "mult",
                "contract_multiplier",
                "contract_size",
                "trade_contract_size",
                "margin",
                "margin_rate",
                "margin_ratio",
                "leverage",
                "lever",
                "commission",
                "commission_rate",
                "open_commission_rate",
                "close_commission_rate",
                "taker_commission_rate",
                "maker_commission_rate",
                "commission_amount",
            ):
                return True
        return False

    @classmethod
    def _sync_unit_contract_metadata_from_instance(
        cls,
        unit: StrategyUnit,
        instance: Mapping[str, object] | None,
    ) -> bool:
        if is_server_owned_ai_research_unit(unit):
            # Paper-review provenance binds the initial research handoff.  A
            # later read of the mutable instance store must not rewrite the
            # unit configuration that the next runtime sync consumes.
            return False
        instance_params = _safe_dict((instance or {}).get("params"))
        instance_metadata = instance_params.get("contract_metadata")
        if not isinstance(instance_metadata, dict) or not instance_metadata:
            return False

        params = _safe_dict(getattr(unit, "params", None))
        raw_current_metadata = params.get("contract_metadata")
        current_metadata = (
            dict(raw_current_metadata) if isinstance(raw_current_metadata, dict) else {}
        )
        changed = False
        for key, value in instance_metadata.items():
            if not isinstance(value, dict):
                continue
            normalized_key = str(key)
            existing_value = _asset_spec_for_symbol(current_metadata, normalized_key)
            normalized_value = _merge_asset_spec_update(existing_value, dict(value))
            for alias in symbol_aliases(normalized_key):
                current_metadata[str(alias)] = dict(normalized_value)
            if existing_value != normalized_value:
                changed = True
        if not changed:
            return False
        params["contract_metadata"] = current_metadata
        unit.params = params
        return True

    @classmethod
    def _sync_unit_contract_metadata_from_specs(
        cls,
        unit: StrategyUnit,
        asset_specs: dict[str, dict[str, Any]],
    ) -> bool:
        if is_server_owned_ai_research_unit(unit):
            # Gateway/local discovery remains available to runtime-local
            # readers, but must not become an unsigned mutation of an
            # attested paper unit's persisted execution parameters.
            return False
        if not asset_specs:
            return False

        params = _safe_dict(getattr(unit, "params", None))
        raw_current_metadata = params.get("contract_metadata")
        current_metadata = (
            dict(raw_current_metadata) if isinstance(raw_current_metadata, dict) else {}
        )
        changed = False
        for key, value in asset_specs.items():
            if not isinstance(value, dict):
                continue
            normalized_key = str(key)
            existing_value = _asset_spec_for_symbol(current_metadata, normalized_key)
            normalized_value = _merge_asset_spec_update(existing_value, dict(value))
            for alias in symbol_aliases(normalized_key):
                current_metadata[str(alias)] = dict(normalized_value)
            if existing_value != normalized_value:
                changed = True
        if not changed:
            return False
        params["contract_metadata"] = current_metadata
        unit.params = params
        return True

    @classmethod
    def _unit_asset_spec_symbols(
        cls,
        unit: StrategyUnit,
        instance: Mapping[str, object] | None,
    ) -> list[str]:
        candidates: list[str] = []
        _append_symbol_candidate(candidates, getattr(unit, "symbol", None))
        for config in (
            _safe_dict(getattr(unit, "params", None)),
            _safe_dict(getattr(unit, "data_config", None)),
            _safe_dict(getattr(unit, "unit_settings", None)),
            _safe_dict(getattr(unit, "gateway_config", None)),
            _safe_dict((instance or {}).get("params")),
        ):
            _append_config_symbols(candidates, config)

        symbols: list[str] = []
        seen: set[str] = set()
        for symbol in candidates:
            text = str(symbol or "").strip()
            key = text.upper()
            if not text or key in seen:
                continue
            symbols.append(text)
            seen.add(key)
        return symbols

    @classmethod
    def _refresh_unit_asset_specs_from_manager(
        cls,
        manager: Any,
        unit: StrategyUnit,
        instance: Mapping[str, object] | None,
    ) -> bool:
        if is_server_owned_ai_research_unit(unit):
            return False
        instance_id = str((instance or {}).get("id") or unit.trading_instance_id or "").strip()
        if not instance_id:
            return False
        query_specs = getattr(manager, "query_instance_asset_specs", None)
        if not callable(query_specs):
            return False
        symbols = cls._unit_asset_spec_symbols(unit, instance)
        for symbol in cls._gateway_position_symbols_from_manager(
            manager,
            unit,
            instance_id,
            instance,
        ):
            _append_symbol_candidate(symbols, symbol)
        if not symbols:
            return False
        try:
            raw_specs = query_specs(instance_id, symbols)
        except Exception:
            return False
        if not isinstance(raw_specs, dict):
            return False
        asset_specs = {
            str(key): dict(value)
            for key, value in raw_specs.items()
            if isinstance(value, dict) and value
        }
        if not asset_specs:
            return False
        return cls._sync_unit_contract_metadata_from_specs(unit, asset_specs)

    @classmethod
    def _refresh_unit_asset_specs_from_local(
        cls,
        unit: StrategyUnit,
        instance: Mapping[str, object] | None = None,
    ) -> bool:
        if is_server_owned_ai_research_unit(unit):
            return False
        symbols = cls._unit_asset_spec_symbols(unit, instance)
        if not symbols:
            return False
        asset_specs = _complete_asset_specs_from_local({}, symbols)
        if not asset_specs:
            return False
        runtime_dir = str((instance or {}).get("runtime_dir") or "").strip()
        if runtime_dir:
            try:
                manager_instance = instance if isinstance(instance, dict) else dict(instance or {})
                persist_asset_specs(Path(runtime_dir).expanduser(), manager_instance, asset_specs)
            except Exception:
                pass
        return cls._sync_unit_contract_metadata_from_specs(unit, asset_specs)

    @classmethod
    def _gateway_position_symbols_from_manager(
        cls,
        manager: Any,
        unit: StrategyUnit,
        instance_id: str,
        instance: Mapping[str, object] | None,
    ) -> list[str]:
        query_positions = getattr(manager, "query_instance_gateway_positions", None)
        if not callable(query_positions):
            return []
        try:
            raw_positions = query_positions(instance_id)
        except Exception:
            return []
        if not isinstance(raw_positions, list):
            return []

        allowed_aliases = cls._unit_position_symbol_aliases(unit, instance)
        symbols: list[str] = []
        for item in raw_positions:
            if not isinstance(item, dict):
                continue
            if not any(
                abs(signed_gateway_size(side_item)) > EPSILON
                for side_item in split_bidirectional_position_row(item)
            ):
                continue
            symbol = gateway_position_symbol(item)
            if not symbol:
                continue
            if allowed_aliases and not cls._position_symbol_matches(symbol, allowed_aliases):
                continue
            _append_symbol_candidate(symbols, symbol)
        return symbols

    @classmethod
    def _position_row_should_recalculate_local_pnl(
        cls,
        row: dict[str, Any],
        spec: Any,
        *,
        position_source: str,
        force: bool = False,
    ) -> bool:
        if not force and str(position_source or "").strip().lower() == "gateway":
            return False
        if not (
            getattr(spec, "has_multiplier", False)
            or getattr(spec, "has_commission", False)
            or getattr(spec, "has_margin_rate", False)
            or getattr(spec, "has_margin_amount", False)
        ):
            return False
        if not cls._has_any(
            row,
            "price",
            "avg_price",
            "average_price",
            "price_open",
            "entry_price",
            "avgCost",
            "avgPrice",
            "avgPx",
            "avg_entry_price",
            "avgEntryPrice",
            "entryPrice",
            "open_avg_price",
            "openAvgPrice",
            "Price",
            "AveragePrice",
        ):
            return False
        if not cls._has_any(
            row,
            *_CURRENT_PRICE_FIELD_KEYS,
            "market_value",
            "marketValue",
            "positionValue",
            "position_value",
            "value",
        ):
            return False
        return cls._has_any(row, *_EXPLICIT_NET_PNL_FIELD_KEYS, *_GROSS_PNL_FIELD_KEYS, "pnl")

    @classmethod
    def _position_row_for_valuation(
        cls,
        row: dict[str, Any],
        spec: Any,
        *,
        position_source: str,
    ) -> dict[str, Any]:
        item = dict(row)
        force_recalculate = bool(item.pop("force_recalculate_position_pnl", False))
        if not cls._position_row_should_recalculate_local_pnl(
            item,
            spec,
            position_source=position_source,
            force=force_recalculate,
        ):
            return item
        for key in (*_EXPLICIT_NET_PNL_FIELD_KEYS, *_GROSS_PNL_FIELD_KEYS, "pnl"):
            item.pop(key, None)
        if force_recalculate:
            item["market_value_estimated"] = True
        item["recalculated_position_pnl"] = True
        return item

    @classmethod
    def _position_valuation_warnings(
        cls,
        unit: StrategyUnit,
        row: dict[str, Any],
        spec: Any,
        *,
        position_source: str,
    ) -> list[str]:
        warnings: list[str] = []
        trading_mode = cls.normalize_trading_mode(getattr(unit, "trading_mode", None))
        if trading_mode == "live" and position_source != "gateway":
            warnings.append("未能从交易所网关确认当前持仓，当前数据来自本地日志/快照")

        if not getattr(spec, "has_multiplier", False) and not cls._has_any(
            row, "multiplier", "mult", "contract_multiplier", "contract_size"
        ):
            warnings.append("合约乘数未从交易所或本地资产信息确认，按 1 估算")
        if (
            not getattr(spec, "has_margin_rate", False)
            and not getattr(spec, "has_margin_amount", False)
            and not cls._has_any(
                row,
                "margin",
                "margin_rate",
                "margin_ratio",
                "leverage",
                "lever",
                "margin_value",
                "use_margin",
                "initial_margin",
                "imr",
                "margin_amount",
                "initial_margin_per_lot",
                "margin_initial",
                "maintain_margin",
                "mmr",
                "long_margin_amount",
                "short_margin_amount",
                "MARGIN_PER_LOT",
                "LONG_MARGIN_AMOUNT",
                "SHORT_MARGIN_AMOUNT",
            )
        ):
            warnings.append("保证金率未确认，按全额保证金估算")
        has_real_commission = cls._has_any(row, *_COMMISSION_FIELD_KEYS)
        if row.get("commission_currency_mismatch"):
            warnings.append("成交手续费币种与盈亏计价币种不一致，当前按资产费率估算手续费")
        if not getattr(spec, "has_commission", False) and not has_real_commission:
            warnings.append("手续费未确认，持仓盈亏未扣除真实手续费")
        elif (
            getattr(spec, "has_commission", False)
            and not has_real_commission
            and (row.get("generic_pnl_recalculated") or cls._has_any(row, *_GROSS_PNL_FIELD_KEYS))
        ):
            warnings.append("持仓手续费未从交易所成交/持仓回报确认，当前按资产费率估算")
        return warnings

    @classmethod
    def _unit_position_symbol_aliases(
        cls,
        unit: StrategyUnit,
        instance: Mapping[str, object] | None,
    ) -> set[str]:
        candidates: list[str] = []
        _append_symbol_candidate(candidates, getattr(unit, "symbol", None))
        _append_config_symbols(candidates, _safe_dict(getattr(unit, "params", None)))
        _append_config_symbols(candidates, _safe_dict(getattr(unit, "data_config", None)))
        _append_config_symbols(candidates, _safe_dict(getattr(unit, "unit_settings", None)))
        _append_config_symbols(candidates, _safe_dict(getattr(unit, "gateway_config", None)))
        _append_config_symbols(candidates, _safe_dict((instance or {}).get("params")))
        if not candidates:
            _append_symbol_candidate(candidates, getattr(unit, "symbol_name", None))

        aliases: set[str] = set()
        for symbol in candidates:
            aliases.update(symbol_aliases(symbol))
        return aliases

    @staticmethod
    def _position_symbol_matches(symbol: str, allowed_aliases: set[str]) -> bool:
        if not allowed_aliases:
            return True
        return any(alias in allowed_aliases for alias in symbol_aliases(symbol))

    @classmethod
    def _gateway_position_rows(
        cls,
        unit: StrategyUnit,
        instance: Mapping[str, object] | None,
    ) -> list[dict[str, Any]] | None:
        return _position_normalization.gateway_position_rows(
            cls, unit, instance, dependencies=_position_normalization_dependencies()
        )

    @classmethod
    def _apply_position_rows_to_snapshot(
        cls,
        snapshot: dict[str, Any],
        unit: StrategyUnit,
        instance: Mapping[str, object] | None,
        positions: list[dict[str, Any]],
    ) -> float | None:
        return _workspace_snapshot.apply_position_rows_to_snapshot(
            cls,
            snapshot,
            unit,
            instance,
            positions,
            dependencies=_snapshot_dependencies(),
        )

    @classmethod
    def _build_instance_params(cls, unit: StrategyUnit) -> dict[str, Any]:
        params = dict(unit.params or {})
        params.setdefault("symbol", unit.symbol or "")
        params.setdefault("symbol_name", unit.symbol_name or "")
        params.setdefault("timeframe", unit.timeframe or "1d")
        params.setdefault("timeframe_n", unit.timeframe_n or 1)
        params.setdefault("category", unit.category or "")
        params.setdefault("data_config", dict(unit.data_config or {}))
        params.setdefault("unit_settings", dict(unit.unit_settings or {}))
        params["workspace_unit"] = {
            "workspace_id": unit.workspace_id,
            "unit_id": unit.id,
            "group_name": unit.group_name or "",
            "strategy_name": unit.strategy_name or "",
        }

        trading_mode = cls.normalize_trading_mode(unit.trading_mode)
        gateway_config = cls.normalize_gateway_config(
            unit.gateway_config if isinstance(unit.gateway_config, dict) else {}
        )

        if trading_mode == "live":
            gateway_params = gateway_config.get("params")
            if not isinstance(gateway_params, dict) or not isinstance(
                gateway_params.get("gateway"), dict
            ):
                raise ValueError("实盘单元缺少网关配置")
            params.update(gateway_params)
        else:
            gateway_params = gateway_config.get("params")
            if isinstance(gateway_params, dict) and isinstance(gateway_params.get("gateway"), dict):
                params.update(gateway_params)
            else:
                params["gateway"] = {"enabled": False}

        params["trading_mode"] = trading_mode
        return _json_safe_value(params)

    @classmethod
    def _gateway_startup_key(cls, unit: StrategyUnit) -> str | None:
        """Return a request-local key for units that share one enabled gateway."""
        gateway_config = cls.normalize_gateway_config(
            unit.gateway_config if isinstance(unit.gateway_config, dict) else {}
        )
        params = gateway_config.get("params")
        gateway = params.get("gateway") if isinstance(params, dict) else None
        if not isinstance(gateway, dict) or not gateway.get("enabled"):
            return None
        try:
            return json.dumps(gateway_config, sort_keys=True, default=str, separators=(",", ":"))
        except (TypeError, ValueError):
            return str(gateway_config)

    @staticmethod
    def _is_gateway_startup_failure(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "gateway runtime",
                "gateway runtime not ready",
                "gateway startup",
                "gateway unavailable",
                "ib client portal",
                "ib web session",
                "ib web login",
                "ib web authentication",
            )
        )

    @classmethod
    def _build_snapshot(
        cls,
        unit: StrategyUnit,
        instance: Mapping[str, object] | None,
        *,
        full_log: bool = True,
        include_gateway_positions: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any], int | None, float | None]:
        return _workspace_snapshot.build_snapshot(
            cls,
            unit,
            instance,
            full_log=full_log,
            include_gateway_positions=include_gateway_positions,
            dependencies=_snapshot_dependencies(),
        )

    async def hydrate_units(
        self,
        units: list[StrategyUnit],
        user_id: str,
        *,
        full_log: bool = True,
        refresh_gateway: bool = True,
    ) -> bool:
        # ``get_live_trading_manager`` bootstraps persisted instances and may
        # restore a gateway.  The table and polling paths deliberately pass
        # ``refresh_gateway=False`` and must remain a read of persisted state
        # even when many units are already running.  Detail/position flows
        # opt in with ``refresh_gateway=True`` when fresh runtime data is
        # actually needed.
        manager = get_live_trading_manager() if refresh_gateway else None
        changed = False

        for unit in units:
            previous_trade_keys = self._snapshot_trade_keys(
                _safe_dict(getattr(unit, "trading_snapshot", None))
            )
            instance = None
            if manager is not None and unit.trading_instance_id:
                instance = manager.get_instance(unit.trading_instance_id, user_id=user_id)

            params_before = _safe_dict(getattr(unit, "params", None))
            if instance is not None and self._sync_unit_contract_metadata_from_instance(
                unit,
                instance,
            ):
                changed = True
            is_explicit_paper = str(getattr(unit, "trading_mode", "")).strip().lower() == "paper"
            if (
                manager is not None
                and refresh_gateway
                and not is_explicit_paper
                and self._refresh_unit_asset_specs_from_manager(manager, unit, instance)
            ):
                changed = True
            if not self._unit_has_asset_valuation_config(
                unit
            ) and self._refresh_unit_asset_specs_from_local(unit, instance):
                changed = True
            snapshot_kwargs: dict[str, Any] = {"full_log": full_log}
            if not refresh_gateway or manager is None:
                snapshot_kwargs["include_gateway_positions"] = False
            snapshot, metrics_snapshot, bar_count, elapsed_seconds = self._build_snapshot(
                unit,
                instance,
                **snapshot_kwargs,
            )
            if instance is None:
                # A manager restart does not mean the external strategy process
                # stopped. Keep the persisted lifecycle status until a manager
                # instance or an explicit stop/failure supplies authoritative
                # state; otherwise merely opening a portfolio page would mark
                # every restored unit idle.
                persisted_snapshot = _safe_dict(getattr(unit, "trading_snapshot", None))
                persisted_status = (
                    str(persisted_snapshot.get("instance_status") or unit.run_status or "idle")
                    .strip()
                    .lower()
                )
                snapshot["instance_status"] = persisted_status or "idle"
                if not snapshot.get("error") and persisted_snapshot.get("error"):
                    snapshot["error"] = persisted_snapshot["error"]
                next_run_status = str(unit.run_status or "idle").strip().lower() or "idle"
            else:
                next_run_status = self._map_run_status(
                    snapshot.get("instance_status", "idle"), snapshot.get("error")
                )

            if unit.run_status != next_run_status:
                unit.run_status = next_run_status
                changed = True
            if unit.trading_snapshot != snapshot:
                unit.trading_snapshot = snapshot
                changed = True
            if unit.metrics_snapshot != metrics_snapshot and metrics_snapshot:
                unit.metrics_snapshot = metrics_snapshot
                changed = True
            if bar_count is not None and unit.bar_count != bar_count:
                unit.bar_count = bar_count
                changed = True
            if elapsed_seconds is not None and unit.last_run_time != elapsed_seconds:
                unit.last_run_time = elapsed_seconds
                changed = True
            if _safe_dict(getattr(unit, "params", None)) != params_before:
                changed = True

            instance_id = str(getattr(unit, "trading_instance_id", "") or "").strip()
            is_paper = str(getattr(unit, "trading_mode", "") or "").strip().lower() == "paper"
            new_trade_keys = self._snapshot_trade_keys(snapshot) - previous_trade_keys
            if full_log and is_paper and instance_id and new_trade_keys:
                post_fill_recorded = await self._record_post_fill_runtime_state(
                    user_id=user_id,
                    instance_id=instance_id,
                    snapshot=snapshot,
                    metrics_snapshot=metrics_snapshot,
                    unit_settings=_safe_dict(getattr(unit, "unit_settings", None)),
                    trade_keys=new_trade_keys,
                )
                launch_id = str((instance or {}).get(SERVER_RUNTIME_LAUNCH_ID_FIELD) or "").strip()
                if post_fill_recorded and is_server_owned_ai_research_paper_runtime(unit):
                    observation = issue_ai_research_paper_runtime_metrics_observation(
                        user_id=user_id,
                        paper_workspace_id=str(unit.workspace_id),
                        paper_unit_id=str(unit.id),
                        instance_id=instance_id,
                        launch_id=launch_id,
                        metrics_snapshot=metrics_snapshot,
                    )
                    if observation is not None:
                        settings = _safe_dict(getattr(unit, "unit_settings", None))
                        if (
                            settings.get(AI_RESEARCH_PAPER_RUNTIME_METRICS_OBSERVATION_FIELD)
                            != observation
                        ):
                            settings[AI_RESEARCH_PAPER_RUNTIME_METRICS_OBSERVATION_FIELD] = (
                                observation
                            )
                            unit.unit_settings = settings
                            changed = True

        return changed

    @staticmethod
    def _snapshot_trade_keys(snapshot: dict[str, Any]) -> set[str]:
        """Return stable identifiers used to detect newly hydrated fills."""
        values = snapshot.get("trades") if isinstance(snapshot, dict) else None
        if not isinstance(values, list):
            return set()
        keys: set[str] = set()
        for index, row in enumerate(values):
            if not isinstance(row, dict):
                continue
            value = row.get("id") or row.get("trade_id") or row.get("ref")
            if value is None:
                value = (
                    f"{row.get('symbol', '')}:{row.get('dtclose', row.get('datetime', ''))}:{index}"
                )
            keys.add(str(value))
        return keys

    async def _record_post_fill_runtime_state(
        self,
        *,
        user_id: str,
        instance_id: str,
        snapshot: dict[str, Any],
        metrics_snapshot: dict[str, Any],
        unit_settings: dict[str, Any],
        trade_keys: set[str],
    ) -> bool:
        """Persist one post-fill equity point and evaluate post-fill risk limits."""
        from app.services.paper_runtime_service import PaperRuntimeService

        service = PaperRuntimeService()
        try:
            equity = _safe_float(metrics_snapshot.get("final_value"), 0.0)
            if equity <= 0:
                equity = _safe_float(unit_settings.get("initial_cash"), 100000.0) + _safe_float(
                    snapshot.get("cumulative_pnl"), 0.0
                )
            position_value = _safe_float(snapshot.get("long_market_value"), 0.0) + _safe_float(
                snapshot.get("short_market_value"), 0.0
            )
            daily_pnl = _safe_float(snapshot.get("today_pnl"), 0.0)
            await service.record_valuation_snapshot(
                user_id,
                instance_id,
                trading_snapshot=snapshot,
                metrics_snapshot=metrics_snapshot,
                unit_settings=unit_settings,
                source="post_fill",
                metadata={"trade_keys": sorted(trade_keys)},
            )
            await service.evaluate_post_fill(
                user_id,
                instance_id,
                current_equity=equity,
                position_value=position_value,
                drawdown_pct=_safe_float(snapshot.get("max_drawdown_rate"), 0.0),
                daily_loss_pct=abs(daily_pnl) / equity * 100
                if daily_pnl < 0 and equity > 0
                else 0.0,
            )
            return True
        except Exception:
            logger.warning(
                "Unable to persist post-fill runtime state for %s",
                instance_id,
                exc_info=True,
            )
            return False

    async def start_units(
        self,
        units: list[StrategyUnit],
        user_id: str,
        workspace_settings: dict[str, Any] | None = None,
        *,
        allow_server_owned_ai_research_live_handoff_start: bool = False,
        live_handoff_pre_start_validator: Callable[[], Awaitable[None]] | None = None,
    ) -> list[dict[str, Any]]:
        return await _workspace_startup.start_units(
            self,
            units,
            user_id,
            workspace_settings,
            allow_server_owned_ai_research_live_handoff_start=(
                allow_server_owned_ai_research_live_handoff_start
            ),
            live_handoff_pre_start_validator=live_handoff_pre_start_validator,
            dependencies=_startup_dependencies(),
        )

    async def stop_units(
        self,
        units: list[StrategyUnit],
        user_id: str,
        *,
        allow_server_owned_ai_research_stop: bool = False,
        allow_server_owned_ai_research_live_handoff_stop: bool = False,
    ) -> list[dict[str, Any]]:
        manager = get_live_trading_manager()
        results: list[dict[str, Any]] = []

        # Reject the complete public batch before any ordinary unit is
        # stopped.  Otherwise a browser can use workspace stop to leave an
        # attested paper runtime inactive while preserving its old review
        # metrics.  The review-failure workflow has an explicit server-only
        # capability and is the sole caller allowed to stop these units.
        if not (
            allow_server_owned_ai_research_stop or allow_server_owned_ai_research_live_handoff_stop
        ):
            from app.services.workspace.units import AIStrategyResearchPaperRuntimeStopError

            if any(is_server_owned_ai_research_unit(unit) for unit in units):
                raise AIStrategyResearchPaperRuntimeStopError()

        for unit in units:
            cancelled = False
            stopped_instance = None
            open_order_cancel: dict[str, Any] | None = None
            error_message: str | None = None
            try:
                if unit.lock_running and not allow_server_owned_ai_research_live_handoff_stop:
                    raise ValueError("该策略单元已锁定运行")
                if unit.lock_trading and not allow_server_owned_ai_research_live_handoff_stop:
                    raise ValueError("该策略单元已锁定交易")
                if unit.trading_instance_id:
                    protected_runtime = is_server_owned_ai_research_unit(unit)
                    stop_instance_kwargs: dict[str, Any] = {}
                    if protected_runtime:
                        stop_instance_kwargs["user_id"] = user_id
                        if allow_server_owned_ai_research_stop:
                            stop_instance_kwargs["allow_server_owned_ai_research_stop"] = True
                        if allow_server_owned_ai_research_live_handoff_stop:
                            stop_instance_kwargs[
                                "allow_server_owned_ai_research_live_handoff_stop"
                            ] = True
                    stop_result = await manager.stop_instance(
                        str(unit.trading_instance_id),
                        **stop_instance_kwargs,
                    )
                    if isinstance(stop_result, dict):
                        value = stop_result.get("open_order_cancel")
                        open_order_cancel = value if isinstance(value, dict) else None
                    stopped_instance = manager.get_instance(
                        str(unit.trading_instance_id), user_id=user_id
                    )
                    cancelled = True
                unit.run_status = "idle"
                if stopped_instance:
                    snapshot, metrics_snapshot, bar_count, elapsed_seconds = self._build_snapshot(
                        unit, stopped_instance
                    )
                    if metrics_snapshot:
                        unit.metrics_snapshot = metrics_snapshot
                    if bar_count is not None:
                        unit.bar_count = bar_count
                    if elapsed_seconds is not None:
                        unit.last_run_time = elapsed_seconds
                else:
                    snapshot = self.default_snapshot(unit=unit, instance_status="stopped")
                    snapshot["stopped_at"] = _now_local_text()
                if open_order_cancel is not None:
                    snapshot["open_order_cancel"] = open_order_cancel
                unit.trading_snapshot = snapshot
            except Exception as exc:
                metadata = getattr(exc, "open_order_cancel", None)
                if isinstance(metadata, dict):
                    open_order_cancel = metadata
                error_message = str(exc)
                unit.run_status = "failed"
                snapshot = self.default_snapshot(
                    unit=unit,
                    instance_status="error",
                    error=str(exc),
                )
                if open_order_cancel is not None:
                    snapshot["open_order_cancel"] = open_order_cancel
                unit.trading_snapshot = snapshot
            result: dict[str, Any] = {"unit_id": unit.id, "cancelled": cancelled}
            if error_message:
                result["error"] = error_message
            if open_order_cancel is not None:
                result["open_order_cancel"] = open_order_cancel
            results.append(result)

        return results

    def get_auto_trading_config(self) -> dict[str, Any]:
        return dict(get_auto_trading_scheduler().get_config())

    def update_auto_trading_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        scheduler = get_auto_trading_scheduler()
        return dict(
            scheduler.update_config(
                enabled=payload.get("enabled"),
                buffer_minutes=payload.get("buffer_minutes"),
                sessions=payload.get("sessions"),
                scope=payload.get("scope"),
            )
        )

    def get_auto_trading_schedule(self) -> list[dict[str, Any]]:
        scheduler = get_auto_trading_scheduler()
        return [dict(item) for item in scheduler.get_schedule()]

    @staticmethod
    def _instance_log_result(
        unit: StrategyUnit,
        user_id: str,
    ) -> dict[str, Any] | None:
        if not unit.trading_instance_id:
            return None
        manager = get_live_trading_manager()
        instance = manager.get_instance(unit.trading_instance_id, user_id=user_id)
        if not instance:
            return None
        log_dir = _instance_log_dir(instance)
        if not log_dir:
            return None
        return parse_log_dir(log_dir)

    @staticmethod
    def _weighted_avg_price(positions: list[dict[str, Any]]) -> float | None:
        total_size = 0.0
        total_cost = 0.0
        for item in positions:
            size = abs(_safe_float(item.get("size")))
            price = _safe_float(item.get("price"))
            if size <= 0 or price <= 0:
                continue
            total_size += size
            total_cost += size * price
        if total_size <= 0:
            return None
        return round(total_cost / total_size, 4)

    @staticmethod
    def _position_row_direction(row: dict[str, Any]) -> str:
        return _position_normalization.position_row_direction(
            row, dependencies=_position_normalization_dependencies()
        )

    @staticmethod
    def _first_row_number(row: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = row.get(key)
            if value in (None, ""):
                continue
            return _safe_float(value)
        return None

    @classmethod
    def _position_row_open_size(cls, row: dict[str, Any]) -> float:
        return _position_normalization.position_row_open_size(
            cls, row, dependencies=_position_normalization_dependencies()
        )

    @classmethod
    def _position_row_needs_response_valuation(cls, row: dict[str, Any]) -> bool:
        if abs(_safe_float(row.get("size"))) <= EPSILON and cls._has_any(
            row, *_POSITION_SIZE_ALIAS_KEYS
        ):
            return True
        if (
            abs(_safe_float(row.get("size"))) > EPSILON
            and not cls._has_any(row, *_EXPLICIT_NET_PNL_FIELD_KEYS)
            and cls._has_any(row, *_GROSS_PNL_FIELD_KEYS)
            and cls._has_any(row, *_COMMISSION_FIELD_KEYS)
        ):
            return True
        return cls._has_any(row, *_POSITION_RESPONSE_REVALUE_KEYS)

    @staticmethod
    def _numbers_close(left: float, right: float) -> bool:
        return abs(left - right) <= max(abs(left), abs(right), 1.0) * 1e-6

    @classmethod
    def _position_row_conflicts_with_unit_asset_spec(
        cls,
        unit: StrategyUnit,
        row: dict[str, Any],
    ) -> bool:
        if cls._position_source_for_row(row, None).lower() != "gateway":
            return False
        data_name = gateway_position_symbol(
            row,
            str(unit.symbol or unit.symbol_name or unit.strategy_name or ""),
        )
        spec = cls._contract_spec(
            unit,
            data_name,
            None,
            cls._asset_spec_config_for_row(_safe_dict(row)),
        )
        if not getattr(spec, "has_multiplier", False):
            return False

        valuation_row = dict(row)
        valuation_row["market_value_estimated"] = True
        valued = value_position(valuation_row, spec=spec)
        if valued is None:
            return False

        explicit_market_value = cls._first_row_number(
            row,
            "market_value",
            "marketValue",
            "mktValue",
            "positionValue",
            "position_value",
            "value",
        )
        if explicit_market_value is not None and not cls._numbers_close(
            abs(explicit_market_value),
            valued.market_value,
        ):
            return True

        return cls._has_any(row, *_EXPLICIT_NET_PNL_FIELD_KEYS) and not cls._has_any(
            row, "valuation_status"
        )

    @classmethod
    def _position_row_needs_asset_spec_revaluation(
        cls,
        unit: StrategyUnit,
        row: dict[str, Any],
    ) -> bool:
        if abs(_safe_float(row.get("size"))) <= EPSILON and not cls._has_any(
            row, *_POSITION_SIZE_ALIAS_KEYS
        ):
            return False
        if not cls._unit_has_asset_valuation_config(unit):
            return False
        row_source = cls._position_source_for_row(row, None).lower()
        if row_source == "gateway":
            if cls._position_row_conflicts_with_unit_asset_spec(unit, row):
                return True
            if cls._has_any(row, *_EXPLICIT_NET_PNL_FIELD_KEYS):
                return False
            if cls._has_any(row, "valuation_status", "commission", "gross_pnl"):
                return False
        if (
            cls._has_any(row, *_EXPLICIT_NET_PNL_FIELD_KEYS, *_GROSS_PNL_FIELD_KEYS, "pnl")
            and cls._has_any(
                row,
                "price",
                "avg_price",
                "average_price",
                "price_open",
                "entry_price",
                "avgCost",
                "avgPrice",
                "avgPx",
                "avg_entry_price",
                "avgEntryPrice",
                "entryPrice",
                "open_avg_price",
                "openAvgPrice",
                "Price",
                "AveragePrice",
            )
            and cls._has_any(
                row,
                *_CURRENT_PRICE_FIELD_KEYS,
                "market_value",
                "marketValue",
                "positionValue",
                "position_value",
                "value",
            )
        ):
            return True
        return not cls._has_any(row, "multiplier", "margin_rate", "margin_value")

    @classmethod
    def _position_rows_for_response_valuation(
        cls,
        rows: list[dict[str, Any]],
        snapshot: dict[str, Any],
        unit: StrategyUnit | None = None,
    ) -> list[dict[str, Any]]:
        latest_price = snapshot.get("latest_price")
        updated_at = snapshot.get("updated_at")
        valued_rows: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if unit is not None and cls._position_row_needs_asset_spec_revaluation(unit, item):
                item["force_recalculate_position_pnl"] = True
            if (
                latest_price not in (None, "")
                and cls._first_row_number(item, *_CURRENT_PRICE_FIELD_KEYS) is None
            ):
                item["latest_price"] = latest_price
            if updated_at not in (None, "") and not cls._position_updated_at(item):
                item["updated_at"] = updated_at
            valued_rows.append(item)
        return valued_rows

    async def build_positions_response(
        self,
        units: list[StrategyUnit],
        user_id: str,
        *,
        hydrate: bool = True,
    ) -> PositionManagerResponse:
        if hydrate:
            await self.hydrate_units(units, user_id)

        positions: list[dict[str, Any]] = []
        total_long_value = 0.0
        total_short_value = 0.0
        total_pnl = 0.0

        for unit in units:
            snapshot = _safe_dict(unit.trading_snapshot)
            position_rows = list(snapshot.get("positions") or [])
            raw_position_rows = [row for row in position_rows if isinstance(row, dict)]
            snapshot_revalued = False
            if raw_position_rows and any(
                self._position_row_needs_response_valuation(row)
                or self._position_row_needs_asset_spec_revaluation(unit, row)
                for row in raw_position_rows
            ):
                latest_price = self._apply_position_rows_to_snapshot(
                    snapshot,
                    unit,
                    None,
                    self._position_rows_for_response_valuation(
                        raw_position_rows,
                        snapshot,
                        unit,
                    ),
                )
                if latest_price is not None:
                    snapshot["latest_price"] = round(latest_price, 4)
                position_rows = list(snapshot.get("positions") or [])
                snapshot_revalued = True
            if snapshot_revalued and getattr(unit, "trading_snapshot", None) != snapshot:
                unit.trading_snapshot = snapshot
            active_position_rows = [
                row
                for row in position_rows
                if isinstance(row, dict) and self._position_row_open_size(row) > EPSILON
            ]
            if position_rows and not active_position_rows:
                continue
            long_position = _safe_float(snapshot.get("long_position"))
            short_position = _safe_float(snapshot.get("short_position"))
            long_market_value = _safe_float(snapshot.get("long_market_value"))
            short_market_value = _safe_float(snapshot.get("short_market_value"))
            position_pnl = _safe_float(snapshot.get("position_pnl"))
            if active_position_rows:
                derived_long_position = 0.0
                derived_short_position = 0.0
                derived_long_market_value = 0.0
                derived_short_market_value = 0.0
                has_row_market_value = False
                row_pnl_values: list[float] = []
                for row in active_position_rows:
                    size = abs(_safe_float(row.get("size")))
                    directional_sizes = _position_normalization.position_row_directional_sizes(
                        row,
                        size,
                        first_row_number=self._first_row_number,
                        dependencies=_position_normalization_dependencies(),
                    )
                    if directional_sizes is not None:
                        row_long, row_short = directional_sizes
                        derived_long_position += row_long
                        derived_short_position += row_short
                        row_market_value = self._first_row_number(row, "market_value")
                        if row_market_value is not None:
                            has_row_market_value = True
                            row_total = row_long + row_short
                            if row_total > EPSILON:
                                derived_long_market_value += abs(row_market_value) * (
                                    row_long / row_total
                                )
                                derived_short_market_value += abs(row_market_value) * (
                                    row_short / row_total
                                )
                        row_pnl = self._first_row_number(row, *_PNL_FIELD_KEYS)
                        if row_pnl is not None:
                            row_pnl_values.append(row_pnl)
                        continue
                    is_short = self._position_row_direction(row) == "short"
                    if is_short:
                        derived_short_position += size
                    else:
                        derived_long_position += size
                    row_market_value = self._first_row_number(row, "market_value")
                    if row_market_value is not None:
                        has_row_market_value = True
                        if is_short:
                            derived_short_market_value += abs(row_market_value)
                        else:
                            derived_long_market_value += abs(row_market_value)
                    row_pnl = self._first_row_number(row, *_PNL_FIELD_KEYS)
                    if row_pnl is not None:
                        row_pnl_values.append(row_pnl)
                if derived_long_position > EPSILON or derived_short_position > EPSILON:
                    long_position = derived_long_position
                    short_position = derived_short_position
                if has_row_market_value:
                    long_market_value = derived_long_market_value
                    short_market_value = derived_short_market_value
                if row_pnl_values:
                    position_pnl = sum(row_pnl_values)
            market_value = round(long_market_value + short_market_value, 2)
            if (
                abs(long_position) <= EPSILON
                and abs(short_position) <= EPSILON
                and not active_position_rows
            ):
                continue
            updated_at = self._latest_position_updated_at(position_rows) or _safe_iso_text(
                snapshot.get("updated_at")
            )
            data_time = self._latest_position_data_time(active_position_rows)
            data_name = (
                str(
                    active_position_rows[0].get("data_name")
                    or active_position_rows[0].get("symbol")
                    or ""
                )
                if len(active_position_rows) == 1
                else ""
            )
            position_source = _unique_text(
                [
                    row.get("position_source") or row.get("source")
                    for row in active_position_rows
                    if isinstance(row, dict)
                ]
            ) or _safe_iso_text(snapshot.get("position_source"))
            asset_spec_source = _unique_text(
                [
                    row.get("asset_spec_source")
                    for row in active_position_rows
                    if isinstance(row, dict)
                ]
            ) or _safe_iso_text(snapshot.get("asset_spec_source"))
            valuation_warnings: list[str] = []
            _append_unique(valuation_warnings, snapshot.get("valuation_warnings") or [])
            for row in active_position_rows:
                if isinstance(row, dict):
                    _append_unique(valuation_warnings, row.get("valuation_warnings") or [])
            valuation_status = str(snapshot.get("valuation_status") or "").strip() or (
                "estimated" if valuation_warnings else "confirmed"
            )
            margin_value = sum(_safe_float(row.get("margin_value")) for row in active_position_rows)
            commission = sum(_safe_float(row.get("commission")) for row in active_position_rows)
            commission_source = _unique_text(
                [
                    row.get("commission_source")
                    for row in active_position_rows
                    if isinstance(row, dict)
                ]
            )
            gross_pnl_values = [
                row.get("gross_pnl")
                for row in active_position_rows
                if isinstance(row, dict) and row.get("gross_pnl") not in (None, "")
            ]
            gross_pnl = (
                sum(_safe_float(value) for value in gross_pnl_values) if gross_pnl_values else None
            )
            total_long_value += long_market_value
            total_short_value += short_market_value
            total_pnl += position_pnl

            positions.append(
                {
                    "unit_id": str(unit.id),
                    "unit_name": str(unit.strategy_name or unit.strategy_id or unit.id),
                    "symbol": data_name or str(unit.symbol or ""),
                    "data_name": data_name or None,
                    "symbol_name": str(unit.symbol_name or "") or None,
                    "trading_mode": self.normalize_trading_mode(unit.trading_mode),
                    "long_position": _round_quantity(long_position),
                    "short_position": _round_quantity(short_position),
                    "avg_price": self._weighted_avg_price(active_position_rows),
                    "latest_price": (
                        round(_safe_float(snapshot.get("latest_price")), 4)
                        if snapshot.get("latest_price") is not None
                        else None
                    ),
                    "position_pnl": round(position_pnl, 2),
                    "market_value": market_value,
                    "long_market_value": round(long_market_value, 2),
                    "short_market_value": round(short_market_value, 2),
                    "margin_value": round(margin_value, 2) if active_position_rows else None,
                    "multiplier": _unique_number(
                        [
                            row.get("multiplier")
                            for row in active_position_rows
                            if isinstance(row, dict)
                        ]
                    ),
                    "margin_rate": _unique_number(
                        [
                            row.get("margin_rate")
                            for row in active_position_rows
                            if isinstance(row, dict)
                        ]
                    ),
                    "leverage": _unique_number(
                        [
                            row.get("leverage")
                            or _leverage_from_margin_rate(row.get("margin_rate"))
                            for row in active_position_rows
                            if isinstance(row, dict)
                        ]
                    ),
                    "commission": round(commission, 4) if active_position_rows else None,
                    "commission_source": commission_source,
                    "gross_pnl": round(gross_pnl, 2) if gross_pnl is not None else None,
                    "updated_at": updated_at,
                    "data_time": data_time,
                    "position_source": position_source,
                    "asset_spec_source": asset_spec_source,
                    "valuation_status": valuation_status,
                    "valuation_warnings": valuation_warnings,
                }
            )

        positions.sort(key=lambda item: (item["symbol"], item["unit_name"]))
        return PositionManagerResponse(
            positions=positions,
            total_long_value=round(total_long_value, 2),
            total_short_value=round(total_short_value, 2),
            total_pnl=round(total_pnl, 2),
        )

    async def build_daily_summary_response(
        self,
        units: list[StrategyUnit],
        user_id: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> TradingDailySummaryResponse:
        summary_by_day: dict[str, dict[str, Any]] = {}

        for unit in units:
            log_result = self._instance_log_result(unit, user_id)
            if not log_result:
                continue

            dates = [str(value)[:10] for value in (log_result.get("equity_dates") or []) if value]
            equity_curve = list(log_result.get("equity_curve") or [])
            drawdown_curve = list(log_result.get("drawdown_curve") or [])
            trades = list(log_result.get("trades") or [])
            initial_cash = _safe_float(log_result.get("initial_cash"), 0.0)

            trade_count_by_day: dict[str, int] = {}
            for trade in trades:
                trade_day = str(
                    trade.get("dtclose") or trade.get("datetime") or trade.get("dtopen") or ""
                )[:10]
                if trade_day:
                    trade_count_by_day[trade_day] = trade_count_by_day.get(trade_day, 0) + 1

            equity_by_day: dict[str, float] = {}
            drawdown_by_day: dict[str, float] = {}
            for index, trading_date in enumerate(dates):
                previous = next(reversed(equity_by_day.values()), initial_cash)
                equity_value = _safe_float(
                    equity_curve[index] if index < len(equity_curve) else previous,
                    previous,
                )
                equity_by_day[trading_date] = equity_value
                drawdown_value = _safe_float(
                    drawdown_curve[index] if index < len(drawdown_curve) else 0.0,
                    0.0,
                )
                drawdown_by_day[trading_date] = max(
                    drawdown_by_day.get(trading_date, 0.0),
                    drawdown_value,
                )

            prev_equity = initial_cash
            for trading_date in sorted(equity_by_day):
                equity_value = equity_by_day[trading_date]
                if start_date and trading_date < start_date:
                    prev_equity = equity_value
                    continue
                if end_date and trading_date > end_date:
                    break

                daily_pnl = equity_value - prev_equity
                prev_equity = equity_value
                drawdown_value = drawdown_by_day.get(trading_date, 0.0)
                bucket = summary_by_day.setdefault(
                    trading_date,
                    {
                        "trading_date": trading_date,
                        "daily_pnl": 0.0,
                        "trade_count": 0,
                        "cumulative_pnl": 0.0,
                        "max_drawdown": 0.0,
                    },
                )
                bucket["daily_pnl"] += daily_pnl
                bucket["trade_count"] += trade_count_by_day.get(trading_date, 0)
                bucket["cumulative_pnl"] += equity_value - initial_cash
                bucket["max_drawdown"] = max(bucket["max_drawdown"], drawdown_value)

        summaries = [
            {
                "trading_date": trading_date,
                "daily_pnl": round(payload["daily_pnl"], 2),
                "trade_count": _safe_int(payload["trade_count"]),
                "cumulative_pnl": round(payload["cumulative_pnl"], 2),
                "max_drawdown": round(payload["max_drawdown"], 2),
            }
            for trading_date, payload in sorted(summary_by_day.items())
        ]
        return TradingDailySummaryResponse(summaries=summaries)

    def build_status_responses(self, units: list[StrategyUnit]) -> list[UnitStatusResponse]:
        responses: list[UnitStatusResponse] = []
        for unit in units:
            responses.append(
                UnitStatusResponse(
                    id=str(unit.id),
                    run_status=str(unit.run_status or "idle"),
                    last_task_id=str(unit.last_task_id) if unit.last_task_id else None,
                    metrics_snapshot=_safe_dict(unit.metrics_snapshot),
                    run_count=int(unit.run_count or 0),
                    last_run_time=float(unit.last_run_time)
                    if unit.last_run_time is not None
                    else None,
                    bar_count=int(unit.bar_count) if unit.bar_count is not None else None,
                    trading_instance_id=str(unit.trading_instance_id)
                    if unit.trading_instance_id
                    else None,
                    trading_snapshot=_safe_dict(unit.trading_snapshot),
                    trading_mode=self.normalize_trading_mode(unit.trading_mode),
                    lock_trading=bool(unit.lock_trading),
                    lock_running=bool(unit.lock_running),
                    opt_status=None,
                    opt_total=None,
                    opt_completed=None,
                    opt_progress=None,
                    opt_elapsed_time=None,
                    opt_remaining_time=None,
                )
            )
        return responses
