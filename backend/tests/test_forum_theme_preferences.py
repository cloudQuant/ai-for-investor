from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1 import preferences
from app.models.preference import UserPreference
from app.models.user import User
from app.schemas.preference import UserPreferenceUpdate


class FakeScalarResult:
    def __init__(self, value: Any = None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value


class FakeSession:
    def __init__(self, results: list[FakeScalarResult]) -> None:
        self.results = results
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> FakeScalarResult:
        if self.results:
            return self.results.pop(0)
        return FakeScalarResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/api/v1/preferences/me/preferences",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-theme"
    return request


def make_user(user_id: int = 7) -> User:
    return User(
        id=user_id,
        email=f"user{user_id}@example.com",
        username=f"user{user_id}",
        password_hash="hash",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )


def patch_current_user(monkeypatch, user: User | None) -> None:
    async def fake_get_current_user(request: Request, db: FakeSession) -> User | None:
        return user

    monkeypatch.setattr(preferences, "get_current_user", fake_get_current_user)


@pytest.mark.asyncio
async def test_visitor_preferences_return_default_forum_theme(monkeypatch) -> None:
    patch_current_user(monkeypatch, None)

    response = await preferences.get_preferences(make_request(), FakeSession([]))

    assert response["data"]["ui_theme"] == "fintech-trust-light"


@pytest.mark.asyncio
async def test_authenticated_user_can_persist_supported_forum_theme(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(7))
    pref = UserPreference(id=1, user_id=7, ui_theme="fintech-trust-light", system_theme_sync=0)
    db = FakeSession([FakeScalarResult(pref)])

    response = await preferences.update_preferences(
        make_request(),
        UserPreferenceUpdate(ui_theme="terminal-agent-dark"),
        db,
    )

    assert pref.ui_theme == "terminal-agent-dark"
    assert db.commits == 1
    assert response["data"]["ui_theme"] == "terminal-agent-dark"


@pytest.mark.asyncio
async def test_authenticated_user_preference_rejects_unknown_forum_theme(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(7))

    with pytest.raises(HTTPException) as error:
        await preferences.update_preferences(
            make_request(),
            UserPreferenceUpdate(ui_theme="unknown-theme"),
            FakeSession([]),
        )

    assert error.value.status_code == 400
