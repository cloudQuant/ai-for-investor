from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1 import tools
from app.models.audit import AuditLog
from app.models.tool import Tool, ToolManifest
from app.models.user import Role, User
from app.schemas.tool import ToolManifestCreate, ToolConfigCreate


class FakeScalarResult:
    def __init__(self, value: Any = None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value


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
    request.state.request_id = "req-security"
    return request


def admin_user() -> User:
    user = User(id=7, email="admin@example.com", username="admin", password_hash="hash", is_active=True)
    user.roles = [Role(id=1, name="admin")]
    return user


def patch_current_user(monkeypatch) -> None:
    async def fake_get_current_user(request: Request, db: FakeSession) -> User:
        return admin_user()

    monkeypatch.setattr(tools, "get_current_user", fake_get_current_user)


def security_review(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    review = {
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
    }
    if overrides:
        review.update(overrides)
    return review


def safe_manifest_payload(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "name": "Backtest Manifest",
        "version": "1.0.0",
        "image": "registry.example.com/ai-for-investor/backtest@sha256:" + "a" * 64,
        "entrypoint": {"mode": "container", "command": ["python", "-m", "safe_backtest"]},
        "parameters_schema": {"allowed": {"symbol": {"type": "string", "max_length": 12}}},
        "resources": {"cpu": 1, "memory_mb": 512, "timeout_seconds": 60},
        "network": {"mode": "none", "allowed_hosts": []},
        "output": {"format": "json", "max_bytes": 100000},
        "security_review": security_review(),
    }
    if overrides:
        payload.update(overrides)
    return payload


def make_manifest(security_overrides: dict[str, Any] | None = None, network: dict[str, Any] | None = None) -> ToolManifest:
    payload = safe_manifest_payload({"security_review": security_review(security_overrides), "network": network or {"mode": "none", "allowed_hosts": []}})
    return ToolManifest(id=3, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc), **payload)


def make_tool(manifest: ToolManifest, risk_level: str = "low", run_mode: str = "internal") -> Tool:
    tool = Tool(
        id=5,
        name="Backtest Demo",
        slug="backtest-demo",
        description="Educational backtest demo.",
        risk_level=risk_level,
        run_mode=run_mode,
        source_url="https://github.com/example/backtest-demo",
        license="MIT",
        manifest_id=manifest.id,
        config_status="draft",
        is_active=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    tool.manifest = manifest
    return tool


@pytest.mark.asyncio
async def test_manifest_onboarding_requires_license_review(monkeypatch) -> None:
    patch_current_user(monkeypatch)
    payload = safe_manifest_payload({"security_review": security_review({"license_reviewed": False})})

    with pytest.raises(HTTPException) as exc:
        await tools.create_tool_manifest(make_request(), ToolManifestCreate(**payload), FakeSession())

    assert exc.value.status_code == 400
    assert exc.value.detail == "Tool security review incomplete"


@pytest.mark.asyncio
async def test_manifest_onboarding_requires_dependency_and_image_scan_review(monkeypatch) -> None:
    patch_current_user(monkeypatch)
    payload = safe_manifest_payload({"security_review": security_review({"dependency_scan_status": "failed"})})

    with pytest.raises(HTTPException) as exc:
        await tools.create_tool_manifest(make_request(), ToolManifestCreate(**payload), FakeSession())

    assert exc.value.status_code == 400
    assert exc.value.detail == "Tool vulnerability review failed"


@pytest.mark.asyncio
async def test_manifest_onboarding_requires_container_read_only_and_tmp_cleanup(monkeypatch) -> None:
    patch_current_user(monkeypatch)
    payload = safe_manifest_payload({"security_review": security_review({"container_read_only": False, "tmp_cleanup_enabled": False})})

    with pytest.raises(HTTPException) as exc:
        await tools.create_tool_manifest(make_request(), ToolManifestCreate(**payload), FakeSession())

    assert exc.value.status_code == 400
    assert exc.value.detail == "Tool container policy incomplete"


@pytest.mark.asyncio
async def test_manifest_rejects_allowlist_network_without_approved_domain_match(monkeypatch) -> None:
    patch_current_user(monkeypatch)
    payload = safe_manifest_payload(
        {
            "network": {"mode": "allowlist", "allowed_hosts": ["api.example.com"]},
            "security_review": security_review({"network_approved_hosts": ["data.example.com"]}),
        }
    )

    with pytest.raises(HTTPException) as exc:
        await tools.create_tool_manifest(make_request(), ToolManifestCreate(**payload), FakeSession())

    assert exc.value.status_code == 400
    assert exc.value.detail == "Network allowlist requires approved domains"


@pytest.mark.asyncio
async def test_manifest_create_accepts_complete_supply_chain_review(monkeypatch) -> None:
    patch_current_user(monkeypatch)
    db = FakeSession()

    response = await tools.create_tool_manifest(make_request(), ToolManifestCreate(**safe_manifest_payload()), db)

    manifest = db.added[0]
    audit = db.added[1]
    assert manifest.security_review["license_status"] == "approved"
    assert response["data"]["security_review"]["image_scan_status"] == "passed"
    assert isinstance(audit, AuditLog)


@pytest.mark.asyncio
async def test_publish_blocks_manifest_with_broker_or_live_trading_capabilities(monkeypatch) -> None:
    patch_current_user(monkeypatch)
    manifest = make_manifest({"capabilities": ["broker_connected", "live_trading"]})
    tool = make_tool(manifest)
    db = FakeSession([FakeScalarResult(tool)])

    with pytest.raises(HTTPException) as exc:
        await tools.update_tool_config_status(5, "publish", make_request(), db)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Tool capabilities are excluded from MVP execution"


@pytest.mark.asyncio
async def test_publish_requires_complete_security_review(monkeypatch) -> None:
    patch_current_user(monkeypatch)
    manifest = make_manifest({"image_scan_status": "pending"})
    tool = make_tool(manifest)
    db = FakeSession([FakeScalarResult(tool)])

    with pytest.raises(HTTPException) as exc:
        await tools.update_tool_config_status(5, "publish", make_request(), db)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Tool vulnerability review failed"
