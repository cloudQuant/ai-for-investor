from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1 import tools
from app.models.audit import AuditLog
from app.models.tool import Tool, ToolManifest
from app.models.user import Role, User
from app.schemas.tool import ToolConfigCreate, ToolConfigUpdate, ToolManifestCreate, ToolManifestUpdate


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
            "path": "/api/v1/tools/admin/manifests",
            "headers": [(b"user-agent", b"pytest")],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-tool-admin"
    return request


def admin_user() -> User:
    user = User(id=7, email="admin@example.com", username="admin", password_hash="hash", is_active=True)
    user.roles = [Role(id=1, name="admin")]
    return user


def regular_user() -> User:
    user = User(id=8, email="user@example.com", username="user", password_hash="hash", is_active=True)
    user.roles = [Role(id=2, name="user")]
    return user


def patch_current_user(monkeypatch, user: User) -> None:
    async def fake_get_current_user(request: Request, db: FakeSession) -> User:
        return user

    monkeypatch.setattr(tools, "get_current_user", fake_get_current_user)


def safe_manifest_payload() -> dict[str, Any]:
    return {
        "name": "Backtest Manifest",
        "version": "1.0.0",
        "image": "registry.example.com/ai-for-investor/backtest:1.0.0",
        "entrypoint": {"mode": "container", "command": ["python", "-m", "safe_backtest"]},
        "parameters_schema": {
            "allowed": {
                "symbol": {"type": "string", "max_length": 12},
                "lookback_days": {"type": "integer", "minimum": 1, "maximum": 365},
            }
        },
        "resources": {"cpu": 1, "memory_mb": 512, "timeout_seconds": 60},
        "network": {"mode": "none", "allowed_hosts": []},
        "output": {"format": "json", "max_bytes": 100000},
        "security_review": {
            "license_reviewed": True,
            "license_status": "approved",
            "dependency_scan_status": "passed",
            "image_scan_status": "passed",
            "image_digest": "sha256:" + "a" * 64,
            "container_read_only": True,
            "tmp_cleanup_enabled": True,
            "network_reviewed": True,
            "network_approved_hosts": [],
            "capabilities": ["research_only"],
        },
    }


def make_manifest() -> ToolManifest:
    payload = safe_manifest_payload()
    return ToolManifest(id=3, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc), **payload)


