"""
Bond Zh Hs Cov Daily

数据源: AkShare
函数: bond_zh_hs_cov_daily
频率: daily
"""

from typing import cast

import pandas as pd

from app.data_fetch.configs.db_config import DB_CONFIG
from app.data_fetch.providers.akshare_to_mysql import AkshareToMySql


class BondZhHsCovDaily(AkshareToMySql):
    """Bond Zh Hs Cov Daily"""

    def __init__(self, db_config=DB_CONFIG, logger=None):
        super().__init__(db_config, logger)
        self.table_name = "BOND_ZH_HS_COV_DAILY"
        self.create_table_sql = """
    CREATE TABLE IF NOT EXISTS `BOND_ZH_HS_COV_DAILY` (
        `R_ID` INT AUTO_INCREMENT PRIMARY KEY,
            `symbol` VARCHAR(50) COMMENT '品种代码',
            `name` VARCHAR(100) COMMENT '品种名称',
            `data_date` DATE COMMENT '数据日期',
            `source` VARCHAR(32) NOT NULL DEFAULT 'sina' COMMENT '数据来源',
            `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        UNIQUE KEY uk_symbol_date_source (`symbol`, `data_date`, `source`),
        INDEX idx_data_date (`data_date`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Bond Zh Hs Cov Daily'
    """

    def create_table_if_not_exists(
        self, table_name: str | None = None, create_table_sql: str | None = None
    ) -> bool:
        """Create table when absent, or backfill ``source`` and 3-column UK on legacy tables."""
        created = super().create_table_if_not_exists(table_name, create_table_sql)
        target_table = table_name or self.table_name
        if not created and target_table == self.table_name:
            self._migrate_legacy_schema(target_table)
        return created

    def _migrate_legacy_schema(self, table_name: str = "BOND_ZH_HS_COV_DAILY") -> None:
        """Ensure legacy ``BOND_ZH_HS_COV_DAILY`` tables have ``source`` and ``uk_symbol_date_source``."""
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
                    "VARCHAR(32) NOT NULL DEFAULT 'sina' COMMENT '数据来源'"
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

            desired_cols = ("symbol", "data_date", "source")
            has_desired_uk = False
            for idx_name, col_pairs in unique_indexes.items():
                ordered = tuple(col for _, col in sorted(col_pairs))
                if ordered == desired_cols:
                    has_desired_uk = True
                elif ordered == ("symbol", "data_date"):
                    safe_idx = idx_name.replace("`", "``")
                    cursor.execute(
                        f"ALTER TABLE `{safe_table}` DROP INDEX `{safe_idx}`"  # nosec B608
                    )

            if not has_desired_uk:
                cursor.execute(
                    f"ALTER TABLE `{safe_table}` "  # nosec B608
                    "ADD UNIQUE KEY uk_symbol_date_source (`symbol`, `data_date`, `source`)"
                )
            conn.commit()
        except Exception as exc:
            self.logger.warning(f"Failed to check/migrate {table_name} schema: {exc}")
        finally:
            self.disconnect_db()

    def fetch_data(self, **kwargs):
        """Fetch data from AkShare and save to database.

        Args:
            **kwargs: Parameters to pass to ak.bond_zh_hs_cov_daily

        Returns:
            pd.DataFrame: Fetched data
        """
        try:
            # ``source`` selects the observation series (the table's NOT NULL
            # source column) and is not a parameter of the upstream function.
            source = str(kwargs.pop("source", "") or "sina").strip().lower() or "sina"
            # Fetch data from AkShare
            df = self.fetch_ak_data("bond_zh_hs_cov_daily", **kwargs)

            if df is None or df.empty:
                self.logger.warning("No data found")
                return pd.DataFrame()

            # Process data if needed
            # AkShare returns the bar columns only; the requested symbol is the
            # instrument identity and `date` is the trading session, so the
            # unique key (symbol, data_date, source) avoids cross-day collisions.
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df = df.dropna(subset=["date"]).drop_duplicates(subset=["date"])
                if df.empty:
                    self.logger.warning("No valid dated rows found after parsing dates")
                    return pd.DataFrame()
                df["data_date"] = df["date"].dt.date
            elif "data_date" not in df.columns:
                df["data_date"] = pd.Timestamp.now().date()
            requested_symbol = str(kwargs.get("symbol") or "").strip()
            if not requested_symbol:
                self.logger.warning("No symbol supplied; daily bars would have no instrument key")
                return pd.DataFrame()
            if "symbol" not in df.columns:
                df["symbol"] = requested_symbol
            if "name" not in df.columns:
                df["name"] = requested_symbol
            if "source" not in df.columns:
                df["source"] = source
        except Exception as e:
            self.logger.error(f"Error fetching data: {e}")
            return pd.DataFrame()

        # Persist outside the fetch try/except so database failures propagate loudly.
        self.create_table_if_not_exists(self.table_name, self.create_table_sql)
        self.save_data(
            df,
            self.table_name,
            ignore_duplicates=True,
            unique_keys=["symbol", "data_date", "source"],
        )

        return df


def main():
    """Main function to run the data fetch"""

    script = BondZhHsCovDaily()
    script.fetch_data()


if __name__ == "__main__":
    main()
