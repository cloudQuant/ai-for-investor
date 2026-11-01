from __future__ import annotations

import math
import typing
from collections.abc import Hashable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import pandas as pd
from sqlalchemy import text

from app.db.akshare_data_database import _get_akshare_data_engine

MarketAssetType = Literal["stock", "futures", "bond", "fund", "option", "fx", "crypto"]
_RowKey = typing.TypeVar("_RowKey", bound=Hashable)


class LegacyMarketDataOnlineRefreshDisabledError(RuntimeError):
    """Raised when a legacy endpoint attempts an untracked online refresh."""

    code = "MARKET_DATA_LEGACY_ONLINE_REFRESH_DISABLED"


_BUILTIN_INSTRUMENTS: dict[MarketAssetType, tuple[tuple[str, str, str], ...]] = {
    "stock": (
        ("000001", "平安银行", "CN"),
        ("600519", "贵州茅台", "CN"),
        ("300750", "宁德时代", "CN"),
    ),
    "futures": (("RB0", "螺纹钢连续", "CF"), ("IF0", "沪深 300 股指连续", "CFFEX")),
    "bond": (("sh110074", "银华转债", "CN"),),
    "fund": (("510300", "沪深 300 ETF", "CN"),),
    "option": (("MO", "中证 1000 期权主力合约", "CFFEX"),),
    "fx": (("USDCNH", "美元离岸人民币", "FX"),),
    "crypto": (("BTCJPY", "比特币 / 日元", "CRYPTO"),),
}

_WAREHOUSE_PROVIDER = "akshare_data"
_ONLINE_PROVIDER = "akshare"
_HISTORY_FRESHNESS_DAYS: dict[MarketAssetType, int] = {
    # These are calendar-day tolerances, deliberately wider than a single
    # session so normal weekends and provider publication delays do not force
    # an unnecessary online fetch. They are still narrow enough to prevent an
    # old warehouse fallback from being presented as current market data.
    "stock": 5,
    "futures": 5,
    "bond": 5,
    "fund": 5,
    "option": 5,
    "fx": 5,
    "crypto": 2,
}


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _safe_int(value: Any) -> int | None:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return int(numeric)


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


def _first_present(row: Mapping[_RowKey, object], *keys: str) -> object | None:
    for key in keys:
        for row_key, value in row.items():
            if isinstance(row_key, str) and row_key == key and value is not None:
                return value
    return None


def _name_or_fallback(value: object, fallback: str) -> str:
    """Keep a non-empty string name, but never display a numeric snapshot value as a name."""
    return value if isinstance(value, str) and value else fallback


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    """Return the first present value, accepting both original and lower-case keys."""
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        if not key:
            continue
        if key in row and row[key] is not None:
            return row[key]
        lowered_value = lowered.get(key.lower())
        if lowered_value is not None:
            return lowered_value
    return None


def _date_text(value: date | str | None, fallback: date) -> str:
    if value is None:
        return fallback.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    return value.replace("-", "")


