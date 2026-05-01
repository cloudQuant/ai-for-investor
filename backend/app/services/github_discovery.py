from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.discovery import DiscoveryKeyword, OpenSourceProject, ProjectSnapshot


class GitHubDiscoveryRateLimitError(Exception):
    def __init__(self, message: str, reset_at: str | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class GitHubDiscoveryClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token if token is not None else settings.GITHUB_TOKEN

    async def search_repositories(self, query: str) -> list[dict[str, Any]]:
        headers = github_auth_headers(self.token)
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "stars", "order": "desc", "per_page": 20},
                headers=headers,
            )
        if response.status_code in {403, 429}:
            raise GitHubDiscoveryRateLimitError("GitHub API rate limit exceeded", response.headers.get("x-ratelimit-reset"))
        response.raise_for_status()
        return response.json().get("items", [])


def github_auth_headers(token: str | None = None) -> dict[str, str]:
    resolved_token = token if token is not None else settings.GITHUB_TOKEN
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if resolved_token:
        headers["Authorization"] = f"Bearer {resolved_token}"
    return headers


def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def project_from_repo(repo: dict[str, Any]) -> OpenSourceProject:
    license_payload = repo.get("license") or {}
    return OpenSourceProject(
        repo_full_name=repo["full_name"],
        repo_url=repo.get("html_url") or f"https://github.com/{repo['full_name']}",
        description=repo.get("description"),
        stars=repo.get("stargazers_count") or 0,
        forks=repo.get("forks_count") or 0,
        language=repo.get("language"),
        license=license_payload.get("spdx_id") or license_payload.get("key"),
        topics=repo.get("topics") or [],
        latest_commit_at=parse_github_datetime(repo.get("updated_at")),
        status="pending",
    )


def project_snapshot_from_repo(repo: dict[str, Any], keyword_id: int | None = None, status: str = "success") -> ProjectSnapshot:
    license_payload = repo.get("license") or {}
    return ProjectSnapshot(
        keyword_id=keyword_id,
        repo_full_name=repo.get("full_name"),
        repo_url=repo.get("html_url"),
        description=repo.get("description"),
        stars=repo.get("stargazers_count") or 0,
        forks=repo.get("forks_count") or 0,
        language=repo.get("language"),
        license_signal=license_payload.get("spdx_id") or license_payload.get("key"),
        topics=repo.get("topics") or [],
        readme_summary=repo.get("readme_summary"),
        latest_commit_at=parse_github_datetime(repo.get("pushed_at") or repo.get("updated_at")),
        latest_release_at=parse_github_datetime(repo.get("latest_release_at")),
        raw_payload=repo,
        status=status,
        collected_at=datetime.now(timezone.utc),
    )


def failed_project_snapshot(keyword_id: int | None, detail: dict[str, Any]) -> ProjectSnapshot:
    return ProjectSnapshot(
        keyword_id=keyword_id,
        status="failed",
        error_detail=detail,
        retry_count=0,
        collected_at=datetime.now(timezone.utc),
    )


def safe_error_detail(error: Exception) -> dict[str, Any]:
    if isinstance(error, GitHubDiscoveryRateLimitError):
        return {"type": "rate_limit", "message": "GitHub API rate limit exceeded", "reset_at": error.reset_at}
    return {"type": "error", "message": error.__class__.__name__}


async def collect_github_projects(
    db: AsyncSession,
    client: Any | None = None,
    actor_id: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    github_client = client or GitHubDiscoveryClient()
    keyword_result = await db.execute(select(DiscoveryKeyword).where(DiscoveryKeyword.is_active == True))
    keywords = keyword_result.scalars().all()
    collected = 0
    failures: list[dict[str, Any]] = []

    for keyword in keywords:
        try:
            repos = await github_client.search_repositories(keyword.keyword)
        except Exception as error:
            detail = safe_error_detail(error)
            detail["keyword_id"] = keyword.id
            failures.append(detail)
            db.add(failed_project_snapshot(keyword.id, detail))
            db.add(
                AuditLog(
                    actor_id=actor_id,
                    action="github_discovery_failed",
                    resource_type="discovery_keyword",
                    resource_id=keyword.id,
                    changes=detail,
                    request_id=request_id,
                )
            )
            continue

        for repo in repos:
            existing_result = await db.execute(
                select(OpenSourceProject).where(OpenSourceProject.repo_full_name == repo["full_name"])
            )
            existing_project = existing_result.scalar_one_or_none()
            snapshot = project_snapshot_from_repo(repo, keyword_id=keyword.id)
            if existing_project:
                snapshot.project_id = existing_project.id
                db.add(snapshot)
                continue

            project = project_from_repo(repo)
            db.add(project)
            db.add(snapshot)
            collected += 1

    await db.commit()
    return {"collected": collected, "failures": failures}
