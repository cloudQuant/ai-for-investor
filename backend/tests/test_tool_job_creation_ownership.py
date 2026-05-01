from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1 import tools
from app.models.tool import Tool, ToolJob, ToolManifest
from app.models.user import User
from app.schemas.tool import ToolJobCreate


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
        self.added: list[Any] = []
        self.committed = False
        self.refreshed: list[Any] = []

    async def execute(self, statement: Any) -> FakeScalarResult:
        if self.results:
            return self.results.pop(0)
        return FakeScalarResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = len(self.refreshed) + 1
        self.refreshed.append(obj)


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/tools/jobs",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-job"
    return request


def verified_user(user_id: int = 7) -> User:
    return User(
        id=user_id,
        email=f"user{user_id}@example.com",
        username=f"user{user_id}",
        password_hash="hash",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )


def unverified_user() -> User:
    user = verified_user()
    user.email_verified_at = None
    return user


def patch_current_user(monkeypatch, user: User | None) -> None:
    async def fake_get_current_user(request: Request, db: FakeSession) -> User | None:
        return user

    monkeypatch.setattr(tools, "get_current_user", fake_get_current_user)


def make_manifest() -> ToolManifest:
    return ToolManifest(
        id=3,
        name="Backtest Manifest",
        version="1.0.0",
        entrypoint={"mode": "container", "command": ["python", "-m", "safe_backtest"]},
        parameters_schema={
            "allowed": {
                "symbol": {"type": "string", "max_length": 12},
                "lookback_days": {"type": "integer", "minimum": 1, "maximum": 365},
            }
        },
        resources={"cpu": 1, "memory_mb": 512, "timeout_seconds": 60},
        network={"mode": "none", "allowed_hosts": []},
        output={"format": "json", "max_bytes": 100000},
    )


def make_tool(risk_level: str = "low", run_mode: str = "internal", status: str = "published") -> Tool:
    tool = Tool(
        id=5,
        name="Backtest Demo",
        slug="backtest-demo",
        risk_level=risk_level,
        run_mode=run_mode,
        manifest_id=3,
        config_status=status,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    tool.manifest = make_manifest()
    return tool


def make_job(user_id: int = 7) -> ToolJob:
    return ToolJob(
        id=1,
        job_id="job_abc123",
        tool_id=5,
        user_id=user_id,
        parameters={"symbol": "AAPL", "lookback_days": 30},
        status="queued",
        queued_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_unauthenticated_user_is_guided_to_login_when_creating_job(monkeypatch) -> None:
    patch_current_user(monkeypatch, None)

    with pytest.raises(HTTPException) as exc:
        await tools.create_job(make_request(), ToolJobCreate(tool_id=5, parameters={}), FakeSession())

    assert exc.value.status_code == 401
    assert exc.value.detail == "Authentication required; please login to run tools"


@pytest.mark.asyncio
async def test_unverified_user_cannot_create_tool_job(monkeypatch) -> None:
    patch_current_user(monkeypatch, unverified_user())

    with pytest.raises(HTTPException) as exc:
        await tools.create_job(make_request(), ToolJobCreate(tool_id=5, parameters={}), FakeSession())

    assert exc.value.status_code == 403
    assert exc.value.detail == "Email verification required"


@pytest.mark.asyncio
async def test_verified_user_can_create_owned_job_with_valid_manifest_parameters(monkeypatch) -> None:
    patch_current_user(monkeypatch, verified_user(7))
    db = FakeSession([FakeScalarResult(make_tool())])

    response = await tools.create_job(
        make_request(),
        ToolJobCreate(tool_id=5, parameters={"symbol": "AAPL", "lookback_days": 30}),
        db,
    )

    job = db.added[0]
    assert job.user_id == 7
    assert job.parameters == {"symbol": "AAPL", "lookback_days": 30}
    assert job.status == "queued"
    assert response["data"]["user_id"] == 7
    assert response["data"]["status"] == "queued"


@pytest.mark.asyncio
async def test_job_creation_rejects_unsupported_manifest_parameter(monkeypatch) -> None:
    patch_current_user(monkeypatch, verified_user())
    db = FakeSession([FakeScalarResult(make_tool())])

    with pytest.raises(HTTPException) as exc:
        await tools.create_job(
            make_request(),
            ToolJobCreate(tool_id=5, parameters={"symbol": "AAPL", "user_code": "print(1)"}),
            db,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Unsupported tool parameter"


@pytest.mark.asyncio
async def test_job_creation_rejects_invalid_manifest_parameter_value(monkeypatch) -> None:
    patch_current_user(monkeypatch, verified_user())
    db = FakeSession([FakeScalarResult(make_tool())])

    with pytest.raises(HTTPException) as exc:
        await tools.create_job(
            make_request(),
            ToolJobCreate(tool_id=5, parameters={"symbol": "TOO-LONG-SYMBOL", "lookback_days": 500}),
            db,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid tool parameter value"


@pytest.mark.asyncio
async def test_only_published_low_risk_internal_tools_can_create_jobs(monkeypatch) -> None:
    patch_current_user(monkeypatch, verified_user())

    with pytest.raises(HTTPException) as high_risk:
        await tools.create_job(make_request(), ToolJobCreate(tool_id=5, parameters={}), FakeSession([FakeScalarResult(make_tool(risk_level="medium"))]))
    assert high_risk.value.status_code == 403
    assert high_risk.value.detail == "Tool not approved for user execution"

    with pytest.raises(HTTPException) as unpublished:
        await tools.create_job(make_request(), ToolJobCreate(tool_id=5, parameters={}), FakeSession([FakeScalarResult(make_tool(status="draft"))]))
    assert unpublished.value.status_code == 403
    assert unpublished.value.detail == "Tool not approved for user execution"


@pytest.mark.asyncio
async def test_user_cannot_view_another_users_private_job(monkeypatch) -> None:
    patch_current_user(monkeypatch, verified_user(7))
    db = FakeSession([FakeScalarResult(make_job(user_id=8))])

    with pytest.raises(HTTPException) as exc:
        await tools.get_job("job_abc123", make_request(), db)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Not authorized to view this job"
