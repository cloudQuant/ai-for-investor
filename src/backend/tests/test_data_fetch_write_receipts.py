"""Regression tests for the data-fetch write receipt contract.

The warehouse writer must report the rows MySQL actually applied, not the rows
the DataFrame offered.  With ``INSERT IGNORE`` a duplicate-heavy batch applies
zero rows; returning the offered length makes the execution receipt claim a
commit that never happened and lets the empty-completion guard pass.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.data_fetch.core.mysql_base import MysqlBase


class _FakeCursor:
    def __init__(
        self,
        *,
        rowcount: int = -1,
        table: str = "FAKE_TABLE",
        info: str | None = None,
        result_message: bytes | str | None = None,
        columns: list[tuple[object, ...]] | None = None,
    ) -> None:
        self.rowcount = rowcount
        self.table = table
        self.info = info
        self._result = (
            type("_Result", (), {"message": result_message})()
            if result_message is not None
            else None
        )
        self._columns = columns or [("value",)]
        self.inserted: tuple[str, list[list[object]]] | None = None
        self.closed = False

    def execute(self, sql: str, params: object = ()) -> None:
        del params
        if sql.startswith("SHOW TABLES LIKE"):
            self._last = self.table
        else:
            self._last = None

    def executemany(self, sql: str, data: list[list[object]]) -> None:
        self.inserted = (sql, data)

    def fetchone(self):
        return getattr(self, "_last", None)

    def fetchall(self):
        return self._columns

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True

    def is_connected(self) -> bool:
        return True


def _mysql_base(*, rowcount: int) -> tuple[MysqlBase, _FakeCursor, _FakeConnection]:
    service = MysqlBase({})
    cursor = _FakeCursor(rowcount=rowcount)
    connection = _FakeConnection()
    service.cursor = cursor
    service.connection = connection
    service.connect_db = lambda: None  # type: ignore[method-assign]
    return service, cursor, connection


@pytest.mark.parametrize(
    ("rowcount", "expected"),
    [
        (0, 0),  # INSERT IGNORE: every row duplicated
        (1, 1),  # partial duplicate
        (3, 3),  # all rows applied
        (-1, 3),  # driver/test double without rowcount -> offered length
        (99, 3),  # driver over-reports -> cap at the batch length
    ],
)
def test_mysql_base_save_data_returns_affected_rows(rowcount: int, expected: int) -> None:
    service, cursor, connection = _mysql_base(rowcount=rowcount)

    result = service.save_data(
        pd.DataFrame({"value": [1, 2, 3]}),
        "FAKE_TABLE",
        ignore_duplicates=True,
    )

    assert result == expected
    assert cursor.inserted is not None
    assert connection.commits == 1


def test_mysql_base_execute_batch_returns_rowcount_not_bool() -> None:
    service, _cursor, _connection = _mysql_base(rowcount=0)

    assert service._execute_batch("INSERT IGNORE INTO t VALUES (%s)", [[1], [2]]) == 0


def test_akshare_provider_save_data_returns_affected_rows() -> None:
    pytest.importorskip("akshare", reason="optional akshare provider package is required")
    from app.data_fetch.providers.akshare_provider import AkshareProvider

    service = AkshareProvider({})
    cursor = _FakeCursor(rowcount=0)
    connection = _FakeConnection()
    service.cursor = cursor
    service.connection = connection
    service.connect_db = lambda: True  # type: ignore[method-assign]
    service.disconnect_db = lambda: None  # type: ignore[method-assign]

    result = service.save_data(
        pd.DataFrame({"value": [1, 2]}),
        "FAKE_TABLE",
        ignore_duplicates=True,
    )

    assert result == 0
    assert cursor.inserted is not None
    assert connection.commits == 1


def test_akshare_provider_drops_unknown_columns_coerces_values_and_disconnects_on_error() -> None:
    pytest.importorskip("akshare", reason="optional akshare provider package is required")
    from app.data_fetch.providers.akshare_provider import AkshareProvider

    service = AkshareProvider({})
    cursor = _FakeCursor(rowcount=2, columns=[("value",), ("meta",)])
    connection = _FakeConnection()
    disconnects = []
    service.cursor = cursor
    service.connection = connection
    service.connect_db = lambda: True  # type: ignore[method-assign]
    service.disconnect_db = lambda: disconnects.append(1)  # type: ignore[method-assign]

    df = pd.DataFrame(
        {
            "value": [1.5, float("inf")],
            "meta": [{"k": 1}, ["a", "b"]],
            "unknown_upstream_col": ["drop1", "drop2"],
        }
    )
    result = service.save_data(df, "FAKE_TABLE", on_duplicate_update=True, unique_keys=["value"])

    assert result == 2
    assert len(disconnects) == 1
    assert cursor.inserted is not None
    sql, batch = cursor.inserted
    assert "unknown_upstream_col" not in sql
    assert "`value`" in sql and "`meta`" in sql
    assert batch[0] == [1.5, '{"k": 1}']
    assert batch[1] == [None, '["a", "b"]']

    # Invalid identifier or early None return from _align_df_to_table must still disconnect
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        service.save_data(pd.DataFrame({"value": [1]}), "bad table name")
    assert len(disconnects) == 2

    assert service.save_data(pd.DataFrame({"completely_unknown": [1]}), "FAKE_TABLE") is False
    assert len(disconnects) == 3


@pytest.mark.parametrize(
    ("rowcount", "info", "result_message", "expected"),
    [
        (0, "Records: 3  Duplicates: 3  Warnings: 0", None, 0),  # 3 unchanged duplicates
        (2, "Records: 3  Duplicates: 3  Warnings: 0", None, 1),  # 1 updated + 2 unchanged (was 2)
        (3, "Records: 3  Duplicates: 2  Warnings: 0", None, 2),  # 1 inserted + 1 updated (was 3)
        (6, "Records: 3  Duplicates: 3  Warnings: 0", None, 3),  # 3 updated -> 6 reported
        (2, None, b"Records: 3  Duplicates: 3  Warnings: 0", 1),  # PyMySQL OK-packet message
    ],
)
def test_on_duplicate_key_update_deduplicates_double_counted_rows(
    rowcount: int,
    info: str | None,
    result_message: bytes | None,
    expected: int,
) -> None:
    sql = "INSERT INTO `T` (`k`, `v`) VALUES (%s, %s) ON DUPLICATE KEY UPDATE `v`=VALUES(`v`)"
    batch = [["a", 1], ["b", 2], ["c", 3]]

    service = MysqlBase({})
    cursor = _FakeCursor(rowcount=rowcount, info=info, result_message=result_message)
    connection = _FakeConnection()
    service.cursor = cursor
    service.connection = connection
    assert service._execute_batch(sql, batch) == expected

    pytest.importorskip("akshare", reason="optional akshare provider package is required")
    from app.data_fetch.providers.akshare_provider import AkshareProvider

    provider = AkshareProvider({})
    provider.cursor = _FakeCursor(rowcount=rowcount, info=info, result_message=result_message)
    provider.connection = _FakeConnection()
    assert provider._execute_batch(sql, batch) == expected


def test_scripts_treat_zero_row_idempotent_save_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.data_fetch.scripts.bonds.weekly.bond_info_cm import BondInfoCm
    from app.data_fetch.scripts.common.daily import akshare_catalog_endpoint
    from app.data_fetch.scripts.funds.weekly.fund_rating_all import FundRatingAll
    from app.data_fetch.scripts.funds.weekly.open_fund_daily_em import OpenFundDailyEm
    from app.data_fetch.scripts.indexs.daily.stock_hk_index_spot_em import StockHkIndexSpotEm

    noop_logger = SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )

    spot = object.__new__(StockHkIndexSpotEm)
    spot.table_name = "T"
    spot.logger = noop_logger
    spot.table_exists = lambda _t: True
    spot.fetch_index_spot = lambda: pd.DataFrame(
        {"INDEX_CODE": ["HSI"], "TRADE_DATE": ["2026-11-19"]}
    )
    spot.save_data = lambda **k: 0
    assert spot.run() is True
    spot.save_data = lambda **k: False
    assert spot.run() is False

    rating = object.__new__(FundRatingAll)
    rating.table_name = "T"
    rating.logger = noop_logger
    rating.save_data = lambda *a, **k: 0
    assert rating.save_rating_data(pd.DataFrame({"R_ID": ["1"]})) is True
    rating.save_data = lambda *a, **k: False
    assert rating.save_rating_data(pd.DataFrame({"R_ID": ["1"]})) is False

    open_fund = object.__new__(OpenFundDailyEm)
    open_fund.table_name = "T"
    open_fund.logger = noop_logger
    open_fund.create_table_if_not_exists = lambda *a, **k: False
    open_fund.get_latest_net_value_date = lambda: None
    open_fund.fetch_open_fund_daily_data = lambda: pd.DataFrame({"R_ID": ["1"]})
    open_fund.save_open_fund_daily_data = lambda df: 0
    open_fund.disconnect_db = lambda: None
    assert open_fund.run() is True
    open_fund.save_open_fund_daily_data = lambda df: False
    assert open_fund.run() is False

    bond = object.__new__(BondInfoCm)
    bond.table_name = "T"
    bond.create_table_sql = ""
    bond.logger = noop_logger
    bond.table_exists = lambda _t: True
    bond.fetch_bond_info = lambda max_pages=None: pd.DataFrame({"BOND_CODE": ["01"]})
    bond.save_data = lambda **k: 0
    assert bond.run() is True

    fake_provider = SimpleNamespace(
        fetch_ak_data=lambda *a, **k: pd.DataFrame({"a": [1]}),
        create_table_from_dataframe_if_not_exists=lambda **k: False,
        save_data=lambda *a, **k: 0,
    )
    monkeypatch.setattr(akshare_catalog_endpoint, "AkshareToMySql", lambda *a, **k: fake_provider)
    res = akshare_catalog_endpoint.run_endpoint(
        endpoint_name="stock_zh_a_spot_em", target_table="T"
    )
    assert res["success"] is True
    fake_provider.save_data = lambda *a, **k: False
    res_fail = akshare_catalog_endpoint.run_endpoint(
        endpoint_name="stock_zh_a_spot_em", target_table="T"
    )
    assert res_fail["success"] is False
