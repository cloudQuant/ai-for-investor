"""Quote-page projection over exact operator-configured service-market keys.

Online quote and chart reads never construct a provider route from workspace
metadata and never fall back to the retired raw-ZMQ market path. Unconfigured
or unsupported online routes return finite capability errors. Imported and
research history remains on its independent local-data APIs.
"""

from __future__ import annotations

import logging
import math
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.quote.cache import (
    load_custom_symbols,
    load_hidden_subscriptions,
    save_custom_symbols,
    save_hidden_subscriptions,
)
from app.services.quote.registry import (
    DEFAULT_ASSET_TYPES as _DEFAULT_ASSET_TYPES,
)
from app.services.quote.registry import (
    DEFAULT_SYMBOLS as _DEFAULT_SYMBOLS,
)
from app.services.quote.registry import (
    DEFAULT_SYMBOLS_BY_ASSET as _DEFAULT_SYMBOLS_BY_ASSET,
)
from app.services.quote.registry import (
    SOURCE_REGISTRY as _SOURCE_REGISTRY,
)
from app.services.quote.registry import (
    SOURCE_TO_LABEL as _SOURCE_TO_LABEL,
)
from app.services.quote.registry import (
    resolve_quote_fields as _resolve_quote_fields,
)
from app.services.quote.service_market import (
    MarketQuoteResult as _MarketQuoteResult,
)
from app.services.quote.service_market import (
    ServiceMarketDeployment as _ServiceMarketDeployment,
)
from app.services.quote.service_market import (
    ServiceMarketDeploymentError as _ServiceMarketDeploymentError,
)
from app.services.quote.tick import (
    build_tick as _build_tick,
)

logger = logging.getLogger(__name__)

_SERVICE_MARKET_HISTORY_TIMEFRAMES = {
    "M1": ("1m", 60),
    "M3": ("3m", 3 * 60),
    "M5": ("5m", 5 * 60),
    "M15": ("15m", 15 * 60),
    "M30": ("30m", 30 * 60),
    "H1": ("1h", 60 * 60),
    "H4": ("4h", 4 * 60 * 60),
    "H2": ("2h", 2 * 60 * 60),
    "H6": ("6h", 6 * 60 * 60),
    "H12": ("12h", 12 * 60 * 60),
    "D1": ("1d", 24 * 60 * 60),
    "D2": ("2d", 2 * 24 * 60 * 60),
    "D3": ("3d", 3 * 24 * 60 * 60),
    "W1": ("1w", 7 * 24 * 60 * 60),
    "S1": ("1s", 1),
    "1s": ("1s", 1),
    "1m": ("1m", 60),
    "3m": ("3m", 3 * 60),
    "5m": ("5m", 5 * 60),
    "15m": ("15m", 15 * 60),
    "30m": ("30m", 30 * 60),
    "1h": ("1h", 60 * 60),
    "2h": ("2h", 2 * 60 * 60),
    "4h": ("4h", 4 * 60 * 60),
    "6h": ("6h", 6 * 60 * 60),
    "12h": ("12h", 12 * 60 * 60),
    "1d": ("1d", 24 * 60 * 60),
    "2d": ("2d", 2 * 24 * 60 * 60),
    "3d": ("3d", 3 * 24 * 60 * 60),
    "1w": ("1w", 7 * 24 * 60 * 60),
}


def _chart_error(
    source: str, symbol: str, timeframe: str, error_code: str
) -> dict[str, Any]:
    return {
        "source": source,
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": [],
        "total": 0,
        "complete": False,
        "error_code": error_code,
    }


