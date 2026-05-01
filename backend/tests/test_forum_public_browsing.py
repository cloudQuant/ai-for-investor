from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1.forum import get_thread, list_categories, list_threads
from app.models.forum import ForumCategory, ForumReply, ForumThread
from app.models.user import User


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


class FakeSequenceSession:
    def __init__(self, results: list[FakeScalarResult]) -> None:
        self.results = results
        self.statements: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> FakeScalarResult:
        self.statements.append(statement)
        if self.results:
            return self.results.pop(0)
        return FakeScalarResult()

    async def commit(self) -> None:
        self.commits += 1


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/forum/threads",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-forum"
    return request


def make_category(category_id: int = 1, slug: str = "ai-research") -> ForumCategory:
    return ForumCategory(
        id=category_id,
        name="AI Research",
        slug=slug,
        description="AI research discussions",
        icon="sparkles",
        sort_order=1,
        is_active=True,
        thread_count=3,
    )


def make_thread(status: str = "normal") -> ForumThread:
    author = User(id=10, email="reader@example.com", username="reader", password_hash="hash")
    category = make_category()
    now = datetime.now(timezone.utc)
    thread = ForumThread(
        id=100,
        title="How to evaluate AI research demos?",
        content="Discussion content",
        author_id=author.id,
        category_id=category.id,
        status=status,
        is_pinned=True,
        is_featured=False,
        is_locked=False,
        view_count=9,
        reply_count=2,
        like_count=1,
        last_replied_at=now,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    thread.author = author
    thread.category = category
    return thread


def make_reply() -> ForumReply:
    author = User(id=11, email="reply@example.com", username="reply_user", password_hash="hash")
    now = datetime.now(timezone.utc)
    reply = ForumReply(
        id=200,
        content="Useful discussion",
        author_id=author.id,
        thread_id=100,
        status="normal",
        like_count=0,
        created_at=now,
        updated_at=now,
    )
    reply.author = author
    return reply


@pytest.mark.asyncio
async def test_public_categories_are_listed_without_authentication() -> None:
    category = make_category()
    response = await list_categories(make_request(), FakeSequenceSession([FakeScalarResult(values=[category])]))

    assert response["request_id"] == "req-forum"
    assert response["data"][0].slug == "ai-research"
    assert response["data"][0].thread_count == 3


@pytest.mark.asyncio
async def test_public_threads_support_category_slug_pagination_and_sorting() -> None:
    thread = make_thread()
    session = FakeSequenceSession([FakeScalarResult(1), FakeScalarResult(values=[thread])])
    response = await list_threads(
        make_request(),
        session,
        page=2,
        page_size=10,
        category_id=None,
        category="ai-research",
        sort="latest",
        search=None,
    )

    compiled_query = str(session.statements[-1].compile(compile_kwargs={"literal_binds": True}))
    assert response["pagination"] == {"page": 2, "page_size": 10, "total": 1}
    assert response["data"][0]["category_slug"] == "ai-research"
    assert "forum_categories.slug = 'ai-research'" in compiled_query
    assert "OFFSET 10" in compiled_query


@pytest.mark.asyncio
async def test_public_thread_detail_is_readable_and_increments_view_count() -> None:
    thread = make_thread()
    reply = make_reply()
    session = FakeSequenceSession([FakeScalarResult(thread), FakeScalarResult(values=[reply])])
    response = await get_thread(100, make_request(), session)

    assert response["data"]["thread"]["id"] == 100
    assert response["data"]["thread"]["category_slug"] == "ai-research"
    assert response["data"]["replies"][0]["author_username"] == "reply_user"
    assert thread.view_count == 10
    assert session.commits == 1


@pytest.mark.asyncio
async def test_public_thread_detail_hides_moderated_or_deleted_threads() -> None:
    for status in ["hidden", "deleted", "spam"]:
        with pytest.raises(HTTPException) as exc:
            await get_thread(100, make_request(), FakeSequenceSession([FakeScalarResult(make_thread(status=status))]))

        assert exc.value.status_code == 404
        assert exc.value.detail == "Thread not found"
