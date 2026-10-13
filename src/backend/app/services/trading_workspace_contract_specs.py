"""Contract metadata discovery and alias-merging helpers for trading workspaces."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

from app.models.workspace import StrategyUnit
from app.services.trading_asset_info_service import symbol_aliases

if TYPE_CHECKING:
    from app.services.position_valuation import PositionSpec
    from app.services.trading_workspace_service import TradingWorkspaceService


class ContractSpecFactory(Protocol):
    def __call__(
        self,
        symbol: str,
        *configs: dict[str, Any] | None,
    ) -> PositionSpec: ...


_ASSET_SPEC_CONTRACT_KEYS = frozenset(
    {
        "multiplier",
        "mult",
        "contract_size",
        "trade_contract_size",
        "contract_multiplier",
        "ctVal",
        "VolumeMultiple",
        "CONTRACT_MULTIPLIER",
    }
)

_ASSET_SPEC_MARGIN_KEYS = frozenset(
    {
        "margin",
        "margin_rate",
        "margin_ratio",
        "leverage",
        "margin_amount",
        "initial_margin_per_lot",
        "margin_initial",
        "long_margin_rate",
        "short_margin_rate",
        "LongMarginRatio",
        "ShortMarginRatio",
        "LongMarginRatioByMoney",
        "ShortMarginRatioByMoney",
        "MARGIN_BUY",
        "MARGIN_SELL",
        "long_margin_amount",
        "short_margin_amount",
        "LongMarginRatioByVolume",
        "ShortMarginRatioByVolume",
        "MARGIN_PER_LOT",
        "LONG_MARGIN_AMOUNT",
        "SHORT_MARGIN_AMOUNT",
    }
)

_ASSET_SPEC_FEE_KEYS = frozenset(
    {
        "commission",
        "commission_rate",
        "open_commission_rate",
        "close_commission_rate",
        "close_today_commission_rate",
        "maker_commission_rate",
        "taker_commission_rate",
        "commission_amount",
        "open_commission_amount",
        "close_commission_amount",
        "close_today_commission_amount",
        "OpenRatioByMoney",
        "CloseRatioByMoney",
        "CloseTodayRatioByMoney",
        "OpenRatioByVolume",
        "CloseRatioByVolume",
        "CloseTodayRatioByVolume",
    }
)

_ASSET_SPEC_AUX_KEYS = frozenset(
    {
        "symbol",
        "data_name",
        "instrument",
        "InstrumentID",
        "exchange",
        "exchange_id",
        "asset_type",
        "instType",
        "contract_type",
        "ctType",
        "base_asset",
        "baseCcy",
        "quote_asset",
        "quoteCcy",
        "settle_currency",
        "settleCcy",
        "fee_currency",
        "feeCcy",
        "current_price",
        "latest_price",
        "last_price",
        "mark_price",
        "price_tick",
        "tick_size",
        "tickSz",
        "min_order_size",
        "min_qty",
        "minSz",
        "max_order_size",
        "max_qty",
        "maxLmtSz",
        "order_size_step",
        "lotSz",
    }
)


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]
    return value


def _asset_spec_for_symbol(specs: dict[str, dict[str, Any]], symbol: str) -> dict[str, Any]:
    for key in symbol_aliases(symbol):
        item = specs.get(key)
        if isinstance(item, dict):
            return dict(item)
    return {}


def _metadata_from_config(config: dict[str, Any], symbol: str) -> dict[str, Any]:
    for container_key in ("contract_metadata", "contracts", "contract_specs", "instrument_specs"):
        container = config.get(container_key)
        if not isinstance(container, dict):
            continue
        item = _asset_spec_for_symbol(
            {str(key): value for key, value in container.items() if isinstance(value, dict)},
            symbol,
        )
        if item:
            return item
    return {}


def _merge_unit_contract_metadata(
    specs: dict[str, dict[str, Any]],
    unit: StrategyUnit,
    instance: Mapping[str, object] | None,
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    completed = {str(key): dict(value) for key, value in specs.items() if isinstance(value, dict)}
    instance_params = _safe_dict((instance or {}).get("params"))
    configs = (
        _safe_dict(getattr(unit, "params", None)),
        _safe_dict(getattr(unit, "unit_settings", None)),
        _safe_dict(getattr(unit, "data_config", None)),
        _safe_dict(getattr(unit, "gateway_config", None)),
        instance_params,
        _safe_dict(instance_params.get("unit_settings")),
        _safe_dict(instance_params.get("data_config")),
        _safe_dict(instance_params.get("gateway")),
        _safe_dict(instance_params.get("simulate")),
        _safe_dict(instance_params.get("backtest")),
        _safe_dict(instance_params.get("live")),
    )
    for symbol in symbols:
        for config in configs:
            metadata = _metadata_from_config(config, symbol)
            if metadata:
                _merge_asset_spec_aliases(completed, symbol, metadata)
    return completed


def _merge_asset_spec_aliases(
    specs: dict[str, dict[str, Any]],
    symbol: str,
    spec: dict[str, Any],
) -> None:
    if not spec:
        return
    spec = _json_safe_value(spec)
    existing = _asset_spec_for_symbol(specs, symbol)
    merged = dict(existing)
    core_contributed = False
    primary_source_contributed = False
    for key, value in spec.items():
        if _can_merge_asset_spec_value(existing, key, value):
            merged[key] = value
            if _is_asset_spec_core_key(key):
                core_contributed = True
            if _is_asset_spec_primary_source_key(existing, key):
                primary_source_contributed = True
    existing_source = str(existing.get("source") or existing.get("asset_spec_source") or "").strip()
    next_source = str(spec.get("source") or spec.get("asset_spec_source") or "").strip()
    if existing_source and next_source and existing_source != next_source and core_contributed:
        merged["source"] = _combined_asset_spec_source(existing_source, next_source)
        merged["asset_spec_source"] = merged["source"]
    elif next_source and not existing_source and primary_source_contributed:
        merged["source"] = next_source
        merged["asset_spec_source"] = next_source
    for key in symbol_aliases(symbol):
        specs[str(key)] = dict(merged)


def _combined_asset_spec_source(*sources: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for part in str(source or "").split("+"):
            text = part.strip()
            if text and text not in seen:
                parts.append(text)
                seen.add(text)
    return "+".join(parts)


def _can_merge_asset_spec_value(existing: dict[str, Any], key: str, value: Any) -> bool:
    if key in {"source", "asset_spec_source"} or value in (None, ""):
        return False
    if existing.get(key) not in (None, ""):
        return False
    if key in _ASSET_SPEC_CONTRACT_KEYS:
        return not _asset_spec_has_any(existing, _ASSET_SPEC_CONTRACT_KEYS)
    if key in _ASSET_SPEC_MARGIN_KEYS:
        return not _asset_spec_has_any(existing, _ASSET_SPEC_MARGIN_KEYS)
    if key in _ASSET_SPEC_FEE_KEYS:
        return not _asset_spec_has_any(existing, _ASSET_SPEC_FEE_KEYS)
    return key in _ASSET_SPEC_AUX_KEYS


def _is_asset_spec_core_key(key: str) -> bool:
    return (
        key in _ASSET_SPEC_CONTRACT_KEYS
        or key in _ASSET_SPEC_MARGIN_KEYS
        or key in _ASSET_SPEC_FEE_KEYS
    )


def _is_asset_spec_primary_source_key(existing: dict[str, Any], key: str) -> bool:
    if key in _ASSET_SPEC_CONTRACT_KEYS or key in _ASSET_SPEC_MARGIN_KEYS:
        return True
    if key in _ASSET_SPEC_FEE_KEYS:
        return not (
            _asset_spec_has_any(existing, _ASSET_SPEC_CONTRACT_KEYS)
            or _asset_spec_has_any(existing, _ASSET_SPEC_MARGIN_KEYS)
        )
    return key in _ASSET_SPEC_AUX_KEYS and not existing


def _asset_spec_has_any(spec: dict[str, Any], keys: frozenset[str]) -> bool:
    return any(spec.get(key) not in (None, "") for key in keys)


def _merge_asset_spec_update(
    existing: dict[str, Any],
    update: dict[str, Any],
) -> dict[str, Any]:
    update = _json_safe_value(update)
    merged = dict(existing)
    core_changed = False
    primary_source_changed = False
    for group in (
        _ASSET_SPEC_CONTRACT_KEYS,
        _ASSET_SPEC_MARGIN_KEYS,
        _ASSET_SPEC_FEE_KEYS,
    ):
        group_items = {key: update.get(key) for key in group if update.get(key) not in (None, "")}
        if not group_items:
            continue
        for key in group:
            if key in merged:
                merged.pop(key, None)
                core_changed = True
                if _is_asset_spec_primary_source_key(existing, key):
                    primary_source_changed = True
        for key, value in group_items.items():
            if merged.get(key) != value:
                merged[key] = value
                core_changed = True
                if _is_asset_spec_primary_source_key(existing, key):
                    primary_source_changed = True
    for key, value in update.items():
        if key in {"source", "asset_spec_source"} or value in (None, ""):
            continue
        if (
            key in _ASSET_SPEC_CONTRACT_KEYS
            or key in _ASSET_SPEC_MARGIN_KEYS
            or key in _ASSET_SPEC_FEE_KEYS
        ):
            continue
        if key in _ASSET_SPEC_AUX_KEYS and merged.get(key) != value:
            merged[key] = value

    existing_source = str(existing.get("source") or existing.get("asset_spec_source") or "").strip()
    next_source = str(update.get("source") or update.get("asset_spec_source") or "").strip()
    if existing_source and next_source and existing_source != next_source and core_changed:
        merged["source"] = _combined_asset_spec_source(existing_source, next_source)
        merged["asset_spec_source"] = merged["source"]
    elif next_source and not existing_source and primary_source_changed:
        merged["source"] = next_source
        merged["asset_spec_source"] = next_source
    return merged


def complete_asset_specs_from_local(
    specs: dict[str, dict[str, Any]],
    symbols: list[str],
    query_local_asset_spec: Callable[[str], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    completed = {str(key): dict(value) for key, value in specs.items() if isinstance(value, dict)}
    for symbol in symbols:
        try:
            local_spec = query_local_asset_spec(symbol)
        except Exception:
            local_spec = {}
        if isinstance(local_spec, dict) and local_spec:
            _merge_asset_spec_aliases(completed, symbol, local_spec)
    return completed


def _append_symbol_candidate(target: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in target:
        target.append(text)


def _append_config_symbols(target: list[str], config: dict[str, Any]) -> None:
    for key in (
        "symbol",
        "data_name",
        "instrument",
        "InstrumentID",
        "trade_symbol",
        "contract_symbol",
        "localSymbol",
        "local_symbol",
        "contractDesc",
        "contract_desc",
        "description",
        "ticker",
    ):
        _append_symbol_candidate(target, config.get(key))
    for key in ("symbols", "symbol_list", "instruments"):
        values = config.get(key)
        if isinstance(values, (list, tuple, set)):
            for value in values:
                _append_symbol_candidate(target, value)
    for section_key in ("data_config", "data", "live", "gateway", "params"):
        section = config.get(section_key)
        if isinstance(section, dict):
            _append_config_symbols(target, section)
    for container_key in ("contract_metadata", "contracts", "contract_specs", "instrument_specs"):
        container = config.get(container_key)
        if not isinstance(container, dict):
            continue
        for key, item in container.items():
            _append_symbol_candidate(target, key)
            if isinstance(item, dict):
                _append_config_symbols(target, item)


def _safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def resolve_contract_spec(
    cls: type[TradingWorkspaceService],
    unit: StrategyUnit,
    symbol: str,
    instance: Mapping[str, object] | None = None,
    *extra_configs: dict[str, Any],
    contract_spec_for: ContractSpecFactory,
    query_local_asset_spec: Callable[[str], dict[str, Any]],
) -> PositionSpec:
    instance_params = _safe_dict((instance or {}).get("params"))
    configs = (
        *extra_configs,
        _safe_dict(getattr(unit, "unit_settings", None)),
        _safe_dict(getattr(unit, "params", None)),
        _safe_dict(getattr(unit, "data_config", None)),
        _safe_dict(getattr(unit, "gateway_config", None)),
        instance_params,
        _safe_dict(instance_params.get("unit_settings")),
        _safe_dict(instance_params.get("data_config")),
        _safe_dict(instance_params.get("gateway")),
        _safe_dict(instance_params.get("simulate")),
        _safe_dict(instance_params.get("backtest")),
        _safe_dict(instance_params.get("live")),
    )
    spec = contract_spec_for(symbol, *configs)
    if cls._position_spec_has_asset_metadata(spec):
        return spec
    if not any(cls._config_can_use_local_asset_spec(config) for config in configs):
        return spec
    try:
        local_spec = query_local_asset_spec(symbol)
    except Exception:
        local_spec = {}
    if isinstance(local_spec, dict) and local_spec:
        return contract_spec_for(symbol, local_spec, *configs)
    return spec
