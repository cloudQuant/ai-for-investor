from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1 import open_source
from app.models.discovery import OpenSourceProject, ProjectScore
from app.models.user import Role, User
from app.schemas.discovery import ProjectReviewUpdate
from app.services.project_scoring import calculate_project_score


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


def make_request(method: str = "PATCH") -> Request:
    request = Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/v1/open-source/projects/1/review",
            "headers": [(b"user-agent", b"pytest")],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-score"
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


def make_project(status: str = "new") -> OpenSourceProject:
    return OpenSourceProject(
        id=1,
        repo_full_name="owner/repo",
        repo_url="https://github.com/owner/repo",
        description="AI investing research toolkit",
        stars=1200,
        forks=100,
        language="Python",
        license="MIT",
        topics=["ai", "investing", "backtesting"],
        readme_summary="Includes documentation and reproducible examples",
        latest_commit_at=datetime.now(timezone.utc) - timedelta(days=10),
        status=status,
        overall_score=0,
    )


def test_automatic_score_uses_transparent_criteria_and_is_editorial_aid() -> None:
    project = make_project()

    result = calculate_project_score(project)

    assert set(result["criteria"].keys()) == {"stars", "activity", "documentation", "license", "relevance"}
    assert result["editorial_aid_only"] is True
    assert "not a recommendation" in result["disclaimer"].lower()
    assert 0 < result["overall_score"] <= 100


@pytest.mark.asyncio
async def test_editor_can_update_review_status_scores_and_rationale(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(7, ["editor"]))
    project = make_project()
    db = FakeSession([FakeScalarResult(project)])

    response = await open_source.review_project(
        1,
        make_request(),
        ProjectReviewUpdate(status="selected", note="Strong docs; selected for editorial review."),
        db,
    )

    score = db.added[0]
    assert isinstance(score, ProjectScore)
    assert score.scorer_id == 7
    assert score.note == "Strong docs; selected for editorial review."
    assert project.status == "selected"
    assert project.overall_score == score.overall_score
    assert response["data"]["status"] == "selected"
    assert response["data"]["score_note"] == "Strong docs; selected for editorial review."
    assert response["data"]["editorial_aid_only"] is True


@pytest.mark.asyncio
async def test_review_rejects_invalid_status(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(7, ["editor"]))

    with pytest.raises(HTTPException) as error:
        await open_source.review_project(
            1,
            make_request(),
            ProjectReviewUpdate(status="approved"),
            FakeSession([FakeScalarResult(make_project())]),
        )

    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_public_project_listing_requires_human_selected_status() -> None:
    selected = make_project(status="selected")
    pending = make_project(status="new")
    db = FakeSession([
        FakeScalarResult(count=1),
        FakeScalarResult(values=[selected, pending]),
    ])

    response = await open_source.list_projects(make_request("GET"), db, status="selected")

    assert response["data"] == [
        {
            "id": selected.id,
            "repo_full_name": selected.repo_full_name,
            "repo_url": selected.repo_url,
            "description": selected.description,
            "stars": selected.stars,
            "language": selected.language,
            "license": selected.license,
            "overall_score": selected.overall_score,
            "status": "selected",
        }
    ]
