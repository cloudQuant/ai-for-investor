from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1 import forum
from app.models.forum import ForumCategory, ForumReply, ForumThread
from app.models.user import User
from app.schemas.forum import ForumReplyCreate, ForumThreadCreate


class FakeScalarResult:
    def __init__(self, value: Any = None, values: list[Any] | None = None) -> None:
        self.value = value
        self.values = values or []

    def scalar(self) -> Any:
        return self.value

    def scalar_one_or_none(self) -> Any:
        return self.value

    def scalars(self) -> "FakeScalarResult":
        return self

    def all(self) -> list[Any]:
        return self.values


class FakeSession:
    def __init__(self, results: list[FakeScalarResult] | None = None) -> None:
        self.results = results or []
        self.added: list[Any] = []
        self.commits = 0
        self.refreshed: Any = None
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> FakeScalarResult:
        self.statements.append(statement)
        if self.results:
            return self.results.pop(0)
        return FakeScalarResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        self.refreshed = obj
        if getattr(obj, "id", None) is None:
            obj.id = 1000
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime.now(timezone.utc)


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/forum/threads",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-write"
    return request


def verified_user(created_at: datetime | None = None) -> User:
    now = datetime.now(timezone.utc)
    return User(
        id=7,
        email="verified@example.com",
        username="verified",
        password_hash="hash",
        is_active=True,
        email_verified_at=now,
        created_at=created_at or now - timedelta(days=3),
    )


def patch_current_user(monkeypatch, user: User) -> None:
    async def fake_get_current_user(request: Request, db: FakeSession) -> User:
        return user

    monkeypatch.setattr(forum, "get_current_user", fake_get_current_user)


def make_category() -> ForumCategory:
    return ForumCategory(id=1, name="AI Research", slug="ai-research", is_active=True, thread_count=0)


def make_thread(is_locked: bool = False, status: str = "normal") -> ForumThread:
    author = verified_user()
    category = make_category()
    now = datetime.now(timezone.utc)
    thread = ForumThread(
        id=10,
        title="Existing thread",
        content="Existing content",
        author_id=author.id,
        category_id=category.id,
        status=status,
        is_locked=is_locked,
        is_pinned=False,
        is_featured=False,
        view_count=0,
        reply_count=0,
        like_count=0,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    thread.author = author
    thread.category = category
    return thread


@pytest.mark.asyncio
async def test_verified_user_can_create_sanitized_thread(monkeypatch) -> None:
    user = verified_user()
    patch_current_user(monkeypatch, user)
    session = FakeSession(results=[FakeScalarResult(make_category())])

    response = await forum.create_thread(
        make_request(),
        ForumThreadCreate(title="  <b>Research demo</b>  ", content="Hello <script>alert(1)</script> world", category_id=1),
        session,
    )

    created = session.added[0]
    assert created.title == "Research demo"
    assert created.content == "Hello alert(1) world"
    assert created.author_id == user.id
    assert response["data"]["title"] == "Research demo"


@pytest.mark.asyncio
async def test_unverified_user_cannot_create_thread(monkeypatch) -> None:
    user = verified_user()
    user.email_verified_at = None
    patch_current_user(monkeypatch, user)

    with pytest.raises(HTTPException) as exc:
        await forum.create_thread(make_request(), ForumThreadCreate(title="Title", content="Content", category_id=1), FakeSession())

    assert exc.value.status_code == 403
    assert exc.value.detail == "Email verification required"


@pytest.mark.asyncio
async def test_new_user_thread_cooldown_is_enforced(monkeypatch) -> None:
    user = verified_user(created_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    patch_current_user(monkeypatch, user)
    session = FakeSession(results=[FakeScalarResult(3), FakeScalarResult(make_category())])

    with pytest.raises(HTTPException) as exc:
        await forum.create_thread(make_request(), ForumThreadCreate(title="Title", content="Content", category_id=1), session)

    assert exc.value.status_code == 429
    assert exc.value.detail == "Posting cooldown active"


@pytest.mark.asyncio
async def test_verified_user_can_create_sanitized_reply(monkeypatch) -> None:
    user = verified_user()
    patch_current_user(monkeypatch, user)
    thread = make_thread()
    session = FakeSession(results=[FakeScalarResult(thread)])

    response = await forum.create_reply(10, make_request(), ForumReplyCreate(content="Reply <img src=x onerror=alert(1)> text"), session)

    reply = session.added[0]
    assert reply.content == "Reply  text"
    assert reply.author_id == user.id
    assert thread.reply_count == 1
    assert response["data"]["content"] == "Reply  text"


@pytest.mark.asyncio
async def test_locked_thread_rejects_new_replies(monkeypatch) -> None:
    user = verified_user()
    patch_current_user(monkeypatch, user)

    with pytest.raises(HTTPException) as exc:
        await forum.create_reply(10, make_request(), ForumReplyCreate(content="Reply"), FakeSession(results=[FakeScalarResult(make_thread(is_locked=True))]))

    assert exc.value.status_code == 403
    assert exc.value.detail == "Thread is locked"
