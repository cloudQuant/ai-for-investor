from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta, timezone
import bleach
import structlog

from app.db.mysql import get_db
from app.models.forum import ForumThread, ForumReply, ForumReport, ForumCategory
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.forum import (
    ForumCategoryResponse, ForumThreadCreate, ForumThreadUpdate,
    ForumThreadResponse, ForumThreadDetailResponse,
    ForumReplyCreate, ForumReplyUpdate, ForumReplyResponse,
    ForumReportCreate, ForumReportResponse, ForumReportStatusUpdate,
)
from app.core.rbac import require_moderator_user

router = APIRouter()
logger = structlog.get_logger()


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User | None:
    from jose import jwt
    from app.core.config import settings

    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None

    token = auth.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if user_id:
            result = await db.execute(select(User).where(User.id == int(user_id)))
            return result.scalar_one_or_none()
    except Exception:
        pass
    return None


def require_verified(user: User | None):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not user.email_verified_at:
        raise HTTPException(status_code=403, detail="Email verification required")


def sanitize_forum_content(value: str) -> str:
    return bleach.clean(value or "", tags=[], attributes={}, strip=True).strip()


def require_non_empty_content(value: str, field_name: str) -> str:
    cleaned = sanitize_forum_content(value)
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty")
    return cleaned


async def enforce_posting_cooldown(db: AsyncSession, user: User, model: type[ForumThread] | type[ForumReply]) -> None:
    now = datetime.now(timezone.utc)
    created_at = user.created_at
    if created_at and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if not created_at or now - created_at > timedelta(days=1):
        return
    since = now - timedelta(minutes=10)
    result = await db.execute(select(func.count(model.id)).where(model.author_id == user.id, model.created_at >= since))
    if result.scalar() >= 3:
        raise HTTPException(status_code=429, detail="Posting cooldown active")


def add_audit_log(request: Request, db: AsyncSession, user: User, action: str, resource_type: str, resource_id: int | None, changes: dict) -> None:
    db.add(AuditLog(
        actor_id=user.id,
        actor_ip=request.client.host if request.client else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        changes=changes,
        request_id=getattr(request.state, "request_id", None),
        user_agent=request.headers.get("user-agent"),
    ))


