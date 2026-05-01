from datetime import datetime, timezone
from typing import Any

import pytest

from app.api.v1 import open_source
from app.models.discovery import OpenSourceProject


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

    async def execute(self, statement: Any) -> FakeScalarResult:
        if self.results:
            return self.results.pop(0)
        return FakeScalarResult()


def make_request():
    from fastapi import Request

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/open-source/projects",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-public-projects"
    return request


def make_project(project_id: int = 1, status: str = "selected", name: str = "owner/repo") -> OpenSourceProject:
    now = datetime.now(timezone.utc)
    return OpenSourceProject(
        id=project_id,
        repo_full_name=name,
        repo_url=f"https://github.com/{name}",
        description="AI investing research toolkit",
        stars=1200,
        forks=100,
        language="Python",
        license="MIT",
        topics=["ai", "investing", "backtesting"],
        latest_commit_at=now,
        readme_summary="Includes documentation, examples, and reproducibility notes.",
        overall_score=88.5,
        status=status,
        risk_note="Research-only project. Not investment advice or a return guarantee.",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_public_project_library_lists_selected_projects_only() -> None:
    selected = make_project(1, "selected")
    ignored = make_project(2, "ignored", "owner/ignored")
    db = FakeSession([
        FakeScalarResult(count=1),
        FakeScalarResult(values=[selected, ignored]),
    ])

    response = await open_source.list_projects(make_request(), db)

    assert response["data"][0]["repo_full_name"] == "owner/repo"
    assert all(project["status"] == "selected" for project in response["data"])
    assert "owner/ignored" not in [project["repo_full_name"] for project in response["data"]]


@pytest.mark.asyncio
async def test_public_project_library_supports_search_and_language_filter() -> None:
    selected = make_project(1, "selected")
    db = FakeSession([
        FakeScalarResult(count=1),
        FakeScalarResult(values=[selected]),
    ])

    response = await open_source.list_projects(make_request(), db, q="investing", language="Python")

    assert response["data"][0]["language"] == "Python"


@pytest.mark.asyncio
async def test_public_project_detail_shows_safe_metadata_and_score_context() -> None:
    selected = make_project(1, "selected")
    db = FakeSession([FakeScalarResult(selected)])

    response = await open_source.get_project_detail(1, make_request(), db)
    data = response["data"]

    assert data["repo_url"] == "https://github.com/owner/repo"
    assert data["readme_summary"] == "Includes documentation, examples, and reproducibility notes."
    assert data["topics"] == ["ai", "investing", "backtesting"]
    assert data["score_note"]
    assert data["license"] == "MIT"
    assert data["latest_commit_at"] is not None
    assert "not investment advice" in data["risk_note"].lower()
    assert "return guarantee" in data["risk_note"].lower()


@pytest.mark.asyncio
async def test_hidden_or_ignored_project_detail_is_not_public() -> None:
    ignored = make_project(2, "ignored", "owner/ignored")
    db = FakeSession([FakeScalarResult(ignored)])

    response = await open_source.get_project_detail(2, make_request(), db)

    assert response["data"] is None
