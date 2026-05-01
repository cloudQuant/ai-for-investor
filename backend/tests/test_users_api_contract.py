from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.v1 import users
from app.models.blog import BlogPost
from app.models.forum import ForumReply, ForumThread
from app.models.user import Role, User
from app.schemas.user import UserUpdate


class FakeScalarResult:
    def __init__(self, value: Any = None, values: list[Any] | None = None) -> None:
        self.value = value
        self.values = values or []

    def scalar_one_or_none(self) -> Any:
        return self.value

    def scalars(self) -> "FakeScalarResult":
        return self

    def all(self) -> list[Any]:
        return self.values


class FakeSession:
    def __init__(self, results: list[FakeScalarResult] | None = None) -> None:
        self.results = results or []
        self.commits = 0
        self.refreshed: Any = None

    async def execute(self, statement: Any) -> FakeScalarResult:
        if self.results:
            return self.results.pop(0)
        return FakeScalarResult()

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        self.refreshed = obj


def make_request(request_id: str = "req-users") -> Any:
    return type("Request", (), {"state": type("State", (), {"request_id": request_id})()})()


def make_user() -> User:
    user = User(
        id=7,
        email="user@example.com",
        username="user",
        password_hash="hash",
        avatar_url=None,
        bio="hello",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    user.roles = [Role(id=1, name="user")]
    return user


@pytest.mark.asyncio
async def test_users_me_returns_authenticated_profile() -> None:
    user = make_user()

    response = await users.get_current_user_profile(user)

    assert response["id"] == 7
    assert response["email"] == "user@example.com"
    assert response["roles"] == ["user"]


@pytest.mark.asyncio
async def test_users_me_update_persists_profile_changes() -> None:
    user = make_user()
    session = FakeSession()

    response = await users.update_current_user(UserUpdate(avatar_url="https://example.com/avatar.png", bio="updated"), user, session)

    assert response["avatar_url"] == "https://example.com/avatar.png"
    assert response["bio"] == "updated"
    assert user.updated_at is not None
    assert session.commits == 1
    assert session.refreshed is user


@pytest.mark.asyncio
async def test_users_me_update_rejects_duplicate_username() -> None:
    user = make_user()
    existing = User(id=8, email="other@example.com", username="taken", password_hash="hash", is_active=True)
    session = FakeSession([FakeScalarResult(existing)])

    with pytest.raises(HTTPException) as exc:
        await users.update_current_user(UserUpdate(username="taken"), user, session)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Username already taken"


@pytest.mark.asyncio
async def test_user_posts_return_public_posts() -> None:
    now = datetime.now(timezone.utc)
    post = BlogPost(id=1, title="Published", slug="published", summary="summary", content="content", author_id=7, status="published", published_at=now, created_at=now)
    session = FakeSession([FakeScalarResult(values=[post])])

    response = await users.get_user_posts(7, make_request(), session)

    assert response["request_id"] == "req-users"
    assert response["posts"] == [{"id": 1, "title": "Published", "slug": "published", "summary": "summary", "status": "published", "published_at": now, "created_at": now}]


@pytest.mark.asyncio
async def test_user_threads_return_public_threads() -> None:
    now = datetime.now(timezone.utc)
    thread = ForumThread(id=3, title="Thread", content="content", author_id=7, category_id=2, status="normal", is_locked=False, reply_count=4, last_replied_at=now, created_at=now)
    session = FakeSession([FakeScalarResult(values=[thread])])

    response = await users.get_user_threads(7, make_request(), session)

    assert response["threads"] == [{"id": 3, "title": "Thread", "category_id": 2, "status": "normal", "is_locked": False, "reply_count": 4, "last_replied_at": now, "created_at": now}]


@pytest.mark.asyncio
async def test_user_replies_return_public_replies() -> None:
    now = datetime.now(timezone.utc)
    reply = ForumReply(id=5, content="Reply", author_id=7, thread_id=3, status="normal", created_at=now, updated_at=now)
    session = FakeSession([FakeScalarResult(values=[reply])])

    response = await users.get_user_replies(7, make_request(), session)

    assert response["replies"] == [{"id": 5, "thread_id": 3, "content": "Reply", "status": "normal", "created_at": now, "updated_at": now}]
