import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.v1 import admin
from app.core.rbac import bootstrap_initial_admin, require_admin_user, require_moderator_user
from app.core.security import verify_password
from app.models.user import Role, User, UserRoleEnum


class FakeScalarResult:
    def __init__(self, value: Any = None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value

    def scalar(self) -> Any:
        return self.value

    def scalars(self) -> "FakeScalarResult":
        return self

    def all(self) -> list[Any]:
        return []


class FakeSession:
    def __init__(self, existing_admin: User | None = None, existing_user: User | None = None, admin_role: Role | None = None) -> None:
        self.existing_admin = existing_admin
        self.existing_user = existing_user
        self.admin_role = admin_role
        self.execute_calls = 0
        self.added: list[Any] = []
        self.commits = 0
        self.refreshed: Any = None

    async def execute(self, statement: Any) -> FakeScalarResult:
        self.execute_calls += 1
        if self.execute_calls == 1:
            return FakeScalarResult(self.existing_admin)
        if self.execute_calls == 2:
            return FakeScalarResult(self.existing_user)
        if self.execute_calls == 3:
            return FakeScalarResult(self.admin_role)
        return FakeScalarResult(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        self.refreshed = obj
        obj.id = 123


def user_with_roles(*role_names: str, active: bool = True) -> User:
    user = User(id=123, email="user@example.com", username="user", password_hash="hash", is_active=active)
    user.roles = [Role(id=index + 1, name=role_name) for index, role_name in enumerate(role_names)]
    return user


def test_role_enum_includes_required_concepts() -> None:
    assert {role.value for role in UserRoleEnum} == {"guest", "user", "author", "editor", "moderator", "admin"}


def test_admin_guard_accepts_admin_role() -> None:
    require_admin_user(user_with_roles("admin"))


def test_admin_guard_rejects_missing_user_with_401() -> None:
    with pytest.raises(HTTPException) as exc:
        require_admin_user(None)

    assert exc.value.status_code == 401
    assert exc.value.detail == "Authentication required"


def test_admin_guard_rejects_non_admin_with_403() -> None:
    with pytest.raises(HTTPException) as exc:
        require_admin_user(user_with_roles("user"))

    assert exc.value.status_code == 403
    assert exc.value.detail == "Insufficient role"


def test_moderator_guard_accepts_moderator_and_admin_roles() -> None:
    require_moderator_user(user_with_roles("moderator"))
    require_moderator_user(user_with_roles("admin"))


def test_admin_bootstrap_creates_verified_active_admin_with_hashed_password() -> None:
    session = FakeSession(admin_role=Role(id=1, name="admin"))

    admin_user = asyncio.run(bootstrap_initial_admin(session, "admin@example.com", "admin", "Password1"))

    assert admin_user.id == 123
    assert admin_user.email == "admin@example.com"
    assert admin_user.username == "admin"
    assert admin_user.is_active is True
    assert admin_user.email_verified_at is not None
    assert verify_password("Password1", admin_user.password_hash) is True
    assert [role.name for role in admin_user.roles] == ["admin"]
    assert session.commits == 1
    assert session.refreshed is admin_user


def test_admin_bootstrap_refuses_second_admin() -> None:
    session = FakeSession(existing_admin=user_with_roles("admin"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(bootstrap_initial_admin(session, "admin2@example.com", "admin2", "Password1"))

    assert exc.value.status_code == 409
    assert exc.value.detail == "Administrator already exists"


def test_admin_sensitive_action_logs_audit_event(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeLogger:
        def info(self, event: str, **kwargs: Any) -> None:
            events.append((event, kwargs))

    monkeypatch.setattr(admin, "logger", FakeLogger())
    request = type("Request", (), {"state": type("State", (), {"request_id": "req-1"})()})()
    session = FakeSession()
    user = user_with_roles("admin")

    async def fake_get_current_user(request: Any, db: Any) -> User:
        return user

    monkeypatch.setattr(admin, "get_current_user", fake_get_current_user)

    asyncio.run(admin.admin_dashboard(request, session))

    assert events == [("admin_dashboard_accessed", {"user_id": 123, "request_id": "req-1"})]
