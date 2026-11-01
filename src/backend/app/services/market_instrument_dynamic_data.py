"""Freshness gating, history gap handling, and local history cache access."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import app.services.market_instrument as _market_instrument
from app.services.market_instrument import MarketAssetType


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
    requested_start = _market_instrument._coerce_date(start_date)
    requested_end = _market_instrument._coerce_date(end_date)
    dates = [
        parsed
        for row in rows
        if (parsed := _market_instrument._coerce_date(row.get("date"))) is not None
    ]
    if not dates or requested_start is None or requested_end is None:
        return True

    earliest = min(dates)
    latest = max(dates)
    if earliest > requested_end or latest < requested_start or latest > requested_end:
        return True

    tolerance = timedelta(days=_market_instrument._HISTORY_FRESHNESS_DAYS[asset_type])
    return latest < requested_end - tolerance


async def _fill_history_gap(
    service: _market_instrument.MarketInstrumentService,
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
    cached_rows = await service._lookup_history_cache(
        asset_type=asset_type,
        symbol=warehouse_payload.get("symbol") or symbol,
        start_date=start_date,
        end_date=end_date,
        period=period,
    )
    if cached_rows and not service._history_requires_refresh(
        asset_type=asset_type,
        rows=cached_rows,
        start_date=start_date,
        end_date=end_date,
    ):
        warnings.append("akshare_data 缺少该资产本地历史数据，已使用补齐缓存")
        return service._merge_history_gap(
            warehouse_payload=warehouse_payload,
            rows=cached_rows,
            period=period,
            provider_suffix="cache",
        )
    if cached_rows:
        warnings.append("MARKET_INSTRUMENT_HISTORY_CACHE 已过期或未覆盖所选区间，跳过缓存")

    online_warnings: list[str] = []
    online_rows = await asyncio.to_thread(
        service._lookup_history_online,
        asset_type=asset_type,
        symbol=warehouse_payload.get("symbol") or symbol,
        start_date=start_date,
        end_date=end_date,
        period=period,
        market=market,
        warnings=online_warnings,
    )
    if not online_rows:
        if not online_warnings:
            online_warnings.append("该资产暂无本地历史数据，在线历史接口也未返回可用记录")
        warnings.extend(online_warnings)
        return warehouse_payload

    if service._history_requires_refresh(
        asset_type=asset_type,
        rows=online_rows,
        start_date=start_date,
        end_date=end_date,
    ):
        warnings.extend(online_warnings)
        warnings.append("在线历史数据未覆盖所选区间，未替换现有仓库记录")
        return warehouse_payload

    cache_error = await service._store_history_cache(
        asset_type=asset_type,
        symbol=warehouse_payload.get("symbol") or symbol,
        name=warehouse_payload.get("name") or symbol,
        market=warehouse_payload.get("market") or market or service._default_market(asset_type),
        period=period,
        rows=online_rows,
    )
    warnings.append("akshare_data 缺少该资产本地历史数据，已使用 AkShare 在线历史行情补齐")
    if cache_error:
        warnings.append(f"在线历史已返回，但写入补齐缓存失败: {cache_error}")
    else:
        warnings.append("在线历史已写入 MARKET_INSTRUMENT_HISTORY_CACHE 补齐缓存")

    return service._merge_history_gap(
        warehouse_payload=warehouse_payload,
        rows=online_rows,
        period=period,
        provider_suffix=_market_instrument._ONLINE_PROVIDER,
    )


async def _fill_history_from_local_cache(
    service: _market_instrument.MarketInstrumentService,
    *,
    asset_type: MarketAssetType,
    warehouse_payload: dict[str, Any],
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    warnings: list[str],
) -> dict[str, Any]:
    """Serve missing history from the local gap-fill cache without provider I/O.

    ``_fill_history_gap`` treats a stale cache as unusable because it can follow
    up online; the legacy lookup endpoint may not reach the network, so a stale
    cache is returned as explicitly partial coverage instead of being dropped.
    """
    cached_rows = await service._lookup_history_cache(
        asset_type=asset_type,
        symbol=warehouse_payload.get("symbol") or symbol,
        start_date=start_date,
        end_date=end_date,
        period=period,
    )
    if not cached_rows:
        return warehouse_payload

    last_bar = str(cached_rows[-1].get("date") or "")
    requested_end = _market_instrument._coerce_date(end_date)
    if requested_end is None or last_bar >= requested_end.isoformat():
        coverage = f"最后一条为 {last_bar}"
    else:
        coverage = f"本地仅覆盖到 {last_bar}，其后区间无数据"
    warnings.append(f"akshare_data 缺少该资产的历史行情，已使用本地补齐缓存（{coverage}）。")
    return service._merge_history_gap(
        warehouse_payload=warehouse_payload,
        rows=cached_rows,
        period=period,
        provider_suffix="cache",
    )


def _merge_history_gap(
    service: _market_instrument.MarketInstrumentService,
    *,
    warehouse_payload: dict[str, Any],
    rows: list[dict[str, Any]],
    period: str,
    provider_suffix: str,
) -> dict[str, Any]:
    merged = {**warehouse_payload}
    merged["history"] = {
        "period": period,
        "rows": rows,
        "total": len(rows),
    }
    merged["provider"] = (
        f"{warehouse_payload.get('provider') or _market_instrument._WAREHOUSE_PROVIDER}+{provider_suffix}"
    )
    snapshot_values = {
        key: value
        for key, value in (merged.get("snapshot") or {}).items()
        if key != "data_source_table"
    }
    if not any(value is not None for value in snapshot_values.values()):
        merged["snapshot"] = service._snapshot_from_latest_history(merged.get("symbol") or "", rows)
    return merged


def _lookup_history_online(
    service: _market_instrument.MarketInstrumentService,
    *,
    asset_type: MarketAssetType,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> list[dict[str, Any]]:
    if asset_type == "stock":
        return service._lookup_stock_history_online(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            warnings=warnings,
        )

    lookup_map = {
        "futures": service._lookup_futures,
        "bond": service._lookup_bond,
        "fund": service._lookup_fund,
        "option": service._lookup_option,
        "fx": service._lookup_fx,
        "crypto": service._lookup_crypto,
    }
    lookup = lookup_map.get(asset_type)
    if lookup is None:
        return []
    payload = lookup(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        period=period,
        market=market,
        warnings=warnings,
    )
    return (payload.get("history") or {}).get("rows") or []


def _lookup_stock_history_online(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    warnings: list[str],
) -> list[dict[str, Any]]:
    import akshare as ak

    code = _market_instrument._normalize_plain_code(symbol)
    try:
        history_df = ak.stock_zh_a_hist(
            symbol=code,
            period=period,
            start_date=_market_instrument._date_text(start_date, date.today() - timedelta(days=90)),
            end_date=_market_instrument._date_text(end_date, date.today()),
            adjust="qfq",
            timeout=10,
        )
        return service._normalize_cn_ohlcv_history(history_df)
    except Exception as exc:
        warnings.append(f"A 股历史行情不可用: {exc}")
        return []


async def _lookup_history_cache(
    service: _market_instrument.MarketInstrumentService,
    *,
    asset_type: MarketAssetType,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
) -> list[dict[str, Any]]:
    try:
        rows = await service._fetch_rows(
            """
            SELECT
                `date`,
                name,
                open,
                high,
                low,
                close,
                price,
                volume,
                turnover,
                change_value,
                change_pct,
                turnover_rate,
                open_interest,
                settle,
                strike,
                days_to_expiry
            FROM MARKET_INSTRUMENT_HISTORY_CACHE
            WHERE asset_type = :asset_type
              AND UPPER(symbol) = :symbol
              AND period = :period
              AND STR_TO_DATE(`date`, '%Y-%m-%d') BETWEEN :start AND :end
            ORDER BY STR_TO_DATE(`date`, '%Y-%m-%d') ASC
            LIMIT 260
            """,
            {
                "asset_type": asset_type,
                "symbol": symbol.upper(),
                "period": period,
                "start": _market_instrument._sql_date_text(start_date, date.today()),
                "end": _market_instrument._sql_date_text(end_date, date.today()),
            },
        )
    except Exception:
        return []

    return [
        {
            "date": _market_instrument._iso_date(_market_instrument._first_value(row, "date")),
            "name": _market_instrument._safe_str(_market_instrument._first_value(row, "name")),
            "open": _market_instrument._safe_float(_market_instrument._first_value(row, "open")),
            "high": _market_instrument._safe_float(_market_instrument._first_value(row, "high")),
            "low": _market_instrument._safe_float(_market_instrument._first_value(row, "low")),
            "close": _market_instrument._safe_float(_market_instrument._first_value(row, "close")),
            "price": _market_instrument._safe_float(_market_instrument._first_value(row, "price")),
            "volume": _market_instrument._safe_int(_market_instrument._first_value(row, "volume")),
            "turnover": _market_instrument._safe_float(
                _market_instrument._first_value(row, "turnover")
            ),
            "change": _market_instrument._safe_float(
                _market_instrument._first_value(row, "change_value")
            ),
            "change_pct": _market_instrument._safe_float(
                _market_instrument._first_value(row, "change_pct")
            ),
            "turnover_rate": _market_instrument._safe_float(
                _market_instrument._first_value(row, "turnover_rate")
            ),
            "open_interest": _market_instrument._safe_int(
                _market_instrument._first_value(row, "open_interest")
            ),
            "settle": _market_instrument._safe_float(
                _market_instrument._first_value(row, "settle")
            ),
            "strike": _market_instrument._safe_float(
                _market_instrument._first_value(row, "strike")
            ),
            "days_to_expiry": _market_instrument._safe_int(
                _market_instrument._first_value(row, "days_to_expiry")
            ),
        }
        for row in rows
    ]


async def _store_history_cache(
    service: _market_instrument.MarketInstrumentService,
    *,
    asset_type: MarketAssetType,
    symbol: str,
    name: str,
    market: str,
    period: str,
    rows: list[dict[str, Any]],
) -> str | None:
    payloads = []
    normalized_symbol = symbol.upper()
    for row in rows:
        row_date = _market_instrument._safe_str(_market_instrument._first_value(row, "date"))
        if not row_date:
            continue
        payloads.append(
            {
                "r_id": f"{asset_type}|{normalized_symbol}|{period}|{row_date}"[:191],
                "asset_type": asset_type,
                "symbol": normalized_symbol,
                "name": _market_instrument._safe_str(_market_instrument._first_value(row, "name"))
                or name,
                "market": market,
                "period": period,
                "date": row_date,
                "open": _market_instrument._safe_float(
                    _market_instrument._first_value(row, "open")
                ),
                "high": _market_instrument._safe_float(
                    _market_instrument._first_value(row, "high")
                ),
                "low": _market_instrument._safe_float(_market_instrument._first_value(row, "low")),
                "close": _market_instrument._safe_float(
                    _market_instrument._first_value(row, "close")
                ),
                "price": _market_instrument._safe_float(
                    _market_instrument._first_value(row, "price")
                ),
                "volume": _market_instrument._safe_int(
                    _market_instrument._first_value(row, "volume")
                ),
                "turnover": _market_instrument._safe_float(
                    _market_instrument._first_value(row, "turnover")
                ),
                "change_value": _market_instrument._safe_float(
                    _market_instrument._first_value(row, "change")
                ),
                "change_pct": _market_instrument._safe_float(
                    _market_instrument._first_value(row, "change_pct")
                ),
                "turnover_rate": _market_instrument._safe_float(
                    _market_instrument._first_value(row, "turnover_rate")
                ),
                "open_interest": _market_instrument._safe_int(
                    _market_instrument._first_value(row, "open_interest")
                ),
                "settle": _market_instrument._safe_float(
                    _market_instrument._first_value(row, "settle")
                ),
                "strike": _market_instrument._safe_float(
                    _market_instrument._first_value(row, "strike")
                ),
                "days_to_expiry": _market_instrument._safe_int(
                    _market_instrument._first_value(row, "days_to_expiry")
                ),
                "provider": _market_instrument._ONLINE_PROVIDER,
            }
        )
    if not payloads:
        return None

    engine = _market_instrument._get_akshare_data_engine()
    if engine is None:
        return "AKSHARE_DATA_DATABASE_URL is not configured"

    try:
        async with engine.begin() as conn:
            await conn.execute(
                _market_instrument.text(
                    """
                    CREATE TABLE IF NOT EXISTS MARKET_INSTRUMENT_HISTORY_CACHE (
                        R_ID VARCHAR(191) PRIMARY KEY,
                        asset_type VARCHAR(32) NOT NULL,
                        symbol VARCHAR(64) NOT NULL,
                        name VARCHAR(128) NULL,
                        market VARCHAR(32) NULL,
                        period VARCHAR(16) NOT NULL,
                        `date` VARCHAR(32) NOT NULL,
                        open DOUBLE NULL,
                        high DOUBLE NULL,
                        low DOUBLE NULL,
                        close DOUBLE NULL,
                        price DOUBLE NULL,
                        volume BIGINT NULL,
                        turnover DOUBLE NULL,
                        change_value DOUBLE NULL,
                        change_pct DOUBLE NULL,
                        turnover_rate DOUBLE NULL,
                        open_interest BIGINT NULL,
                        settle DOUBLE NULL,
                        strike DOUBLE NULL,
                        days_to_expiry INT NULL,
                        provider VARCHAR(64) NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        KEY idx_market_instrument_history_cache_lookup (
                            asset_type,
                            symbol,
                            period,
                            `date`
                        )
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            )
            await conn.execute(
                _market_instrument.text(
                    """
                    INSERT INTO MARKET_INSTRUMENT_HISTORY_CACHE (
                        R_ID,
                        asset_type,
                        symbol,
                        name,
                        market,
                        period,
                        `date`,
                        open,
                        high,
                        low,
                        close,
                        price,
                        volume,
                        turnover,
                        change_value,
                        change_pct,
                        turnover_rate,
                        open_interest,
                        settle,
                        strike,
                        days_to_expiry,
                        provider
                    ) VALUES (
                        :r_id,
                        :asset_type,
                        :symbol,
                        :name,
                        :market,
                        :period,
                        :date,
                        :open,
                        :high,
                        :low,
                        :close,
                        :price,
                        :volume,
                        :turnover,
                        :change_value,
                        :change_pct,
                        :turnover_rate,
                        :open_interest,
                        :settle,
                        :strike,
                        :days_to_expiry,
                        :provider
                    )
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        market = VALUES(market),
                        open = VALUES(open),
                        high = VALUES(high),
                        low = VALUES(low),
                        close = VALUES(close),
                        price = VALUES(price),
                        volume = VALUES(volume),
                        turnover = VALUES(turnover),
                        change_value = VALUES(change_value),
                        change_pct = VALUES(change_pct),
                        turnover_rate = VALUES(turnover_rate),
                        open_interest = VALUES(open_interest),
                        settle = VALUES(settle),
                        strike = VALUES(strike),
                        days_to_expiry = VALUES(days_to_expiry),
                        provider = VALUES(provider)
                    """
                ),
                payloads,
            )
    except Exception as exc:
        return str(exc)
    return None
