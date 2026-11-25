from collections.abc import Sequence

import pytest

pytest.importorskip("akshare", reason="optional akshare provider package is required")

from app.data_fetch.providers import akshare_provider  # noqa: E402
from app.data_fetch.providers.akshare_provider import AkshareProvider  # noqa: E402


class FakeCursor:
    def __init__(self) -> None:
        self.fetchone_result: tuple[object, ...] | None = None
        self.executed: list[tuple[str, object | None]] = []
        self.closed = False

    def execute(self, query: str, args: object | None = None) -> int:
        self.executed.append((query, args))
        return 1

    def executemany(self, query: str, args: Sequence[Sequence[object]]) -> int:
        self.executed.append((query, args))
        return len(args)

    def fetchall(self) -> Sequence[tuple[object, ...]]:
        return []

    def fetchone(self) -> tuple[object, ...] | None:
        return self.fetchone_result

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.is_open = True
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    @property
    def open(self) -> bool:
        return self.is_open

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True
        self.is_open = False


def test_connect_db_narrows_fake_pymysql_connection_and_cursor(monkeypatch) -> None:
    provider = AkshareProvider("mysql://user:password@localhost/market_data")
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    monkeypatch.setattr(akshare_provider, "_get_connection_pool", lambda _config: None)
    monkeypatch.setattr(akshare_provider.pymysql, "connect", lambda **_config: connection)

    assert provider.connect_db() is True
    assert provider.connection is connection
    assert provider.cursor is cursor

    provider.disconnect_db()

    assert cursor.closed is True
    assert connection.closed is True


def test_connect_db_rejects_unsupported_connection_before_cursor_use(monkeypatch) -> None:
    provider = AkshareProvider("mysql://user:password@localhost/market_data")
    monkeypatch.setattr(akshare_provider, "_get_connection_pool", lambda _config: None)
    monkeypatch.setattr(akshare_provider.pymysql, "connect", lambda **_config: object())

    with pytest.raises(TypeError, match="unsupported connection"):
        provider.connect_db()


def test_get_table_row_count_returns_zero_for_empty_fetchone(monkeypatch) -> None:
    provider = AkshareProvider("mysql://user:password@localhost/market_data")
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    provider.cursor = cursor
    provider.connection = connection
    monkeypatch.setattr(provider, "connect_db", lambda: None)

    assert provider.get_table_row_count("prices") == 0
    assert cursor.executed == [("SELECT COUNT(*) FROM `prices`", None)]
    assert cursor.closed is True
    assert connection.closed is True


def test_create_table_if_not_exists_rejects_missing_arguments_without_connecting(
    monkeypatch,
) -> None:
    provider = AkshareProvider("sqlite:///unused.db")
    monkeypatch.setattr(
        provider,
        "connect_db",
        lambda: (_ for _ in ()).throw(AssertionError("missing arguments must not connect")),
    )

    assert provider.create_table_if_not_exists() is False


def test_provider_pools_are_keyed_by_config_and_disconnect_closes_connection_on_cursor_error(
    monkeypatch,
) -> None:
    created_configs = []

    class FakePooledDB:
        def __init__(self, **kwargs):
            created_configs.append(kwargs["database"])

    fake_dbutils = type(
        "FakeDBUtilsMod",
        (),
        {"PooledDB": FakePooledDB},
    )
    monkeypatch.setitem(__import__("sys").modules, "dbutils.pooled_db", fake_dbutils)
    monkeypatch.setattr(akshare_provider, "_connection_pools", {})

    pool_a = akshare_provider._get_connection_pool(
        {
            "host": "h",
            "port": 3306,
            "user": "u",
            "password": "p",
            "database": "db_a",
            "charset": "utf8mb4",
            "autocommit": False,
        }
    )
    pool_b = akshare_provider._get_connection_pool(
        {
            "host": "h",
            "port": 3306,
            "user": "u",
            "password": "p",
            "database": "db_b",
            "charset": "utf8mb4",
            "autocommit": False,
        }
    )
    pool_a2 = akshare_provider._get_connection_pool(
        {
            "host": "h",
            "port": 3306,
            "user": "u",
            "password": "p",
            "database": "db_a",
            "charset": "utf8mb4",
            "autocommit": False,
        }
    )
    assert pool_a is pool_a2
    assert pool_a is not pool_b
    assert created_configs == ["db_a", "db_b"]

    provider = AkshareProvider("mysql://u:p@h/db_a")
    cursor = FakeCursor()
    conn = FakeConnection(cursor)
    cursor.close = lambda: (_ for _ in ()).throw(RuntimeError("cursor close boom"))
    provider.cursor = cursor
    provider.connection = conn
    with pytest.raises(RuntimeError, match="cursor close boom"):
        provider.disconnect_db()
    assert conn.closed is True
    assert provider.connection is None
