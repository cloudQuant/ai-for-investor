from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1 import forum
from app.models.forum import ForumCategory, ForumReply, ForumThread
from app.models.user import User
from app.schemas.forum import ForumReplyUpdate, ForumThreadUpdate


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
    def __init__(self, results: list[FakeScalarResult]) -> None:
        self.results = results
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


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/api/v1/forum/threads/10",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-author"
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


def patch_current_user(monkeypatch, user: User) -> None:
    async def fake_get_current_user(request: Request, db: FakeSession) -> User:
        return user

    monkeypatch.setattr(forum, "get_current_user", fake_get_current_user)


def make_thread(author_id: int = 7, status: str = "normal") -> ForumThread:
    author = make_user(author_id)
    category = ForumCategory(id=1, name="AI Research", slug="ai-research")
    now = datetime.now(timezone.utc)
    thread = ForumThread(
        id=10,
        title="Original title",
        content="Original content",
        author_id=author_id,
        category_id=1,
        status=status,
        is_pinned=False,
        is_featured=False,
        is_locked=False,
        view_count=0,
        reply_count=1,
        like_count=0,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    thread.author = author
    thread.category = category
    return thread


def make_reply(author_id: int = 7, status: str = "normal") -> ForumReply:
    author = make_user(author_id)
    now = datetime.now(timezone.utc)
    reply = ForumReply(
        id=20,
        content="Original reply",
        author_id=author_id,
        thread_id=10,
        status=status,
        like_count=0,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    reply.author = author
    return reply


@pytest.mark.asyncio
async def test_author_can_edit_own_thread_with_sanitized_content(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(7))
    thread = make_thread(author_id=7)
    response = await forum.update_thread(
        10,
        make_request(),
        ForumThreadUpdate(title="<b>Updated</b>", content="Safe <script>alert(1)</script> body"),
        FakeSession([FakeScalarResult(thread)]),
    )

    assert thread.title == "Updated"
    assert thread.content == "Safe alert(1) body"
    assert response["data"]["title"] == "Updated"


@pytest.mark.asyncio
async def test_user_cannot_edit_or_delete_other_users_thread(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(7))

    with pytest.raises(HTTPException) as update_error:
        await forum.update_thread(10, make_request(), ForumThreadUpdate(title="Hack"), FakeSession([FakeScalarResult(make_thread(author_id=8))]))
    with pytest.raises(HTTPException) as delete_error:
        await forum.delete_thread(10, make_request(), FakeSession([FakeScalarResult(make_thread(author_id=8))]))

    assert update_error.value.status_code == 403
    assert delete_error.value.status_code == 403


@pytest.mark.asyncio
async def test_author_can_soft_delete_own_thread(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(7))
    thread = make_thread(author_id=7)
    response = await forum.delete_thread(10, make_request(), FakeSession([FakeScalarResult(thread)]))

    assert thread.status == "deleted"
    assert thread.deleted_at is not None
    assert response["data"]["message"] == "Thread deleted"


@pytest.mark.asyncio
async def test_author_can_edit_and_soft_delete_own_reply(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(7))
    reply = make_reply(author_id=7)
    response = await forum.update_reply(20, make_request(), ForumReplyUpdate(content="Reply <img src=x onerror=alert(1)> updated"), FakeSession([FakeScalarResult(reply)]))
    delete_response = await forum.delete_reply(20, make_request(), FakeSession([FakeScalarResult(reply)]))

    assert reply.content == "Reply  updated"
    assert response["data"]["content"] == "Reply  updated"
    assert reply.status == "deleted"
    assert reply.deleted_at is not None
    assert delete_response["data"]["message"] == "Reply deleted"


@pytest.mark.asyncio
async def test_public_thread_detail_excludes_deleted_replies() -> None:
    thread = make_thread(author_id=7)
    visible_reply = make_reply(author_id=7)
    response = await forum.get_thread(10, make_request(), FakeSession([FakeScalarResult(thread), FakeScalarResult(values=[visible_reply])]))

    assert response["data"]["replies"] == [forum._reply_to_response(visible_reply, visible_reply.author)]