def _sql_date_text(value: date | str | None, fallback: date) -> str:
    if value is None:
        return fallback.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _coerce_date(value: Any) -> date | None:
    """Return a date value without silently accepting an invalid timestamp."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _iso_date(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return str(value)


def _normalize_plain_code(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if "." in normalized:
        left, right = normalized.split(".", 1)
        if left in {"SH", "SZ", "BJ"}:
            return right
        if right in {"SH", "SZ", "BJ"}:
            return left
        return left
    if normalized.startswith(("SH", "SZ", "BJ")) and len(normalized) > 2:
        return normalized[2:]
    return normalized


def _normalize_exchange_symbol(symbol: str, default_prefix: str = "sh") -> str:
    normalized = symbol.strip().lower()
    if "." in normalized:
        code, exchange = normalized.split(".", 1)
        if exchange in {"sh", "sz", "bj"}:
            return f"{exchange}{code}"
    if normalized.startswith(("sh", "sz", "bj")):
        return normalized
    return f"{default_prefix}{normalized}"


def _normalize_tencent_stock_symbol(symbol: str) -> str:
    """Return the Tencent/AkShare exchange-prefixed form for an A-share code."""
    code = _normalize_plain_code(symbol).lower()
    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def _normalize_upper_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "")


def _coerce_cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _coerce_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _coerce_cell(value) for key, value in row.items()}


def _normalize_period(period: str) -> str:
    period_map = {
        "1d": "daily",
        "daily": "daily",
        "day": "daily",
        "1w": "weekly",
        "weekly": "weekly",
        "week": "weekly",
        "1m": "monthly",
        "1M": "monthly",
        "monthly": "monthly",
        "month": "monthly",
    }
    return period_map.get(period, "daily")


class MarketInstrumentService:
    """Aggregate quote snapshots and history for market data lookup pages."""

    async def list_instruments(
        self,
        *,
        asset_type: MarketAssetType,
        search: str = "",
        limit: int = 80,
    ) -> dict[str, Any]:
        """Return selectable instruments from the local market data warehouse."""
        normalized_limit = max(1, min(limit, 200))
        lookup_map = {
            "stock": self._list_stock_instruments,
            "futures": self._list_futures_instruments,
            "bond": self._list_bond_instruments,
            "fund": self._list_fund_instruments,
            "option": self._list_option_instruments,
            "fx": self._list_fx_instruments,
            "crypto": self._list_crypto_instruments,
        }
        lookup = lookup_map.get(asset_type)
        if lookup is None:
            raise ValueError(f"Unsupported asset type: {asset_type}")
        normalized_search = search.strip()
        try:
            items = await lookup(search=normalized_search, limit=normalized_limit)
        except Exception:
            items = []
        try:
            cached_items = await self._list_cached_instruments(
                asset_type=asset_type,
                search=normalized_search,
                limit=normalized_limit,
            )
        except Exception:
            cached_items = []
        items = self._normalize_instrument_options(
            [*items, *cached_items],
            asset_type,
            normalized_limit,
        )
        if not items:
            items = self._fallback_instruments(
                asset_type=asset_type,
                search=normalized_search,
                limit=normalized_limit,
            )
        return {
            "asset_type": asset_type,
            "items": items,
            "total": len(items),
        }

    async def lookup(
        self,
        *,
        asset_type: MarketAssetType,
        symbol: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        period: str = "daily",
        market: str | None = None,
        refresh_online: bool = False,
    ) -> dict[str, Any]:
        """Read an exact instrument from the local warehouse.

        The compatibility endpoint intentionally cannot perform an online
        refresh.  Online provider I/O must use the v2 local-first query path,
        which establishes source authorization, immutable receipts, and a
        persisted local reread before returning a result.
        """
        if asset_type not in _BUILTIN_INSTRUMENTS:
            raise ValueError(f"Unsupported asset type: {asset_type}")
        if refresh_online:
            raise LegacyMarketDataOnlineRefreshDisabledError(
                LegacyMarketDataOnlineRefreshDisabledError.code
            )

        normalized_symbol = symbol.strip().upper()
        end = date.today()
        start = end - timedelta(days=90)
        normalized_period = _normalize_period(period)
        warnings: list[str] = []

        if asset_type == "option" and self._is_option_alias(normalized_symbol):
            warnings.append("期权查询必须使用精确合约代码；不支持主力或别名回退。")
            payload = self._empty_lookup_payload(
                asset_type=asset_type,
                symbol=normalized_symbol,
                market=market,
                period=normalized_period,
            )
            payload["warnings"] = warnings
            payload["indicators"] = self._build_indicators([])
            return payload

        warehouse_payload = await self._lookup_warehouse(
            asset_type=asset_type,
            symbol=normalized_symbol,
            start_date=start_date or start,
            end_date=end_date or end,
            period=normalized_period,
            market=market,
            warnings=warnings,
        )
        if not self._payload_matches_request(
            asset_type=asset_type,
            symbol=normalized_symbol,
            market=market,
            payload=warehouse_payload,
        ):
            warnings.append("本地行情未返回所请求的精确标的，已忽略该结果。")
            warehouse_payload = self._empty_lookup_payload(
                asset_type=asset_type,
                symbol=normalized_symbol,
                market=market,
                period=normalized_period,
            )
        else:
            if not (warehouse_payload.get("history") or {}).get("rows"):
                warehouse_payload = await self._fill_history_from_local_cache(
                    asset_type=asset_type,
                    warehouse_payload=warehouse_payload,
                    symbol=normalized_symbol,
                    start_date=start_date or start,
                    end_date=end_date or end,
                    period=normalized_period,
                    warnings=warnings,
                )
            if not self._payload_has_data(warehouse_payload):
                warnings.append("本地行情未找到所请求的精确标的。")
        warehouse_payload["warnings"] = warnings
        warehouse_payload["indicators"] = self._build_indicators(
            warehouse_payload["history"]["rows"]
        )
        return warehouse_payload

    async def _lookup_warehouse(
        self,
        *,
        asset_type: MarketAssetType,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        lookup_map = {
            "stock": self._lookup_stock_warehouse,
            "futures": self._lookup_futures_warehouse,
            "bond": self._lookup_bond_warehouse,
            "fund": self._lookup_fund_warehouse,
            "option": self._lookup_option_warehouse,
            "fx": self._lookup_fx_warehouse,
            "crypto": self._lookup_crypto_warehouse,
        }
        lookup = lookup_map[asset_type]
        try:
            return await lookup(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                period=period,
                market=market,
                warnings=warnings,
            )
        except RuntimeError:
            warnings.append("本地 MySQL 行情仓库不可用，请检查数据源访问权限。")
        except Exception:
            warnings.append("本地 MySQL 行情仓库不可用，请检查数据源访问权限。")
        return self._payload(
            asset_type=asset_type,
            symbol=symbol,
            name=symbol,
            market=market or self._default_market(asset_type),
            snapshot={},
            rows=[],
            period=period,
            provider=_WAREHOUSE_PROVIDER,
        )

    @staticmethod
    def _payload_has_data(payload: dict[str, Any]) -> bool:
        snapshot = payload.get("snapshot") or {}
        rows = (payload.get("history") or {}).get("rows") or []
        # ``_snapshot_from_latest_history`` uses symbol/name-only metadata
        # when AkShare has no rows.  Those identifiers describe the request,
        # not a market observation, so they must not overwrite usable MySQL
        # warehouse data after a user-triggered online refresh.
        return snapshot.get("price") is not None or bool(rows)

    @staticmethod
    def _identity_key(asset_type: MarketAssetType, symbol: Any) -> str:
        value = _safe_str(symbol) or ""
        if not value:
            return ""
        if asset_type in {"stock", "fund"}:
            return _normalize_plain_code(value).upper()
        if asset_type == "bond":
            return _normalize_exchange_symbol(value).upper()
        return value.upper()

    @classmethod
    def _payload_matches_request(
        cls,
        *,
        asset_type: MarketAssetType,
        symbol: str,
        market: str | None,
        payload: dict[str, Any],
    ) -> bool:
        expected_symbol = cls._identity_key(asset_type, symbol)
        if not expected_symbol:
            return False

        snapshot = payload.get("snapshot") or {}
        for returned_symbol in (payload.get("symbol"), snapshot.get("symbol")):
            if returned_symbol is None:
                continue
            if cls._identity_key(asset_type, returned_symbol) != expected_symbol:
                return False

        if market:
            returned_market = _safe_str(payload.get("market"))
            if returned_market and returned_market.upper() != market.strip().upper():
                return False
        return True

    def _empty_lookup_payload(
        self,
        *,
        asset_type: MarketAssetType,
        symbol: str,
        market: str | None,
        period: str,
    ) -> dict[str, Any]:
        return self._payload(
            asset_type=asset_type,
            symbol=symbol,
            name=symbol,
            market=market or self._default_market(asset_type),
            snapshot={},
            rows=[],
            period=period,
            provider=_WAREHOUSE_PROVIDER,
        )

    @staticmethod
    def _is_option_alias(symbol: str) -> bool:
        return symbol.strip().upper() in {
            "IO",
            "IO0",
            "CFFEX_IO",
            "HO",
            "HO0",
            "CFFEX_HO",
            "MO",
            "MO0",
            "CFFEX_MO",
        }

    @staticmethod
    def _history_requires_refresh(
        *,
        asset_type: MarketAssetType,
        rows: list[dict[str, Any]],
        start_date: date | str,
        end_date: date | str,
    ) -> bool:
        """Return whether rows cannot safely satisfy the requested market interval.

        A non-empty response is not sufficient evidence of usable market data:
        legacy fallbacks can contain a valid-looking 2024 row for a current
        request. Require the latest bar to be inside the requested interval and
        within the source-specific publication-lag tolerance.
        """
        from app.services.market_instrument_dynamic_data import (
            _history_requires_refresh as _delegate,
        )

        return _delegate(asset_type=asset_type, rows=rows, start_date=start_date, end_date=end_date)

    async def _fill_history_gap(
        self,
        *,
        asset_type: MarketAssetType,
        warehouse_payload: dict[str, Any],
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_dynamic_data import (
            _fill_history_gap as _delegate,
        )

        return await _delegate(
            self,
            asset_type=asset_type,
            warehouse_payload=warehouse_payload,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    async def _fill_history_from_local_cache(
        self,
        *,
        asset_type: MarketAssetType,
        warehouse_payload: dict[str, Any],
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_dynamic_data import (
            _fill_history_from_local_cache as _delegate,
        )

        return await _delegate(
            self,
            asset_type=asset_type,
            warehouse_payload=warehouse_payload,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            warnings=warnings,
        )

    def _merge_history_gap(
        self,
        *,
        warehouse_payload: dict[str, Any],
        rows: list[dict[str, Any]],
        period: str,
        provider_suffix: str,
    ) -> dict[str, Any]:
        from app.services.market_instrument_dynamic_data import (
            _merge_history_gap as _delegate,
        )

        return _delegate(
            self,
            warehouse_payload=warehouse_payload,
            rows=rows,
            period=period,
            provider_suffix=provider_suffix,
        )

    def _lookup_history_online(
        self,
        *,
        asset_type: MarketAssetType,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        from app.services.market_instrument_dynamic_data import (
            _lookup_history_online as _delegate,
        )

        return _delegate(
            self,
            asset_type=asset_type,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    def _lookup_stock_history_online(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        from app.services.market_instrument_dynamic_data import (
            _lookup_stock_history_online as _delegate,
        )

        return _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            warnings=warnings,
        )

    async def _list_stock_instruments(self, *, search: str, limit: int) -> list[dict[str, Any]]:
        from app.services.market_instrument_asset_catalog import (
            _list_stock_instruments as _delegate,
        )

        return await _delegate(self, search=search, limit=limit)

    async def _list_futures_instruments(self, *, search: str, limit: int) -> list[dict[str, Any]]:
        from app.services.market_instrument_asset_catalog import (
            _list_futures_instruments as _delegate,
        )

        return await _delegate(self, search=search, limit=limit)

    async def _list_bond_instruments(self, *, search: str, limit: int) -> list[dict[str, Any]]:
        from app.services.market_instrument_asset_catalog import (
            _list_bond_instruments as _delegate,
        )

        return await _delegate(self, search=search, limit=limit)

    async def _list_fund_instruments(self, *, search: str, limit: int) -> list[dict[str, Any]]:
        from app.services.market_instrument_asset_catalog import (
            _list_fund_instruments as _delegate,
        )

        return await _delegate(self, search=search, limit=limit)

    async def _list_option_instruments(self, *, search: str, limit: int) -> list[dict[str, Any]]:
        from app.services.market_instrument_asset_catalog import (
            _list_option_instruments as _delegate,
        )

        return await _delegate(self, search=search, limit=limit)

    async def _list_fx_instruments(self, *, search: str, limit: int) -> list[dict[str, Any]]:
        from app.services.market_instrument_asset_catalog import (
            _list_fx_instruments as _delegate,
        )

        return await _delegate(self, search=search, limit=limit)

    async def _list_crypto_instruments(self, *, search: str, limit: int) -> list[dict[str, Any]]:
        from app.services.market_instrument_asset_catalog import (
            _list_crypto_instruments as _delegate,
        )

        return await _delegate(self, search=search, limit=limit)

    @staticmethod
    def _instrument_query_params(search: str, limit: int) -> dict[str, Any]:
        from app.services.market_instrument_asset_catalog import (
            _instrument_query_params as _delegate,
        )

        return _delegate(search=search, limit=limit)

    def _normalize_instrument_options(
        self,
        rows: list[dict[str, Any]],
        asset_type: MarketAssetType,
        limit: int,
    ) -> list[dict[str, Any]]:
        from app.services.market_instrument_asset_catalog import (
            _normalize_instrument_options as _delegate,
        )

        return _delegate(self, rows=rows, asset_type=asset_type, limit=limit)

    @staticmethod
    def _fallback_instruments(
        *,
        asset_type: MarketAssetType,
        search: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return safe starter symbols when the optional warehouse is unavailable."""
        from app.services.market_instrument_asset_catalog import (
            _fallback_instruments as _delegate,
        )

        return _delegate(asset_type=asset_type, search=search, limit=limit)

    async def _list_cached_instruments(
        self,
        *,
        asset_type: MarketAssetType,
        search: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        from app.services.market_instrument_asset_catalog import (
            _list_cached_instruments as _delegate,
        )

        return await _delegate(self, asset_type=asset_type, search=search, limit=limit)

    async def _lookup_history_cache(
        self,
        *,
        asset_type: MarketAssetType,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
    ) -> list[dict[str, Any]]:
        from app.services.market_instrument_dynamic_data import (
            _lookup_history_cache as _delegate,
        )

        return await _delegate(
            self,
            asset_type=asset_type,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
        )

    async def _store_history_cache(
        self,
        *,
        asset_type: MarketAssetType,
        symbol: str,
        name: str,
        market: str,
        period: str,
        rows: list[dict[str, Any]],
    ) -> str | None:
        from app.services.market_instrument_dynamic_data import (
            _store_history_cache as _delegate,
        )

        return await _delegate(
            self,
            asset_type=asset_type,
            symbol=symbol,
            name=name,
            market=market,
            period=period,
            rows=rows,
        )

    @staticmethod
    def _default_market(asset_type: MarketAssetType) -> str:
        return {
            "stock": "CN",
            "futures": "CN",
            "bond": "CN",
            "fund": "CN",
            "option": "CN",
            "fx": "FX",
            "crypto": "CRYPTO",
        }[asset_type]

    async def _fetch_rows(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        engine = _get_akshare_data_engine()
        if engine is None:
            raise RuntimeError("AKSHARE_DATA_DATABASE_URL is not configured")
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params or {})
            return [_coerce_row(dict(row)) for row in result.mappings().all()]

    async def _fetch_one(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        rows = await self._fetch_rows(sql, params)
        return rows[0] if rows else None

    async def _lookup_stock_warehouse(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_stock_warehouse as _delegate,
        )

        return await _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    async def _lookup_futures_warehouse(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_futures_warehouse as _delegate,
        )

        return await _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    async def _lookup_bond_warehouse(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_bond_warehouse as _delegate,
        )

        return await _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    async def _lookup_fund_warehouse(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_fund_warehouse as _delegate,
        )

        return await _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    async def _lookup_option_warehouse(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_option_warehouse as _delegate,
        )

        return await _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    async def _lookup_fx_warehouse(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_fx_warehouse as _delegate,
        )

        return await _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    async def _lookup_crypto_warehouse(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_crypto_warehouse as _delegate,
        )

        return await _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    @staticmethod
    def _normalize_warehouse_history(
        rows: list[dict[str, Any]],
        *,
        date_key: str,
        open_key: str | None = None,
        high_key: str | None = None,
        low_key: str | None = None,
        close_key: str | None = None,
        volume_key: str | None = None,
        turnover_key: str | None = None,
        change_key: str | None = None,
        change_pct_key: str | None = None,
        turnover_rate_key: str | None = None,
        open_interest_key: str | None = None,
        settle_key: str | None = None,
    ) -> list[dict[str, Any]]:
        from app.services.market_instrument_projection import (
            _normalize_warehouse_history as _delegate,
        )

        return _delegate(
            rows=rows,
            date_key=date_key,
            open_key=open_key,
            high_key=high_key,
            low_key=low_key,
            close_key=close_key,
            volume_key=volume_key,
            turnover_key=turnover_key,
            change_key=change_key,
            change_pct_key=change_pct_key,
            turnover_rate_key=turnover_rate_key,
            open_interest_key=open_interest_key,
            settle_key=settle_key,
        )

    @staticmethod
    def _normalize_fx_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from app.services.market_instrument_projection import (
            _normalize_fx_history as _delegate,
        )

        return _delegate(rows=rows)

    def _lookup_stock(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_stock as _delegate,
        )

        return _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    def _lookup_futures(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_futures as _delegate,
        )

        return _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    def _lookup_bond(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_bond as _delegate,
        )

        return _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    def _lookup_fund(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_fund as _delegate,
        )

        return _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    def _lookup_option(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_option as _delegate,
        )

        return _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    def _lookup_fx(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_fx as _delegate,
        )

        return _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    def _lookup_crypto(
        self,
        *,
        symbol: str,
        start_date: date | str,
        end_date: date | str,
        period: str,
        market: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        from app.services.market_instrument_asset_adapter import (
            _lookup_crypto as _delegate,
        )

        return _delegate(
            self,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            warnings=warnings,
        )

    def _snapshot_from_cn_quote(self, row: dict[str, Any], *, symbol: str) -> dict[str, Any]:
        from app.services.market_instrument_projection import (
            _snapshot_from_cn_quote as _delegate,
        )

        return _delegate(self, row=row, symbol=symbol)

    def _snapshot_from_latest_history(
        self,
        symbol: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from app.services.market_instrument_projection import (
            _snapshot_from_latest_history as _delegate,
        )

        return _delegate(self, symbol=symbol, rows=rows)

    def _payload(
        self,
        *,
        asset_type: MarketAssetType,
        symbol: str,
        name: str,
        market: str,
        snapshot: dict[str, Any],
        rows: list[dict[str, Any]],
        period: str,
        provider: str = _ONLINE_PROVIDER,
    ) -> dict[str, Any]:
        from app.services.market_instrument_projection import (
            _payload as _delegate,
        )

        return _delegate(
            self,
            asset_type=asset_type,
            symbol=symbol,
            name=name,
            market=market,
            snapshot=snapshot,
            rows=rows,
            period=period,
            provider=provider,
        )

    def _match_any(self, df: pd.DataFrame, symbol: str, columns: list[str]) -> pd.DataFrame:
        from app.services.market_instrument_projection import (
            _match_any as _delegate,
        )

        return _delegate(self, df=df, symbol=symbol, columns=columns)

    def _normalize_cn_ohlcv_history(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        from app.services.market_instrument_projection import (
            _normalize_cn_ohlcv_history as _delegate,
        )

        return _delegate(self, df=df)

    def _normalize_generic_ohlcv_history(
        self,
        df: pd.DataFrame,
        start_date: date | str | None,
        end_date: date | str | None,
    ) -> list[dict[str, Any]]:
        from app.services.market_instrument_projection import (
            _normalize_generic_ohlcv_history as _delegate,
        )

        return _delegate(self, df=df, start_date=start_date, end_date=end_date)

    def _normalize_crypto_cme_rows(
        self,
        df: pd.DataFrame,
        value_date: date | str,
    ) -> list[dict[str, Any]]:
        from app.services.market_instrument_projection import (
            _normalize_crypto_cme_rows as _delegate,
        )

        return _delegate(self, df=df, value_date=value_date)

    def _build_indicators(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        from app.services.market_instrument_projection import (
            _build_indicators as _delegate,
        )

        return _delegate(self, rows=rows)
