from datetime import datetime, timezone
import re
from html import escape
from email.utils import format_datetime

import bleach
import markdown
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
import structlog

from app.core.config import settings
from app.db.mysql import get_db
from app.api.v1.auth import get_current_user
from app.core.rbac import require_content_user
from app.models.blog import BlogPost, Category, Tag
from app.models.user import User
from app.schemas.blog import BlogPostCreate, BlogPostUpdate
from app.schemas.blog import CategoryResponse, TagResponse

router = APIRouter()
logger = structlog.get_logger()
MARKDOWN_ALLOWED_TAGS = [
    "a",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
]
MARKDOWN_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel", "target"],
    "code": ["class"],
    "th": ["align"],
    "td": ["align"],
}
MARKDOWN_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


@router.get("/posts")
async def list_posts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None, min_length=1, max_length=100),
    tag: str | None = Query(None, min_length=1, max_length=50),
    q: str | None = Query(None, min_length=1, max_length=100),
):
    request_id = getattr(request.state, "request_id", None)
    base_filter = [BlogPost.status == "published", BlogPost.deleted_at.is_(None), BlogPost.published_at.is_not(None)]
    query_filters = list(base_filter)

    if category:
        query_filters.append(Category.slug == category)
    if tag:
        query_filters.append(Tag.slug == tag)
    if q:
        keyword = f"%{q.strip().lower()}%"
        query_filters.append(
            or_(
                func.lower(BlogPost.title).like(keyword),
                func.lower(BlogPost.summary).like(keyword),
                func.lower(BlogPost.content).like(keyword),
            )
        )

    query = (
        select(BlogPost)
        .options(selectinload(BlogPost.author), selectinload(BlogPost.category), selectinload(BlogPost.tags))
        .outerjoin(BlogPost.category)
        .outerjoin(BlogPost.tags)
        .where(*query_filters)
        .distinct()
        .order_by(BlogPost.is_pinned.desc(), BlogPost.published_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    count_query = (
        select(func.count(func.distinct(BlogPost.id)))
        .outerjoin(BlogPost.category)
        .outerjoin(BlogPost.tags)
        .where(*query_filters)
    )

    total_result = await db.execute(count_query)
    total = total_result.scalar()
    result = await db.execute(query)
    posts = result.scalars().all()

    return {
        "data": [_post_to_list_response(post) for post in posts],
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "request_id": request_id,
    }


@router.get("/posts/{slug}")
async def get_post(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    result = await db.execute(
        select(BlogPost)
        .options(selectinload(BlogPost.author), selectinload(BlogPost.category), selectinload(BlogPost.tags))
        .where(
            BlogPost.slug == slug,
            BlogPost.status == "published",
            BlogPost.deleted_at.is_(None),
            BlogPost.published_at.is_not(None),
        )
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    post.view_count += 1
    await db.commit()
    return {"data": _post_to_detail_response(post), "request_id": request_id}


@router.get("/rss.xml")
async def get_rss_feed(request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    posts = await _published_posts_for_feeds(db)
    feed_url = f"{_site_url()}/api/v1/blog/rss.xml"
    items = "\n".join(_rss_item(post) for post in posts)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "<channel>\n"
        "<title>AI For Investor Blog</title>\n"
        f"<link>{_site_url()}/blog</link>\n"
        "<description>AI交易与投资开源项目精选、实践教程、工具体验与社区讨论平台</description>\n"
        f"<atom:link href=\"{feed_url}\" rel=\"self\" type=\"application/rss+xml\" xmlns:atom=\"http://www.w3.org/2005/Atom\" />\n"
        f"{items}\n"
        "</channel>\n"
        "</rss>"
    )
    response = Response(content=xml, media_type="application/rss+xml")
    response.headers["X-Request-ID"] = request_id or ""
    return response


@router.get("/sitemap.xml")
async def get_sitemap(request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    posts = await _published_posts_for_feeds(db)
    urls = "\n".join(_sitemap_url(post) for post in posts)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>"
    )
    response = Response(content=xml, media_type="application/xml")
    response.headers["X-Request-ID"] = request_id or ""
    return response


@router.post("/posts")
async def create_post(
    request: Request,
    data: BlogPostCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request_id = getattr(request.state, "request_id", None)
    require_content_user(current_user)
    slug = await _unique_slug(db, data.title)
    post = BlogPost(
        title=data.title,
        slug=slug,
        summary=data.summary,
        content=data.content,
        cover_image_url=data.cover_image_url,
        author_id=current_user.id,
        category_id=data.category_id,
        status="draft",
    )
    if data.tag_ids:
        tags = await _load_tags(db, data.tag_ids)
        post.tags = tags
    db.add(post)
    await db.commit()
    await db.refresh(post)
    post = await _get_manageable_post(db, post.id)
    logger.info("blog_post_created", user_id=current_user.id, post_id=post.id, request_id=request_id)
    return {"data": _post_to_detail_response(post), "request_id": request_id}


@router.put("/posts/{post_id}")
async def update_post(
    post_id: int,
    request: Request,
    data: BlogPostUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request_id = getattr(request.state, "request_id", None)
    require_content_user(current_user)
    post = await _get_manageable_post(db, post_id)
    update_data = data.model_dump(exclude_unset=True)
    tag_ids = update_data.pop("tag_ids", None)
    status = update_data.pop("status", None)
    for field, value in update_data.items():
        setattr(post, field, value)
    if tag_ids is not None:
        post.tags = await _load_tags(db, tag_ids)
    if status:
        _set_post_status(post, status)
    await db.commit()
    await db.refresh(post)
    post = await _get_manageable_post(db, post.id)
    logger.info("blog_post_updated", user_id=current_user.id, post_id=post.id, request_id=request_id)
    return {"data": _post_to_detail_response(post), "request_id": request_id}


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request_id = getattr(request.state, "request_id", None)
    require_content_user(current_user)
    post = await _get_manageable_post(db, post_id)
    post.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("blog_post_deleted", user_id=current_user.id, post_id=post.id, request_id=request_id)
    return {"data": {"message": "Post deleted"}, "request_id": request_id}


@router.get("/manage/posts")
async def list_manage_posts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    request_id = getattr(request.state, "request_id", None)
    require_content_user(current_user)
    query = (
        select(BlogPost)
        .options(selectinload(BlogPost.author), selectinload(BlogPost.category), selectinload(BlogPost.tags))
        .where(BlogPost.deleted_at.is_(None))
        .order_by(BlogPost.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    total_result = await db.execute(select(func.count(BlogPost.id)).where(BlogPost.deleted_at.is_(None)))
    total = total_result.scalar()
    result = await db.execute(query)
    posts = result.scalars().all()
    return {
        "data": [_post_to_list_response(post) for post in posts],
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "request_id": request_id,
    }


@router.get("/manage/posts/{post_id}/preview")
async def preview_post(
    post_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request_id = getattr(request.state, "request_id", None)
    require_content_user(current_user)
    post = await _get_manageable_post(db, post_id)
    return {"data": _post_to_detail_response(post), "request_id": request_id}


@router.post("/manage/posts/{post_id}/publish")
async def publish_post(
    post_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request_id = getattr(request.state, "request_id", None)
    require_content_user(current_user)
    post = await _get_manageable_post(db, post_id)
    _set_post_status(post, "published")
    await db.commit()
    await db.refresh(post)
    post = await _get_manageable_post(db, post.id)
    logger.info("blog_post_published", user_id=current_user.id, post_id=post.id, request_id=request_id)
    return {"data": _post_to_detail_response(post), "request_id": request_id}


@router.post("/manage/posts/{post_id}/unpublish")
async def unpublish_post(
    post_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request_id = getattr(request.state, "request_id", None)
    require_content_user(current_user)
    post = await _get_manageable_post(db, post_id)
    _set_post_status(post, "draft")
    await db.commit()
    await db.refresh(post)
    post = await _get_manageable_post(db, post.id)
    logger.info("blog_post_unpublished", user_id=current_user.id, post_id=post.id, request_id=request_id)
    return {"data": _post_to_detail_response(post), "request_id": request_id}


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category).where(Category.is_active == True).order_by(Category.sort_order))
    categories = result.scalars().all()
    return {"data": [CategoryResponse.model_validate(category) for category in categories]}


@router.get("/tags")
async def list_tags(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tag).order_by(Tag.name))
    tags = result.scalars().all()
    return {"data": [TagResponse.model_validate(tag) for tag in tags]}


def _tag_response(tag: Tag) -> dict:
    return {"id": tag.id, "name": tag.name, "slug": tag.slug, "color": tag.color}


def _post_to_list_response(post: BlogPost) -> dict:
    return {
        "id": post.id,
        "title": post.title,
        "slug": post.slug,
        "summary": post.summary,
        "author_username": post.author.username if post.author else "",
        "author_avatar": post.author.avatar_url if post.author else None,
        "category_name": post.category.name if post.category else None,
        "status": post.status,
        "view_count": post.view_count,
        "like_count": post.like_count,
        "published_at": post.published_at,
        "created_at": post.created_at,
        "tags": [_tag_response(tag) for tag in post.tags],
    }


def _post_to_detail_response(post: BlogPost) -> dict:
    response = _post_to_list_response(post)
    canonical_url = _post_url(post)
    response.update(
        {
            "content": post.content,
            "rendered_content": render_markdown_content(post.content),
            "cover_image_url": post.cover_image_url,
            "author_id": post.author_id,
            "category_id": post.category_id,
            "is_pinned": post.is_pinned,
            "canonical_url": canonical_url,
            "open_graph": _open_graph_metadata(post, canonical_url),
            "structured_data": _article_structured_data(post, canonical_url),
        }
    )
    return response


def _site_url() -> str:
    return settings.SITE_URL.rstrip("/")


def _post_url(post: BlogPost) -> str:
    return f"{_site_url()}/blog/{post.slug}"


def _open_graph_metadata(post: BlogPost, canonical_url: str) -> dict:
    return {
        "type": "article",
        "title": post.title,
        "description": post.summary or "",
        "url": canonical_url,
        "image": post.cover_image_url,
        "published_time": post.published_at.isoformat() if post.published_at else None,
        "author": post.author.username if post.author else "",
        "tags": [tag.name for tag in post.tags],
    }


def _article_structured_data(post: BlogPost, canonical_url: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post.title,
        "description": post.summary or "",
        "url": canonical_url,
        "datePublished": post.published_at.isoformat() if post.published_at else None,
        "dateModified": post.updated_at.isoformat() if post.updated_at else None,
        "author": {"@type": "Person", "name": post.author.username if post.author else ""},
        "publisher": {"@type": "Organization", "name": "AI For Investor"},
        "image": post.cover_image_url,
        "articleSection": post.category.name if post.category else None,
        "keywords": [tag.name for tag in post.tags],
    }


async def _published_posts_for_feeds(db: AsyncSession) -> list[BlogPost]:
    result = await db.execute(
        select(BlogPost)
        .options(selectinload(BlogPost.author), selectinload(BlogPost.category), selectinload(BlogPost.tags))
        .where(BlogPost.status == "published", BlogPost.deleted_at.is_(None), BlogPost.published_at.is_not(None))
        .order_by(BlogPost.published_at.desc())
        .limit(100)
    )
    return result.scalars().all()


def _rss_item(post: BlogPost) -> str:
    url = _post_url(post)
    pub_date = format_datetime(post.published_at or post.created_at, usegmt=True)
    return (
        "<item>\n"
        f"<title>{escape(post.title)}</title>\n"
        f"<link>{escape(url)}</link>\n"
        f"<guid>{escape(url)}</guid>\n"
        f"<description>{escape(post.summary or '')}</description>\n"
        f"<pubDate>{pub_date}</pubDate>\n"
        "</item>"
    )


def _sitemap_url(post: BlogPost) -> str:
    lastmod = (post.published_at or post.created_at).date().isoformat()
    return (
        "<url>\n"
        f"<loc>{escape(_post_url(post))}</loc>\n"
        f"<lastmod>{lastmod}</lastmod>\n"
        "</url>"
    )


def render_markdown_content(content: str) -> str:
    html = markdown.markdown(content or "", extensions=["extra", "sane_lists"])
    clean_html = bleach.clean(
        html,
        tags=MARKDOWN_ALLOWED_TAGS,
        attributes=MARKDOWN_ALLOWED_ATTRIBUTES,
        protocols=MARKDOWN_ALLOWED_PROTOCOLS,
        strip=True,
    )
    return re.sub(
        r'<a href="(https?://[^"]+)"([^>]*)>',
        r'<a href="\1" rel="noopener noreferrer" target="_blank"\2>',
        clean_html,
    )


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    return slug or "post"


async def _unique_slug(db: AsyncSession, title: str) -> str:
    base_slug = _slugify(title)
    slug = base_slug
    index = 2
    while True:
        result = await db.execute(select(BlogPost).where(BlogPost.slug == slug))
        if result.scalar_one_or_none() is None:
            return slug
        slug = f"{base_slug}-{index}"
        index += 1


async def _load_tags(db: AsyncSession, tag_ids: list[int]) -> list[Tag]:
    result = await db.execute(select(Tag).where(Tag.id.in_(tag_ids)))
    tags = result.scalars().all()
    if len(tags) != len(set(tag_ids)):
        raise HTTPException(status_code=400, detail="Invalid tag_ids")
    return tags


async def _get_manageable_post(db: AsyncSession, post_id: int) -> BlogPost:
    result = await db.execute(
        select(BlogPost)
        .options(selectinload(BlogPost.author), selectinload(BlogPost.category), selectinload(BlogPost.tags))
        .where(BlogPost.id == post_id, BlogPost.deleted_at.is_(None))
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


def _set_post_status(post: BlogPost, status: str) -> None:
    if status not in {"draft", "published", "archived"}:
        raise HTTPException(status_code=400, detail="Invalid status")
    post.status = status
    if status == "published" and post.published_at is None:
        post.published_at = datetime.now(timezone.utc)
