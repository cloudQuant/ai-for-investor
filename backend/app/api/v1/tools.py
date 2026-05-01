from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
import uuid
import re

from app.db.mysql import get_db
from app.core.rbac import require_admin_user
from app.models.audit import AuditLog
from app.models.tool import Tool, ToolJob, ToolManifest
from app.models.user import User
from app.schemas.tool import (
    ToolConfigCreate,
    ToolConfigUpdate,
    ToolDetailResponse,
    ToolJobCreate,
    ToolJobResponse,
    ToolManifestCreate,
    ToolManifestResponse,
    ToolManifestUpdate,
    ToolResponse,
)

router = APIRouter()
HIGH_RISK_LEVELS = {"high", "extreme"}
SAFE_HIGH_RISK_MODES = {"document", "external"}
SAFE_MANIFEST_MODES = {"container", "document", "external"}
SAFE_NETWORK_MODES = {"none", "allowlist"}
FORBIDDEN_COMMAND_TOKENS = {"bash", "sh", "eval", "exec", "python -c", "node -e", "user_code"}
APPROVED_LICENSE_STATUSES = {"approved", "permissive", "internal_reviewed"}
PASSED_SCAN_STATUSES = {"passed", "not_applicable"}
EXCLUDED_MVP_CAPABILITIES = {"broker_connected", "live_trading", "order_execution", "credential_access"}
MAX_JOB_RESULT_SUMMARY_LENGTH = 1000
SENSITIVE_RESULT_PATTERNS = [
    re.compile(r"(password\s*=\s*)[^\s]+", re.IGNORECASE),
    re.compile(r"(token\s*=\s*)[^\s]+", re.IGNORECASE),
    re.compile(r"(api_key\s*=\s*)[^\s]+", re.IGNORECASE),
]


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
            result = await db.execute(select(User).where(User.id == int(user_id)))
            return result.scalar_one_or_none()
    except Exception:
        pass
    return None


def require_verified(user):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required; please login to run tools")
    if not user.email_verified_at:
        raise HTTPException(status_code=403, detail="Email verification required")


def ensure_public_tool_safety(tool: Tool) -> None:
    if tool.risk_level in HIGH_RISK_LEVELS and tool.run_mode not in SAFE_HIGH_RISK_MODES:
        raise HTTPException(status_code=400, detail="High-risk tools must use document or external mode")


def ensure_tool_job_allowed(tool: Tool) -> None:
    if tool.run_mode != "internal" or tool.risk_level != "low" or tool.config_status != "published":
        raise HTTPException(status_code=403, detail="Tool not approved for user execution")


def validate_job_parameters(tool: Tool, parameters: dict) -> None:
    manifest = getattr(tool, "manifest", None)
    if not manifest or not manifest.parameters_schema:
        raise HTTPException(status_code=400, detail="Tool manifest is required")
    allowed = manifest.parameters_schema.get("allowed", {})
    for key, value in parameters.items():
        if key not in allowed:
            raise HTTPException(status_code=400, detail="Unsupported tool parameter")
        rules = allowed[key]
        expected_type = rules.get("type")
        if expected_type == "string":
            if not isinstance(value, str):
                raise HTTPException(status_code=400, detail="Invalid tool parameter value")
            max_length = rules.get("max_length")
            if max_length is not None and len(value) > max_length:
                raise HTTPException(status_code=400, detail="Invalid tool parameter value")
        if expected_type == "integer":
            if not isinstance(value, int):
                raise HTTPException(status_code=400, detail="Invalid tool parameter value")
            minimum = rules.get("minimum")
            maximum = rules.get("maximum")
            if minimum is not None and value < minimum:
                raise HTTPException(status_code=400, detail="Invalid tool parameter value")
            if maximum is not None and value > maximum:
                raise HTTPException(status_code=400, detail="Invalid tool parameter value")


