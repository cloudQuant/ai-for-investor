from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1 import auth
from app.core.security import hash_password, validate_password_strength, verify_password
from app.db.mysql import get_db
from app.main import create_app
from app.models.user import User
from app.schemas.user import RegisterRequest


class FakeScalarResult:
    def __init__(self, value: Any = None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value


class FakeSession:
    def __init__(self, duplicate_email: bool = False, duplicate_username: bool = False) -> None:
        self.duplicate_email = duplicate_email
        self.duplicate_username = duplicate_username
        self.execute_calls = 0
        self.added_user: User | None = None
        self.committed = False
        self.refreshed = False

    async def execute(self, statement: Any) -> FakeScalarResult:
        self.execute_calls += 1
        if self.execute_calls == 1 and self.duplicate_email:
            return FakeScalarResult(User(email="taken@example.com", username="taken", password_hash="hash"))
        if self.execute_calls == 2 and self.duplicate_username:
            return FakeScalarResult(User(email="other@example.com", username="taken", password_hash="hash"))
        return FakeScalarResult(None)

    def add(self, user: User) -> None:
        self.added_user = user

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, user: User) -> None:
        self.refreshed = True
        user.id = 123


class FakeRedis:
    def __init__(self) -> None:
        self.setex_calls: list[tuple[str, int, str]] = []

    async def get(self, key: str) -> str | None:
        return None

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


def test_register_request_validates_email_format() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="not-an-email", password="Password1")


def test_password_policy_uses_configured_complexity() -> None:
    assert validate_password_strength("short1A")[0] is False
    assert validate_password_strength("password1")[0] is False
    assert validate_password_strength("PASSWORD1")[0] is False
    assert validate_password_strength("Password")[0] is False
    assert validate_password_strength("Password1")[0] is True


def test_password_hash_uses_argon2_and_verifies_password() -> None:
    hashed = hash_password("Password1")

    assert hashed.startswith("$argon2")
    assert hashed != "Password1"
    assert verify_password("Password1", hashed) is True
    assert verify_password("WrongPassword1", hashed) is False


def test_registration_rejects_duplicate_email_safely(fake_redis: FakeRedis) -> None:
    session = FakeSession(duplicate_email=True)
    client = make_client(session)

    response = client.post("/api/v1/auth/register", json={"email": "taken@example.com", "password": "Password1"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"
    assert session.added_user is None
    assert fake_redis.setex_calls == []


def test_registration_accepts_email_password_and_does_not_leak_sensitive_data(fake_redis: FakeRedis) -> None:
    session = FakeSession()
    client = make_client(session)

    response = client.post("/api/v1/auth/register", json={"email": "new@example.com", "password": "Password1"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["user_id"] == 123
    assert body["data"]["message"] == "Registration successful. Please verify your email."
    assert "password" not in str(body).lower()
    assert "token" not in str(body).lower()
    assert session.added_user is not None
    assert session.added_user.email == "new@example.com"
    assert session.added_user.username == "new"
    assert session.added_user.password_hash.startswith("$argon2")
    assert session.committed is True
    assert session.refreshed is True
    assert len(fake_redis.setex_calls) == 1
    assert fake_redis.setex_calls[0][0].startswith("email_verify:")
