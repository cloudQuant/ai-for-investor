from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1 import open_source
from app.models.discovery import OpenSourceProject, WeeklyReportCandidate
from app.models.user import Role, User
from app.schemas.discovery import WeeklyReportCandidateCreate, WeeklyReportCandidateUpdate


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
    def __init__(self, results: list[FakeScalarResult] | None = None) -> None:
        self.results = results or []
        self.added: list[Any] = []
        self.committed = False
        self.refreshed: list[Any] = []

    async def execute(self, statement: Any) -> FakeScalarResult:
        if self.results:
            return self.results.pop(0)
        return FakeScalarResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj: Any) -> None:
        self.refreshed.append(obj)


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/open-source/weekly-report/candidates",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-weekly-candidates"
    return request


def user_with_role(role_name: str = "editor") -> User:
    user = User(id=7, email="editor@example.com", username="editor", password_hash="hash", is_active=True)
    user.roles = [Role(id=1, name=role_name)]
    return user


def patch_current_user(monkeypatch, user: User) -> None:
    async def fake_get_current_user(request: Request, db: FakeSession) -> User:
        return user

    monkeypatch.setattr(open_source, "get_current_user", fake_get_current_user)


def make_project(status: str = "selected") -> OpenSourceProject:
    now = datetime.now(timezone.utc)
    return OpenSourceProject(
        id=11,
        repo_full_name="owner/repo",
        repo_url="https://github.com/owner/repo",
        description="AI investing project",
        stars=1500,
        language="Python",
        license="MIT",
        topics=["ai", "backtesting"],
        latest_commit_at=now,
        score_security=84.0,
        overall_score=91.0,
        status=status,
        risk_note="Research-only project. Not investment advice.",
        created_at=now,
        updated_at=now,
    )


def make_candidate(status: str = "nominated", is_selected: bool = False) -> WeeklyReportCandidate:
    candidate = WeeklyReportCandidate(
        id=101,
        project_id=11,
        added_by_id=7,
        week_number=18,
        year=2026,
        notes="Strong documentation and recent activity.",
        is_selected=is_selected,
        status=status,
        rationale="Useful for this week's open-source roundup.",
        editorial_notes="Verify examples before publishing.",
        created_at=datetime.now(timezone.utc),
    )
    candidate.project = make_project()
    return candidate


@pytest.mark.asyncio
async def test_editor_can_add_selected_project_to_weekly_candidate_pool(monkeypatch) -> None:
    patch_current_user(monkeypatch, user_with_role())
    project = make_project("selected")
    db = FakeSession([FakeScalarResult(project)])

    response = await open_source.create_weekly_report_candidate(
        make_request(),
        WeeklyReportCandidateCreate(
            project_id=11,
            week_number=18,
            year=2026,
            rationale="Useful for weekly research roundup.",
            editorial_notes="Confirm license and reproducibility caveats.",
        ),
        db,
    )

    created = db.added[0]
    assert created.project_id == 11
    assert created.added_by_id == 7
    assert created.status == "nominated"
    assert created.rationale == "Useful for weekly research roundup."
    assert created.editorial_notes == "Confirm license and reproducibility caveats."
    assert response["data"]["license"] == "MIT"
    assert response["data"]["security_score"] == 84.0
    assert db.committed is True


@pytest.mark.asyncio
async def test_candidate_pool_rejects_unselected_project(monkeypatch) -> None:
    patch_current_user(monkeypatch, user_with_role())
    db = FakeSession([FakeScalarResult(make_project("reviewed"))])

    with pytest.raises(HTTPException) as exc:
        await open_source.create_weekly_report_candidate(
            make_request(),
            WeeklyReportCandidateCreate(project_id=11, week_number=18, year=2026, rationale="Maybe later"),
            db,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Only selected projects can be added to weekly candidates"


@pytest.mark.asyncio
async def test_candidate_pool_can_filter_by_week_and_status(monkeypatch) -> None:
    patch_current_user(monkeypatch, user_with_role())
    candidate = make_candidate(status="shortlisted")
    db = FakeSession([
        FakeScalarResult(count=1),
        FakeScalarResult(values=[candidate]),
    ])

    response = await open_source.list_weekly_report_candidates(make_request(), db, week_number=18, year=2026, status="shortlisted")

    assert response["data"][0]["status"] == "shortlisted"
    assert response["data"][0]["license"] == "MIT"
    assert response["data"][0]["security_score"] == 84.0
    assert response["pagination"]["total"] == 1


@pytest.mark.asyncio
async def test_editor_can_update_candidate_status_and_notes(monkeypatch) -> None:
    patch_current_user(monkeypatch, user_with_role())
    candidate = make_candidate()
    db = FakeSession([FakeScalarResult(candidate)])

    response = await open_source.update_weekly_report_candidate(
        101,
        make_request(),
        WeeklyReportCandidateUpdate(status="selected", is_selected=True, editorial_notes="Ready for report."),
        db,
    )

    assert candidate.status == "selected"
    assert candidate.is_selected is True
    assert candidate.editorial_notes == "Ready for report."
    assert response["data"]["is_selected"] is True


@pytest.mark.asyncio
async def test_weekly_report_can_be_assembled_from_selected_candidates(monkeypatch) -> None:
    patch_current_user(monkeypatch, user_with_role())
    candidate = make_candidate(status="selected", is_selected=True)
    db = FakeSession([FakeScalarResult(values=[candidate])])

    response = await open_source.assemble_weekly_report(make_request(), db, week_number=18, year=2026)

    assert response["data"]["week_number"] == 18
    assert response["data"]["year"] == 2026
    assert response["data"]["candidate_count"] == 1
    assert response["data"]["projects"][0]["repo_full_name"] == "owner/repo"
    assert response["data"]["projects"][0]["license"] == "MIT"
    assert response["data"]["projects"][0]["security_score"] == 84.0
    assert "not investment advice" in response["data"]["disclaimer"].lower()
