"""Regression coverage for database-backed administrator identity."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import database as database_module
from app.db.database import async_session_maker, create_default_admin
from app.models.permission import Role, user_roles
from app.models.user import User
from app.utils.security import get_password_hash


@pytest.mark.asyncio
async def test_same_name_account_requires_current_database_admin_role(
    client: AsyncClient,
) -> None:
    """Legacy name ownership never implies admin and role removal affects old tokens."""
    settings = get_settings()
    legacy_password = "LegacyPass12345"
    legacy_hash = get_password_hash(legacy_password)
    async with async_session_maker() as session:
        legacy_user = User(
            username=settings.ADMIN_USERNAME,
            email="legacy-admin-name@example.test",
            hashed_password=legacy_hash,
            is_active=True,
        )
        session.add(legacy_user)
        await session.commit()
        legacy_user_id = legacy_user.id

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.ADMIN_USERNAME, "password": legacy_password},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    with pytest.raises(RuntimeError, match="no ADMIN role"):
        await create_default_admin()

    me = await client.get("/api/v1/auth/me", headers=headers)
    governance = await client.get("/api/v1/data-governance/providers", headers=headers)
    quant_tool = await client.post(
        "/api/v1/quant-tools/call",
        headers=headers,
        json={"tool_name": "data_topics.peek", "input": {"topic": "market:quote:RB2510"}},
    )
    audit = await client.get("/api/v1/audit/records", headers=headers)

    assert me.status_code == 200
    assert me.json()["is_admin"] is False
    assert governance.status_code == 403
    assert quant_tool.status_code == 403
    assert audit.status_code == 403

    async with async_session_maker() as session:
        stored_user = await session.get(User, legacy_user_id)
        assert stored_user is not None
        assert stored_user.hashed_password == legacy_hash
        roles = (
            (
                await session.execute(
                    select(user_roles.c.role).where(user_roles.c.user_id == legacy_user_id)
                )
            )
            .scalars()
            .all()
        )
        assert Role.ADMIN.value not in roles

        await session.execute(
            user_roles.insert().values(user_id=legacy_user_id, role=Role.ADMIN.value)
        )
        await session.commit()

    # Existing access tokens resolve role changes at request time.
    governance_after_grant = await client.get("/api/v1/data-governance/providers", headers=headers)
    assert governance_after_grant.status_code == 200
    assert (
        await client.post(
            "/api/v1/quant-tools/call",
            headers=headers,
            json={"tool_name": "data_topics.peek", "input": {"topic": "market:quote:RB2510"}},
        )
    ).status_code == 200
    assert (await client.get("/api/v1/audit/records", headers=headers)).status_code == 200

    async with async_session_maker() as session:
        await session.execute(
            user_roles.delete().where(
                user_roles.c.user_id == legacy_user_id,
                user_roles.c.role == Role.ADMIN.value,
            )
        )
        await session.commit()

    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["is_admin"] is False
    governance_after_revoke = await client.get("/api/v1/data-governance/providers", headers=headers)
    assert governance_after_revoke.status_code == 403
    assert (
        await client.post(
            "/api/v1/quant-tools/call",
            headers=headers,
            json={"tool_name": "data_topics.peek", "input": {"topic": "market:quote:RB2510"}},
        )
    ).status_code == 403
    assert (await client.get("/api/v1/audit/records", headers=headers)).status_code == 403

    # Re-running bootstrap after revocation cannot restore the role by name.
    with pytest.raises(RuntimeError, match="no ADMIN role"):
        await create_default_admin()


class _FakeResult:
    def __init__(
        self,
        rows: list[object] | None = None,
        scalar: object | None = None,
    ) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[object]:
        return self._rows

    def scalar_one_or_none(self) -> object | None:
        return self._scalar


class _FakeBootstrapSession:
    def __init__(
        self,
        *,
        rows: list[object] | None = None,
        role: object | None = None,
        flush_error: Exception | None = None,
    ) -> None:
        self._rows = rows
        self._role = role
        self._flush_error = flush_error
        self._execute_count = 0
        self.added: list[object] = []
        self.commits = 0

    async def __aenter__(self) -> _FakeBootstrapSession:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return False

    async def execute(self, statement: object) -> _FakeResult:
        del statement
        self._execute_count += 1
        if self._execute_count == 1:
            return _FakeResult(rows=self._rows or [])
        return _FakeResult(scalar=self._role)

    def add(self, entity: object) -> None:
        self.added.append(entity)

    async def flush(self) -> None:
        if self._flush_error is not None:
            raise self._flush_error

    async def commit(self) -> None:
        self.commits += 1


def _bootstrap_settings() -> SimpleNamespace:
    return SimpleNamespace(
        ADMIN_USERNAME="admin",
        ADMIN_EMAIL="admin@example.test",
        ADMIN_PASSWORD="StrongBootstrapPass123",
    )


@pytest.mark.asyncio
async def test_bootstrap_rejects_database_collation_alias(monkeypatch) -> None:
    """A MySQL collation match with different spelling is never adopted."""
    existing_user = SimpleNamespace(id="legacy-id", username="Admin")
    session = _FakeBootstrapSession(rows=[existing_user])
    monkeypatch.setattr(database_module, "get_settings", _bootstrap_settings)
    monkeypatch.setattr(database_module, "async_session_maker", lambda: session)

    with pytest.raises(RuntimeError, match="differently spelled"):
        await create_default_admin()

    assert session._execute_count == 1
    assert session.added == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_bootstrap_rejects_case_equivalent_existing_username_in_sqlite(
    monkeypatch,
) -> None:
    """SQLite's binary comparison cannot hide a reserved-name case alias."""
    existing_user = User(
        username="Admin",
        email="case-alias@example.test",
        hashed_password=get_password_hash("LegacyPass12345"),
        is_active=True,
    )
    async with async_session_maker() as session:
        session.add(existing_user)
        await session.commit()
        existing_user_id = existing_user.id

    monkeypatch.setattr(database_module, "get_settings", _bootstrap_settings)
    with pytest.raises(RuntimeError, match="equivalent to the configured name"):
        await create_default_admin()

    async with async_session_maker() as session:
        stored_user = await session.get(User, existing_user_id)
        assert stored_user is not None
        roles = (
            (
                await session.execute(
                    select(user_roles.c.role).where(user_roles.c.user_id == existing_user_id)
                )
            )
            .scalars()
            .all()
        )
        assert Role.ADMIN.value not in roles


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("concurrent_role", "should_succeed"),
    [(Role.ADMIN.value, True), (None, False)],
)
async def test_bootstrap_unique_key_race_only_accepts_admin_winner(
    monkeypatch, concurrent_role: str | None, should_succeed: bool
) -> None:
    """A fresh transaction distinguishes concurrent bootstrap from signup."""
    from app.utils import security

    existing_user = SimpleNamespace(id="winner-id", username="admin")
    failed_insert = _FakeBootstrapSession(
        flush_error=IntegrityError("insert", {}, RuntimeError("duplicate"))
    )
    retry = _FakeBootstrapSession(rows=[existing_user], role=concurrent_role)
    sessions = iter((failed_insert, retry))
    monkeypatch.setattr(database_module, "get_settings", _bootstrap_settings)
    monkeypatch.setattr(database_module, "async_session_maker", lambda: next(sessions))
    monkeypatch.setattr(security, "get_password_hash", lambda _password: "hashed")

    if should_succeed:
        await create_default_admin()
    else:
        with pytest.raises(RuntimeError, match="no ADMIN role"):
            await create_default_admin()

    assert failed_insert.added
    assert failed_insert.commits == 0
    assert retry._execute_count == 2
    assert retry.added == []
    assert retry.commits == 0
