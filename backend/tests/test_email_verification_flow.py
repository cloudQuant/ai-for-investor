from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1 import auth, forum, tools
from app.core.config import settings
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
    def __init__(self, user: User | None = None, duplicate_email: bool = False) -> None:
        self.user = user
        self.duplicate_email = duplicate_email
        self.execute_calls = 0
        self.added_user: User | None = None
        self.commits = 0
        self.refreshed = False

    async def execute(self, statement: Any) -> FakeScalarResult:
        self.execute_calls += 1
        if self.user is not None:
            return FakeScalarResult(self.user)
        if self.duplicate_email and self.execute_calls == 1:
            return FakeScalarResult(User(email="taken@example.com", username="taken", password_hash="hash"))
        if self.execute_calls in {1, 2} and self.added_user is None:
            return FakeScalarResult(None)
        return FakeScalarResult(self.user or self.added_user)

    def add(self, user: User) -> None:
        self.added_user = user

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, user: User) -> None:
        self.refreshed = True
        user.id = 123
        self.user = user


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.setex_calls: list[tuple[str, int, str]] = []
        self.deleted_keys: list[str] = []

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    def pipeline(self) -> "FakeRedis":
        return self

    def incr(self, key: str) -> None:
        return None

    def expire(self, key: str, ttl: int) -> None:
        return None

    async def execute(self) -> None:
        return None

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.setex_calls.append((key, ttl, value))
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.deleted_keys.append(key)
        self.store.pop(key, None)


@pytest.fixture()
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    redis = FakeRedis()
    monkeypatch.setattr(auth, "get_redis", lambda: redis)
    return redis


def make_client(session: FakeSession) -> TestClient:
    app = create_app(include_lifespan=False)

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_registration_stores_hashed_verification_token_with_expiry(
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plaintext = "plain-verification-token"
    monkeypatch.setattr(auth, "create_email_verification_token", lambda user_id: (plaintext, hash_token(plaintext), datetime.now(timezone.utc)))
    session = FakeSession()
    client = make_client(session)

    response = client.post("/api/v1/auth/register", json={"email": "new@example.com", "password": "Password1"})

    assert response.status_code == 200
    assert len(fake_redis.setex_calls) == 1
    key, ttl, value = fake_redis.setex_calls[0]
    assert key == f"email_verify:{hash_token(plaintext)}"
    assert ttl == settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS * 3600
    assert value == "123"
    assert plaintext not in key
    assert plaintext not in value
    assert plaintext not in response.text


def test_verify_email_accepts_valid_token_marks_user_verified_and_deletes_token(fake_redis: FakeRedis) -> None:
    token = "valid-token"
    user = User(id=123, email="new@example.com", username="new", password_hash="hash")
    session = FakeSession(user=user)
    fake_redis.store[f"email_verify:{hash_token(token)}"] = "123"
    client = make_client(session)

    response = client.post("/api/v1/auth/verify-email", json={"token": token})

    assert response.status_code == 200
    assert response.json()["data"]["message"] == "Email verified successfully"
    assert user.email_verified_at is not None
    assert session.commits == 1
    assert fake_redis.deleted_keys == [f"email_verify:{hash_token(token)}"]


def test_verify_email_rejects_expired_or_missing_token_safely(fake_redis: FakeRedis) -> None:
    session = FakeSession(user=User(id=123, email="new@example.com", username="new", password_hash="hash"))
    client = make_client(session)

    response = client.post("/api/v1/auth/verify-email", json={"token": "missing-token"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired verification token"
    assert "missing-token" not in response.text


def test_verify_email_rejects_reused_token(fake_redis: FakeRedis) -> None:
    token = "single-use-token"
    user = User(id=123, email="new@example.com", username="new", password_hash="hash")
    session = FakeSession(user=user)
    fake_redis.store[f"email_verify:{hash_token(token)}"] = "123"
    client = make_client(session)

    first = client.post("/api/v1/auth/verify-email", json={"token": token})
    second = client.post("/api/v1/auth/verify-email", json={"token": token})

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"] == "Invalid or expired verification token"


def test_unverified_users_are_blocked_from_forum_and_tool_actions() -> None:
    unverified = User(id=123, email="new@example.com", username="new", password_hash="hash")

    with pytest.raises(HTTPException) as forum_error:
        forum.require_verified(unverified)
    with pytest.raises(HTTPException) as tool_error:
        tools.require_verified(unverified)

    assert forum_error.value.status_code == 403
    assert forum_error.value.detail == "Email verification required"
    assert tool_error.value.status_code == 403
    assert tool_error.value.detail == "Email verification required"
