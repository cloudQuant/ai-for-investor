from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import structlog

from app.db.mysql import get_db
from app.core.rbac import require_admin_user
from app.core.observability import api_snapshot, build_alerts, email_snapshot, worker_snapshot

router = APIRouter()
logger = structlog.get_logger()


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):
    from jose import jwt
    from app.core.config import settings
    from app.models.user import User

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


def require_admin(user):
    require_admin_user(user)


@router.get("/dashboard")
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_admin(current_user)
    logger.info("admin_dashboard_accessed", user_id=current_user.id, request_id=request_id)

    from app.models.user import User
    from app.models.blog import BlogPost
    from app.models.forum import ForumThread
    from app.models.tool import ToolJob

    users_count = await db.execute(select(func.count(User.id)))
    total_users = users_count.scalar()

    posts_count = await db.execute(select(func.count(BlogPost.id)))
    total_posts = posts_count.scalar()

    threads_count = await db.execute(select(func.count(ForumThread.id)))
    total_threads = threads_count.scalar()

    jobs_count = await db.execute(select(func.count(ToolJob.id)))
    total_jobs = jobs_count.scalar()

    return {
        "data": {
            "total_users": total_users,
            "total_posts": total_posts,
            "total_threads": total_threads,
            "total_jobs": total_jobs,
        },
        "request_id": request_id,
    }


@router.get("/users")
async def list_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_admin(current_user)
    logger.info("admin_users_listed", user_id=current_user.id, request_id=request_id)

    from app.models.user import User

    query = select(User).order_by(User.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    total_result = await db.execute(select(func.count(User.id)))
    total = total_result.scalar()

    result = await db.execute(query)
    users = result.scalars().all()

    return {
        "data": [{"id": u.id, "email": u.email, "username": u.username, "is_active": u.is_active, "email_verified_at": u.email_verified_at, "created_at": u.created_at} for u in users],
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "request_id": request_id,
    }


@router.get("/observability")
async def observability_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_admin(current_user)
    logger.info("admin_observability_accessed", user_id=current_user.id, request_id=request_id)

    from app.models.audit import AuditLog
    from app.models.tool import ToolJob, ToolJobStatus

    queued_result = await db.execute(select(func.count(ToolJob.id)).where(ToolJob.status == ToolJobStatus.QUEUED.value))
    queued_jobs = queued_result.scalar() or 0

    running_result = await db.execute(select(func.count(ToolJob.id)).where(ToolJob.status == ToolJobStatus.RUNNING.value))
    running_jobs = running_result.scalar() or 0

    failed_result = await db.execute(select(func.count(ToolJob.id)).where(ToolJob.status.in_([ToolJobStatus.FAILED.value, ToolJobStatus.TIMEOUT.value])))
    failed_jobs = failed_result.scalar() or 0

    total_result = await db.execute(select(func.count(ToolJob.id)))
    total_jobs = total_result.scalar() or 0

    audit_result = await db.execute(select(func.count(AuditLog.id)))
    audit_events = audit_result.scalar() or 0

    api = api_snapshot()
    worker = worker_snapshot(queued_jobs=queued_jobs, running_jobs=running_jobs, failed_jobs=failed_jobs, total_jobs=total_jobs)
    email = email_snapshot()
    database = {"health": "healthy", "slow_query_indicator": "not_configured", "audit_events": audit_events}
    storage = {"health": "healthy", "mysql": "healthy", "mongodb": "healthy", "redis": "healthy"}
    alerts = build_alerts(api, worker, email, database, storage)

    return {
        "data": {
            "api": api,
            "worker": worker,
            "email": email,
            "database": database,
            "storage": storage,
            "alerts": alerts,
        },
        "request_id": request_id,
    }
