from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from app.db.mysql import get_db
from app.core.rbac import require_content_user
from app.models.discovery import OpenSourceProject, DiscoveryKeyword, ProjectScore, WeeklyReportCandidate
from app.schemas.discovery import DiscoveryKeywordCreate, ProjectReviewUpdate, WeeklyReportCandidateCreate, WeeklyReportCandidateUpdate
from app.services.github_discovery import collect_github_projects
from app.services.project_scoring import calculate_project_score

router = APIRouter()
REVIEW_STATUSES = {"new", "reviewed", "selected", "ignored"}
CANDIDATE_STATUSES = {"nominated", "shortlisted", "selected", "rejected"}


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):
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
            from app.models.user import User
            result = await db.execute(select(User).where(User.id == int(user_id)))
            return result.scalar_one_or_none()
    except Exception:
        pass
    return None


def serialize_keyword(keyword: DiscoveryKeyword) -> dict:
    return {
        "id": keyword.id,
        "keyword": keyword.keyword,
        "is_active": keyword.is_active,
        "created_at": keyword.created_at,
        "updated_at": keyword.updated_at,
    }


def serialize_project(project: OpenSourceProject) -> dict:
    return {
        "id": project.id,
        "repo_full_name": project.repo_full_name,
        "repo_url": project.repo_url,
        "description": project.description,
        "stars": project.stars,
        "language": project.language,
        "license": project.license,
        "overall_score": project.overall_score,
        "status": project.status,
    }


def serialize_project_detail(project: OpenSourceProject) -> dict:
    return {
        **serialize_project(project),
        "forks": project.forks,
        "topics": project.topics or [],
        "readme_summary": project.readme_summary,
        "score_note": project.risk_note or "Editorial score is provided for research context only, not as a recommendation.",
        "latest_commit_at": project.latest_commit_at,
        "latest_release_at": project.latest_release_at,
        "risk_note": project.risk_note or "Research-only project. Not investment advice, not a return guarantee, and not a trading recommendation.",
    }


def serialize_candidate(candidate: WeeklyReportCandidate) -> dict:
    project = getattr(candidate, "project", None)
    return {
        "id": candidate.id,
        "project_id": candidate.project_id,
        "week_number": candidate.week_number,
        "year": candidate.year,
        "notes": candidate.notes,
        "rationale": candidate.rationale,
        "editorial_notes": candidate.editorial_notes,
        "status": candidate.status,
        "is_selected": candidate.is_selected,
        "created_at": candidate.created_at,
        "repo_full_name": project.repo_full_name if project else None,
        "repo_url": project.repo_url if project else None,
        "license": project.license if project else None,
        "security_score": project.score_security if project else None,
        "risk_note": project.risk_note if project else None,
    }


