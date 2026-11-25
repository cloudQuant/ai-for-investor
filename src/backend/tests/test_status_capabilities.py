import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.db.database import create_default_admin
from tests.conftest import register_and_login


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    await create_default_admin()
    settings = get_settings()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_status_endpoints_require_admin_auth(client):
    assert (await client.get("/api/v1/status/capabilities")).status_code == 401
    assert (await client.get("/api/v1/status/routers")).status_code == 401
    assert (await client.get("/api/v1/status/cache")).status_code == 401

    _, user_headers = await register_and_login(client, username="status_non_admin")
    assert (
        await client.get("/api/v1/status/capabilities", headers=user_headers)
    ).status_code == 403
    assert (await client.get("/api/v1/status/routers", headers=user_headers)).status_code == 403
    assert (await client.get("/api/v1/status/cache", headers=user_headers)).status_code == 403


@pytest.mark.asyncio
async def test_capability_status_returns_product_domains(client):
    headers = await _admin_headers(client)
    response = await client.get("/api/v1/status/capabilities", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    domain_ids = {domain["id"] for domain in payload["domains"]}

    assert {"data", "research", "trading", "portfolio", "ai", "admin"} <= domain_ids
    research = next(domain for domain in payload["domains"] if domain["id"] == "research")
    assert research["status"] == "available"
    assert any(capability["id"] == "research.backtests" for capability in research["capabilities"])
    capability_ids = {
        capability["id"] for domain in payload["domains"] for capability in domain["capabilities"]
    }
    assert "trading.brokers" not in capability_ids
    assert "portfolio.ledger" not in capability_ids


@pytest.mark.asyncio
async def test_capability_status_marks_optional_router_degraded(client, monkeypatch):
    from app.api import router as router_module

    headers = await _admin_headers(client)
    monkeypatch.setitem(
        router_module.optional_router_status,
        "kb_chat",
        {"available": False, "error": "import failed"},
    )

    response = await client.get("/api/v1/status/capabilities", headers=headers)

    assert response.status_code == 200
    ai_domain = next(domain for domain in response.json()["domains"] if domain["id"] == "ai")
    chat_capability = next(
        capability for capability in ai_domain["capabilities"] if capability["id"] == "ai.chat"
    )

    assert ai_domain["status"] == "degraded"
    assert chat_capability["available"] is False
    assert "kb_chat" in chat_capability["degraded_reason"]


@pytest.mark.asyncio
async def test_router_status_endpoint_keeps_existing_shape(client):
    headers = await _admin_headers(client)
    response = await client.get("/api/v1/status/routers", headers=headers)

    assert response.status_code == 200
    assert "optional_routers" in response.json()