def sanitize_result_text(value: str | None) -> str | None:
    if value is None:
        return None
    if "traceback" in value.lower():
        return "Tool execution failed"
    sanitized = value
    for pattern in SENSITIVE_RESULT_PATTERNS:
        sanitized = pattern.sub(lambda match: f"{match.group(1)}[redacted]", sanitized)
    if len(sanitized) > MAX_JOB_RESULT_SUMMARY_LENGTH:
        sanitized = sanitized[:MAX_JOB_RESULT_SUMMARY_LENGTH]
    return sanitized


def serialize_tool_job(job: ToolJob) -> dict:
    payload = ToolJobResponse.model_validate(job).model_dump()
    payload["result_summary"] = sanitize_result_text(payload.get("result_summary"))
    payload["error_message"] = sanitize_result_text(payload.get("error_message"))
    return payload


def validate_manifest_boundaries(entrypoint: dict, parameters_schema: dict, resources: dict, network: dict) -> None:
    mode = entrypoint.get("mode")
    if mode not in SAFE_MANIFEST_MODES:
        raise HTTPException(status_code=400, detail="Unsafe manifest execution mode")
    command = entrypoint.get("command", [])
    command_text = " ".join(str(part).lower() for part in command)
    if any(token in command_text for token in FORBIDDEN_COMMAND_TOKENS):
        raise HTTPException(status_code=400, detail="Unsafe manifest execution mode")
    if "allowed" not in parameters_schema or not isinstance(parameters_schema["allowed"], dict):
        raise HTTPException(status_code=400, detail="Unsupported parameter schema")
    timeout = resources.get("timeout_seconds")
    if not isinstance(timeout, int) or timeout < 1 or timeout > 600:
        raise HTTPException(status_code=400, detail="Unsupported resource limits")
    if resources.get("cpu", 0) > 4 or resources.get("memory_mb", 0) > 4096:
        raise HTTPException(status_code=400, detail="Unsupported resource limits")
    if network.get("mode") not in SAFE_NETWORK_MODES:
        raise HTTPException(status_code=400, detail="Unsupported network policy")
    if network.get("mode") == "allowlist" and "*" in network.get("allowed_hosts", []):
        raise HTTPException(status_code=400, detail="Unsupported network policy")


def validate_security_review(security_review: dict | None, network: dict) -> None:
    review = security_review or {}
    if not review.get("license_reviewed") or review.get("license_status") not in APPROVED_LICENSE_STATUSES:
        raise HTTPException(status_code=400, detail="Tool security review incomplete")
    if review.get("dependency_scan_status") not in PASSED_SCAN_STATUSES or review.get("image_scan_status") not in PASSED_SCAN_STATUSES:
        raise HTTPException(status_code=400, detail="Tool vulnerability review failed")
    image_digest = review.get("image_digest")
    if image_digest is not None and not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", str(image_digest)):
        raise HTTPException(status_code=400, detail="Tool vulnerability review failed")
    if not review.get("container_read_only") or not review.get("tmp_cleanup_enabled"):
        raise HTTPException(status_code=400, detail="Tool container policy incomplete")
    if network.get("mode") == "allowlist":
        allowed_hosts = set(network.get("allowed_hosts", []))
        approved_hosts = set(review.get("network_approved_hosts", []))
        if not review.get("network_reviewed") or not allowed_hosts or not allowed_hosts.issubset(approved_hosts):
            raise HTTPException(status_code=400, detail="Network allowlist requires approved domains")
    capabilities = set(review.get("capabilities", []))
    if capabilities.intersection(EXCLUDED_MVP_CAPABILITIES):
        raise HTTPException(status_code=400, detail="Tool capabilities are excluded from MVP execution")


def validate_tool_publish_security(tool: Tool) -> None:
    manifest = getattr(tool, "manifest", None)
    if not manifest:
        raise HTTPException(status_code=400, detail="Tool security review incomplete")
    validate_security_review(getattr(manifest, "security_review", None), getattr(manifest, "network", None) or {})


