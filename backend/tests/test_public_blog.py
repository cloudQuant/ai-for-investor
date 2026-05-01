from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1.blog import get_post, get_rss_feed, get_sitemap, list_posts, render_markdown_content
from app.models.blog import BlogPost, Category, Tag
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


class FakeSession:
    def __init__(self, posts: list[BlogPost] | None = None, post: BlogPost | None = None) -> None:
        self.posts = posts or []
        self.post = post
        self.execute_calls = 0
        self.commits = 0
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> FakeScalarResult:
        self.execute_calls += 1
        self.statements.append(statement)
        if self.execute_calls == 1 and self.posts:
            return FakeScalarResult(len(self.posts))
        if self.posts:
            return FakeScalarResult(values=self.posts)
        return FakeScalarResult(self.post)

    async def commit(self) -> None:
        self.commits += 1


class FakeFeedSession:
    def __init__(self, posts: list[BlogPost]) -> None:
        self.posts = posts

    async def execute(self, statement: Any) -> FakeScalarResult:
        return FakeScalarResult(values=self.posts)


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/blog/posts",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-1"
    return request


def make_post(status: str = "published", deleted: bool = False, published: bool = True) -> BlogPost:
    author = User(id=1, email="author@example.com", username="author", password_hash="hash")
    category = Category(id=1, name="AI Investing", slug="ai-investing")
    tag = Tag(id=1, name="LLM", slug="llm", color="#3b82f6")
    now = datetime.now(timezone.utc)
    post = BlogPost(
        id=10,
        title="Published insight",
        slug="published-insight",
        summary="Summary",
        content="Content",
        cover_image_url="https://example.com/cover.png",
        author_id=author.id,
        category_id=category.id,
        status=status,
        view_count=7,
        like_count=2,
        is_pinned=False,
        published_at=now if published else None,
        created_at=now,
        deleted_at=now if deleted else None,
    )
    post.author = author
    post.category = category
    post.tags = [tag]
    return post


@pytest.mark.asyncio
async def test_public_blog_list_returns_published_post_shape() -> None:
    post = make_post()
    response = await list_posts(
        make_request(),
        FakeSession(posts=[post]),
        page=1,
        page_size=20,
        category=None,
        tag=None,
        q=None,
    )

    assert response["request_id"] == "req-1"
    assert response["pagination"] == {"page": 1, "page_size": 20, "total": 1}
    assert response["data"] == [
        {
            "id": 10,
            "title": "Published insight",
            "slug": "published-insight",
            "summary": "Summary",
            "author_username": "author",
            "author_avatar": None,
            "category_name": "AI Investing",
            "status": "published",
            "view_count": 7,
            "like_count": 2,
            "published_at": post.published_at,
            "created_at": post.created_at,
            "tags": [{"id": 1, "name": "LLM", "slug": "llm", "color": "#3b82f6"}],
        }
    ]


@pytest.mark.asyncio
async def test_public_blog_list_accepts_category_tag_and_search_filters() -> None:
    post = make_post()
    session = FakeSession(posts=[post])
    response = await list_posts(
        make_request(),
        session,
        page=1,
        page_size=20,
        category="ai-investing",
        tag="llm",
        q="risk",
    )

    compiled_query = str(session.statements[-1].compile(compile_kwargs={"literal_binds": True}))
    assert response["data"][0]["slug"] == "published-insight"
    assert "categories.slug = 'ai-investing'" in compiled_query
    assert "tags.slug = 'llm'" in compiled_query
    assert "lower(blog_posts.title)" in compiled_query
    assert "lower(blog_posts.summary)" in compiled_query
    assert "lower(blog_posts.content)" in compiled_query


@pytest.mark.asyncio
async def test_public_blog_detail_returns_content_and_increments_view_count() -> None:
    post = make_post()
    response = await get_post("published-insight", make_request(), FakeSession(post=post))

    assert response["data"]["slug"] == "published-insight"
    assert response["data"]["content"] == "Content"
    assert response["data"]["rendered_content"] == "<p>Content</p>"
    assert response["data"]["canonical_url"] == "http://localhost:3000/blog/published-insight"
    assert response["data"]["open_graph"]["type"] == "article"
    assert response["data"]["open_graph"]["url"] == "http://localhost:3000/blog/published-insight"
    assert response["data"]["structured_data"]["@type"] == "Article"
    assert response["data"]["structured_data"]["headline"] == "Published insight"
    assert response["data"]["cover_image_url"] == "https://example.com/cover.png"
    assert response["data"]["author_id"] == 1
    assert response["data"]["category_id"] == 1
    assert post.view_count == 8


@pytest.mark.asyncio
async def test_public_blog_detail_returns_safe_not_found_for_missing_or_non_public_post() -> None:
    with pytest.raises(HTTPException) as exc:
        await get_post("missing", make_request(), FakeSession(post=None))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Post not found"


def test_markdown_renderer_supports_common_article_formatting() -> None:
    rendered = render_markdown_content(
        "# Heading\n\n- Item\n\n[External](https://example.com)\n\n```python\nprint('safe')\n```\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    )

    assert "<h1>Heading</h1>" in rendered
    assert "<li>Item</li>" in rendered
    assert '<a href="https://example.com" rel="noopener noreferrer" target="_blank">External</a>' in rendered
    assert "<code" in rendered
    assert "print" in rendered
    assert "<table>" in rendered


def test_markdown_renderer_sanitizes_unsafe_html_and_urls() -> None:
    rendered = render_markdown_content(
        "# Safe\n\n<script>alert('xss')</script>\n\n<img src=x onerror=alert(1)>\n\n[Bad](javascript:alert(1))"
    )

    assert "<h1>Safe</h1>" in rendered
    assert "<script" not in rendered
    assert "onerror" not in rendered
    assert "javascript:" not in rendered


@pytest.mark.asyncio
async def test_rss_feed_contains_published_posts() -> None:
    post = make_post()
    response = await get_rss_feed(make_request(), FakeFeedSession([post]))
    body = response.body.decode()

    assert response.media_type == "application/rss+xml"
    assert "<rss version=\"2.0\">" in body
    assert "<title>Published insight</title>" in body
    assert "<link>http://localhost:3000/blog/published-insight</link>" in body
    assert "<guid>http://localhost:3000/blog/published-insight</guid>" in body


@pytest.mark.asyncio
async def test_sitemap_contains_published_blog_urls() -> None:
    post = make_post()
    response = await get_sitemap(make_request(), FakeFeedSession([post]))
    body = response.body.decode()

    assert response.media_type == "application/xml"
    assert "<urlset" in body
    assert "<loc>http://localhost:3000/blog/published-insight</loc>" in body
    assert f"<lastmod>{post.published_at.date().isoformat()}</lastmod>" in body
