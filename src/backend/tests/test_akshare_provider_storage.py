from collections.abc import Sequence

import pytest

from app.data_fetch.providers import akshare_provider
from app.data_fetch.providers.akshare_provider import AkshareProvider


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
