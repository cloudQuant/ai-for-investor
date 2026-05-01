from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import auth
from app.core.config import settings
from app.core.security import hash_password
from app.db.mysql import get_db
from app.main import create_app
from app.models.user import Role, User


class FakeScalarResult:
    def __init__(self, value: Any = None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value


class FakeSession:
    def __init__(self, user: User | None = None) -> None:
        self.user = user
        self.commits = 0

    async def execute(self, statement: Any) -> FakeScalarResult:
        return FakeScalarResult(self.user)

    async def commit(self) -> None:
        self.commits += 1


class FakeRedis:
    def __init__(self, rate_limited: bool = False) -> None:
        self.rate_limited = rate_limited
        self.store: dict[str, str] = {}
        self.setex_calls: list[tuple[str, int, str]] = []

    async def get(self, key: str) -> str | None:
        if self.rate_limited and key.startswith("rate_limit:login:"):
            return str(settings.RATE_LIMIT_LOGIN_MAX)
        return self.store.get(key)

    def pipeline(self) -> "FakeRedis":
        return self

    def incr(self, key: str) -> None:
        self.store[key] = str(int(self.store.get(key, "0")) + 1)

    def expire(self, key: str, ttl: int) -> None:
        return None

    async def execute(self) -> None:
        return None

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.setex_calls.append((key, ttl, value))
        self.store[key] = value


@pytest.fixture()
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    redis = FakeRedis()
    monkeypatch.setattr(auth, "get_redis", lambda: redis)
    return redis


def make_user(password: str = "Password1") -> User:
    user = User(
        id=123,
        email="user@example.com",
        username="user",
        password_hash=hash_password(password),
        email_verified_at=datetime.now(timezone.utc),
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    user.roles = [Role(id=1, name="user")]
    return user


def make_client(session: FakeSession) -> TestClient:
    app = create_app(include_lifespan=False)

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "Password1"})
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


def test_login_returns_bearer_tokens_and_updates_last_login(fake_redis: FakeRedis) -> None:
    user = make_user()
    session = FakeSession(user=user)
    client = make_client(session)

    response = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "Password1"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert user.last_login_at is not None
    assert user.last_login_ip == "testclient"
    assert session.commits == 1


def test_login_failure_uses_generic_error_message(fake_redis: FakeRedis) -> None:
    session = FakeSession(user=make_user())
    client = make_client(session)

    response = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "WrongPassword1"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_login_attempts_are_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis(rate_limited=True)
    monkeypatch.setattr(auth, "get_redis", lambda: redis)
    session = FakeSession(user=make_user())
    client = make_client(session)

    response = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "Password1"})

    assert response.status_code == 429
    assert response.json()["detail"] == "Too many login attempts"


def test_current_user_returns_identity_roles_and_verification_state(fake_redis: FakeRedis) -> None:
    user = make_user()
    session = FakeSession(user=user)
    client = make_client(session)
    token = login(client)

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == 123
    assert data["email"] == "user@example.com"
    assert data["username"] == "user"
    assert data["email_verified"] is True
    assert data["email_verified_at"] is not None
    assert data["roles"] == ["user"]
    assert "password" not in str(data).lower()


def test_logout_blacklists_active_access_token(fake_redis: FakeRedis) -> None:
    user = make_user()
    session = FakeSession(user=user)
    client = make_client(session)
    token = login(client)

    response = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["data"]["message"] == "Logged out successfully"
    assert fake_redis.setex_calls == [(f"token_blacklist:{token}", settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, "123")]


def test_blacklisted_access_token_cannot_fetch_current_user(fake_redis: FakeRedis) -> None:
    user = make_user()
    session = FakeSession(user=user)
    client = make_client(session)
    token = login(client)
    fake_redis.store[f"token_blacklist:{token}"] = "123"

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"
