"""Asset specification lookup, merge, and source adapters for portfolios."""

from collections.abc import Callable
from typing import Any

from app.api.portfolio.portfolio_common import (
    _EXPLICIT_NET_PNL_FIELD_KEYS,
    _GROSS_PNL_FIELD_KEYS,
    _has_any,
    _json_safe_value,
    _PortfolioSource,
)
from app.services.position_valuation import contract_spec_for
from app.services.trading_asset_info_service import query_local_asset_spec, symbol_aliases

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


def _merge_source_contract_metadata(
    specs: dict[str, dict[str, Any]],
    source: _PortfolioSource,
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    completed = {str(key): dict(value) for key, value in specs.items() if isinstance(value, dict)}
    for symbol in symbols:
        for config in source.valuation_configs:
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
    for group in (_ASSET_SPEC_CONTRACT_KEYS, _ASSET_SPEC_MARGIN_KEYS, _ASSET_SPEC_FEE_KEYS):
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


def _position_spec_has_asset_metadata(spec: Any) -> bool:
    return bool(
        getattr(spec, "has_multiplier", False)
        or getattr(spec, "has_margin_rate", False)
        or getattr(spec, "has_margin_amount", False)
        or getattr(spec, "has_commission", False)
    )


def _row_can_use_local_asset_spec(row: dict[str, Any]) -> bool:
    if _has_any(row, *_EXPLICIT_NET_PNL_FIELD_KEYS, *_GROSS_PNL_FIELD_KEYS, "pnl"):
        return True
    return _has_any(
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
    ) and _has_any(
        row,
        "current_price",
        "latest_price",
        "last_price",
        "mark_price",
        "markPrice",
        "markPx",
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


def _contract_spec_for_position(
    symbol: str,
    row: dict[str, Any],
    source: _PortfolioSource,
    *,
    contract_spec_for_fn: Callable[..., Any] = contract_spec_for,
    query_local_asset_spec_fn: Callable[[str], Any] = query_local_asset_spec,
) -> Any:
    spec = contract_spec_for_fn(symbol, row, source.snapshot or {}, *source.valuation_configs)
    if _position_spec_has_asset_metadata(spec):
        return spec
    if not _row_can_use_local_asset_spec(row):
        return spec
    try:
        local_spec = query_local_asset_spec_fn(symbol)
    except Exception:
        local_spec = {}
    if isinstance(local_spec, dict) and local_spec:
        return contract_spec_for_fn(
            symbol,
            row,
            local_spec,
            source.snapshot or {},
            *source.valuation_configs,
        )
    return spec


def _complete_asset_specs_from_local(
    specs: dict[str, dict[str, Any]],
    symbols: list[str],
    *,
    query_local_asset_spec_fn: Callable[[str], Any] = query_local_asset_spec,
) -> dict[str, dict[str, Any]]:
    completed = {str(key): dict(value) for key, value in specs.items() if isinstance(value, dict)}
    for symbol in symbols:
        try:
            local_spec = query_local_asset_spec_fn(symbol)
        except Exception:
            local_spec = {}
        if isinstance(local_spec, dict) and local_spec:
            _merge_asset_spec_aliases(completed, symbol, local_spec)
    return completed


def _append_symbol_candidate(target: list[str], value: Any) -> None:
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _append_symbol_candidate(target, item)
        return
    text = str(value or "").strip()
    if text:
        target.append(text)


def _source_symbol_aliases(source: _PortfolioSource) -> set[str]:
    candidates: list[str] = []
    _append_symbol_candidate(candidates, source.symbol)
    for config in source.valuation_configs:
        if not isinstance(config, dict):
            continue
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
            "symbols",
            "symbol_list",
        ):
            _append_symbol_candidate(candidates, config.get(key))
        data_config = config.get("data_config")
        if isinstance(data_config, dict):
            for key in ("symbol", "symbols", "symbol_list", "instrument", "InstrumentID"):
                _append_symbol_candidate(candidates, data_config.get(key))
        for container_key in (
            "contract_metadata",
            "contracts",
            "contract_specs",
            "instrument_specs",
        ):
            container = config.get(container_key)
            if not isinstance(container, dict):
                continue
            for item_key in container.keys():
                _append_symbol_candidate(candidates, item_key)
            for item in container.values():
                if not isinstance(item, dict):
                    continue
                for key in (
                    "symbol",
                    "data_name",
                    "instrument",
                    "InstrumentID",
                    "REFERENCE_CODE",
                    "localSymbol",
                    "local_symbol",
                    "contractDesc",
                    "contract_desc",
                    "description",
                ):
                    _append_symbol_candidate(candidates, item.get(key))

    aliases: set[str] = set()
    for candidate in candidates:
        for alias in symbol_aliases(candidate):
            aliases.add(alias)
            aliases.add(alias.upper())
    return aliases


def _position_symbol_matches(symbol: str, allowed_aliases: set[str]) -> bool:
    if not allowed_aliases:
        return True
    return any(
        alias in allowed_aliases or alias.upper() in allowed_aliases
        for alias in symbol_aliases(symbol)
    )
