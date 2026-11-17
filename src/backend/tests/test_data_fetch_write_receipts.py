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
    def __init__(self, *, rowcount: int = -1, table: str = "FAKE_TABLE") -> None:
        self.rowcount = rowcount
        self.table = table
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
        return [("value",)]

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
