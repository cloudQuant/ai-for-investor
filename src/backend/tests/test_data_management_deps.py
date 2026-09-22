from types import SimpleNamespace

import pytest
from starlette.requests import Request as StarletteRequest

from app.api.data.deps import (
    get_authorized_market_data_access,
    get_current_db_user,
    require_data_admin_user,
)
from app.db.database import async_session_maker, create_tables
from app.models.permission import Permission, Role, user_roles
from app.models.user import User
from app.services.market_data.access import MarketDataAccessAuthorizer, MarketDataPrincipal
from app.utils.security import get_password_hash


def make_request() -> StarletteRequest:
    return StarletteRequest(
        {
            "type": "http",
            "method": "GET",
            "path": "/data/test",
            "headers": [],
            "query_string": b"",
        }
    )


@pytest.mark.asyncio
async def test_get_authorized_market_data_access_preserves_authorized_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = MarketDataPrincipal(
        principal_id="user-123",
        principal_scope="principal-v1:test",
        tenant_scope="tenant:test",
        roles=(Role.USER.value,),
        permissions=(Permission.READ_DATA.value,),
        entitlement_revision="revision-1",
    )

    class FakeMarketDataAccessAuthorizer(MarketDataAccessAuthorizer):
        def __init__(self) -> None:
            self.principal_users: list[object] = []

        async def principal_for_user(self, user: object) -> MarketDataPrincipal:
            self.principal_users.append(user)
            return principal

    access_authorizer = FakeMarketDataAccessAuthorizer()
    read_checks: list[MarketDataPrincipal] = []

    def require_read_data(*, principal: MarketDataPrincipal) -> None:
        read_checks.append(principal)

    monkeypatch.setattr(access_authorizer, "require_read_data", require_read_data)
    current_user = SimpleNamespace(id="user-123")

    access = await get_authorized_market_data_access(
        current_user=current_user,
        access_authorizer=access_authorizer,
    )

    assert access_authorizer.principal_users == [current_user]
    assert read_checks == [principal]
    assert access.principal is principal
    assert access.authorizer is access_authorizer


@pytest.mark.asyncio
async def test_get_current_db_user_returns_database_user(monkeypatch):
    await create_tables()

    async with async_session_maker() as session:
        user = User(
            username="data-user",
            email="data-user@test.example.com",
            hashed_password=get_password_hash("StrongPass1!"),
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        monkeypatch.setattr(
            "app.api.data.deps.decode_access_token",
            lambda _: {"sub": user.id, "username": user.username},
            raising=True,
        )

        request = make_request()
        credentials = SimpleNamespace(credentials="valid-token")
        resolved_user = await get_current_db_user(
            request=request,
            credentials=credentials,
            db=session,
        )

    assert resolved_user.id == user.id
    assert request.state.user_id == user.id


@pytest.mark.asyncio
async def test_require_data_admin_user_accepts_admin_role(monkeypatch):
    await create_tables()

    async with async_session_maker() as session:
        user = User(
            username="role-admin",
            email="role-admin@test.example.com",
            hashed_password=get_password_hash("StrongPass1!"),
            is_active=True,
        )
        session.add(user)
        await session.flush()
        await session.execute(user_roles.insert().values(user_id=user.id, role=Role.ADMIN.value))
        await session.commit()
        await session.refresh(user)

        monkeypatch.setattr(
            "app.api.data.deps.decode_access_token",
            lambda _: {"sub": user.id, "username": user.username},
            raising=True,
        )

        request = make_request()
        credentials = SimpleNamespace(credentials="valid-token")
        resolved_user = await require_data_admin_user(
            request=request,
            credentials=credentials,
            db=session,
        )

    assert resolved_user.id == user.id


@pytest.mark.asyncio
async def test_require_data_admin_user_rejects_non_admin(monkeypatch):
    await create_tables()

    async with async_session_maker() as session:
        user = User(
            username="plain-user",
            email="plain-user@test.example.com",
            hashed_password=get_password_hash("StrongPass1!"),
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        monkeypatch.setattr(
            "app.api.data.deps.decode_access_token",
            lambda _: {"sub": user.id, "username": user.username},
            raising=True,
        )

        request = make_request()
        credentials = SimpleNamespace(credentials="valid-token")
        with pytest.raises(Exception) as exc_info:
            await require_data_admin_user(
                request=request,
                credentials=credentials,
                db=session,
            )

    assert getattr(exc_info.value, "status_code", None) == 403
