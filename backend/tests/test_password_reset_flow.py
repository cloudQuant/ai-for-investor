from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import auth
from app.core.config import settings
from app.core.security import verify_password
from app.core.tokens import hash_token
from app.db.mysql import get_db
from app.main import create_app
from app.models.user import User


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
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.setex_calls: list[tuple[str, int, str]] = []
        self.deleted_keys: list[str] = []

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.setex_calls.append((key, ttl, value))
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.deleted_keys.append(key)
        self.store.pop(key, None)

    def pipeline(self) -> "FakeRedis":
        return self

    def incr(self, key: str) -> None:
        return None

    def expire(self, key: str, ttl: int) -> None:
        return None

    async def execute(self) -> None:
        return None


@pytest.fixture()
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    redis = FakeRedis()
    monkeypatch.setattr(auth, "get_redis", lambda: redis)
    return redis


def make_user() -> User:
    return User(
        id=123,
        email="user@example.com",
        username="user",
        password_hash="old-hash",
        email_verified_at=datetime.now(timezone.utc),
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


def make_client(session: FakeSession) -> TestClient:
    app = create_app(include_lifespan=False)

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_password_reset_request_does_not_expose_account_existence(fake_redis: FakeRedis) -> None:
    existing_client = make_client(FakeSession(user=make_user()))
    missing_client = make_client(FakeSession(user=None))

    existing = existing_client.post("/api/v1/auth/password-reset", json={"email": "user@example.com"})
    missing = missing_client.post("/api/v1/auth/password-reset", json={"email": "missing@example.com"})

    assert existing.status_code == 200
    assert missing.status_code == 200
    assert existing.json()["data"] == missing.json()["data"]
    assert existing.json()["data"]["message"] == "If the email exists, a reset link has been sent"


def test_password_reset_request_stores_hashed_token_with_configured_expiry(
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plaintext = "plain-reset-token"
    monkeypatch.setattr(auth, "create_password_reset_token", lambda user_id: (plaintext, hash_token(plaintext), datetime.now(timezone.utc)))
    client = make_client(FakeSession(user=make_user()))

    response = client.post("/api/v1/auth/password-reset", json={"email": "user@example.com"})

    assert response.status_code == 200
    assert len(fake_redis.setex_calls) == 1
    key, ttl, value = fake_redis.setex_calls[0]
    assert key == f"password_reset:{hash_token(plaintext)}"
    assert ttl == settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS * 3600
    assert value == "123"
    assert plaintext not in key
    assert plaintext not in value
    assert plaintext not in response.text


def test_password_reset_confirm_applies_password_policy(fake_redis: FakeRedis) -> None:
    token = "valid-reset-token"
    fake_redis.store[f"password_reset:{hash_token(token)}"] = "123"
    client = make_client(FakeSession(user=make_user()))

    response = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "weakpass"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Password must contain at least one uppercase letter"


def test_password_reset_confirm_updates_hash_and_deletes_token(fake_redis: FakeRedis) -> None:
    token = "valid-reset-token"
    user = make_user()
    fake_redis.store[f"password_reset:{hash_token(token)}"] = "123"
    session = FakeSession(user=user)
    client = make_client(session)

    response = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "NewPassword1"})

    assert response.status_code == 200
    assert response.json()["data"]["message"] == "Password reset successfully"
    assert verify_password("NewPassword1", user.password_hash) is True
    assert user.password_hash != "old-hash"
    assert user.updated_at is not None
    assert session.commits == 1
    assert fake_redis.deleted_keys == [f"password_reset:{hash_token(token)}"]


def test_password_reset_confirm_rejects_expired_or_reused_token(fake_redis: FakeRedis) -> None:
    token = "single-use-reset-token"
    user = make_user()
    fake_redis.store[f"password_reset:{hash_token(token)}"] = "123"
    client = make_client(FakeSession(user=user))

    first = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "NewPassword1"})
    second = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "NewPassword2"})

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"] == "Invalid or expired reset token"
    assert token not in second.text
