from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.mysql import get_db
from app.api.v1.auth import get_current_user
from app.models.blog import BlogPost
from app.models.forum import ForumReply, ForumThread
from app.models.user import User
from app.schemas.user import UserResponse, UserDetailResponse, UserUpdate

router = APIRouter()


def _user_detail_response(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "avatar_url": user.avatar_url,
        "bio": user.bio,
        "email_verified_at": user.email_verified_at,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "roles": [role.name for role in user.roles],
    }


def _post_response(post: BlogPost) -> dict:
    return {
        "id": post.id,
        "title": post.title,
        "slug": post.slug,
        "summary": post.summary,
        "status": post.status,
        "published_at": post.published_at,
        "created_at": post.created_at,
    }


def _thread_response(thread: ForumThread) -> dict:
    return {
        "id": thread.id,
        "title": thread.title,
        "category_id": thread.category_id,
        "status": thread.status,
        "is_locked": thread.is_locked,
        "reply_count": thread.reply_count,
        "last_replied_at": thread.last_replied_at,
        "created_at": thread.created_at,
    }


def _reply_response(reply: ForumReply) -> dict:
    return {
        "id": reply.id,
        "thread_id": reply.thread_id,
        "content": reply.content,
        "status": reply.status,
        "created_at": reply.created_at,
        "updated_at": reply.updated_at,
    }


@router.get("/me", response_model=UserDetailResponse)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    """Get current user profile - requires authentication"""
    return _user_detail_response(current_user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_by_id(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get user by ID (public profile)"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/me", response_model=UserDetailResponse)
async def update_current_user(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user profile"""
    if user_update.username is not None and user_update.username != current_user.username:
        existing = await db.execute(select(User).where(User.username == user_update.username, User.id != current_user.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already taken")
        current_user.username = user_update.username
    if user_update.avatar_url is not None:
        current_user.avatar_url = user_update.avatar_url
    if user_update.bio is not None:
        current_user.bio = user_update.bio
    current_user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(current_user)
    return _user_detail_response(current_user)


@router.get("/{user_id}/posts")
async def get_user_posts(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get posts by user"""
    request_id = getattr(request.state, "request_id", None)
    result = await db.execute(
        select(BlogPost)
        .where(
            BlogPost.author_id == user_id,
            BlogPost.status == "published",
            BlogPost.deleted_at.is_(None),
            BlogPost.published_at.is_not(None),
        )
        .order_by(BlogPost.published_at.desc(), BlogPost.created_at.desc())
    )
    return {"posts": [_post_response(post) for post in result.scalars().all()], "request_id": request_id}


@router.get("/{user_id}/threads")
async def get_user_threads(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get forum threads by user"""
    request_id = getattr(request.state, "request_id", None)
    result = await db.execute(
        select(ForumThread)
        .where(ForumThread.author_id == user_id, ForumThread.status == "normal", ForumThread.deleted_at.is_(None))
        .order_by(ForumThread.created_at.desc())
    )
    return {"threads": [_thread_response(thread) for thread in result.scalars().all()], "request_id": request_id}


@router.get("/{user_id}/replies")
async def get_user_replies(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get forum replies by user"""
    request_id = getattr(request.state, "request_id", None)
    result = await db.execute(
        select(ForumReply)
        .options(selectinload(ForumReply.thread))
        .where(ForumReply.author_id == user_id, ForumReply.status == "normal", ForumReply.deleted_at.is_(None))
        .order_by(ForumReply.created_at.desc())
    )
    return {"replies": [_reply_response(reply) for reply in result.scalars().all()], "request_id": request_id}