def _history_time_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _parse_history_time(value: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ValueError
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError
    return parsed


def _chart_bar_from_history(bar: Any) -> dict[str, Any]:
    values: dict[str, float] = {}
    for name in ("open", "high", "low", "close", "volume"):
        value = getattr(bar, name, None)
        if type(value) is not str:
            raise ValueError
        number = float(value)
        if not math.isfinite(number):
            raise ValueError
        values[name] = number
    opened = getattr(bar, "open_time_utc", None)
    _parse_history_time(opened)
    return {"date": opened, **values}

# ---------------------------------------------------------------------------
# Persistent storage for custom symbols
# ---------------------------------------------------------------------------


# ===================================================================
# QuoteService
# ===================================================================


class QuoteService:
    """Singleton quote-page service with a bounded service-v2 market slice."""

    _instance: QuoteService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> QuoteService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init_state()
                    cls._instance = inst
        return cls._instance

    def _init_state(self) -> None:
        # custom symbols: {user_id: {source: [symbol, ...]}}
        self._custom_symbols: dict[str, dict[str, list[str]]] = load_custom_symbols()
        # Persistently hidden regular subscriptions. Running-workspace rows
        # never enter this collection because their dismissal is UI-local.
        self._hidden_subscriptions: dict[str, dict[str, list[str]]] = load_hidden_subscriptions()
        # Cleanup-only compatibility for receiver objects left alive by an
        # older in-process service version. New code never creates receivers.
        self._receivers: dict[str, Any] = {}
        # Matching cleanup-only state for those pre-existing receivers.
        self._subscribed_symbols: dict[str, set[str]] = {}
        self._service_market_loaded = False
        self._service_market_deployment: _ServiceMarketDeployment | None = None
        self._service_market_error: str | None = None
        self._service_market_load_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Data-source status
    # ------------------------------------------------------------------

    def get_data_sources(
        self,
        user_id: str = "",
        workspace_names: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return all data sources with their current status."""
        manager = self._get_live_trading_manager()
        workspace_context = self._get_running_workspace_context(
            manager,
            user_id,
            workspace_names,
        )

        results = []
        for reg in _SOURCE_REGISTRY:
            source = reg["source"]
            label = reg["source_label"]
            caps = reg["capabilities"]
            source_context = workspace_context.get(source, {})
            gateway_states = self._get_source_gateway_states(
                manager,
                source,
                source_context,
            )
            workspace_runs = self._build_workspace_runs(source_context)
            running_symbol_count = len(
                {
                    symbol_key
                    for gateway in source_context.values()
                    for symbol_key in gateway["symbols"]
                }
            )
            profile_symbols = [
                item["symbol"] for item in self._get_default_symbols_for_source(source)
            ]
            profile_symbols.extend(self._custom_symbols.get(user_id, {}).get(source, []))
            profile_symbols.extend(
                metadata["symbol"]
                for gateway in source_context.values()
                for metadata in gateway.get("symbols", {}).values()
            )
            profile_symbols = list(dict.fromkeys(profile_symbols))
            routes, market_config_error, _deployment = (
                self._configured_service_market_routes(source, user_id, profile_symbols)
            )

            if not caps:
                status = "unavailable"
                msg = "UNSUPPORTED_CAPABILITY"
            elif source != "OKX":
                status = "unavailable"
                msg = "UNSUPPORTED_CAPABILITY"
            elif market_config_error is not None:
                status = "unavailable"
                msg = market_config_error
            elif routes:
                status = "available"
                msg = None
            else:
                status = "not_configured"
                msg = "SERVICE_MARKET_PROFILE_REQUIRED"

            results.append(
                {
                    "source": source,
                    "source_label": label,
                    "status": status,
                    "status_message": msg,
                    "capabilities": caps,
                    "gateway_count": len(gateway_states),
                    "workspace_count": len(workspace_runs),
                    "running_symbol_count": running_symbol_count,
                    "workspaces": workspace_runs,
                }
            )
        return results

    # ------------------------------------------------------------------
    # Symbols
    # ------------------------------------------------------------------

    def get_symbols(self, source: str, user_id: str) -> dict[str, Any]:
        """Return symbols plus the complete configured category catalog for a source."""
        source = str(source or "").strip().upper()
        hidden = self._hidden_symbol_set(source, user_id)
        defaults = [
            item
            for item in self._get_default_symbols_for_source(source)
            if item["symbol"] not in hidden
        ]
        customs = self._custom_symbols.get(user_id, {}).get(source, [])
        context = self._get_running_workspace_context(
            self._get_live_trading_manager(),
            user_id,
        ).get(source, {})
        default_map = {item["symbol"]: item for item in defaults}
        running_symbols: list[dict[str, str]] = []
        seen: set[str] = set()
        for gateway in context.values():
            for symbol_key, metadata in gateway["symbols"].items():
                if symbol_key in seen:
                    continue
                seen.add(symbol_key)
                symbol = metadata["symbol"]
                running_symbols.append(
                    dict(
                        default_map.get(
                            symbol,
                            {
                                "symbol": symbol,
                                "name": "",
                                "exchange": "",
                                "category": "",
                            },
                        )
                    )
                )
        return {
            "source": source,
            "default_symbols": defaults,
            "custom_symbols": customs,
            "running_symbols": running_symbols,
            "categories": self.get_source_categories(source),
        }

    @staticmethod
    def get_source_categories(source: str) -> list[str]:
        """Return every configured category for a data source.

        Quote snapshots may contain only the instruments currently subscribed
        by a gateway.  Deriving the filter menu from those rows hides valid
        categories whenever a market is inactive or a workspace uses a small
        symbol subset, so build the catalog from both base and asset-specific
        symbol configuration instead.
        """
        normalized_source = str(source or "").strip().upper()
        configured_symbols = list(_DEFAULT_SYMBOLS.get(normalized_source, []))
        for (configured_source, _asset_type), symbols in _DEFAULT_SYMBOLS_BY_ASSET.items():
            if str(configured_source).strip().upper() == normalized_source:
                configured_symbols.extend(symbols)

        categories = {
            str(item.get("category") or "").strip()
            for item in configured_symbols
            if isinstance(item, dict) and str(item.get("category") or "").strip()
        }
        return sorted(categories)

    def _hidden_symbol_set(self, source: str, user_id: str) -> set[str]:
        normalized_source = str(source or "").strip().upper()
        return {
            str(symbol).strip()
            for symbol in self._hidden_subscriptions.get(user_id, {}).get(normalized_source, [])
            if str(symbol).strip()
        }

    def _unhide_subscription_symbols(self, source: str, user_id: str, symbols: list[str]) -> None:
        normalized_source = str(source or "").strip().upper()
        restore_set = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
        if not restore_set:
            return
        by_source = self._hidden_subscriptions.get(user_id)
        if not by_source or normalized_source not in by_source:
            return
        by_source[normalized_source] = [
            symbol for symbol in by_source[normalized_source] if symbol not in restore_set
        ]
        if not by_source[normalized_source]:
            by_source.pop(normalized_source, None)
        if not by_source:
            self._hidden_subscriptions.pop(user_id, None)
        save_hidden_subscriptions(self._hidden_subscriptions)

    def add_custom_symbols(self, source: str, user_id: str, symbols: list[str]) -> list[str]:
        """Add custom symbols for a user+source. Returns updated list."""
        source = str(source or "").strip().upper()
        if user_id not in self._custom_symbols:
            self._custom_symbols[user_id] = {}
        if source not in self._custom_symbols[user_id]:
            self._custom_symbols[user_id][source] = []

        existing = set(self._custom_symbols[user_id][source])
        for s in symbols:
            if s not in existing:
                self._custom_symbols[user_id][source].append(s)
                existing.add(s)

        self._unhide_subscription_symbols(source, user_id, symbols)

        save_custom_symbols(self._custom_symbols)
        return self._custom_symbols[user_id][source]

    def remove_custom_symbols(self, source: str, user_id: str, symbols: list[str]) -> list[str]:
        """Remove custom symbols. Returns updated list."""
        source = str(source or "").strip().upper()
        if user_id not in self._custom_symbols:
            return []
        if source not in self._custom_symbols[user_id]:
            return []

        remove_set = set(symbols)
        self._custom_symbols[user_id][source] = [
            s for s in self._custom_symbols[user_id][source] if s not in remove_set
        ]
        save_custom_symbols(self._custom_symbols)
        return self._custom_symbols[user_id][source]

    def remove_subscriptions(self, source: str, user_id: str, symbols: list[str]) -> list[str]:
        """Permanently remove saved/default subscriptions for a user.

        This intentionally excludes workspace-driven rows: the frontend hides
        those only for its current session so a refresh or service restart
        restores the strategy's live instrument monitoring.
        """
        source = str(source or "").strip().upper()
        remove_set = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
        if not source or not remove_set:
            return self._custom_symbols.get(user_id, {}).get(source, [])

        user_custom = self._custom_symbols.setdefault(user_id, {})
        if source in user_custom:
            user_custom[source] = [
                symbol for symbol in user_custom[source] if symbol not in remove_set
            ]
        hidden_by_source = self._hidden_subscriptions.setdefault(user_id, {})
        current_hidden = set(hidden_by_source.get(source, []))
        current_hidden.update(remove_set)
        hidden_by_source[source] = sorted(current_hidden)
        save_custom_symbols(self._custom_symbols)
        save_hidden_subscriptions(self._hidden_subscriptions)
        return user_custom.get(source, [])

    def search_symbols(self, source: str, keyword: str) -> list[dict[str, str]]:
        """Search symbols within a data source by keyword."""
        keyword_lower = keyword.lower()
        defaults = self._get_default_symbols_for_source(source)
        results = []
        for item in defaults:
            if (
                keyword_lower in item["symbol"].lower()
                or keyword_lower in item.get("name", "").lower()
            ):
                results.append(item)
        return results

    # ------------------------------------------------------------------
    # Quote data
    # ------------------------------------------------------------------

    def get_quotes(
        self,
        source: str,
        user_id: str,
        symbols: list[str] | None = None,
        workspace_names: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch quote ticks for the given source and symbol list.

        If *symbols* is ``None``, returns quotes for default + custom symbols.
        """
        source = str(source or "").strip().upper()
        label = _SOURCE_TO_LABEL.get(source, source)
        manager = self._get_live_trading_manager()
        if symbols is None:
            hidden = self._hidden_symbol_set(source, user_id)
            subscription_symbols = [
                item["symbol"]
                for item in self._get_default_symbols_for_source(source)
                if item["symbol"] not in hidden
            ]
            subscription_symbols.extend(self._custom_symbols.get(user_id, {}).get(source, []))
        else:
            subscription_symbols = symbols
        subscription_symbols = list(
            dict.fromkeys(str(sym).strip() for sym in subscription_symbols if str(sym).strip())
        )

        workspace_context = self._get_running_workspace_context(
            manager,
            user_id,
            workspace_names,
        ).get(source, {})
        workspace_symbols = [
            metadata["symbol"]
            for gateway in workspace_context.values()
            for metadata in gateway.get("symbols", {}).values()
        ]
        route_symbols = list(dict.fromkeys([*subscription_symbols, *workspace_symbols]))
        service_market_results, service_market_config_error = self._read_service_market_quotes(
            source,
            user_id,
            route_symbols,
        )
        has_configured_market_routes = bool(service_market_results) and (
            service_market_config_error is None
        )
        missing_route_error = (
            "UNSUPPORTED_CAPABILITY"
            if source != "OKX"
            else "SERVICE_MARKET_PROFILE_REQUIRED"
        )
        if service_market_config_error is not None:
            missing_route_error = service_market_config_error
        for symbol in route_symbols:
            service_market_results.setdefault(
                symbol,
                _MarketQuoteResult(None, missing_route_error, False),
            )
        service_market_symbols = set(service_market_results)
        service_market_symbol_keys = {symbol.upper() for symbol in service_market_symbols}

        defaults_map: dict[str, dict[str, str]] = {}
        for item in self._get_default_symbols_for_source(source):
            defaults_map[item["symbol"]] = item

        now = datetime.now(timezone.utc).isoformat()
        ticks: list[dict[str, Any]] = []
        has_service_market = any(result.healthy for result in service_market_results.values())

        workspace_symbol_metadata: dict[str, dict[str, set[str]]] = {}
        for gateway in workspace_context.values():
            for symbol_key, metadata in gateway.get("symbols", {}).items():
                if symbol_key not in service_market_symbol_keys:
                    continue
                row = workspace_symbol_metadata.setdefault(
                    symbol_key,
                    {"workspace_ids": set(), "workspace_names": set()},
                )
                row["workspace_ids"].update(metadata["workspace_ids"])
                row["workspace_names"].update(metadata["workspace_names"])
        for symbol, result in service_market_results.items():
            meta = defaults_map.get(
                symbol,
                {"symbol": symbol, "name": "", "exchange": "OKX", "category": ""},
            )
            raw = dict(result.data) if result.data is not None else None
            tick = self._build_tick(source, label, symbol, meta, raw, now)
            if result.error_code is not None:
                tick["status"] = "error"
                tick["error_message"] = result.error_code
            tick["quote_key"] = f"service-market:{symbol}"
            tick["gateway_key"] = "service-market"
            origins = set()
            if symbol in subscription_symbols:
                origins.add("subscription")
            if symbol.upper() in workspace_symbol_metadata:
                origins.add("workspace")
            tick["origins"] = sorted(origins)
            metadata = workspace_symbol_metadata.get(
                symbol.upper(), {"workspace_ids": set(), "workspace_names": set()}
            )
            tick["workspace_ids"] = sorted(metadata["workspace_ids"])
            tick["workspace_names"] = sorted(metadata["workspace_names"])
            ticks.append(tick)
        fields = _resolve_quote_fields(source, ticks)

        return {
            "source": source,
            "source_label": label,
            "total": len(ticks),
            "ticks": ticks,
            "fields": fields,
            "update_time": now,
            "refresh_mode": (
                "push"
                if has_service_market
                else "polling"
                if has_configured_market_routes
                else "manual"
            ),
        }

    def _read_service_market_quotes(
        self,
        source: str,
        subject: str,
        symbols: list[str],
    ) -> tuple[dict[str, _MarketQuoteResult], str | None]:
        """Read only keys selected by the exact configured JWT subject."""

        if source != "OKX" or not symbols:
            return {}, None
        routes, config_error, deployment = self._configured_service_market_routes(
            source,
            subject,
            symbols,
        )
        if config_error is not None:
            return {
                symbol: _MarketQuoteResult(None, config_error, False)
                for symbol in symbols
            }, config_error
        if deployment is None or not routes:
            return {}, None
        try:
            observations = deployment.read_quotes(subject, routes, wait_ms=250)
        except _ServiceMarketDeploymentError as error:
            return {
                symbol: _MarketQuoteResult(None, error.code, False)
                for symbol in routes
            }, None
        except Exception:
            return {
                symbol: _MarketQuoteResult(None, "SERVICE_MARKET_UNAVAILABLE", False)
                for symbol in routes
            }, None
        by_stream = observations
        return {
            symbol: by_stream.get(
                key.stream_id,
                _MarketQuoteResult(None, "SERVICE_MARKET_RESULT_MISSING", False),
            )
            for symbol, key in routes.items()
        }, None

    def _configured_service_market_routes(
        self,
        source: str,
        subject: str,
        symbols: list[str],
    ) -> tuple[dict[str, Any], str | None, _ServiceMarketDeployment | None]:
        """Resolve configured keys without starting an owner or reading events."""

        if source != "OKX" or not symbols:
            return {}, None, None
        with self._service_market_load_lock:
            if not self._service_market_loaded:
                try:
                    self._service_market_deployment = (
                        _ServiceMarketDeployment.from_environment()
                    )
                except _ServiceMarketDeploymentError as error:
                    self._service_market_error = error.code
                finally:
                    self._service_market_loaded = True
            config_error = self._service_market_error
            deployment = self._service_market_deployment
        if config_error is not None:
            return {}, config_error, None
        if deployment is None:
            return {}, None, None
        routes = deployment.configured_routes(subject, source, symbols)
        return routes, None, deployment

    def _configured_service_market_history_route(
        self,
        source: str,
        subject: str,
        symbol: str,
        timeframe: str,
    ) -> tuple[Any | None, bool, str | None, _ServiceMarketDeployment | None]:
        """Resolve one exact bar key without starting an operator or owner."""

        if source.strip().upper() != "OKX" or type(symbol) is not str or not symbol:
            return None, False, None, None
        with self._service_market_load_lock:
            if not self._service_market_loaded:
                try:
                    self._service_market_deployment = (
                        _ServiceMarketDeployment.from_environment()
                    )
                except _ServiceMarketDeploymentError as error:
                    self._service_market_error = error.code
                finally:
                    self._service_market_loaded = True
            config_error = self._service_market_error
            deployment = self._service_market_deployment
        if config_error is not None or deployment is None:
            return None, False, config_error, deployment
        configured_symbol = deployment.has_configured_history_symbol(
            subject, source, symbol
        )
        if not configured_symbol:
            return None, False, None, deployment
        key = deployment.configured_history_key(
            subject, source, symbol, timeframe
        )
        return key, True, None, deployment

    # ------------------------------------------------------------------
    # Chart data (P1)
    # ------------------------------------------------------------------

    def get_chart_data(
        self,
        source: str,
        symbol: str,
        timeframe: str = "M1",
        count: int = 200,
        subject: str | None = None,
    ) -> dict[str, Any]:
        """Fetch bars only from an exact configured service-v2 history route."""
        if subject is not None:
            timeframe_value = timeframe.strip() if type(timeframe) is str else ""
            service_timeframe = _SERVICE_MARKET_HISTORY_TIMEFRAMES.get(
                timeframe_value
            ) or _SERVICE_MARKET_HISTORY_TIMEFRAMES.get(timeframe_value.upper())
            timeframe_key = service_timeframe[0] if service_timeframe else ""
            key, configured_symbol, config_error, deployment = (
                self._configured_service_market_history_route(
                    source, subject, symbol, timeframe_key
                )
            )
            if config_error is not None:
                return _chart_error(source, symbol, timeframe, config_error)
            if configured_symbol:
                if service_timeframe is None or key is None or deployment is None:
                    return _chart_error(
                        source,
                        symbol,
                        timeframe,
                        "HISTORY_TIMEFRAME_NOT_CONFIGURED",
                    )
                return self._read_service_market_chart_history(
                    deployment,
                    subject,
                    source,
                    symbol,
                    timeframe,
                    key,
                    count,
                    service_timeframe[1],
                )
        error_code = (
            "UNSUPPORTED_CAPABILITY"
            if source.strip().upper() != "OKX"
            else "SERVICE_MARKET_PROFILE_REQUIRED"
        )
        return _chart_error(source, symbol, timeframe, error_code)

    def _read_service_market_chart_history(
        self,
        deployment: _ServiceMarketDeployment,
        subject: str,
        source: str,
        symbol: str,
        timeframe: str,
        key: Any,
        count: int,
        bar_duration_seconds: int,
    ) -> dict[str, Any]:
        if type(count) is not int or isinstance(count, bool) or not 1 <= count <= 1_000:
            return _chart_error(source, symbol, timeframe, "INVALID_HISTORY_LIMIT")
        try:
            from bt_api_base.market_history_protocol import (
                MarketHistoryPage,
                MarketHistoryRequest,
            )
        except ImportError:
            return _chart_error(source, symbol, timeframe, "SDK_HISTORY_PROTOCOL_UNAVAILABLE")

        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=bar_duration_seconds * count)
        start_text = _history_time_text(start)
        end_text = _history_time_text(end)
        try:
            request = MarketHistoryRequest(
                key=key,
                start_time_utc=start_text,
                end_time_utc=end_text,
                limit=count,
            )
            page = deployment.read_history_page(
                subject,
                source,
                symbol,
                key.timeframe,
                key,
                request,
            )
            if type(page) is not MarketHistoryPage or page.request != request:
                raise _ServiceMarketDeploymentError("INVALID_HISTORY_PAGE")
            normalized = [_chart_bar_from_history(bar) for bar in page.bars]
        except _ServiceMarketDeploymentError as error:
            return _chart_error(source, symbol, timeframe, error.code)
        except Exception:
            return _chart_error(source, symbol, timeframe, "SERVICE_MARKET_HISTORY_UNAVAILABLE")

        return {
            "source": source,
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": normalized,
            "total": len(normalized),
            "complete": page.complete,
            "error_code": None if page.complete else "HISTORY_RESULT_INCOMPLETE",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_live_trading_manager():
        """Read an existing manager without starting legacy session restoration."""
        try:
            from app.services.live_trading_manager import get_existing_live_trading_manager

            return get_existing_live_trading_manager()
        except Exception:
            return None

    @staticmethod
    def _snapshot_gateway_states(manager: Any) -> dict[str, dict[str, Any]]:
        """Safely snapshot the manager's in-memory gateway registry."""
        if manager is None:
            return {}
        try:
            lock = getattr(manager, "_gateway_lock", None)
            if lock is None:
                states = dict(getattr(manager, "_gateways", {}))
            else:
                with lock:
                    states = dict(getattr(manager, "_gateways", {}))
            return {
                str(gateway_key): state
                for gateway_key, state in states.items()
                if isinstance(state, dict) and state.get("config") is not None
            }
        except Exception:
            logger.debug("Unable to snapshot gateway states for quote monitoring", exc_info=True)
            return {}

    def _get_running_workspace_context(
        self,
        manager: Any,
        user_id: str,
        workspace_names: dict[str, str] | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Group running workspace instruments by source and gateway.

        Only instances belonging to the current user are included.  The
        result is intentionally keyed by concrete gateway session, which
        prevents duplicate subscriptions when many strategy units share one
        gateway while still preserving separate sessions of the same exchange.
        """
        if manager is None or not user_id:
            return {}
        try:
            instances = manager.list_instances(user_id=user_id)
        except Exception:
            logger.debug("Unable to list running workspace instances", exc_info=True)
            return {}

        states = self._snapshot_gateway_states(manager)
        instance_gateways: dict[str, str] = {}
        try:
            lock = getattr(manager, "_gateway_lock", None)
            if lock is None:
                instance_gateways = {
                    str(instance_id): str(gateway_key)
                    for instance_id, gateway_key in getattr(
                        manager, "_instance_gateways", {}
                    ).items()
                }
            else:
                with lock:
                    instance_gateways = {
                        str(instance_id): str(gateway_key)
                        for instance_id, gateway_key in getattr(
                            manager, "_instance_gateways", {}
                        ).items()
                    }
        except Exception:
            logger.debug("Unable to read instance gateway assignments", exc_info=True)

        names = workspace_names or {}
        context: dict[str, dict[str, dict[str, Any]]] = {}
        for instance in instances:
            if str(instance.get("status") or "").lower() != "running":
                continue
            params = instance.get("params")
            if not isinstance(params, dict):
                continue
            workspace_unit = params.get("workspace_unit")
            if not isinstance(workspace_unit, dict):
                # Regular live-trading instances remain available as manual
                # subscriptions but are not presented as a trading workspace.
                continue
            workspace_id = str(workspace_unit.get("workspace_id") or "").strip()
            if not workspace_id:
                continue
            symbol = str(params.get("symbol") or "").strip()
            if not symbol:
                continue
            instance_id = str(instance.get("id") or "").strip()
            gateway_key = instance_gateways.get(instance_id, "")
            if not gateway_key:
                for candidate_key, state in states.items():
                    linked_instances = state.get("instances", set()) or set()
                    if instance_id in {str(item) for item in linked_instances}:
                        gateway_key = candidate_key
                        break
            gateway_state = states.get(gateway_key)
            if gateway_state is None:
                continue
            source = str(gateway_state.get("exchange_type") or "").strip().upper()
            if not source:
                continue

            source_context = context.setdefault(source, {})
            gateway = source_context.setdefault(
                gateway_key,
                {
                    "state": gateway_state,
                    "symbols": {},
                    "workspaces": {},
                },
            )
            symbol_key = symbol.upper()
            workspace_name = str(
                names.get(workspace_id) or workspace_unit.get("workspace_name") or workspace_id
            ).strip()
            gateway["symbols"].setdefault(
                symbol_key,
                {
                    "symbol": symbol,
                    "workspace_ids": set(),
                    "workspace_names": set(),
                },
            )
            gateway["symbols"][symbol_key]["workspace_ids"].add(workspace_id)
            gateway["symbols"][symbol_key]["workspace_names"].add(workspace_name)
            workspace = gateway["workspaces"].setdefault(
                workspace_id,
                {
                    "workspace_id": workspace_id,
                    "workspace_name": workspace_name,
                    "symbols": set(),
                },
            )
            workspace["symbols"].add(symbol)
        return context

    def _get_source_gateway_states(
        self,
        manager: Any,
        source: str,
        workspace_context: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Return visible manual and running-workspace gateways for a source."""
        normalized_source = str(source or "").strip().upper()
        result: dict[str, dict[str, Any]] = {}
        for gateway_key, state in self._snapshot_gateway_states(manager).items():
            if str(state.get("exchange_type") or "").strip().upper() == normalized_source and bool(
                state.get("manual")
            ):
                result[gateway_key] = state
        for gateway_key, gateway in (workspace_context or {}).items():
            workspace_state = gateway.get("state")
            if isinstance(workspace_state, dict):
                result[gateway_key] = workspace_state
        return result

    @staticmethod
    def _build_workspace_runs(
        workspace_context: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Format workspace monitor metadata for the data-source endpoint."""
        runs: list[dict[str, Any]] = []
        for gateway_key, gateway in workspace_context.items():
            for workspace in gateway["workspaces"].values():
                symbols = sorted(workspace["symbols"])
                runs.append(
                    {
                        "workspace_id": workspace["workspace_id"],
                        "workspace_name": workspace["workspace_name"],
                        "gateway_key": gateway_key,
                        "symbol_count": len(symbols),
                        "symbols": symbols,
                    }
                )
        return sorted(runs, key=lambda item: (item["workspace_name"], item["gateway_key"]))

    def _get_default_symbols_for_source(self, source: str) -> list[dict[str, str]]:
        manager = self._get_live_trading_manager()
        state = self._find_gateway_state(manager, source)
        asset_type = self._get_source_asset_type(source, state)
        return list(
            _DEFAULT_SYMBOLS_BY_ASSET.get((source, asset_type), _DEFAULT_SYMBOLS.get(source, []))
        )

    @staticmethod
    def _get_source_asset_type(source: str, state: dict[str, Any] | None) -> str:
        if state is None:
            return _DEFAULT_ASSET_TYPES.get(source, "")
        asset_type = (
            str(state.get("asset_type") or getattr(state.get("config"), "asset_type", "") or "")
            .strip()
            .upper()
        )
        if asset_type:
            return asset_type
        return _DEFAULT_ASSET_TYPES.get(source, "")

    def _find_gateway_state(self, manager, source: str) -> dict[str, Any] | None:
        """Find in-memory gateway metadata without probing its command channel."""
        _gateway_key, state = self._find_gateway_state_with_key(manager, source)
        return state

    def _find_gateway_state_with_key(
        self,
        manager: Any,
        source: str,
    ) -> tuple[str, dict[str, Any] | None]:
        """Find metadata for a manual gateway without starting or probing it."""
        normalized_source = str(source or "").strip().upper()
        candidates = [
            (gateway_key, state)
            for gateway_key, state in self._snapshot_gateway_states(manager).items()
            if str(state.get("exchange_type") or "").strip().upper() == normalized_source
        ]
        manual = [(key, state) for key, state in candidates if state.get("manual")]
        preferred = manual or candidates
        if preferred:
            return preferred[0]
        return "", None

    @staticmethod
    def _build_tick(
        source: str,
        label: str,
        symbol: str,
        meta: dict[str, str],
        raw: dict[str, Any] | None,
        now: str,
    ) -> dict[str, Any]:
        """Build a QuoteTick dict from a normalized market projection."""
        return _build_tick(source, label, symbol, meta, raw, now)

    def shutdown(self) -> bool:
        """Stop quote owners and report whether service-market clients closed."""
        with self._service_market_load_lock:
            deployment = self._service_market_deployment
            market_owners_closed = deployment is None
            if deployment is not None:
                try:
                    deployment.close()
                except _ServiceMarketDeploymentError as error:
                    logger.error("Service-market shutdown reported %s", error.code)
                except Exception:
                    logger.exception("Unexpected service-market shutdown failure")
                else:
                    market_owners_closed = True
            if market_owners_closed and self._service_market_deployment is deployment:
                self._service_market_deployment = None
                self._service_market_error = None
                self._service_market_loaded = False
        for gateway_key, receiver in tuple(self._receivers.items()):
            try:
                receiver.stop()
            except Exception:
                logger.exception("Error stopping receiver for %s", gateway_key)
            else:
                self._receivers.pop(gateway_key, None)
                self._subscribed_symbols.pop(gateway_key, None)
        return market_owners_closed


def get_quote_service() -> QuoteService:
    """Dependency-injection helper."""
    return QuoteService()
