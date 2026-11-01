"""Asset-specific instrument catalog queries and fallback normalization."""

from __future__ import annotations

from typing import Any

import app.services.market_instrument as _market_instrument
from app.services.market_instrument import MarketAssetType


async def _list_stock_instruments(
    service: _market_instrument.MarketInstrumentService, *, search: str, limit: int
) -> list[dict[str, Any]]:
    rows = await service._fetch_rows(
        """
        SELECT
            symbol,
            name,
            'CN' AS market,
            'STOCK_ZH_A_SPOT_EM' AS source_table,
            MAX(latest_date) AS latest_date,
            1 AS has_snapshot,
            0 AS has_history,
            0 AS history_rows,
            MAX(sort_value) AS sort_value
        FROM (
            SELECT
                COALESCE(NULLIF(symbol, ''), `代码`) AS symbol,
                COALESCE(NULLIF(name, ''), `名称`, `代码`) AS name,
                data_date AS latest_date,
                `成交额` AS sort_value
            FROM STOCK_ZH_A_SPOT_EM
            WHERE (:search = ''
                OR COALESCE(symbol, '') LIKE :pattern
                OR COALESCE(name, '') LIKE :pattern
                OR `代码` LIKE :pattern
                OR `名称` LIKE :pattern)
        ) AS candidates
        WHERE symbol IS NOT NULL AND symbol <> ''
        GROUP BY symbol, name
        ORDER BY latest_date DESC, sort_value DESC, symbol ASC
        LIMIT :limit
        """,
        service._instrument_query_params(search, limit),
    )
    return service._normalize_instrument_options(rows, "stock", limit)


async def _list_futures_instruments(
    service: _market_instrument.MarketInstrumentService, *, search: str, limit: int
) -> list[dict[str, Any]]:
    params = service._instrument_query_params(search, limit)
    if not search:
        latest = await service._fetch_one(
            "SELECT MAX(TRADE_DATE) AS latest_date FROM FUTURES_DAILY_MARKET"
        )
        latest_date = latest.get("latest_date") if latest else None
        if latest_date:
            rows = await service._fetch_rows(
                """
                SELECT
                    SYMBOL AS symbol,
                    CONCAT(
                        SYMBOL,
                        ' / ',
                        COALESCE(NULLIF(VARIETY, ''), COALESCE(MARKET, 'CN'))
                    ) AS name,
                    COALESCE(MARKET, 'CN') AS market,
                    'FUTURES_DAILY_MARKET' AS source_table,
                    MAX(TRADE_DATE) AS latest_date,
                    0 AS has_snapshot,
                    1 AS has_history,
                    COUNT(*) AS history_rows
                FROM FUTURES_DAILY_MARKET
                WHERE TRADE_DATE = :latest_date
                GROUP BY SYMBOL, VARIETY, MARKET
                ORDER BY history_rows DESC, SYMBOL ASC
                LIMIT :limit
                """,
                {**params, "latest_date": latest_date},
            )
            return service._normalize_instrument_options(rows, "futures", limit)

    exact_rows = await service._fetch_rows(
        """
        SELECT
            SYMBOL AS symbol,
            CONCAT(
                SYMBOL,
                ' / ',
                COALESCE(NULLIF(MAX(VARIETY), ''), COALESCE(MAX(MARKET), 'CN'))
            ) AS name,
            COALESCE(MAX(MARKET), 'CN') AS market,
            'FUTURES_DAILY_MARKET' AS source_table,
            MAX(TRADE_DATE) AS latest_date,
            0 AS has_snapshot,
            1 AS has_history,
            COUNT(*) AS history_rows
        FROM FUTURES_DAILY_MARKET
        WHERE SYMBOL IN (:search, :upper_search)
        GROUP BY SYMBOL
        ORDER BY latest_date DESC, history_rows DESC, SYMBOL ASC
        LIMIT :limit
        """,
        {**params, "upper_search": search.upper()},
    )
    if exact_rows:
        return service._normalize_instrument_options(exact_rows, "futures", limit)

    rows = await service._fetch_rows(
        """
        SELECT
            SYMBOL AS symbol,
            CONCAT(SYMBOL, ' / ', COALESCE(NULLIF(VARIETY, ''), COALESCE(MARKET, 'CN'))) AS name,
            COALESCE(MARKET, 'CN') AS market,
            'FUTURES_DAILY_MARKET' AS source_table,
            MAX(TRADE_DATE) AS latest_date,
            0 AS has_snapshot,
            1 AS has_history,
            COUNT(*) AS history_rows
        FROM FUTURES_DAILY_MARKET
        WHERE (SYMBOL LIKE :prefix_pattern
            OR COALESCE(VARIETY, '') LIKE :pattern
            OR COALESCE(MARKET, '') LIKE :pattern)
        GROUP BY SYMBOL, VARIETY, MARKET
        ORDER BY latest_date DESC, history_rows DESC, SYMBOL ASC
        LIMIT :limit
        """,
        {**params, "prefix_pattern": f"{search}%"},
    )
    return service._normalize_instrument_options(rows, "futures", limit)


