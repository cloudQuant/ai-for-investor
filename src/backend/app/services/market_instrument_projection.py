"""Normalize instrument histories and project snapshots and indicators."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

import app.services.market_instrument as _market_instrument
from app.services.market_instrument import MarketAssetType


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
    normalized_rows: list[dict[str, Any]] = []
    previous_close: float | None = None
    for row in rows:
        close_value = (
            _market_instrument._safe_float(_market_instrument._first_value(row, close_key))
            if close_key
            else None
        )
        change_pct = (
            _market_instrument._safe_float(_market_instrument._first_value(row, change_pct_key))
            if change_pct_key
            else None
        )
        if change_pct is None and previous_close and close_value is not None:
            change_pct = ((close_value / previous_close) - 1) * 100
        normalized_rows.append(
            {
                "date": _market_instrument._iso_date(
                    _market_instrument._first_value(row, date_key)
                ),
                "open": _market_instrument._safe_float(
                    _market_instrument._first_value(row, open_key)
                )
                if open_key
                else close_value,
                "high": _market_instrument._safe_float(
                    _market_instrument._first_value(row, high_key)
                )
                if high_key
                else close_value,
                "low": _market_instrument._safe_float(_market_instrument._first_value(row, low_key))
                if low_key
                else close_value,
                "close": close_value,
                "volume": _market_instrument._safe_int(
                    _market_instrument._first_value(row, volume_key)
                )
                if volume_key
                else None,
                "turnover": _market_instrument._safe_float(
                    _market_instrument._first_value(row, turnover_key)
                )
                if turnover_key
                else None,
                "change": _market_instrument._safe_float(
                    _market_instrument._first_value(row, change_key)
                )
                if change_key
                else None,
                "change_pct": change_pct,
                "turnover_rate": _market_instrument._safe_float(
                    _market_instrument._first_value(row, turnover_rate_key)
                )
                if turnover_rate_key
                else None,
                "open_interest": _market_instrument._safe_int(
                    _market_instrument._first_value(row, open_interest_key)
                )
                if open_interest_key
                else None,
                "settle": _market_instrument._safe_float(
                    _market_instrument._first_value(row, settle_key)
                )
                if settle_key
                else None,
            }
        )
        if close_value is not None:
            previous_close = close_value
    return normalized_rows


def _normalize_fx_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    previous_close: float | None = None
    for row in rows:
        close_value = _market_instrument._safe_float(_market_instrument._first_value(row, "close"))
        change_pct = None
        if previous_close and close_value is not None:
            change_pct = ((close_value / previous_close) - 1) * 100
        normalized_rows.append(
            {
                "date": _market_instrument._iso_date(_market_instrument._first_value(row, "date")),
                "open": previous_close or close_value,
                "high": close_value,
                "low": close_value,
                "close": close_value,
                "change_pct": change_pct,
            }
        )
        if close_value is not None:
            previous_close = close_value
    return normalized_rows


def _fx_history_column(symbol: str) -> str:
    upper_symbol = symbol.upper()
    column_by_currency = {
        "USD": "美元",
        "EUR": "欧元",
        "JPY": "日元",
        "HKD": "港元",
        "GBP": "英镑",
        "AUD": "澳元",
        "NZD": "新西兰元",
        "SGD": "新加坡元",
        "CHF": "瑞士法郎",
        "CAD": "加元",
    }
    for currency, column in column_by_currency.items():
        if upper_symbol.startswith(currency) or upper_symbol.endswith(currency):
            return column
    return "美元"


def _snapshot_from_cn_quote(
    service: _market_instrument.MarketInstrumentService, row: dict[str, Any], *, symbol: str
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "name": _market_instrument._safe_str(_market_instrument._first_present(row, "名称", "name"))
        or symbol,
        "price": _market_instrument._safe_float(
            _market_instrument._first_present(row, "最新价", "收盘", "price")
        ),
        "change": _market_instrument._safe_float(
            _market_instrument._first_present(row, "涨跌额", "change")
        ),
        "change_pct": _market_instrument._safe_float(
            _market_instrument._first_present(row, "涨跌幅", "change_pct")
        ),
        "open": _market_instrument._safe_float(
            _market_instrument._first_present(row, "今开", "开盘价", "开盘", "open")
        ),
        "high": _market_instrument._safe_float(
            _market_instrument._first_present(row, "最高价", "最高", "high")
        ),
        "low": _market_instrument._safe_float(
            _market_instrument._first_present(row, "最低价", "最低", "low")
        ),
        "previous_close": _market_instrument._safe_float(
            _market_instrument._first_present(row, "昨收", "previous_close")
        ),
        "volume": _market_instrument._safe_int(
            _market_instrument._first_present(row, "成交量", "volume")
        ),
        "turnover": _market_instrument._safe_float(
            _market_instrument._first_present(row, "成交额", "turnover")
        ),
        "market_cap": _market_instrument._safe_float(
            _market_instrument._first_present(row, "总市值")
        ),
        "float_market_cap": _market_instrument._safe_float(
            _market_instrument._first_present(row, "流通市值")
        ),
        "pe": _market_instrument._safe_float(
            _market_instrument._first_present(row, "市盈率-动态", "市盈率")
        ),
        "pb": _market_instrument._safe_float(_market_instrument._first_present(row, "市净率")),
        "update_time": _market_instrument._safe_str(
            _market_instrument._first_present(row, "更新时间", "数据日期")
        )
        or datetime.now().isoformat(),
    }


def _snapshot_from_latest_history(
    service: _market_instrument.MarketInstrumentService,
    symbol: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not rows:
        return {"symbol": symbol, "name": symbol}
    latest = rows[-1]
    return {
        "symbol": symbol,
        "name": symbol,
        "price": latest.get("close"),
        "change_pct": latest.get("change_pct"),
        "open": latest.get("open"),
        "high": latest.get("high"),
        "low": latest.get("low"),
        "volume": latest.get("volume"),
        "turnover": latest.get("turnover"),
        "open_interest": latest.get("open_interest"),
        "settle": latest.get("settle"),
        "update_time": latest.get("date"),
    }


def _payload(
    service: _market_instrument.MarketInstrumentService,
    *,
    asset_type: MarketAssetType,
    symbol: str,
    name: str,
    market: str,
    snapshot: dict[str, Any],
    rows: list[dict[str, Any]],
    period: str,
    provider: str = _market_instrument._ONLINE_PROVIDER,
) -> dict[str, Any]:
    return {
        "asset_type": asset_type,
        "symbol": symbol,
        "name": name,
        "market": market,
        "provider": provider,
        "snapshot": snapshot,
        "history": {
            "period": period,
            "rows": rows,
            "total": len(rows),
        },
    }


def _match_any(
    service: _market_instrument.MarketInstrumentService,
    df: pd.DataFrame,
    symbol: str,
    columns: list[str],
) -> pd.DataFrame:
    if df.empty:
        return df
    normalized = symbol.upper()
    mask = pd.Series(False, index=df.index)
    for column in columns:
        if column in df.columns:
            mask = mask | (df[column].astype(str).str.upper() == normalized)
    return df[mask]


def _normalize_cn_ohlcv_history(
    service: _market_instrument.MarketInstrumentService, df: pd.DataFrame
) -> list[dict[str, Any]]:
    return service._normalize_generic_ohlcv_history(
        df.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume",
                "成交额": "turnover",
                "振幅": "amplitude",
                "涨跌幅": "change_pct",
                "涨跌额": "change",
                "换手率": "turnover_rate",
            }
        ),
        start_date=None,
        end_date=None,
    )


def _normalize_generic_ohlcv_history(
    service: _market_instrument.MarketInstrumentService,
    df: pd.DataFrame,
    start_date: date | str | None,
    end_date: date | str | None,
) -> list[dict[str, Any]]:
    if df.empty:
        return []
    normalized = df.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "turnover",
            "涨跌幅": "change_pct",
            "涨跌额": "change",
            "持仓": "open_interest",
            "hold": "open_interest",
            "settle": "settle",
        }
    ).copy()
    if "date" not in normalized.columns:
        return []
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    if start_date is not None:
        start = pd.to_datetime(
            _market_instrument._date_text(start_date, date.today() - timedelta(days=90))
        )
        normalized = normalized[normalized["date"] >= start]
    if end_date is not None:
        end = pd.to_datetime(_market_instrument._date_text(end_date, date.today()))
        normalized = normalized[normalized["date"] <= end]
    rows: list[dict[str, Any]] = []
    for _, row in normalized.iterrows():
        rows.append(
            {
                "date": _market_instrument._iso_date(row.get("date")),
                "open": _market_instrument._safe_float(row.get("open")),
                "high": _market_instrument._safe_float(row.get("high")),
                "low": _market_instrument._safe_float(row.get("low")),
                "close": _market_instrument._safe_float(row.get("close")),
                "volume": _market_instrument._safe_int(row.get("volume")),
                "turnover": _market_instrument._safe_float(row.get("turnover")),
                "change": _market_instrument._safe_float(row.get("change")),
                "change_pct": _market_instrument._safe_float(row.get("change_pct")),
                "turnover_rate": _market_instrument._safe_float(row.get("turnover_rate")),
                "open_interest": _market_instrument._safe_int(row.get("open_interest")),
                "settle": _market_instrument._safe_float(row.get("settle")),
            }
        )
    return rows


def _normalize_crypto_cme_rows(
    service: _market_instrument.MarketInstrumentService,
    df: pd.DataFrame,
    value_date: date | str,
) -> list[dict[str, Any]]:
    if df.empty:
        return []
    rows: list[dict[str, Any]] = []
    day = _market_instrument._iso_date(value_date)
    for _, row in df.iterrows():
        rows.append(
            {
                "date": day,
                "name": _market_instrument._safe_str(row.get("类型"))
                or _market_instrument._safe_str(row.get("商品")),
                "volume": _market_instrument._safe_int(row.get("成交量")),
                "open_interest": _market_instrument._safe_int(row.get("未平仓合约")),
                "change": _market_instrument._safe_float(row.get("持仓变化")),
            }
        )
    return rows


def _build_indicators(
    service: _market_instrument.MarketInstrumentService, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    closes: list[float] = []
    volumes: list[float] = []
    for row in rows:
        close = _market_instrument._safe_float(row.get("close"))
        if close is not None:
            closes.append(close)
        volume = _market_instrument._safe_float(row.get("volume"))
        if volume is not None:
            volumes.append(volume)
    if not closes:
        return {
            "latest_close": None,
            "return_pct": None,
            "highest_close": None,
            "lowest_close": None,
            "avg_volume": sum(volumes) / len(volumes) if volumes else None,
            "observation_count": len(rows),
        }

    first_close = closes[0]
    latest_close = closes[-1]
    return_pct = ((latest_close / first_close) - 1) * 100 if first_close else None
    avg_volume = sum(volumes) / len(volumes) if volumes else None
    return {
        "latest_close": latest_close,
        "return_pct": return_pct,
        "highest_close": max(closes),
        "lowest_close": min(closes),
        "avg_volume": avg_volume,
        "observation_count": len(closes),
    }
