from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1.blog import create_post, delete_post, preview_post, publish_post, unpublish_post, update_post
from app.core.rbac import require_content_user
from app.models.blog import BlogPost, Category, Tag
from app.models.user import Role, User
from app.schemas.blog import BlogPostCreate, BlogPostUpdate


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
        self.execute_calls = 0
        self.added: list[Any] = []
        self.commits = 0
        self.refreshed: Any = None

    async def execute(self, statement: Any) -> FakeScalarResult:
        self.execute_calls += 1
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
            obj.id = 100


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/blog/posts",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-blog"
    return request


def user_with_roles(*role_names: str) -> User:
    user = User(id=7, email="author@example.com", username="author", password_hash="hash", is_active=True)
    user.roles = [Role(id=index + 1, name=role_name) for index, role_name in enumerate(role_names)]
    return user


def make_post(status: str = "draft", published_at: datetime | None = None) -> BlogPost:
    author = user_with_roles("author")
    category = Category(id=1, name="AI Investing", slug="ai-investing")
    tag = Tag(id=1, name="LLM", slug="llm")
    now = datetime.now(timezone.utc)
    post = BlogPost(
        id=100,
        title="Draft title",
        slug="draft-title",
        summary="Draft summary",
        content="Draft content",
        author_id=author.id,
        category_id=category.id,
        status=status,
        view_count=0,
        like_count=0,
        is_pinned=False,
        published_at=published_at,
        created_at=now,
        updated_at=now,
    )
    post.author = author
    post.category = category
    post.tags = [tag]
    return post


def test_content_guard_accepts_author_editor_and_admin_roles() -> None:
    require_content_user(user_with_roles("author"))
    require_content_user(user_with_roles("editor"))
    require_content_user(user_with_roles("admin"))


def test_content_guard_rejects_regular_user() -> None:
    with pytest.raises(HTTPException) as exc:
        require_content_user(user_with_roles("user"))

    assert exc.value.status_code == 403
    assert exc.value.detail == "Insufficient role"


@pytest.mark.asyncio
async def test_author_can_create_draft_post_with_generated_slug_and_tags() -> None:
    tag = Tag(id=1, name="LLM", slug="llm")
    reloaded_post = make_post()
    reloaded_post.title = "My First Draft"
    reloaded_post.slug = "my-first-draft"
    reloaded_post.summary = "Summary"
    reloaded_post.content = "Content"
    reloaded_post.tags = [tag]
    session = FakeSession(results=[FakeScalarResult(None), FakeScalarResult(values=[tag]), FakeScalarResult(reloaded_post)])
    response = await create_post(
        make_request(),
        BlogPostCreate(title="My First Draft", summary="Summary", content="Content", category_id=1, tag_ids=[1]),
        session,
        user_with_roles("author"),
    )

    created = session.added[0]
    assert created.slug == "my-first-draft"
    assert created.status == "draft"
    assert created.author_id == 7
    assert created.tags == [tag]
    assert session.commits == 1
    assert response["data"]["id"] == 100
    assert response["data"]["status"] == "draft"


@pytest.mark.asyncio
async def test_author_can_preview_draft_before_publication() -> None:
    post = make_post()
    response = await preview_post(100, make_request(), FakeSession(results=[FakeScalarResult(post)]), user_with_roles("author"))

    assert response["data"]["id"] == 100
    assert response["data"]["status"] == "draft"
    assert response["data"]["content"] == "Draft content"


@pytest.mark.asyncio
async def test_author_can_update_draft_content_and_tags() -> None:
    post = make_post()
    new_tag = Tag(id=2, name="Risk", slug="risk")
    session = FakeSession(results=[FakeScalarResult(post), FakeScalarResult(values=[new_tag]), FakeScalarResult(post)])
    response = await update_post(
        100,
        make_request(),
        BlogPostUpdate(title="Updated title", tag_ids=[2]),
        session,
        user_with_roles("editor"),
    )

    assert post.title == "Updated title"
    assert post.tags == [new_tag]
    assert session.commits == 1
    assert response["data"]["title"] == "Updated title"


@pytest.mark.asyncio
async def test_author_can_publish_and_unpublish_post() -> None:
    post = make_post()
    publish_response = await publish_post(100, make_request(), FakeSession(results=[FakeScalarResult(post), FakeScalarResult(post)]), user_with_roles("author"))

    assert post.status == "published"
    assert post.published_at is not None
    assert publish_response["data"]["status"] == "published"

    unpublish_response = await unpublish_post(100, make_request(), FakeSession(results=[FakeScalarResult(post), FakeScalarResult(post)]), user_with_roles("author"))

    assert post.status == "draft"
    assert post.published_at is not None
    assert unpublish_response["data"]["status"] == "draft"


@pytest.mark.asyncio
async def test_author_can_soft_delete_post() -> None:
    post = make_post()
    response = await delete_post(100, make_request(), FakeSession(results=[FakeScalarResult(post)]), user_with_roles("admin"))

    assert post.deleted_at is not None
    assert response["data"] == {"message": "Post deleted"}


@pytest.mark.asyncio
async def test_regular_user_cannot_manage_posts() -> None:
    with pytest.raises(HTTPException) as exc:
        await preview_post(100, make_request(), FakeSession(results=[FakeScalarResult(make_post())]), user_with_roles("user"))

    assert exc.value.status_code == 403
    assert exc.value.detail == "Insufficient role"