async def _list_bond_instruments(
    service: _market_instrument.MarketInstrumentService, *, search: str, limit: int
) -> list[dict[str, Any]]:
    params = service._instrument_query_params(search, limit)
    rows = await service._fetch_rows(
        """
        SELECT
            symbol,
            COALESCE(NULLIF(name, ''), code, symbol) AS name,
            'CN' AS market,
            'BOND_ZH_HS_COV_SPOT' AS source_table,
            MAX(data_date) AS latest_date,
            1 AS has_snapshot,
            0 AS has_history,
            0 AS history_rows
        FROM BOND_ZH_HS_COV_SPOT
        WHERE (:search = ''
            OR LOWER(symbol) LIKE LOWER(:pattern)
            OR code LIKE :pattern
            OR COALESCE(name, '') LIKE :pattern)
        GROUP BY symbol, name, code
        ORDER BY latest_date DESC, symbol ASC
        LIMIT :limit
        """,
        params,
    )
    rows.extend(
        await service._fetch_rows(
            """
            SELECT
                symbol,
                COALESCE(NULLIF(MAX(name), ''), symbol) AS name,
                'CN' AS market,
                'BOND_ZH_HS_COV_MIN' AS source_table,
                MAX(data_date) AS latest_date,
                0 AS has_snapshot,
                1 AS has_history,
                COUNT(*) AS history_rows
            FROM BOND_ZH_HS_COV_MIN
            WHERE (:search = ''
                OR LOWER(symbol) LIKE LOWER(:pattern)
                OR COALESCE(name, '') LIKE :pattern)
            GROUP BY symbol
            ORDER BY latest_date DESC, history_rows DESC, symbol ASC
            LIMIT :limit
            """,
            params,
        )
    )
    return service._normalize_instrument_options(rows, "bond", limit)


async def _list_fund_instruments(
    service: _market_instrument.MarketInstrumentService, *, search: str, limit: int
) -> list[dict[str, Any]]:
    params = service._instrument_query_params(search, limit)
    rows = await service._fetch_rows(
        """
        SELECT
            ETF_CODE AS symbol,
            COALESCE(NULLIF(ETF_NAME, ''), ETF_CODE) AS name,
            'CN' AS market,
            'ETF_REALTIME_QUOTE_EM' AS source_table,
            MAX(QUOTE_DATE) AS latest_date,
            1 AS has_snapshot,
            0 AS has_history,
            0 AS history_rows
        FROM ETF_REALTIME_QUOTE_EM
        WHERE (:search = ''
            OR ETF_CODE LIKE :pattern
            OR COALESCE(ETF_NAME, '') LIKE :pattern)
        GROUP BY ETF_CODE, ETF_NAME
        ORDER BY latest_date DESC, symbol ASC
        LIMIT :limit
        """,
        params,
    )
    rows.extend(
        await service._fetch_rows(
            """
            SELECT
                FUND_CODE AS symbol,
                FUND_CODE AS name,
                'CN' AS market,
                'ETF_FUND_HIST_EM' AS source_table,
                MAX(VALUE_DATE) AS latest_date,
                0 AS has_snapshot,
                1 AS has_history,
                COUNT(*) AS history_rows
            FROM ETF_FUND_HIST_EM
            WHERE (:search = '' OR FUND_CODE LIKE :pattern)
            GROUP BY FUND_CODE
            ORDER BY latest_date DESC, history_rows DESC, FUND_CODE ASC
            LIMIT :limit
            """,
            params,
        )
    )
    return service._normalize_instrument_options(rows, "fund", limit)


