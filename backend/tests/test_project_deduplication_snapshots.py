from datetime import datetime, timezone
from typing import Any

import pytest

from app.models.discovery import DiscoveryKeyword, OpenSourceProject, ProjectSnapshot
from app.services.github_discovery import GitHubDiscoveryRateLimitError, collect_github_projects, project_snapshot_from_repo


class FakeScalarResult:
    def __init__(self, value: Any = None, values: list[Any] | None = None) -> None:
        self.value = value
        self.values = values or []

    def scalar_one_or_none(self) -> Any:
        return self.value

    def scalars(self) -> "FakeScalarResult":
        return self

    def all(self) -> list[Any]:
        return self.values


class FakeSession:
    def __init__(self, results: list[FakeScalarResult]) -> None:
        self.results = results
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> FakeScalarResult:
        if self.results:
            return self.results.pop(0)
        return FakeScalarResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


class FakeGitHubClient:
    def __init__(self, result: list[dict[str, Any]] | Exception) -> None:
        self.result = result

    async def search_repositories(self, query: str) -> list[dict[str, Any]]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def repo_payload(full_name: str = "owner/repo") -> dict[str, Any]:
    return {
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "description": "AI investing research",
        "stargazers_count": 123,
        "forks_count": 7,
        "language": "Python",
        "license": {"spdx_id": "MIT"},
        "topics": ["ai", "investing"],
        "updated_at": "2026-04-30T00:00:00Z",
        "pushed_at": "2026-04-29T00:00:00Z",
        "readme_summary": "Research demo with reproducibility notes",
    }


@pytest.mark.asyncio
async def test_collection_does_not_insert_duplicate_project_records() -> None:
    keyword = DiscoveryKeyword(id=1, keyword="ai investing", is_active=True)
    existing = OpenSourceProject(id=10, repo_full_name="owner/repo", repo_url="https://github.com/owner/repo")
    db = FakeSession([
        FakeScalarResult(values=[keyword]),
        FakeScalarResult(existing),
    ])

    result = await collect_github_projects(db, client=FakeGitHubClient([repo_payload()]))

    projects = [item for item in db.added if isinstance(item, OpenSourceProject)]
    snapshots = [item for item in db.added if isinstance(item, ProjectSnapshot)]
    assert result["collected"] == 0
    assert len(projects) == 0
    assert len(snapshots) == 1
    assert snapshots[0].repo_full_name == "owner/repo"


@pytest.mark.asyncio
async def test_collection_inserts_new_project_and_raw_snapshot_separately() -> None:
    keyword = DiscoveryKeyword(id=1, keyword="ai investing", is_active=True)
    db = FakeSession([
        FakeScalarResult(values=[keyword]),
        FakeScalarResult(None),
    ])

    result = await collect_github_projects(db, client=FakeGitHubClient([repo_payload()]))

    projects = [item for item in db.added if isinstance(item, OpenSourceProject)]
    snapshots = [item for item in db.added if isinstance(item, ProjectSnapshot)]
    assert result["collected"] == 1
    assert len(projects) == 1
    assert len(snapshots) == 1
    assert snapshots[0].raw_payload["full_name"] == "owner/repo"
    assert snapshots[0].readme_summary == "Research demo with reproducibility notes"
    assert snapshots[0].license_signal == "MIT"
    assert snapshots[0].latest_commit_at is not None


def test_project_snapshot_preserves_metadata_for_trend_history() -> None:
    snapshot = project_snapshot_from_repo(repo_payload(), keyword_id=1, status="success")

    assert snapshot.repo_full_name == "owner/repo"
    assert snapshot.stars == 123
    assert snapshot.forks == 7
    assert snapshot.topics == ["ai", "investing"]
    assert snapshot.collected_at is not None
    assert snapshot.status == "success"


@pytest.mark.asyncio
async def test_failed_snapshot_collection_records_retryable_failure_snapshot() -> None:
    keyword = DiscoveryKeyword(id=1, keyword="ai investing", is_active=True)
    db = FakeSession([FakeScalarResult(values=[keyword])])
    client = FakeGitHubClient(GitHubDiscoveryRateLimitError("rate limit exceeded", reset_at="2026-04-30T01:00:00Z"))

    result = await collect_github_projects(db, client=client, actor_id=7, request_id="req-snapshot")

    snapshots = [item for item in db.added if isinstance(item, ProjectSnapshot)]
    assert result["failures"][0]["type"] == "rate_limit"
    assert len(snapshots) == 1
    assert snapshots[0].status == "failed"
    assert snapshots[0].retry_count == 0
    assert snapshots[0].error_detail["type"] == "rate_limit"