def make_tool(status: str = "draft") -> Tool:
    tool = Tool(
        id=5,
        name="Backtest Demo",
        slug="backtest-demo",
        description="Educational backtest demo.",
        risk_level="medium",
        run_mode="internal",
        source_url="https://github.com/example/backtest-demo",
        license="MIT",
        config_status=status,
        is_active=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    tool.manifest = make_manifest()
    return tool


@pytest.mark.asyncio
async def test_admin_can_create_safe_tool_manifest_and_audit_change(monkeypatch) -> None:
    patch_current_user(monkeypatch, admin_user())
    db = FakeSession()

    response = await tools.create_tool_manifest(make_request(), ToolManifestCreate(**safe_manifest_payload()), db)

    manifest = db.added[0]
    audit = db.added[1]
    assert manifest.entrypoint["mode"] == "container"
    assert manifest.resources["timeout_seconds"] == 60
    assert manifest.network["mode"] == "none"
    assert isinstance(audit, AuditLog)
    assert audit.action == "tool_manifest_created"
    assert response["data"]["name"] == "Backtest Manifest"
    assert db.committed is True


@pytest.mark.asyncio
async def test_manifest_validation_rejects_unsafe_execution_and_arbitrary_code(monkeypatch) -> None:
    patch_current_user(monkeypatch, admin_user())
    payload = safe_manifest_payload()
    payload["entrypoint"] = {"mode": "shell", "command": ["bash", "-lc", "eval $USER_CODE"]}

    with pytest.raises(HTTPException) as exc:
        await tools.create_tool_manifest(make_request(), ToolManifestCreate(**payload), FakeSession())

    assert exc.value.status_code == 400
    assert exc.value.detail == "Unsafe manifest execution mode"


@pytest.mark.asyncio
async def test_manifest_validation_rejects_unsupported_network_policy(monkeypatch) -> None:
    patch_current_user(monkeypatch, admin_user())
    payload = safe_manifest_payload()
    payload["network"] = {"mode": "open_internet", "allowed_hosts": ["*"]}

    with pytest.raises(HTTPException) as exc:
        await tools.create_tool_manifest(make_request(), ToolManifestCreate(**payload), FakeSession())

    assert exc.value.status_code == 400
    assert exc.value.detail == "Unsupported network policy"


@pytest.mark.asyncio
async def test_non_admin_cannot_create_tool_manifest(monkeypatch) -> None:
    patch_current_user(monkeypatch, regular_user())

    with pytest.raises(HTTPException) as exc:
        await tools.create_tool_manifest(make_request(), ToolManifestCreate(**safe_manifest_payload()), FakeSession())

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_update_manifest_and_create_audit_record(monkeypatch) -> None:
    patch_current_user(monkeypatch, admin_user())
    manifest = make_manifest()
    db = FakeSession([FakeScalarResult(manifest)])

    response = await tools.update_tool_manifest(
        3,
        make_request(),
        ToolManifestUpdate(resources={"cpu": 1, "memory_mb": 1024, "timeout_seconds": 90}),
        db,
    )

    assert manifest.resources["memory_mb"] == 1024
    assert any(isinstance(item, AuditLog) and item.action == "tool_manifest_updated" for item in db.added)
    assert response["data"]["resources"]["timeout_seconds"] == 90


@pytest.mark.asyncio
async def test_admin_can_create_and_publish_unpublish_retire_tool_configuration(monkeypatch) -> None:
    patch_current_user(monkeypatch, admin_user())
    manifest = make_manifest()
    tool = make_tool()
    db = FakeSession([FakeScalarResult(manifest), FakeScalarResult(tool), FakeScalarResult(tool), FakeScalarResult(tool)])

    create_response = await tools.create_tool_config(
        make_request(),
        ToolConfigCreate(
            name="Backtest Demo",
            slug="backtest-demo",
            description="Educational backtest demo.",
            risk_level="medium",
            run_mode="internal",
            source_url="https://github.com/example/backtest-demo",
            license="MIT",
            manifest_id=3,
            resource_cost="cpu: low",
            usage_limitations="Sample data only.",
            financial_risk_reminder="Not investment advice.",
            execution_risk_reminder="No live execution.",
        ),
        db,
    )
    assert create_response["data"]["config_status"] == "draft"
    assert isinstance(db.added[1], AuditLog)

    publish_response = await tools.update_tool_config_status(5, "publish", make_request(), db)
    assert publish_response["data"]["config_status"] == "published"
    assert tool.is_active is True

    unpublish_response = await tools.update_tool_config_status(5, "unpublish", make_request(), db)
    assert unpublish_response["data"]["config_status"] == "unpublished"
    assert tool.is_active is False

    retire_response = await tools.update_tool_config_status(5, "retire", make_request(), db)
    assert retire_response["data"]["config_status"] == "retired"
    assert tool.is_active is False


@pytest.mark.asyncio
async def test_admin_config_rejects_high_risk_internal_tool(monkeypatch) -> None:
    patch_current_user(monkeypatch, admin_user())
    manifest = make_manifest()
    db = FakeSession([FakeScalarResult(manifest)])

    with pytest.raises(HTTPException) as exc:
        await tools.create_tool_config(
            make_request(),
            ToolConfigCreate(
                name="Unsafe Demo",
                slug="unsafe-demo",
                risk_level="high",
                run_mode="internal",
                manifest_id=3,
            ),
            db,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "High-risk tools must use document or external mode"