def add_audit_log(db: AsyncSession, request: Request, actor: User, action: str, resource_type: str, resource_id: int | None, changes: dict) -> None:
    client = request.client.host if request.client else None
    db.add(
        AuditLog(
            actor_id=actor.id,
            actor_ip=client,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            changes=changes,
            request_id=getattr(request.state, "request_id", None),
            user_agent=request.headers.get("user-agent"),
        )
    )


async def require_admin_from_request(request: Request, db: AsyncSession) -> User:
    current_user = await get_current_user(request, db)
    require_admin_user(current_user)
    return current_user


@router.get("/tools")
async def list_tools(request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    result = await db.execute(select(Tool).where(Tool.is_active == True).order_by(Tool.created_at.desc()))
    tools = result.scalars().all()
    for tool in tools:
        ensure_public_tool_safety(tool)
    return {"data": [ToolResponse.model_validate(t).model_dump() for t in tools], "request_id": request_id}


@router.get("/tools/{slug}")
async def get_tool(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    result = await db.execute(select(Tool).where(Tool.slug == slug, Tool.is_active == True))
    tool = result.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    ensure_public_tool_safety(tool)
    return {"data": ToolDetailResponse.model_validate(tool).model_dump(), "request_id": request_id}


@router.post("/admin/manifests")
async def create_tool_manifest(request: Request, data: ToolManifestCreate, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await require_admin_from_request(request, db)
    validate_manifest_boundaries(data.entrypoint, data.parameters_schema, data.resources, data.network)
    validate_security_review(data.security_review, data.network)
    manifest = ToolManifest(
        name=data.name,
        version=data.version,
        image=data.image,
        entrypoint=data.entrypoint,
        parameters_schema=data.parameters_schema,
        resources=data.resources,
        network=data.network,
        output=data.output,
        security_review=data.security_review,
    )
    db.add(manifest)
    add_audit_log(db, request, current_user, "tool_manifest_created", "tool_manifest", None, data.model_dump())
    await db.commit()
    await db.refresh(manifest)
    return {"data": ToolManifestResponse.model_validate(manifest).model_dump(), "request_id": request_id}


@router.patch("/admin/manifests/{manifest_id}")
async def update_tool_manifest(
    manifest_id: int,
    request: Request,
    data: ToolManifestUpdate,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await require_admin_from_request(request, db)
    result = await db.execute(select(ToolManifest).where(ToolManifest.id == manifest_id))
    manifest = result.scalar_one_or_none()
    if not manifest:
        raise HTTPException(status_code=404, detail="Tool manifest not found")

    candidate_entrypoint = data.entrypoint if data.entrypoint is not None else manifest.entrypoint
    candidate_parameters = data.parameters_schema if data.parameters_schema is not None else manifest.parameters_schema
    candidate_resources = data.resources if data.resources is not None else manifest.resources
    candidate_network = data.network if data.network is not None else manifest.network
    candidate_security_review = data.security_review if data.security_review is not None else manifest.security_review
    validate_manifest_boundaries(candidate_entrypoint, candidate_parameters, candidate_resources, candidate_network)
    validate_security_review(candidate_security_review, candidate_network)

    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(manifest, field, value)
    add_audit_log(db, request, current_user, "tool_manifest_updated", "tool_manifest", manifest_id, changes)
    await db.commit()
    return {"data": ToolManifestResponse.model_validate(manifest).model_dump(), "request_id": request_id}


@router.post("/admin/configs")
async def create_tool_config(request: Request, data: ToolConfigCreate, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await require_admin_from_request(request, db)
    if data.risk_level in HIGH_RISK_LEVELS and data.run_mode not in SAFE_HIGH_RISK_MODES:
        raise HTTPException(status_code=400, detail="High-risk tools must use document or external mode")
    if data.manifest_id is not None:
        result = await db.execute(select(ToolManifest).where(ToolManifest.id == data.manifest_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Tool manifest not found")

    tool = Tool(
        name=data.name,
        slug=data.slug,
        description=data.description,
        risk_level=data.risk_level,
        run_mode=data.run_mode,
        source_url=data.source_url,
        license=data.license,
        manifest_id=data.manifest_id,
        resource_cost=data.resource_cost,
        usage_limitations=data.usage_limitations,
        financial_risk_reminder=data.financial_risk_reminder,
        execution_risk_reminder=data.execution_risk_reminder,
        config_status="draft",
        is_active=False,
    )
    db.add(tool)
    add_audit_log(db, request, current_user, "tool_config_created", "tool", None, data.model_dump())
    await db.commit()
    await db.refresh(tool)
    return {"data": ToolResponse.model_validate(tool).model_dump(), "request_id": request_id}


@router.patch("/admin/configs/{tool_id}")
async def update_tool_config(tool_id: int, request: Request, data: ToolConfigUpdate, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await require_admin_from_request(request, db)
    result = await db.execute(select(Tool).where(Tool.id == tool_id))
    tool = result.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    changes = data.model_dump(exclude_unset=True)
    risk_level = changes.get("risk_level", tool.risk_level)
    run_mode = changes.get("run_mode", tool.run_mode)
    if risk_level in HIGH_RISK_LEVELS and run_mode not in SAFE_HIGH_RISK_MODES:
        raise HTTPException(status_code=400, detail="High-risk tools must use document or external mode")
    for field, value in changes.items():
        setattr(tool, field, value)
    add_audit_log(db, request, current_user, "tool_config_updated", "tool", tool_id, changes)
    await db.commit()
    return {"data": ToolResponse.model_validate(tool).model_dump(), "request_id": request_id}


@router.patch("/admin/configs/{tool_id}/{action}")
async def update_tool_config_status(tool_id: int, action: str, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await require_admin_from_request(request, db)
    result = await db.execute(select(Tool).options(selectinload(Tool.manifest)).where(Tool.id == tool_id))
    tool = result.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    status_map = {
        "publish": ("published", True),
        "unpublish": ("unpublished", False),
        "retire": ("retired", False),
    }
    if action not in status_map:
        raise HTTPException(status_code=400, detail="Invalid tool config action")
    if action == "publish":
        validate_tool_publish_security(tool)
    tool.config_status, tool.is_active = status_map[action]
    add_audit_log(db, request, current_user, f"tool_config_{action}ed", "tool", tool_id, {"config_status": tool.config_status, "is_active": tool.is_active})
    await db.commit()
    return {"data": ToolResponse.model_validate(tool).model_dump(), "request_id": request_id}


@router.post("/jobs")
async def create_job(
    request: Request,
    data: ToolJobCreate,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_verified(current_user)

    tool_result = await db.execute(
        select(Tool).options(selectinload(Tool.manifest)).where(Tool.id == data.tool_id, Tool.is_active == True)
    )
    tool = tool_result.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    ensure_tool_job_allowed(tool)
    validate_job_parameters(tool, data.parameters)

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    queued_at = datetime.now(timezone.utc)

    job = ToolJob(
        job_id=job_id,
        tool_id=tool.id,
        user_id=current_user.id,
        parameters=data.parameters,
        status="queued",
        queued_at=queued_at,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    return {"data": ToolJobResponse.model_validate(job).model_dump(), "request_id": request_id}


@router.get("/jobs")
async def list_jobs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_verified(current_user)

    if not isinstance(page, int):
        page = 1
    if not isinstance(page_size, int):
        page_size = 20
    query = select(ToolJob).where(ToolJob.user_id == current_user.id).order_by(ToolJob.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return {
        "data": [serialize_tool_job(j) for j in jobs],
        "request_id": request_id,
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)
    require_verified(current_user)

    result = await db.execute(select(ToolJob).where(ToolJob.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this job")

    return {"data": serialize_tool_job(job), "request_id": request_id}
