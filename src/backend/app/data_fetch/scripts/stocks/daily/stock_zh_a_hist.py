"""
Stock Zh A Hist

数据源: AkShare
函数: stock_zh_a_hist
频率: daily
"""

from typing import cast

import pandas as pd
from akshare.utils.request import request_with_retry as request_eastmoney

from app.data_fetch.configs.db_config import DB_CONFIG
from app.data_fetch.providers.akshare_to_mysql import AkshareToMySql


class StockZhAHist(AkshareToMySql):
    """Stock Zh A Hist"""

    def __init__(self, db_config=DB_CONFIG, logger=None):
        super().__init__(db_config, logger)
        self.table_name = "STOCK_ZH_A_HIST"
        self.create_table_sql = """
    CREATE TABLE IF NOT EXISTS `STOCK_ZH_A_HIST` (
        `R_ID` INT AUTO_INCREMENT PRIMARY KEY,
            `symbol` VARCHAR(50) COMMENT '品种代码',
            `name` VARCHAR(100) COMMENT '品种名称',
            `data_date` DATE COMMENT '数据日期',
            `source` VARCHAR(32) NOT NULL DEFAULT 'eastmoney' COMMENT '数据来源',
            `adjustment` VARCHAR(32) NOT NULL DEFAULT 'qfq' COMMENT '复权口径',
            `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        UNIQUE KEY uk_symbol_date_adjustment_source (`symbol`, `data_date`, `adjustment`, `source`),
        INDEX idx_data_date (`data_date`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Stock Zh A Hist'
    """

    def create_table_if_not_exists(
        self, table_name: str | None = None, create_table_sql: str | None = None
    ) -> bool:
        """Create table when absent, or backfill ``source``/``adjustment``/UK on legacy tables."""
        created = super().create_table_if_not_exists(table_name, create_table_sql)
        target_table = table_name or self.table_name
        if not created and target_table == self.table_name:
            self._migrate_legacy_schema(target_table)
        return created

    def _migrate_legacy_schema(self, table_name: str = "STOCK_ZH_A_HIST") -> None:
        """Ensure legacy ``STOCK_ZH_A_HIST`` tables have ``source``, ``adjustment``, and the 4-col UK."""
        safe_table = str(table_name).replace("`", "``")
        try:
            self.connect_db()
            cursor = self.require_cursor()
            conn = self.require_connection()

            cursor.execute(f"SHOW COLUMNS FROM `{safe_table}`")  # nosec B608
            existing_cols = {
                str(row[0]).lower() for row in (cursor.fetchall() or []) if row and row[0]
            }
            if "source" not in existing_cols:
                cursor.execute(
                    f"ALTER TABLE `{safe_table}` ADD COLUMN `source` "  # nosec B608
                    "VARCHAR(32) NOT NULL DEFAULT 'eastmoney' COMMENT '数据来源'"
                )
            if "adjustment" not in existing_cols:
                cursor.execute(
                    f"ALTER TABLE `{safe_table}` ADD COLUMN `adjustment` "  # nosec B608
                    "VARCHAR(32) NOT NULL DEFAULT 'qfq' COMMENT '复权口径'"
                )

            cursor.execute(f"SHOW INDEX FROM `{safe_table}`")  # nosec B608
            unique_indexes: dict[str, list[tuple[int, str]]] = {}
            for row in cursor.fetchall() or []:
                if not row or len(row) < 5:
                    continue
                non_unique = int(cast(int, row[1])) if row[1] is not None else 1
                key_name = str(row[2])
                if non_unique != 0 or key_name.upper() == "PRIMARY":
                    continue
                seq_in_index = int(cast(int, row[3])) if row[3] is not None else 0
                col_name = str(row[4]).lower()
                unique_indexes.setdefault(key_name, []).append((seq_in_index, col_name))

            desired_cols = ("symbol", "data_date", "adjustment", "source")
            has_desired_uk = False
            for idx_name, col_pairs in unique_indexes.items():
                ordered = tuple(col for _, col in sorted(col_pairs))
                if ordered == desired_cols:
                    has_desired_uk = True
                elif ordered in {("symbol", "data_date"), ("symbol", "data_date", "adjustment")}:
                    safe_idx = idx_name.replace("`", "``")
                    cursor.execute(
                        f"ALTER TABLE `{safe_table}` DROP INDEX `{safe_idx}`"  # nosec B608
                    )

            if not has_desired_uk:
                cursor.execute(
                    f"ALTER TABLE `{safe_table}` "  # nosec B608
                    "ADD UNIQUE KEY uk_symbol_date_adjustment_source "
                    "(`symbol`, `data_date`, `adjustment`, `source`)"
                )
            conn.commit()
        except Exception as exc:
            self.logger.warning(f"Failed to check/migrate {table_name} schema: {exc}")
        finally:
            self.disconnect_db()

    @staticmethod
    def _normalize_adjust(raw_adjust: object) -> tuple[str, str]:
        """Return ``(upstream_ak_adjust, warehouse_adjustment_label)``.

        Explicit empty string ``""`` denotes unadjusted (不复权) prices and must
        never collapse into ``"qfq"``. When omitted (``None``), preserve the
        historical ``"qfq"`` default and pass it consistently upstream.
        """
        if raw_adjust is None:
            return "qfq", "qfq"
        text = str(raw_adjust).strip().lower()
        if text in {"", "none", "unadjusted", "bfq"}:
            return "", "none"
        return text, text

    @staticmethod
    def _trend_secid(symbol: str) -> str:
        symbol = str(symbol or "").strip()
        market = "1" if symbol.startswith("6") else "0"
        return f"{market}.{symbol}"

    @staticmethod
    def _tx_symbol(symbol: str) -> str:
        symbol = str(symbol or "").strip()
        if symbol.startswith(("sh", "sz", "bj")):
            return symbol
        if symbol.startswith("920"):
            # Beijing Stock Exchange renumbered its board to 920xxxx in 2024; the old
            # 4xxxxx/8xxxxx rule leaves these misrouted to Shenzhen, where they 404.
            return f"bj{symbol}"
        if symbol.startswith("9"):
            # 900xxx are Shanghai B shares, not another Beijing segment.
            return f"sh{symbol}"
        if symbol.startswith("6"):
            return f"sh{symbol}"
        if symbol.startswith(("4", "8")):
            return f"bj{symbol}"
        return f"sz{symbol}"

    def _fetch_daily_from_tencent(self, **kwargs) -> pd.DataFrame:
        symbol = str(kwargs.get("symbol") or "000001").strip()
        upstream_adjust, _ = self._normalize_adjust(kwargs.get("adjust"))
        tx_kwargs = {
            "symbol": self._tx_symbol(symbol),
            "start_date": kwargs.get("start_date", "19700101"),
            "end_date": kwargs.get("end_date", "20500101"),
            "adjust": upstream_adjust,
        }
        if kwargs.get("_call_timeout") is not None:
            tx_kwargs["_call_timeout"] = kwargs["_call_timeout"]
        try:
            df = self.fetch_ak_data("stock_zh_a_hist_tx", **tx_kwargs)
        except Exception as exc:
            self.logger.warning(f"Tencent stock history fetch failed: {exc}")
            return pd.DataFrame()
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(
            columns={
                "date": "日期",
                "open": "开盘",
                "close": "收盘",
                "high": "最高",
                "low": "最低",
                "amount": "成交量",
            }
        )
        df["股票代码"] = symbol
        df["symbol"] = symbol
        df["name"] = symbol
        if "成交额" not in df.columns:
            df["成交额"] = None
        for column in ("振幅", "涨跌幅", "涨跌额", "换手率"):
            if column not in df.columns:
                df[column] = None
        self.logger.info("Populated STOCK_ZH_A_HIST from Tencent daily history")
        return df

    def _fetch_daily_from_trends(
        self, symbol: str, start_date: str | None = None, end_date: str | None = None
    ) -> pd.DataFrame:
        url = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
        params = {
            "secid": self._trend_secid(symbol),
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "iscr": "0",
            "iscca": "0",
            "ndays": "5",
        }
        try:
            data_json = request_eastmoney(url, params=params, timeout=20).json()
        except Exception as exc:
            self.logger.warning(f"Eastmoney trends2 fallback failed: {exc}")
            return pd.DataFrame()

        data = data_json.get("data") or {}
        trends = data.get("trends") or []
        if not trends:
            return pd.DataFrame()
        df = pd.DataFrame([item.split(",") for item in trends])
        if df.empty or df.shape[1] < 7:
            return pd.DataFrame()
        df = df.iloc[:, :7]
        df.columns = ["时间", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]
        df["时间"] = pd.to_datetime(df["时间"], errors="coerce")
        df = df.dropna(subset=["时间"])
        if df.empty:
            return pd.DataFrame()
        for column in ("开盘", "收盘", "最高", "最低", "成交量", "成交额"):
            df[column] = pd.to_numeric(df[column], errors="coerce")
        df["日期"] = df["时间"].dt.strftime("%Y-%m-%d")
        grouped = (
            df.groupby("日期", as_index=False)
            .agg(
                开盘=("开盘", "first"),
                收盘=("收盘", "last"),
                最高=("最高", "max"),
                最低=("最低", "min"),
                成交量=("成交量", "sum"),
                成交额=("成交额", "sum"),
            )
            .sort_values("日期")
        )
        # `preClose` is often absent from the Eastmoney payload. to_numeric(None, errors="coerce")
        # already returns NaN and every reader below tests only `pd.isna(previous_close)`, so the
        # explicit None branch keeps the value exactly what the old call produced.
        raw_pre_close = data.get("preClose")
        previous_close = (
            pd.to_numeric(raw_pre_close, errors="coerce")
            if raw_pre_close is not None
            else float("nan")
        )
        changes: list[float | None] = []
        pct_changes: list[float | None] = []
        amplitudes: list[float | None] = []
        for _, row in grouped.iterrows():
            close = row["收盘"]
            high = row["最高"]
            low = row["最低"]
            if pd.isna(previous_close) or previous_close == 0:
                changes.append(None)
                pct_changes.append(None)
                amplitudes.append(None)
            else:
                change = close - previous_close
                changes.append(change)
                pct_changes.append(change / previous_close * 100)
                amplitudes.append((high - low) / previous_close * 100)
            previous_close = close
        grouped["涨跌额"] = changes
        grouped["涨跌幅"] = pct_changes
        grouped["振幅"] = amplitudes
        grouped["换手率"] = None
        grouped["股票代码"] = symbol
        grouped["symbol"] = symbol
        grouped["name"] = data.get("name") or symbol
        grouped["data_date"] = grouped["日期"]
        if start_date:
            start = pd.to_datetime(start_date, errors="coerce")
            if not pd.isna(start):
                grouped = grouped[pd.to_datetime(grouped["日期"]) >= start]
        if end_date:
            end = pd.to_datetime(end_date, errors="coerce")
            if not pd.isna(end):
                grouped = grouped[pd.to_datetime(grouped["日期"]) <= end]
        if not grouped.empty:
            self.logger.warning(
                "Eastmoney kline returned empty; populated STOCK_ZH_A_HIST from same-source trends2 aggregation"
            )
        return grouped.reset_index(drop=True)

    def fetch_data(self, **kwargs):
        """Fetch data from AkShare and save to database.

        Args:
            **kwargs: Parameters to pass to ak.stock_zh_a_hist

        Returns:
            pd.DataFrame: Fetched data
        """
        raw_adjust = kwargs.pop("adjust", None)
        upstream_adjust, adjustment_label = self._normalize_adjust(raw_adjust)
        source = str(kwargs.pop("source", "auto") or "auto").lower()
        source_aliases = {
            "tx": "tencent",
            "qq": "tencent",
            "em": "eastmoney",
            "east_money": "eastmoney",
        }
        source = source_aliases.get(source, source)
        if source not in {"auto", "eastmoney", "tencent"}:
            self.logger.warning(f"Unknown stock history source {source!r}; using auto")
            source = "auto"

        fetch_kwargs = dict(kwargs)
        fetch_kwargs["adjust"] = upstream_adjust

        try:
            source_used = "eastmoney"
            symbol = str(fetch_kwargs.get("symbol") or "000001")
            if source == "tencent":
                df = self._fetch_daily_from_tencent(**fetch_kwargs)
                source_used = "tencent"
            else:
                try:
                    df = self.fetch_ak_data("stock_zh_a_hist", **fetch_kwargs)
                except Exception as fetch_exc:
                    self.logger.warning(f"Eastmoney kline fetch failed: {fetch_exc}")
                    df = pd.DataFrame()

                if (df is None or df.empty) and source == "auto":
                    df = self._fetch_daily_from_tencent(**fetch_kwargs)
                    if df is not None and not df.empty:
                        source_used = "tencent"

                if df is None or df.empty:
                    df = self._fetch_daily_from_trends(
                        symbol=symbol,
                        start_date=fetch_kwargs.get("start_date"),
                        end_date=fetch_kwargs.get("end_date"),
                    )
                    if df is not None and not df.empty:
                        source_used = "eastmoney_trends"
                        adjustment_label = "none"

            if df is None or df.empty:
                self.logger.warning("No data found")
                return pd.DataFrame()

            # Add data_date if not exists
            if "日期" in df.columns:
                df["日期"] = pd.to_datetime(df["日期"], errors="coerce").dt.strftime("%Y-%m-%d")
                df = df.dropna(subset=["日期"]).drop_duplicates(subset=["日期"])
                if df.empty:
                    self.logger.warning("No valid rows left after date normalization")
                    return pd.DataFrame()
                df["data_date"] = df["日期"]
            elif "data_date" not in df.columns:
                df["data_date"] = pd.Timestamp.now().date()
            if "symbol" not in df.columns:
                if "股票代码" in df.columns:
                    df["symbol"] = df["股票代码"].astype(str)
                elif fetch_kwargs.get("symbol") is not None:
                    df["symbol"] = str(fetch_kwargs["symbol"])
            if "name" not in df.columns and fetch_kwargs.get("symbol") is not None:
                df["name"] = str(fetch_kwargs["symbol"])
            # A business date can carry several observation series (adjustment
            # basis and source are part of the table's unique key). Stamping
            # both keeps this run's series distinct from other bases/sources.
            df["source"] = source_used
            df["adjustment"] = adjustment_label
        except Exception as exc:
            self.logger.error(f"Error fetching data: {exc}")
            return pd.DataFrame()

        self.logger.info(
            "stock save payload symbol=%s rows=%d adjustment=%s source=%s last_date=%s",
            df["symbol"].iloc[-1],
            len(df),
            df["adjustment"].iloc[-1],
            df["source"].iloc[-1],
            df["data_date"].iloc[-1],
        )
        self.create_table_if_not_exists(self.table_name, self.create_table_sql)
        self.save_data(
            df,
            self.table_name,
            on_duplicate_update=True,
            unique_keys=["symbol", "data_date", "adjustment", "source"],
        )

        return df


def main():
    """Main function to run the data fetch"""

    script = StockZhAHist()
    script.fetch_data()


if __name__ == "__main__":
    main()