async def _list_option_instruments(
    service: _market_instrument.MarketInstrumentService, *, search: str, limit: int
) -> list[dict[str, Any]]:
    rows = await service._fetch_rows(
        """
        SELECT
            symbol,
            name,
            'CN' AS market,
            'OPTION_CURRENT_EM' AS source_table,
            MAX(latest_date) AS latest_date,
            1 AS has_snapshot,
            1 AS has_history,
            COUNT(*) AS history_rows
        FROM (
            SELECT
                COALESCE(NULLIF(symbol, ''), `代码`) AS symbol,
                COALESCE(NULLIF(name, ''), `名称`, `代码`) AS name,
                data_date AS latest_date
            FROM OPTION_CURRENT_EM
            WHERE (:search = ''
                OR COALESCE(symbol, '') LIKE :pattern
                OR COALESCE(name, '') LIKE :pattern
                OR `代码` LIKE :pattern
                OR `名称` LIKE :pattern)
        ) AS candidates
        WHERE symbol IS NOT NULL AND symbol <> ''
        GROUP BY symbol, name
        ORDER BY latest_date DESC, history_rows DESC, symbol ASC
        LIMIT :limit
        """,
        service._instrument_query_params(search, limit),
    )
    return service._normalize_instrument_options(rows, "option", limit)


async def _list_fx_instruments(
    service: _market_instrument.MarketInstrumentService, *, search: str, limit: int
) -> list[dict[str, Any]]:
    # FOREX_SPOT_EM holds one snapshot row per pair per import date, and the merged option
    # sums history_rows across sources, so counting its rows as history both inflated the
    # depth of every pair and promised history to the pairs no series can be derived for.
    rows = await service._fetch_rows(
        """
        SELECT
            symbol,
            name,
            'FX' AS market,
            'FOREX_SPOT_EM' AS source_table,
            MAX(latest_date) AS latest_date,
            1 AS has_snapshot,
            0 AS has_history,
            0 AS history_rows
        FROM (
            SELECT
                COALESCE(NULLIF(symbol, ''), `代码`) AS symbol,
                COALESCE(NULLIF(name, ''), `名称`, `代码`) AS name,
                data_date AS latest_date
            FROM FOREX_SPOT_EM
            WHERE (:search = ''
                OR COALESCE(symbol, '') LIKE :pattern
                OR COALESCE(name, '') LIKE :pattern
                OR `代码` LIKE :pattern
                OR `名称` LIKE :pattern)
        ) AS candidates
        WHERE symbol IS NOT NULL AND symbol <> ''
        GROUP BY symbol, name
        ORDER BY latest_date DESC, symbol ASC
        LIMIT :limit
        """,
        service._instrument_query_params(search, limit),
    )
    return service._normalize_instrument_options(rows, "fx", limit)


async def _list_crypto_instruments(
    service: _market_instrument.MarketInstrumentService, *, search: str, limit: int
) -> list[dict[str, Any]]:
    rows = await service._fetch_rows(
        """
        SELECT
            SYMBOL AS symbol,
            CONCAT(SYMBOL, ' / BINANCE') AS name,
            'BINANCE' AS market,
            'CRYPTO_DAILY_MARKET' AS source_table,
            MAX(TRADE_DATE) AS latest_date,
            1 AS has_snapshot,
            COUNT(*) > 0 AS has_history,
            COUNT(*) AS history_rows
        FROM CRYPTO_DAILY_MARKET
        WHERE MARKET = 'BINANCE'
          AND (:search = '' OR SYMBOL LIKE :pattern)
        GROUP BY SYMBOL
        ORDER BY latest_date DESC, symbol ASC
        LIMIT :limit
        """,
        service._instrument_query_params(search, limit),
    )
    return service._normalize_instrument_options(rows, "crypto", limit)


def _instrument_query_params(search: str, limit: int) -> dict[str, Any]:
    return {
        "search": search,
        "pattern": f"%{search}%",
        "limit": limit,
    }