@router.get("/projects")
async def list_projects(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query("selected"),
    q: str | None = Query(None),
    language: str | None = Query(None),
):
    request_id = getattr(request.state, "request_id", None)
    status = "selected"
    page = page if isinstance(page, int) else 1
    page_size = page_size if isinstance(page_size, int) else 20

    query = select(OpenSourceProject).where(OpenSourceProject.status == status)
    count_query = select(func.count(OpenSourceProject.id)).where(OpenSourceProject.status == status)
    if q:
        search_filter = or_(
            OpenSourceProject.repo_full_name.ilike(f"%{q}%"),
            OpenSourceProject.description.ilike(f"%{q}%"),
            OpenSourceProject.readme_summary.ilike(f"%{q}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
    if language:
        query = query.where(OpenSourceProject.language == language)
        count_query = count_query.where(OpenSourceProject.language == language)

    query = query.order_by(OpenSourceProject.overall_score.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    result = await db.execute(query)
    projects = result.scalars().all()

    return {
        "data": [serialize_project(p) for p in projects if p.status == "selected"],
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "request_id": request_id,
    }


@router.get("/projects/{repo_full_name}")
async def get_project(repo_full_name: str, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)

    result = await db.execute(select(OpenSourceProject).where(OpenSourceProject.repo_full_name == repo_full_name))
    project = result.scalar_one_or_none()
    if not project:
        return {"data": None, "request_id": request_id}

    return {"data": {"id": project.id, "repo_full_name": project.repo_full_name, "repo_url": project.repo_url, "description": project.description, "stars": project.stars, "forks": project.forks, "language": project.language, "license": project.license, "topics": project.topics, "overall_score": project.overall_score, "status": project.status, "risk_note": project.risk_note}, "request_id": request_id}


@router.get("/projects/id/{project_id}")
async def get_project_detail(project_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    result = await db.execute(select(OpenSourceProject).where(OpenSourceProject.id == project_id))
    project = result.scalar_one_or_none()
    if not project or project.status != "selected":
        return {"data": None, "request_id": request_id}
    return {"data": serialize_project_detail(project), "request_id": request_id}


@router.get("/discovery/keywords")
async def list_discovery_keywords(request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_content_user(current_user)

    result = await db.execute(select(DiscoveryKeyword).order_by(DiscoveryKeyword.created_at.desc()))
    keywords = result.scalars().all()
    return {"data": [serialize_keyword(keyword) for keyword in keywords], "request_id": request_id}


@router.post("/discovery/keywords")
async def create_discovery_keyword(
    request: Request,
    data: DiscoveryKeywordCreate,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_content_user(current_user)

    keyword = DiscoveryKeyword(keyword=data.keyword.strip(), is_active=True)
    db.add(keyword)
    await db.commit()
    await db.refresh(keyword)
    return {"data": serialize_keyword(keyword), "request_id": request_id}


@router.post("/discovery/collect")
async def run_discovery_collection(request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_content_user(current_user)

    result = await collect_github_projects(db, actor_id=current_user.id, request_id=request_id)
    return {"data": result, "request_id": request_id}


@router.post("/weekly-report/candidates")
async def create_weekly_report_candidate(
    request: Request,
    data: WeeklyReportCandidateCreate,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_content_user(current_user)

    result = await db.execute(select(OpenSourceProject).where(OpenSourceProject.id == data.project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status != "selected":
        raise HTTPException(status_code=400, detail="Only selected projects can be added to weekly candidates")

    candidate = WeeklyReportCandidate(
        project_id=project.id,
        added_by_id=current_user.id,
        week_number=data.week_number,
        year=data.year,
        notes=data.notes,
        rationale=data.rationale,
        editorial_notes=data.editorial_notes,
        status="nominated",
        is_selected=False,
    )
    candidate.project = project
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)
    return {"data": serialize_candidate(candidate), "request_id": request_id}


@router.get("/weekly-report/candidates")
async def list_weekly_report_candidates(
    request: Request,
    db: AsyncSession = Depends(get_db),
    week_number: int | None = Query(None),
    year: int | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_content_user(current_user)
    page = page if isinstance(page, int) else 1
    page_size = page_size if isinstance(page_size, int) else 20

    query = select(WeeklyReportCandidate)
    count_query = select(func.count(WeeklyReportCandidate.id))
    if week_number is not None:
        query = query.where(WeeklyReportCandidate.week_number == week_number)
        count_query = count_query.where(WeeklyReportCandidate.week_number == week_number)
    if year is not None:
        query = query.where(WeeklyReportCandidate.year == year)
        count_query = count_query.where(WeeklyReportCandidate.year == year)
    if status is not None:
        query = query.where(WeeklyReportCandidate.status == status)
        count_query = count_query.where(WeeklyReportCandidate.status == status)

    query = query.order_by(WeeklyReportCandidate.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    result = await db.execute(query)
    candidates = result.scalars().all()

    return {
        "data": [serialize_candidate(candidate) for candidate in candidates],
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "request_id": request_id,
    }


@router.patch("/weekly-report/candidates/{candidate_id}")
async def update_weekly_report_candidate(
    candidate_id: int,
    request: Request,
    data: WeeklyReportCandidateUpdate,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_content_user(current_user)

    result = await db.execute(select(WeeklyReportCandidate).where(WeeklyReportCandidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if data.status is not None and data.status not in CANDIDATE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid candidate status")

    if data.notes is not None:
        candidate.notes = data.notes
    if data.rationale is not None:
        candidate.rationale = data.rationale
    if data.editorial_notes is not None:
        candidate.editorial_notes = data.editorial_notes
    if data.status is not None:
        candidate.status = data.status
    if data.is_selected is not None:
        candidate.is_selected = data.is_selected

    await db.commit()
    return {"data": serialize_candidate(candidate), "request_id": request_id}


@router.get("/weekly-report/assemble")
async def assemble_weekly_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    week_number: int = Query(...),
    year: int = Query(...),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_content_user(current_user)

    result = await db.execute(
        select(WeeklyReportCandidate).where(
            WeeklyReportCandidate.week_number == week_number,
            WeeklyReportCandidate.year == year,
            WeeklyReportCandidate.status == "selected",
            WeeklyReportCandidate.is_selected.is_(True),
        )
    )
    candidates = result.scalars().all()
    projects = []
    for candidate in candidates:
        project = getattr(candidate, "project", None)
        if not project:
            continue
        projects.append(
            {
                "candidate_id": candidate.id,
                "project_id": project.id,
                "repo_full_name": project.repo_full_name,
                "repo_url": project.repo_url,
                "description": project.description,
                "license": project.license,
                "security_score": project.score_security,
                "rationale": candidate.rationale,
                "editorial_notes": candidate.editorial_notes,
                "risk_note": project.risk_note,
            }
        )

    return {
        "data": {
            "week_number": week_number,
            "year": year,
            "candidate_count": len(projects),
            "projects": projects,
            "disclaimer": "Weekly report candidates are for education and research only, not investment advice or a return guarantee.",
        },
        "request_id": request_id,
    }


@router.patch("/projects/{project_id}/review")
async def review_project(
    project_id: int,
    request: Request,
    data: ProjectReviewUpdate,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_content_user(current_user)

    result = await db.execute(select(OpenSourceProject).where(OpenSourceProject.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if data.status is not None and data.status not in REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid review status")

    automatic_score = calculate_project_score(project)
    criteria = automatic_score["criteria"]
    score = ProjectScore(
        project_id=project.id,
        scorer_id=current_user.id,
        score_relevance=data.score_relevance if data.score_relevance is not None else criteria["relevance"],
        score_activity=data.score_activity if data.score_activity is not None else criteria["activity"],
        score_influence=data.score_influence if data.score_influence is not None else criteria["stars"],
        score_reproducibility=data.score_reproducibility if data.score_reproducibility is not None else criteria["documentation"],
        score_security=data.score_security if data.score_security is not None else criteria["license"],
        overall_score=data.overall_score if data.overall_score is not None else automatic_score["overall_score"],
        note=data.note,
    )
    db.add(score)

    project.score_relevance = score.score_relevance
    project.score_activity = score.score_activity
    project.score_influence = score.score_influence
    project.score_reproducibility = score.score_reproducibility
    project.score_security = score.score_security
    project.overall_score = score.overall_score
    if data.status is not None:
        project.status = data.status
    if data.risk_note is not None:
        project.risk_note = data.risk_note

    await db.commit()

    return {
        "data": {
            **serialize_project(project),
            "score_note": score.note,
            "score_criteria": criteria,
            "editorial_aid_only": True,
            "disclaimer": automatic_score["disclaimer"],
        },
        "request_id": request_id,
    }
