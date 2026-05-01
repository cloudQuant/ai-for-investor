from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1 import open_source
from app.models.audit import AuditLog
from app.models.discovery import DiscoveryKeyword, OpenSourceProject
from app.models.user import Role, User
from app.schemas.discovery import DiscoveryKeywordCreate
from app.services.github_discovery import GitHubDiscoveryRateLimitError, collect_github_projects, github_auth_headers


class FakeScalarResult:
    def __init__(self, value: Any = None, values: list[Any] | None = None, count: int | None = None) -> None:
        self.value = value
        self.values = values or []
        self.count = count

    def scalar_one_or_none(self) -> Any:
        return self.value

    def scalar(self) -> int:
        return self.count if self.count is not None else 0

    def scalars(self) -> "FakeScalarResult":
        return self

    def all(self) -> list[Any]:
        return self.values


class FakeSession:
    def __init__(self, results: list[FakeScalarResult]) -> None:
        self.results = results
        self.added: list[Any] = []
        self.commits = 0
        self.refreshed: Any = None

    async def execute(self, statement: Any) -> FakeScalarResult:
        if self.results:
            return self.results.pop(0)
        return FakeScalarResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        self.refreshed = obj
        if getattr(obj, "id", None) is None:
            obj.id = 42
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime.now(timezone.utc)


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/open-source/discovery/keywords",
            "headers": [(b"user-agent", b"pytest")],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-discovery"
    return request


def make_user(user_id: int = 7, roles: list[str] | None = None) -> User:
    user = User(
        id=user_id,
        email=f"user{user_id}@example.com",
        username=f"user{user_id}",
        password_hash="hash",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    user.roles = [Role(name=role) for role in roles or ["editor"]]
    return user


def patch_current_user(monkeypatch, user: User) -> None:
    async def fake_get_current_user(request: Request, db: FakeSession) -> User:
        return user

    monkeypatch.setattr(open_source, "get_current_user", fake_get_current_user)


class FakeGitHubClient:
    def __init__(self, result: list[dict[str, Any]] | Exception) -> None:
        self.result = result
        self.queries: list[str] = []

    async def search_repositories(self, query: str) -> list[dict[str, Any]]:
        self.queries.append(query)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
async def test_editor_can_create_discovery_keyword(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(7, ["editor"]))
    db = FakeSession([])

    response = await open_source.create_discovery_keyword(
        make_request(),
        DiscoveryKeywordCreate(keyword="ai investing"),
        db,
    )

    keyword = db.added[0]
    assert isinstance(keyword, DiscoveryKeyword)
    assert keyword.keyword == "ai investing"
    assert response["data"]["keyword"] == "ai investing"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_non_editor_cannot_create_discovery_keyword(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(7, ["user"]))

    with pytest.raises(HTTPException) as error:
        await open_source.create_discovery_keyword(
            make_request(),
            DiscoveryKeywordCreate(keyword="ai investing"),
            FakeSession([]),
        )

    assert error.value.status_code == 403


def test_github_auth_headers_read_token_from_settings(monkeypatch) -> None:
    monkeypatch.setattr("app.services.github_discovery.settings.GITHUB_TOKEN", "ghp_test_token")

    headers = github_auth_headers()

    assert headers["Authorization"] == "Bearer ghp_test_token"
    assert headers["Accept"] == "application/vnd.github+json"


@pytest.mark.asyncio
async def test_collect_github_projects_queries_active_keywords_and_records_projects() -> None:
    keyword = DiscoveryKeyword(id=1, keyword="ai investing", is_active=True)
    db = FakeSession([FakeScalarResult(values=[keyword])])
    client = FakeGitHubClient([
        {
            "full_name": "owner/repo",
            "html_url": "https://github.com/owner/repo",
            "description": "AI investing research",
            "stargazers_count": 123,
            "forks_count": 7,
            "language": "Python",
            "license": {"spdx_id": "MIT"},
            "topics": ["ai", "investing"],
            "updated_at": "2026-04-30T00:00:00Z",
        }
    ])

    result = await collect_github_projects(db, client=client, actor_id=7, request_id="req-discovery")

    assert client.queries == ["ai investing"]
    assert result["collected"] == 1
    assert any(isinstance(item, OpenSourceProject) and item.repo_full_name == "owner/repo" for item in db.added)
    assert db.commits == 1


@pytest.mark.asyncio
async def test_collect_github_projects_handles_rate_limit_gracefully() -> None:
    keyword = DiscoveryKeyword(id=1, keyword="ai investing", is_active=True)
    db = FakeSession([FakeScalarResult(values=[keyword])])
    client = FakeGitHubClient(GitHubDiscoveryRateLimitError("rate limit exceeded", reset_at="2026-04-30T01:00:00Z"))

    result = await collect_github_projects(db, client=client, actor_id=7, request_id="req-discovery")

    assert result["collected"] == 0
    assert result["failures"][0]["type"] == "rate_limit"
    assert any(isinstance(item, AuditLog) and item.action == "github_discovery_failed" for item in db.added)
    assert "ghp_" not in str(db.added[-1].changes)