def _normalize_instrument_options(
    service: _market_instrument.MarketInstrumentService,
    rows: list[dict[str, Any]],
    asset_type: MarketAssetType,
    limit: int,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _market_instrument._safe_str(_market_instrument._first_value(row, "symbol"))
        if not symbol:
            continue
        key = symbol.upper()
        if key not in merged:
            merged[key] = {
                "asset_type": asset_type,
                "symbol": symbol,
                "name": _market_instrument._safe_str(_market_instrument._first_value(row, "name"))
                or symbol,
                "market": _market_instrument._safe_str(
                    _market_instrument._first_value(row, "market")
                )
                or service._default_market(asset_type),
                "source_table": _market_instrument._safe_str(
                    _market_instrument._first_value(row, "source_table")
                ),
                "latest_date": _market_instrument._safe_str(
                    _market_instrument._first_value(row, "latest_date")
                ),
                "has_snapshot": bool(
                    _market_instrument._safe_int(
                        _market_instrument._first_value(row, "has_snapshot")
                    )
                ),
                "has_history": bool(
                    _market_instrument._safe_int(
                        _market_instrument._first_value(row, "has_history")
                    )
                ),
                "history_rows": _market_instrument._safe_int(
                    _market_instrument._first_value(row, "history_rows")
                )
                or 0,
            }
            continue

        option = merged[key]
        option["has_snapshot"] = bool(
            option["has_snapshot"]
            or _market_instrument._safe_int(_market_instrument._first_value(row, "has_snapshot"))
        )
        option["has_history"] = bool(
            option["has_history"]
            or _market_instrument._safe_int(_market_instrument._first_value(row, "has_history"))
        )
        option["history_rows"] = int(option["history_rows"]) + (
            _market_instrument._safe_int(_market_instrument._first_value(row, "history_rows")) or 0
        )
        latest_date = _market_instrument._safe_str(
            _market_instrument._first_value(row, "latest_date")
        )
        if latest_date and (not option["latest_date"] or latest_date > option["latest_date"]):
            option["latest_date"] = latest_date
        source_table = _market_instrument._safe_str(
            _market_instrument._first_value(row, "source_table")
        )
        if source_table and source_table not in str(option["source_table"] or ""):
            option["source_table"] = (
                f"{option['source_table']}/{source_table}"
                if option["source_table"]
                else source_table
            )
        name = _market_instrument._safe_str(_market_instrument._first_value(row, "name"))
        if name and option["name"] == option["symbol"]:
            option["name"] = name

    return sorted(
        merged.values(),
        key=lambda item: (
            item.get("latest_date") or "",
            bool(item.get("has_snapshot")),
            int(item.get("history_rows") or 0),
        ),
        reverse=True,
    )[:limit]


def _fallback_instruments(
    *,
    asset_type: MarketAssetType,
    search: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Return safe starter symbols when the optional warehouse is unavailable."""
    normalized_search = search.casefold()
    options: list[dict[str, Any]] = []
    for symbol, name, market in _market_instrument._BUILTIN_INSTRUMENTS[asset_type]:
        searchable = " ".join((symbol, name, market)).casefold()
        if normalized_search and normalized_search not in searchable:
            continue
        options.append(
            {
                "asset_type": asset_type,
                "symbol": symbol,
                "name": name,
                "market": market,
                "source_table": "builtin_fallback",
                "latest_date": None,
                "has_snapshot": False,
                "has_history": False,
                "history_rows": 0,
            }
        )
    return options[:limit]


async def _list_cached_instruments(
    service: _market_instrument.MarketInstrumentService,
    *,
    asset_type: MarketAssetType,
    search: str,
    limit: int,
) -> list[dict[str, Any]]:
    try:
        rows = await service._fetch_rows(
            """
            SELECT
                symbol,
                COALESCE(NULLIF(MAX(name), ''), symbol) AS name,
                COALESCE(NULLIF(MAX(market), ''), :market) AS market,
                'MARKET_INSTRUMENT_HISTORY_CACHE' AS source_table,
                MAX(`date`) AS latest_date,
                0 AS has_snapshot,
                1 AS has_history,
                COUNT(*) AS history_rows
            FROM MARKET_INSTRUMENT_HISTORY_CACHE
            WHERE asset_type = :asset_type
              AND (:search = ''
                OR symbol LIKE :pattern
                OR COALESCE(name, '') LIKE :pattern
                OR COALESCE(market, '') LIKE :pattern)
            GROUP BY symbol
            ORDER BY latest_date DESC, history_rows DESC, symbol ASC
            LIMIT :limit
            """,
            {
                **service._instrument_query_params(search, limit),
                "asset_type": asset_type,
                "market": service._default_market(asset_type),
            },
        )
    except Exception:
        return []
    return rows
