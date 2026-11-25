"""Regression coverage for iteration 207 authentication and authorization."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from starlette.websockets import WebSocketDisconnect

from app.api import backtest_enhanced
from app.api.data import topics as topic_api
from app.api.data.deps import get_current_db_user
from app.api.deps import WEBSOCKET_TOKEN_PROTOCOL, get_websocket_current_user
from app.api.strategy.ai_research_config_profiles import get_ai_strategy_research_config_profiles
from app.config import get_settings
from app.db.database import async_session_maker, create_default_admin
from app.main import app
from app.models.permission import Role, user_roles
from app.models.user import User
from app.schemas.ai_strategy_research import AIStrategyResearchConfigProfileCreate
from app.services.ai_strategy_research_config_profiles import (
    AIStrategyResearchConfigProfileService,
)
from tests.conftest import register_and_login


async def _set_role(username: str, role: Role) -> None:
    async with async_session_maker() as db:
        result = await db.execute(select(User.id).where(User.username == username))
        user_id = result.scalar_one()
        await db.execute(delete(user_roles).where(user_roles.c.user_id == user_id))
        await db.execute(user_roles.insert().values(user_id=user_id, role=role.value))
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("account_state", ["disabled", "deleted"])
async def test_revoked_account_token_is_rejected_by_http_and_websocket(
    client: AsyncClient, account_state: str
) -> None:
    _, headers = await register_and_login(client, username=f"revoked_{account_state}")
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    user_id = me.json()["id"]

    async with async_session_maker() as db:
        if account_state == "disabled":
            await db.execute(update(User).where(User.id == user_id).values(is_active=False))
        else:
            await db.execute(delete(User).where(User.id == user_id))
        await db.commit()

    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401

    token = headers["Authorization"].removeprefix("Bearer ")
    websocket = SimpleNamespace(
        headers={"sec-websocket-protocol": f"{WEBSOCKET_TOKEN_PROTOCOL}, {token}"}
    )
    current_user, _ = await get_websocket_current_user(websocket)
    assert current_user is None

    async with async_session_maker() as db:
        with pytest.raises(HTTPException) as exc_info:
            await get_current_db_user(
                request=SimpleNamespace(state=SimpleNamespace()),
                credentials=HTTPAuthorizationCredentials(
                    scheme="Bearer", credentials=headers["Authorization"].removeprefix("Bearer ")
                ),
                db=db,
            )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [Role.USER, Role.PREMIUM, Role.ADMIN])
async def test_authorized_roles_can_manage_own_strategies_and_backtests(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    role: Role,
) -> None:
    user, headers = await register_and_login(client, username=f"rbac_positive_{role.value}")
    await _set_role(user["username"], role)

    created = await client.post(
        "/api/v1/strategy/",
        headers=headers,
        json={"name": f"owned-{role.value}", "code": "class Strategy: pass\n"},
    )
    assert created.status_code == 200, created.text
    strategy_id = created.json()["id"]
    updated = await client.put(
        f"/api/v1/strategy/{strategy_id}", headers=headers, json={"name": "updated"}
    )
    assert updated.status_code == 200, updated.text

    backtest_service = SimpleNamespace(
        run_backtest=AsyncMock(
            return_value=SimpleNamespace(task_id="task-positive", status="pending")
        ),
        delete_result=AsyncMock(return_value=False),
        get_result=AsyncMock(return_value=None),
    )
    app.dependency_overrides[backtest_enhanced.get_backtest_service] = lambda: backtest_service
    try:
        run = await client.post(
            "/api/v1/backtests/run",
            headers=headers,
            json={
                "strategy_id": strategy_id,
                "symbol": "000001.SZ",
                "start_date": "2024-01-01T00:00:00Z",
                "end_date": "2024-02-01T00:00:00Z",
                "initial_cash": 100000,
                "commission": 0.001,
            },
        )
        assert run.status_code == 200, run.text
        backtest_service.run_backtest.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(backtest_enhanced.get_backtest_service, None)

    assert (await client.delete("/api/v1/backtests/missing", headers=headers)).status_code == 404
    for report_format in ("html", "pdf", "excel"):
        expected = 403 if role is Role.USER else 404
        assert (
            await client.get(f"/api/v1/backtests/missing/report/{report_format}", headers=headers)
        ).status_code == expected

    deleted = await client.delete(f"/api/v1/strategy/{strategy_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text


@pytest.mark.asyncio
async def test_strategy_ownership_is_independent_of_role_permission(client: AsyncClient) -> None:
    _, owner_headers = await register_and_login(client, username="strategy_owner")
    _, other_headers = await register_and_login(client, username="strategy_other")
    created = await client.post(
        "/api/v1/strategy/",
        headers=owner_headers,
        json={"name": "owner-only", "code": "class Strategy: pass\n"},
    )
    assert created.status_code == 200, created.text
    strategy_id = created.json()["id"]

    assert (
        await client.put(
            f"/api/v1/strategy/{strategy_id}", headers=other_headers, json={"name": "stolen"}
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/strategy/{strategy_id}", headers=other_headers)
    ).status_code == 404


@pytest.mark.asyncio
async def test_strategy_and_backtest_routes_enforce_role_permissions(
    client: AsyncClient,
) -> None:
    user, headers = await register_and_login(client, username="rbac_default_user")
    await _set_role(user["username"], Role.GUEST)

    strategy_payload = {"name": "forbidden", "code": "class Strategy: pass\n"}
    assert (
        await client.post("/api/v1/strategy/", headers=headers, json=strategy_payload)
    ).status_code == 403
    assert (
        await client.put("/api/v1/strategy/missing", headers=headers, json={"name": "x"})
    ).status_code == 403
    assert (await client.delete("/api/v1/strategy/missing", headers=headers)).status_code == 403

    backtest_payload = {
        "strategy_id": "missing",
        "symbol": "000001.SZ",
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-02-01T00:00:00Z",
        "initial_cash": 100000,
        "commission": 0.001,
    }
    assert (
        await client.post("/api/v1/backtests/run", headers=headers, json=backtest_payload)
    ).status_code == 403
    assert (await client.delete("/api/v1/backtests/missing", headers=headers)).status_code == 403
    for report_format in ("html", "pdf", "excel"):
        assert (
            await client.get(f"/api/v1/backtests/missing/report/{report_format}", headers=headers)
        ).status_code == 403

    await _set_role(user["username"], Role.USER)
    assert (
        await client.get("/api/v1/backtests/missing/report/html", headers=headers)
    ).status_code == 403


@pytest.mark.asyncio
async def test_config_profiles_are_owner_scoped_and_bundled_profiles_are_read_only(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    service = AIStrategyResearchConfigProfileService(tmp_path / "profiles.yaml")
    await service.create_profile(
        AIStrategyResearchConfigProfileCreate(id="bundled", name="Bundled", config={})
    )
    monkeypatch.setattr(
        app,
        "dependency_overrides",
        {**app.dependency_overrides, get_ai_strategy_research_config_profiles: lambda: service},
    )

    _, owner_headers = await register_and_login(client, username="profile_owner")
    _, other_headers = await register_and_login(client, username="profile_other")
    created = await client.post(
        "/api/v1/strategy/ai-research/config-profiles",
        headers=owner_headers,
        json={"id": "personal", "name": "Personal", "config": {"symbol": "RB0"}},
    )
    assert created.status_code == 201, created.text

    other_list = await client.get(
        "/api/v1/strategy/ai-research/config-profiles", headers=other_headers
    )
    assert other_list.status_code == 200
    assert [item["id"] for item in other_list.json()["items"]] == ["bundled"]
    assert (
        await client.get(
            "/api/v1/strategy/ai-research/config-profiles/personal", headers=other_headers
        )
    ).status_code == 404
    assert (
        await client.put(
            "/api/v1/strategy/ai-research/config-profiles/personal",
            headers=other_headers,
            json={"name": "stolen"},
        )
    ).status_code == 404
    assert (
        await client.delete(
            "/api/v1/strategy/ai-research/config-profiles/personal", headers=other_headers
        )
    ).status_code == 404
    assert (
        await client.put(
            "/api/v1/strategy/ai-research/config-profiles/bundled",
            headers=owner_headers,
            json={"name": "modified"},
        )
    ).status_code == 404
    assert (await service.get_profile("personal", owner_id="profile_owner")) is None
    assert (await service.get_profile("personal", owner_id=created.json()["owner_id"])) is not None

    await create_default_admin()
    settings = get_settings()
    admin_login = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD},
    )
    assert admin_login.status_code == 200
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    admin_update = await client.put(
        "/api/v1/strategy/ai-research/config-profiles/bundled",
        headers=admin_headers,
        json={"name": "Admin updated"},
    )
    assert admin_update.status_code == 200, admin_update.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("topic", "expected_close"),
    [("market:quote:RB2510", 1008), ("user:{user_id}:watchlist", 1000)],
)
async def test_websocket_topic_refresh_requires_namespace_write_access(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    topic: str,
    expected_close: int,
) -> None:
    user, headers = await register_and_login(client, username="topic_refresh_user")
    user_id = (await client.get("/api/v1/auth/me", headers=headers)).json()["id"]
    topic = topic.format(user_id=user_id)
    token = headers["Authorization"].removeprefix("Bearer ")
    hub = MagicMock()
    hub.peek = AsyncMock(return_value=None)
    hub.request = AsyncMock(return_value={"ok": True})
    gateway = MagicMock()
    gateway.connect = AsyncMock(return_value=True)
    gateway.subscribe = AsyncMock()
    gateway.pop_messages = MagicMock(return_value=[])
    monkeypatch.setattr(topic_api, "_bind_shared_topic_gateway", lambda: (hub, gateway))

    class FakeWebSocket:
        def __init__(self) -> None:
            self.headers = {"sec-websocket-protocol": f"{WEBSOCKET_TOKEN_PROTOCOL}, {token}"}
            self.incoming = iter(["refresh", "close"])
            self.accept = AsyncMock()
            self.send_json = AsyncMock()
            self.close = AsyncMock()

        async def receive_text(self) -> str:
            data = next(self.incoming)
            if data == "close":
                await self.close(code=1000)
                raise WebSocketDisconnect(code=1000)
            return data

    websocket = FakeWebSocket()
    await topic_api._stream_topics_websocket(websocket, topic=topic)

    websocket.close.assert_awaited_once_with(code=expected_close)
    if expected_close == 1000:
        hub.request.assert_awaited_once_with(topic, force=True)
    else:
        hub.request.assert_not_awaited()
