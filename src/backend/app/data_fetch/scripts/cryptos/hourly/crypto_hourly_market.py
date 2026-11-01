"""Crypto Hourly Market

数据源: Binance (data-api.binance.vision / data.binance.vision)
接口: /api/v3/klines (interval=1h) + spot daily kline archives
频率: hourly

写入表: CRYPTO_HOURLY_MARKET，唯一键 (MARKET, SYMBOL, TRADE_DATETIME)
时间基准为 UTC，K 线时间存的是开盘时刻。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from app.data_fetch.configs.db_config import DB_CONFIG
from app.data_fetch.providers.binance_to_mysql import (
    DEFAULT_CRYPTO_SYMBOLS,
    BinanceToMySql,
    hourly_table_ddl,
)

SCRIPT_NAME = "Crypto Hourly Market"
DESCRIPTION = "数字货币 Binance 小时线历史行情（现货 USDT 交易对，UTC 开盘时刻）"
TARGET_TABLE = "CRYPTO_HOURLY_MARKET"


class CryptoHourlyMarket(BinanceToMySql):
    """Pull Binance hourly spot klines for the configured crypto universe."""

    time_column = "TRADE_DATETIME"
    interval = "1h"
    reference_code = "CRYPTO_HOURLY"

    def __init__(self, db_config=DB_CONFIG, logger=None):
        super().__init__(db_config, logger)
        self.table_name = TARGET_TABLE
        self.create_table_sql = hourly_table_ddl(self.table_name)

    def fetch_data(self, **kwargs: Any) -> pd.DataFrame:
        """Keyword args: symbols, since (default 2020-01-01), tail_days (default 3)."""
        symbols = [str(s).upper() for s in kwargs.get("symbols") or DEFAULT_CRYPTO_SYMBOLS]
        since = kwargs.get("since") or date(2020, 1, 1)
        tail_days = int(kwargs.get("tail_days", 3))
        written = 0
        for symbol in symbols:
            try:
                written += self.backfill_history(symbol, start=since) or 0
                written += self.refresh_tail(symbol, days=tail_days) or 0
            except Exception as exc:
                self.logger.error("crypto hourly %s failed: %s", symbol, exc)
        self.logger.info("crypto hourly 写入 %s 行，覆盖 %s 个交易对", written, len(symbols))
        return pd.DataFrame({"symbol": symbols, "written": [written] * len(symbols)})


def main():
    """Main function to run the data fetch"""
    return CryptoHourlyMarket().fetch_data()


if __name__ == "__main__":
    main()
