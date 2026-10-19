"""Asset-specific warehouse and provider lookup adapters."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import app.services.market_instrument as _market_instrument


async def _lookup_stock_warehouse(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    code = _market_instrument._normalize_plain_code(symbol)
    spot = await service._fetch_one(
        """
        SELECT *
        FROM STOCK_ZH_A_SPOT_EM
        WHERE symbol = :code OR `代码` = :code
        ORDER BY data_date DESC
        LIMIT 1
        """,
        {"code": code},
    )

    rows = await service._fetch_rows(
        """
        SELECT *
        FROM STOCK_ZH_A_HIST
        WHERE (symbol = :code OR `股票代码` = :code)
          AND STR_TO_DATE(`日期`, '%Y-%m-%d') BETWEEN :start AND :end
        ORDER BY STR_TO_DATE(`日期`, '%Y-%m-%d') ASC
        LIMIT 260
        """,
        {
            "code": code,
            "start": _market_instrument._sql_date_text(start_date, date.today()),
            "end": _market_instrument._sql_date_text(end_date, date.today()),
        },
    )
    history_rows = service._normalize_warehouse_history(
        rows,
        date_key="日期",
        open_key="开盘",
        high_key="最高",
        low_key="最低",
        close_key="收盘",
        volume_key="成交量",
        turnover_key="成交额",
        change_key="涨跌额",
        change_pct_key="涨跌幅",
        turnover_rate_key="换手率",
    )
    history_table = "STOCK_ZH_A_HIST" if history_rows else None

    snapshot = service._snapshot_from_cn_quote(spot or {}, symbol=code) if spot else {}
    snapshot = snapshot or service._snapshot_from_latest_history(code, history_rows)
    snapshot["data_source_table"] = (
        f"STOCK_ZH_A_SPOT_EM/{history_table}" if history_table else "STOCK_ZH_A_SPOT_EM"
    )
    return service._payload(
        asset_type="stock",
        symbol=code,
        name=snapshot.get("name") or code,
        market=market or "CN",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
        provider=_market_instrument._WAREHOUSE_PROVIDER,
    )


async def _lookup_futures_warehouse(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    requested = symbol.upper()
    rows = await service._fetch_rows(
        """
        SELECT *
        FROM FUTURES_DAILY_MARKET
        WHERE SYMBOL = :symbol
          AND TRADE_DATE BETWEEN :start AND :end
        ORDER BY TRADE_DATE ASC
        LIMIT 260
        """,
        {"symbol": requested, "start": start_date, "end": end_date},
    )
    history_rows = service._normalize_warehouse_history(
        rows,
        date_key="TRADE_DATE",
        open_key="OPEN_PRICE",
        high_key="HIGH_PRICE",
        low_key="LOW_PRICE",
        close_key="CLOSE_PRICE",
        volume_key="VOLUME",
        turnover_key="TURNOVER",
        settle_key="SETTLE_PRICE",
        open_interest_key="OPEN_INTEREST",
    )
    snapshot = service._snapshot_from_latest_history(requested, history_rows)
    latest_raw = rows[-1] if rows else {}
    snapshot.update(
        {
            "name": requested,
            "settle": _market_instrument._safe_float(
                _market_instrument._first_value(latest_raw, "SETTLE_PRICE")
            ),
            "previous_settle": _market_instrument._safe_float(
                _market_instrument._first_value(latest_raw, "PREV_SETTLE")
            ),
            "open_interest": _market_instrument._safe_int(
                _market_instrument._first_value(latest_raw, "OPEN_INTEREST")
            ),
            "turnover": _market_instrument._safe_float(
                _market_instrument._first_value(latest_raw, "TURNOVER")
            ),
            "data_source_table": "FUTURES_DAILY_MARKET",
        }
    )
    return service._payload(
        asset_type="futures",
        symbol=requested,
        name=requested,
        market=market
        or _market_instrument._safe_str(_market_instrument._first_value(latest_raw, "MARKET"))
        or "CN",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
        provider=_market_instrument._WAREHOUSE_PROVIDER,
    )


async def _lookup_bond_warehouse(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    exchange_symbol = _market_instrument._normalize_exchange_symbol(symbol, default_prefix="sh")
    plain_code = exchange_symbol[2:]
    spot = await service._fetch_one(
        """
        SELECT *
        FROM BOND_ZH_HS_COV_SPOT
        WHERE LOWER(symbol) = :symbol OR code = :code
        ORDER BY data_date DESC
        LIMIT 1
        """,
        {"symbol": exchange_symbol.lower(), "code": plain_code},
    )
    rows = await service._fetch_rows(
        """
        SELECT *
        FROM BOND_ZH_HS_COV_MIN
        WHERE LOWER(symbol) = :symbol
          AND data_date BETWEEN :start AND :end
        ORDER BY `时间` ASC
        LIMIT 260
        """,
        {
            "symbol": exchange_symbol.lower(),
            "start": _market_instrument._sql_date_text(start_date, date.today()),
            "end": _market_instrument._sql_date_text(end_date, date.today()),
        },
    )
    history_rows = service._normalize_warehouse_history(
        rows,
        date_key="时间",
        open_key="开盘",
        high_key="最高",
        low_key="最低",
        close_key="收盘",
        volume_key="成交量",
        turnover_key="成交额",
    )
    if spot:
        snapshot = {
            "symbol": exchange_symbol,
            "name": _market_instrument._safe_str(
                _market_instrument._first_value(spot, "name", "code")
            )
            or exchange_symbol,
            "price": _market_instrument._safe_float(_market_instrument._first_value(spot, "trade")),
            "change": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "pricechange")
            ),
            "change_pct": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "changepercent")
            ),
            "open": _market_instrument._safe_float(_market_instrument._first_value(spot, "open")),
            "high": _market_instrument._safe_float(_market_instrument._first_value(spot, "high")),
            "low": _market_instrument._safe_float(_market_instrument._first_value(spot, "low")),
            "previous_close": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "settlement")
            ),
            "bid": _market_instrument._safe_float(_market_instrument._first_value(spot, "buy")),
            "ask": _market_instrument._safe_float(_market_instrument._first_value(spot, "sell")),
            "volume": _market_instrument._safe_int(_market_instrument._first_value(spot, "volume")),
            "turnover": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "amount")
            ),
            "update_time": _market_instrument._safe_str(
                _market_instrument._first_value(spot, "ticktime", "data_date")
            ),
            "data_source_table": "BOND_ZH_HS_COV_SPOT",
        }
    else:
        snapshot = service._snapshot_from_latest_history(exchange_symbol, history_rows)
        snapshot["data_source_table"] = "BOND_ZH_HS_COV_MIN"
    return service._payload(
        asset_type="bond",
        symbol=exchange_symbol,
        name=_market_instrument._name_or_fallback(snapshot.get("name"), plain_code),
        market=market or "CN",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
        provider=_market_instrument._WAREHOUSE_PROVIDER,
    )


async def _lookup_fund_warehouse(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    code = _market_instrument._normalize_plain_code(symbol)
    spot = await service._fetch_one(
        """
        SELECT *
        FROM ETF_REALTIME_QUOTE_EM
        WHERE ETF_CODE = :code
        ORDER BY QUOTE_DATE DESC
        LIMIT 1
        """,
        {"code": code},
    )
    rows: list[dict[str, Any]] = []
    if code == "510300":
        rows = await service._fetch_rows(
            """
            SELECT *
            FROM FUND_ETF_HIST_SINA
            WHERE STR_TO_DATE(`date`, '%Y-%m-%d') BETWEEN :start AND :end
            ORDER BY STR_TO_DATE(`date`, '%Y-%m-%d') ASC
            LIMIT 260
            """,
            {
                "start": _market_instrument._sql_date_text(start_date, date.today()),
                "end": _market_instrument._sql_date_text(end_date, date.today()),
            },
        )
    else:
        nav_rows = await service._fetch_rows(
            """
            SELECT *
            FROM ETF_FUND_HIST_EM
            WHERE FUND_CODE = :code
              AND VALUE_DATE BETWEEN :start AND :end
            ORDER BY VALUE_DATE ASC
            LIMIT 260
            """,
            {
                "code": code,
                "start": _market_instrument._sql_date_text(start_date, date.today()),
                "end": _market_instrument._sql_date_text(end_date, date.today()),
            },
        )
        rows = [
            {
                "date": row.get("VALUE_DATE"),
                "open": row.get("UNIT_NET_VALUE"),
                "high": row.get("UNIT_NET_VALUE"),
                "low": row.get("UNIT_NET_VALUE"),
                "close": row.get("UNIT_NET_VALUE"),
                "change_pct": row.get("DAILY_GROWTH_RATE"),
            }
            for row in nav_rows
        ]

    history_rows = service._normalize_warehouse_history(
        rows,
        date_key="date",
        open_key="open",
        high_key="high",
        low_key="low",
        close_key="close",
        volume_key="volume",
        turnover_key="amount",
    )
    if spot:
        snapshot = {
            "symbol": code,
            "name": _market_instrument._safe_str(_market_instrument._first_value(spot, "ETF_NAME"))
            or code,
            "price": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "LATEST_PRICE")
            ),
            "change": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "CHANGE_AMOUNT")
            ),
            "change_pct": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "CHANGE_PERCENT")
            ),
            "open": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "OPEN_PRICE")
            ),
            "high": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "HIGH_PRICE")
            ),
            "low": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "LOW_PRICE")
            ),
            "previous_close": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "PREV_CLOSE")
            ),
            "volume": _market_instrument._safe_int(_market_instrument._first_value(spot, "VOLUME")),
            "turnover": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "TURNOVER")
            ),
            "turnover_rate": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "TURNOVER_RATE")
            ),
            "market_cap": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "TOTAL_MARKET_CAP")
            ),
            "float_market_cap": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "CIRC_MARKET_CAP")
            ),
            "bid": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "BID_PRICE")
            ),
            "ask": _market_instrument._safe_float(
                _market_instrument._first_value(spot, "ASK_PRICE")
            ),
            "update_time": _market_instrument._safe_str(
                _market_instrument._first_value(spot, "UPDATE_TIME", "QUOTE_DATE")
            ),
            "data_source_table": "ETF_REALTIME_QUOTE_EM",
        }
    else:
        snapshot = service._snapshot_from_latest_history(code, history_rows)
    return service._payload(
        asset_type="fund",
        symbol=code,
        name=_market_instrument._name_or_fallback(snapshot.get("name"), code),
        market=market or "CN",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
        provider=_market_instrument._WAREHOUSE_PROVIDER,
    )


async def _lookup_option_warehouse(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    normalized = symbol.upper()
    current = await service._fetch_one(
        """
        SELECT *
        FROM OPTION_CURRENT_EM
        WHERE UPPER(symbol) = :symbol OR UPPER(`代码`) = :symbol
        ORDER BY data_date DESC
        LIMIT 1
        """,
        {"symbol": normalized},
    )
    rows = await service._fetch_rows(
        """
        SELECT *
        FROM OPTION_CURRENT_EM
        WHERE (UPPER(symbol) = :symbol OR UPPER(`代码`) = :symbol)
          AND data_date BETWEEN :start AND :end
        ORDER BY data_date ASC
        LIMIT 260
        """,
        {
            "symbol": normalized,
            "start": _market_instrument._sql_date_text(start_date, date.today()),
            "end": _market_instrument._sql_date_text(end_date, date.today()),
        },
    )
    history_rows = [
        {
            "date": _market_instrument._iso_date(_market_instrument._first_value(row, "data_date")),
            "name": _market_instrument._safe_str(
                _market_instrument._first_value(row, "名称", "name", "代码", "symbol")
            ),
            "price": _market_instrument._safe_float(_market_instrument._first_value(row, "最新价")),
            "volume": _market_instrument._safe_int(_market_instrument._first_value(row, "成交量")),
            "turnover": _market_instrument._safe_float(
                _market_instrument._first_value(row, "成交额")
            ),
            "open_interest": _market_instrument._safe_int(
                _market_instrument._first_value(row, "持仓量")
            ),
            "change": _market_instrument._safe_float(
                _market_instrument._first_value(row, "涨跌额", "日增")
            ),
            "change_pct": _market_instrument._safe_float(
                _market_instrument._first_value(row, "涨跌幅")
            ),
            "strike": _market_instrument._safe_float(
                _market_instrument._first_value(row, "行权价")
            ),
            "days_to_expiry": _market_instrument._safe_int(
                _market_instrument._first_value(row, "剩余日")
            ),
        }
        for row in rows
    ]
    snapshot = {
        "symbol": normalized,
        "name": _market_instrument._safe_str(
            _market_instrument._first_value(current or {}, "名称", "name", "代码", "symbol")
        )
        or normalized,
        "price": _market_instrument._safe_float(
            _market_instrument._first_value(current or {}, "最新价")
        ),
        "change": _market_instrument._safe_float(
            _market_instrument._first_value(current or {}, "涨跌额")
        ),
        "change_pct": _market_instrument._safe_float(
            _market_instrument._first_value(current or {}, "涨跌幅")
        ),
        "open": _market_instrument._safe_float(
            _market_instrument._first_value(current or {}, "今开")
        ),
        "previous_settle": _market_instrument._safe_float(
            _market_instrument._first_value(current or {}, "昨结")
        ),
        "volume": _market_instrument._safe_int(
            _market_instrument._first_value(current or {}, "成交量")
        ),
        "turnover": _market_instrument._safe_float(
            _market_instrument._first_value(current or {}, "成交额")
        ),
        "open_interest": _market_instrument._safe_int(
            _market_instrument._first_value(current or {}, "持仓量")
        ),
        "strike": _market_instrument._safe_float(
            _market_instrument._first_value(current or {}, "行权价")
        ),
        "days_to_expiry": _market_instrument._safe_int(
            _market_instrument._first_value(current or {}, "剩余日")
        ),
        "update_time": _market_instrument._safe_str(
            _market_instrument._first_value(current or {}, "data_date")
        ),
        "data_source_table": "OPTION_CURRENT_EM",
    }
    return service._payload(
        asset_type="option",
        symbol=normalized,
        name=_market_instrument._name_or_fallback(snapshot.get("name"), normalized),
        market=market or "CN",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
        provider=_market_instrument._WAREHOUSE_PROVIDER,
    )


async def _lookup_fx_warehouse(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    normalized = symbol.upper()
    spot = await service._fetch_one(
        """
        SELECT *
        FROM FOREX_SPOT_EM
        WHERE UPPER(`代码`) = :symbol OR UPPER(symbol) = :symbol
        ORDER BY data_date DESC
        LIMIT 1
        """,
        {"symbol": normalized},
    )
    # CURRENCY_BOC_SAFE is a currency reference series, not a history of an
    # exact FX pair. It must not be presented as a requested pair's bars.
    history_rows: list[dict[str, Any]] = []
    snapshot = {
        "symbol": normalized,
        "name": _market_instrument._safe_str(
            _market_instrument._first_value(spot or {}, "名称", "name", "代码")
        )
        or normalized,
        "price": _market_instrument._safe_float(
            _market_instrument._first_value(spot or {}, "最新价")
        ),
        "change": _market_instrument._safe_float(
            _market_instrument._first_value(spot or {}, "涨跌额")
        ),
        "change_pct": _market_instrument._safe_float(
            _market_instrument._first_value(spot or {}, "涨跌幅")
        ),
        "open": _market_instrument._safe_float(_market_instrument._first_value(spot or {}, "今开")),
        "high": _market_instrument._safe_float(_market_instrument._first_value(spot or {}, "最高")),
        "low": _market_instrument._safe_float(_market_instrument._first_value(spot or {}, "最低")),
        "previous_close": _market_instrument._safe_float(
            _market_instrument._first_value(spot or {}, "昨收")
        ),
        "update_time": _market_instrument._safe_str(
            _market_instrument._first_value(spot or {}, "data_date")
        ),
        "data_source_table": "FOREX_SPOT_EM",
    }
    snapshot = snapshot or service._snapshot_from_latest_history(normalized, history_rows)
    return service._payload(
        asset_type="fx",
        symbol=normalized,
        name=_market_instrument._name_or_fallback(snapshot.get("name"), normalized),
        market=market or "FX",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
        provider=_market_instrument._WAREHOUSE_PROVIDER,
    )


_CRYPTO_INTRADAY_PERIODS = frozenset({"1m", "5m", "15m", "30m", "1h", "2h", "4h", "hourly"})


def _crypto_pair_code(symbol: str) -> str:
    """Normalise BTC-USDT / BTC/USDT / btcusdt to the Binance code BTCUSDT."""
    return "".join(character for character in symbol.upper() if character.isalnum())


async def _lookup_crypto_warehouse(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    normalized = _crypto_pair_code(symbol)
    intraday = (period or "").strip().lower() in _CRYPTO_INTRADAY_PERIODS
    table = "CRYPTO_HOURLY_MARKET" if intraday else "CRYPTO_DAILY_MARKET"
    time_column = "TRADE_DATETIME" if intraday else "TRADE_DATE"
    start_text = _market_instrument._sql_date_text(start_date, date.today())
    end_text = _market_instrument._sql_date_text(end_date, date.today())
    # DATETIME comparisons against a bare date string drop the whole end day.
    if intraday:
        start_text = f"{start_text} 00:00:00"
        end_text = f"{end_text} 23:59:59"
    rows = await service._fetch_rows(
        f"""
        SELECT *
        FROM {table}
        WHERE MARKET = 'BINANCE'
          AND SYMBOL = :symbol
          AND {time_column} BETWEEN :start AND :end
        ORDER BY {time_column} DESC
        LIMIT 1000
        """,
        {"symbol": normalized, "start": start_text, "end": end_text},
    )
    # Most recent window first, then back to chronological order so
    # change_pct can be derived from the previous close.
    rows = list(reversed(rows))
    if intraday:
        # ``_iso_date`` truncates a datetime to its date, which would collapse
        # every bar of a day onto one category label.  Hand it a pre-formatted
        # string instead so the hourly labels stay distinct.
        for row in rows:
            stamp = _market_instrument._first_value(row, time_column)
            if isinstance(stamp, datetime):
                row[time_column] = stamp.strftime("%Y-%m-%d %H:%M")
    history_rows = service._normalize_warehouse_history(
        rows,
        date_key=time_column,
        open_key="OPEN_PRICE",
        high_key="HIGH_PRICE",
        low_key="LOW_PRICE",
        close_key="CLOSE_PRICE",
        volume_key="VOLUME",
        turnover_key="TURNOVER",
    )
    snapshot = service._snapshot_from_latest_history(normalized, history_rows)
    latest_raw = rows[-1] if rows else {}
    previous_close = (
        _market_instrument._safe_float(
            _market_instrument._first_value(rows[-2], "CLOSE_PRICE")
        )
        if len(rows) > 1
        else None
    )
    latest_close = snapshot.get("price")
    snapshot.update(
        {
            "symbol": symbol.strip().upper(),
            "name": symbol.strip().upper(),
            "data_source_symbol": normalized,
            "market": "BINANCE",
            "change": (
                latest_close - previous_close
                if latest_close is not None and previous_close is not None
                else None
            ),
            "trade_count": _market_instrument._safe_int(
                _market_instrument._first_value(latest_raw, "TRADE_COUNT")
            ),
            "data_source_table": table,
        }
    )
    return service._payload(
        asset_type="crypto",
        # Echo the requested code so ``_payload_matches_request`` (which keys
        # crypto on a plain upper()) accepts BTC-USDT / btcusdt variants; the
        # canonical Binance pair stays in data_source_symbol.
        symbol=symbol.strip().upper(),
        name=_market_instrument._name_or_fallback(snapshot.get("name"), normalized),
        market=market or "BINANCE",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
        provider=_market_instrument._WAREHOUSE_PROVIDER,
    )


def _lookup_stock(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    import akshare as ak

    code = _market_instrument._normalize_plain_code(symbol)
    history_rows: list[dict[str, Any]] = []

    try:
        history_df = ak.stock_zh_a_hist(
            symbol=code,
            period=period,
            start_date=_market_instrument._date_text(start_date, date.today() - timedelta(days=90)),
            end_date=_market_instrument._date_text(end_date, date.today()),
            adjust="qfq",
            timeout=10,
        )
        history_rows = service._normalize_cn_ohlcv_history(history_df)
    except Exception as exc:
        warnings.append(f"A 股历史行情不可用: {exc}")

    # Eastmoney's daily endpoint can return an empty frame without raising.
    # The explicit query button must still retrieve current data, so use
    # AkShare's Tencent-backed endpoint as a daily-history fallback.
    if not history_rows and period == "daily":
        try:
            tencent_history_df = ak.stock_zh_a_hist_tx(
                symbol=_market_instrument._normalize_tencent_stock_symbol(code),
                start_date=_market_instrument._date_text(
                    start_date, date.today() - timedelta(days=90)
                ),
                end_date=_market_instrument._date_text(end_date, date.today()),
                adjust="qfq",
                timeout=10,
            )
            history_rows = service._normalize_generic_ohlcv_history(
                tencent_history_df.rename(columns={"amount": "volume"}),
                start_date,
                end_date,
            )
            if history_rows:
                warnings.append("A 股东方财富日线未返回数据，已切换腾讯行情源。")
        except Exception as exc:
            warnings.append(f"A 股腾讯历史行情不可用: {exc}")

    # stock_zh_a_spot_em fetches the entire market in many paginated requests.
    # A single-symbol history query is much faster and already contains the
    # most recent close needed to render the data page.
    snapshot = service._snapshot_from_latest_history(symbol, history_rows)
    return service._payload(
        asset_type="stock",
        symbol=symbol,
        name=snapshot.get("name") or symbol,
        market=market or "CN",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
    )


def _lookup_futures(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    import akshare as ak

    normalized_market = (market or "CF").strip().upper()
    snapshot: dict[str, Any] = {}
    history_rows: list[dict[str, Any]] = []

    try:
        spot_df = ak.futures_zh_spot(symbol=symbol, market=normalized_market, adjust="0")
        matched = service._match_any(spot_df, symbol, ["symbol", "代码", "合约"])
        if not matched.empty:
            row = matched.iloc[0].to_dict()
            snapshot = {
                "symbol": symbol,
                "name": _market_instrument._safe_str(row.get("symbol")) or symbol,
                "price": _market_instrument._safe_float(row.get("current_price")),
                "open": _market_instrument._safe_float(row.get("open")),
                "high": _market_instrument._safe_float(row.get("high")),
                "low": _market_instrument._safe_float(row.get("low")),
                "previous_close": _market_instrument._safe_float(row.get("last_close")),
                "settle": _market_instrument._safe_float(row.get("avg_price")),
                "previous_settle": _market_instrument._safe_float(row.get("last_settle_price")),
                "bid": _market_instrument._safe_float(row.get("bid_price")),
                "ask": _market_instrument._safe_float(row.get("ask_price")),
                "volume": _market_instrument._safe_int(row.get("volume")),
                "open_interest": _market_instrument._safe_int(row.get("hold")),
                "update_time": _market_instrument._safe_str(row.get("time")),
            }
        elif not spot_df.empty:
            warnings.append(f"未在期货实时快照中找到 {symbol}")
    except Exception as exc:
        warnings.append(f"期货实时快照不可用: {exc}")

    try:
        history_df = ak.futures_zh_daily_sina(symbol=symbol)
        history_rows = service._normalize_generic_ohlcv_history(history_df, start_date, end_date)
    except Exception as exc:
        warnings.append(f"期货历史行情不可用: {exc}")

    snapshot = snapshot or service._snapshot_from_latest_history(symbol, history_rows)
    return service._payload(
        asset_type="futures",
        symbol=symbol,
        name=snapshot.get("name") or symbol,
        market=normalized_market,
        snapshot=snapshot,
        rows=history_rows,
        period=period,
    )


def _lookup_bond(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    import akshare as ak

    exchange_symbol = _market_instrument._normalize_exchange_symbol(symbol)
    history_rows: list[dict[str, Any]] = []

    try:
        history_df = ak.bond_zh_hs_cov_daily(symbol=exchange_symbol)
        history_rows = service._normalize_generic_ohlcv_history(history_df, start_date, end_date)
    except Exception as exc:
        warnings.append(f"债券历史行情不可用: {exc}")

    snapshot = service._snapshot_from_latest_history(exchange_symbol, history_rows)
    return service._payload(
        asset_type="bond",
        symbol=exchange_symbol,
        name=snapshot.get("name") or exchange_symbol,
        market=market or "CN",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
    )


def _lookup_fund(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    import akshare as ak

    code = _market_instrument._normalize_plain_code(symbol)
    history_rows: list[dict[str, Any]] = []

    try:
        history_df = ak.fund_etf_hist_em(
            symbol=code,
            period=period,
            start_date=_market_instrument._date_text(start_date, date.today() - timedelta(days=90)),
            end_date=_market_instrument._date_text(end_date, date.today()),
            adjust="qfq",
        )
        history_rows = service._normalize_cn_ohlcv_history(history_df)
    except Exception as exc:
        warnings.append(f"基金历史行情不可用: {exc}")

    snapshot = service._snapshot_from_latest_history(code, history_rows)
    return service._payload(
        asset_type="fund",
        symbol=code,
        name=snapshot.get("name") or code,
        market=market or "CN",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
    )


def _lookup_option(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    import akshare as ak

    resolved_symbol = symbol.strip()
    normalized_symbol = resolved_symbol.lower()
    history_rows: list[dict[str, Any]] = []
    try:
        if normalized_symbol.startswith("io"):
            history_df = ak.option_cffex_hs300_daily_sina(symbol=resolved_symbol)
        elif normalized_symbol.startswith("ho"):
            history_df = ak.option_cffex_sz50_daily_sina(symbol=resolved_symbol)
        elif normalized_symbol.startswith("mo"):
            history_df = ak.option_cffex_zz1000_daily_sina(symbol=resolved_symbol)
        elif "." in resolved_symbol:
            history_df = ak.option_commodity_hist_sina(symbol=resolved_symbol.split(".", 1)[1])
        else:
            history_df = ak.option_sse_daily_sina(symbol=resolved_symbol)
        history_rows = service._normalize_generic_ohlcv_history(history_df, start_date, end_date)
    except Exception as exc:
        warnings.append(f"期权历史行情不可用: {exc}")

    snapshot = service._snapshot_from_latest_history(resolved_symbol, history_rows)
    return service._payload(
        asset_type="option",
        symbol=resolved_symbol,
        name=resolved_symbol,
        market=market or "CN",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
    )


def _lookup_fx(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    import akshare as ak

    snapshot: dict[str, Any] = {}
    history_rows: list[dict[str, Any]] = []

    try:
        spot_df = ak.forex_spot_em()
        matched = service._match_any(spot_df, symbol, ["代码", "名称", "货币对", "symbol"])
        if not matched.empty:
            row = matched.iloc[0].to_dict()
            snapshot = {
                "symbol": _market_instrument._safe_str(
                    _market_instrument._first_present(row, "代码", "货币对", "symbol")
                )
                or symbol,
                "name": _market_instrument._safe_str(
                    _market_instrument._first_present(row, "名称", "货币对", "代码")
                )
                or symbol,
                "price": _market_instrument._safe_float(
                    _market_instrument._first_present(row, "最新价", "最新", "price", "close")
                ),
                "change": _market_instrument._safe_float(
                    _market_instrument._first_present(row, "涨跌额", "change")
                ),
                "change_pct": _market_instrument._safe_float(
                    _market_instrument._first_present(row, "涨跌幅", "change_pct")
                ),
                "open": _market_instrument._safe_float(
                    _market_instrument._first_present(row, "今开", "开盘", "open")
                ),
                "high": _market_instrument._safe_float(
                    _market_instrument._first_present(row, "最高", "high")
                ),
                "low": _market_instrument._safe_float(
                    _market_instrument._first_present(row, "最低", "low")
                ),
                "previous_close": _market_instrument._safe_float(
                    _market_instrument._first_present(row, "昨收", "previous_close")
                ),
                "update_time": _market_instrument._safe_str(
                    _market_instrument._first_present(row, "更新时间", "时间", "update_time")
                ),
            }
    except Exception as exc:
        warnings.append(f"外汇实时快照不可用: {exc}")

    try:
        history_df = ak.forex_hist_em(symbol=symbol)
        history_rows = service._normalize_generic_ohlcv_history(history_df, start_date, end_date)
    except Exception as exc:
        warnings.append(f"外汇历史行情不可用: {exc}")

    snapshot = snapshot or service._snapshot_from_latest_history(symbol, history_rows)
    return service._payload(
        asset_type="fx",
        symbol=symbol,
        name=snapshot.get("name") or symbol,
        market=market or "FX",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
    )


def _lookup_crypto(
    service: _market_instrument.MarketInstrumentService,
    *,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    period: str,
    market: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    import akshare as ak

    snapshot: dict[str, Any] = {}
    history_rows: list[dict[str, Any]] = []

    try:
        spot_df = ak.crypto_js_spot()
        matched = service._match_any(spot_df, symbol, ["交易品种"])
        if not matched.empty:
            row = matched.iloc[0].to_dict()
            snapshot = {
                "symbol": _market_instrument._safe_str(row.get("交易品种")) or symbol,
                "name": _market_instrument._safe_str(row.get("交易品种")) or symbol,
                "price": _market_instrument._safe_float(row.get("最近报价")),
                "change": _market_instrument._safe_float(row.get("涨跌额")),
                "change_pct": _market_instrument._safe_float(row.get("涨跌幅")),
                "high": _market_instrument._safe_float(row.get("24小时最高")),
                "low": _market_instrument._safe_float(row.get("24小时最低")),
                "volume": _market_instrument._safe_float(row.get("24小时成交量")),
                "market": _market_instrument._safe_str(row.get("市场")),
                "update_time": _market_instrument._safe_str(row.get("更新时间")),
            }
        else:
            warnings.append(f"未在数字货币实时快照中找到 {symbol}")
    except Exception as exc:
        warnings.append(f"数字货币实时快照不可用: {exc}")

    return service._payload(
        asset_type="crypto",
        symbol=symbol,
        name=snapshot.get("name") or symbol,
        market=market or _market_instrument._safe_str(snapshot.get("market")) or "CRYPTO",
        snapshot=snapshot,
        rows=history_rows,
        period=period,
    )