async def get_moderated_thread(db: AsyncSession, thread_id: int) -> ForumThread:
    result = await db.execute(select(ForumThread).where(ForumThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


def _thread_to_response(thread: ForumThread, author: User) -> dict:
    return {
        "id": thread.id,
        "title": thread.title,
        "content": thread.content,
        "category_id": thread.category_id,
        "category_name": thread.category.name if thread.category else None,
        "category_slug": thread.category.slug if thread.category else None,
        "author_id": thread.author_id,
        "author_username": author.username if author else "",
        "author_avatar": author.avatar_url if author else None,
        "status": thread.status,
        "is_pinned": thread.is_pinned,
        "is_featured": thread.is_featured,
        "is_locked": thread.is_locked,
        "view_count": thread.view_count,
        "reply_count": thread.reply_count,
        "like_count": thread.like_count,
        "last_replied_at": thread.last_replied_at,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
    }


def _reply_to_response(reply: ForumReply, author: User) -> dict:
    return {
        "id": reply.id,
        "content": reply.content,
        "author_id": reply.author_id,
        "author_username": author.username if author else "",
        "author_avatar": author.avatar_url if author else None,
        "thread_id": reply.thread_id,
        "status": reply.status,
        "like_count": reply.like_count,
        "created_at": reply.created_at,
        "updated_at": reply.updated_at,
    }


@router.get("/categories")
async def list_categories(request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    result = await db.execute(select(ForumCategory).where(ForumCategory.is_active == True).order_by(ForumCategory.sort_order))
    categories = result.scalars().all()
    return {"data": [ForumCategoryResponse.model_validate(c) for c in categories], "request_id": request_id}


@router.get("/threads")
async def list_threads(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category_id: int = None,
    category: str = None,
    sort: str = Query("latest", pattern="^(latest|newest|popular)$"),
    search: str = None,
):
    request_id = getattr(request.state, "request_id", None)

    query = (
        select(ForumThread)
        .options(selectinload(ForumThread.author), selectinload(ForumThread.category))
        .outerjoin(ForumThread.category)
        .where(ForumThread.status == "normal", ForumThread.deleted_at.is_(None))
    )
    count_query = (
        select(func.count(ForumThread.id))
        .outerjoin(ForumThread.category)
        .where(ForumThread.status == "normal", ForumThread.deleted_at.is_(None))
    )

    if category_id:
        query = query.where(ForumThread.category_id == category_id)
        count_query = count_query.where(ForumThread.category_id == category_id)
    if category:
        query = query.where(ForumCategory.slug == category)
        count_query = count_query.where(ForumCategory.slug == category)

    if search:
        search_filter = or_(
            ForumThread.title.ilike(f"%{search}%"),
            ForumThread.content.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    if sort == "newest":
        query = query.order_by(ForumThread.is_pinned.desc(), ForumThread.created_at.desc())
    elif sort == "popular":
        query = query.order_by(ForumThread.is_pinned.desc(), ForumThread.reply_count.desc(), ForumThread.view_count.desc())
    else:
        query = query.order_by(ForumThread.is_pinned.desc(), ForumThread.last_replied_at.desc().nullslast(), ForumThread.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    result = await db.execute(query)
    threads = result.scalars().all()

    return {
        "data": [_thread_to_response(t, t.author) for t in threads],
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "request_id": request_id,
    }


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)

    result = await db.execute(
        select(ForumThread)
        .options(selectinload(ForumThread.author), selectinload(ForumThread.category))
        .where(ForumThread.id == thread_id)
    )
    thread = result.scalar_one_or_none()
    if not thread or thread.status != "normal" or thread.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Thread not found")

    thread.view_count += 1
    await db.commit()

    replies_result = await db.execute(
        select(ForumReply)
        .options(selectinload(ForumReply.author))
        .where(ForumReply.thread_id == thread_id, ForumReply.status == "normal")
        .order_by(ForumReply.created_at)
    )
    replies = replies_result.scalars().all()

    return {
        "data": {
            "thread": _thread_to_response(thread, thread.author),
            "replies": [_reply_to_response(r, r.author) for r in replies],
        },
        "request_id": request_id,
    }


@router.post("/threads")
async def create_thread(
    request: Request,
    data: ForumThreadCreate,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_verified(current_user)
    await enforce_posting_cooldown(db, current_user, ForumThread)

    category_result = await db.execute(select(ForumCategory).where(ForumCategory.id == data.category_id, ForumCategory.is_active == True))
    category = category_result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=400, detail="Invalid category")

    title = require_non_empty_content(data.title, "Title")
    content = require_non_empty_content(data.content, "Content")

    thread = ForumThread(
        title=title,
        content=content,
        author_id=current_user.id,
        category_id=data.category_id,
    )
    thread.author = current_user
    thread.category = category
    db.add(thread)
    await db.commit()
    await db.refresh(thread)

    return {"data": _thread_to_response(thread, current_user), "request_id": request_id}


@router.patch("/threads/{thread_id}")
async def update_thread(
    thread_id: int,
    request: Request,
    data: ForumThreadUpdate,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_verified(current_user)

    result = await db.execute(select(ForumThread).where(ForumThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    if thread.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if data.title is not None:
        thread.title = require_non_empty_content(data.title, "Title")
    if data.content is not None:
        thread.content = require_non_empty_content(data.content, "Content")

    thread.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(thread)
    logger.info("forum_thread_updated", thread_id=thread.id, author_id=current_user.id, request_id=request_id)

    return {"data": _thread_to_response(thread, current_user), "request_id": request_id}


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_verified(current_user)

    result = await db.execute(select(ForumThread).where(ForumThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    if thread.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    thread.status = "deleted"
    thread.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("forum_thread_deleted", thread_id=thread.id, author_id=current_user.id, request_id=request_id)

    return {"data": {"message": "Thread deleted"}, "request_id": request_id}


@router.post("/threads/{thread_id}/replies")
async def create_reply(
    thread_id: int,
    request: Request,
    data: ForumReplyCreate,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_verified(current_user)
    await enforce_posting_cooldown(db, current_user, ForumReply)

    thread_result = await db.execute(select(ForumThread).where(ForumThread.id == thread_id))
    thread = thread_result.scalar_one_or_none()
    if not thread or thread.status != "normal" or thread.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if thread.is_locked:
        raise HTTPException(status_code=403, detail="Thread is locked")

    content = require_non_empty_content(data.content, "Content")
    reply = ForumReply(
        content=content,
        author_id=current_user.id,
        thread_id=thread_id,
    )
    reply.author = current_user
    db.add(reply)

    thread.reply_count += 1
    thread.last_replied_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(reply)

    return {"data": _reply_to_response(reply, current_user), "request_id": request_id}


@router.patch("/replies/{reply_id}")
async def update_reply(
    reply_id: int,
    request: Request,
    data: ForumReplyUpdate,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_verified(current_user)

    result = await db.execute(select(ForumReply).where(ForumReply.id == reply_id))
    reply = result.scalar_one_or_none()
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")

    if reply.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    reply.content = require_non_empty_content(data.content, "Content")
    reply.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(reply)
    logger.info("forum_reply_updated", reply_id=reply.id, author_id=current_user.id, request_id=request_id)

    return {"data": _reply_to_response(reply, current_user), "request_id": request_id}


@router.delete("/replies/{reply_id}")
async def delete_reply(reply_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_verified(current_user)

    result = await db.execute(select(ForumReply).where(ForumReply.id == reply_id))
    reply = result.scalar_one_or_none()
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")

    if reply.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    reply.status = "deleted"
    reply.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("forum_reply_deleted", reply_id=reply.id, author_id=current_user.id, request_id=request_id)

    return {"data": {"message": "Reply deleted"}, "request_id": request_id}


@router.post("/threads/{thread_id}/pin")
async def pin_thread(thread_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_moderator_user(current_user)

    thread = await get_moderated_thread(db, thread_id)
    previous = thread.is_pinned

    thread.is_pinned = not thread.is_pinned
    add_audit_log(request, db, current_user, "forum_thread_pin_toggled", "forum_thread", thread.id, {"from": previous, "to": thread.is_pinned})
    await db.commit()
    logger.info("forum_thread_pin_toggled", thread_id=thread.id, moderator_id=current_user.id, is_pinned=thread.is_pinned, request_id=request_id)

    return {"data": {"is_pinned": thread.is_pinned}, "request_id": request_id}


@router.post("/threads/{thread_id}/lock")
async def lock_thread(thread_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_moderator_user(current_user)

    thread = await get_moderated_thread(db, thread_id)
    previous = thread.is_locked

    thread.is_locked = not thread.is_locked
    add_audit_log(request, db, current_user, "forum_thread_lock_toggled", "forum_thread", thread.id, {"from": previous, "to": thread.is_locked})
    await db.commit()
    logger.info("forum_thread_lock_toggled", thread_id=thread.id, moderator_id=current_user.id, is_locked=thread.is_locked, request_id=request_id)

    return {"data": {"is_locked": thread.is_locked}, "request_id": request_id}


@router.post("/threads/{thread_id}/feature")
async def feature_thread(thread_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_moderator_user(current_user)

    thread = await get_moderated_thread(db, thread_id)
    previous = thread.is_featured

    thread.is_featured = not thread.is_featured
    add_audit_log(request, db, current_user, "forum_thread_feature_toggled", "forum_thread", thread.id, {"from": previous, "to": thread.is_featured})
    await db.commit()
    logger.info("forum_thread_feature_toggled", thread_id=thread.id, moderator_id=current_user.id, is_featured=thread.is_featured, request_id=request_id)

    return {"data": {"is_featured": thread.is_featured}, "request_id": request_id}


@router.post("/threads/{thread_id}/hide")
async def hide_thread(thread_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_moderator_user(current_user)

    thread = await get_moderated_thread(db, thread_id)
    previous = thread.status

    thread.status = "hidden" if thread.status == "normal" else "normal"
    add_audit_log(request, db, current_user, "forum_thread_hide_toggled", "forum_thread", thread.id, {"from": previous, "to": thread.status})
    await db.commit()
    logger.info("forum_thread_hide_toggled", thread_id=thread.id, moderator_id=current_user.id, status=thread.status, request_id=request_id)

    return {"data": {"status": thread.status}, "request_id": request_id}


@router.post("/reports")
async def create_report(request: Request, data: ForumReportCreate, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_verified(current_user)

    if bool(data.thread_id) == bool(data.reply_id):
        raise HTTPException(status_code=400, detail="Report exactly one thread or reply")

    if data.thread_id:
        result = await db.execute(select(ForumThread).where(ForumThread.id == data.thread_id, ForumThread.deleted_at.is_(None)))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Thread not found")
    if data.reply_id:
        result = await db.execute(select(ForumReply).where(ForumReply.id == data.reply_id, ForumReply.deleted_at.is_(None)))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Reply not found")

    report = ForumReport(
        reporter_id=current_user.id,
        thread_id=data.thread_id,
        reply_id=data.reply_id,
        reason=data.reason,
        description=data.description,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    logger.info("forum_report_created", report_id=report.id, reporter_id=current_user.id, thread_id=data.thread_id, reply_id=data.reply_id, request_id=request_id)

    return {"data": ForumReportResponse.model_validate(report), "request_id": request_id}


@router.get("/reports")
async def list_reports(
    request: Request,
    status: str | None = Query(default=None, pattern="^(pending|reviewing|resolved|rejected)$"),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_moderator_user(current_user)

    statement = select(ForumReport).order_by(ForumReport.created_at.desc())
    if status:
        statement = statement.where(ForumReport.status == status)
    result = await db.execute(statement)
    reports = result.scalars().all()

    return {"data": [ForumReportResponse.model_validate(report) for report in reports], "request_id": request_id}


@router.patch("/reports/{report_id}")
async def update_report_status(
    report_id: int,
    request: Request,
    data: ForumReportStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_moderator_user(current_user)

    result = await db.execute(select(ForumReport).where(ForumReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    previous_status = report.status
    report.status = data.status
    report.handler_note = data.handler_note
    report.handler_id = current_user.id
    report.handled_at = datetime.now(timezone.utc)
    add_audit_log(request, db, current_user, "forum_report_status_updated", "forum_report", report.id, {"from": previous_status, "to": report.status})
    await db.commit()
    await db.refresh(report)
    logger.info("forum_report_status_updated", report_id=report.id, moderator_id=current_user.id, status=report.status, request_id=request_id)

    return {"data": ForumReportResponse.model_validate(report), "request_id": request_id}
