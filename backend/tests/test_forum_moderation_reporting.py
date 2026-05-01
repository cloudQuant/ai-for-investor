from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1 import forum
from app.models.audit import AuditLog
from app.models.forum import ForumReport, ForumReply, ForumThread
from app.models.user import Role, User
from app.schemas.forum import ForumReportCreate, ForumReportStatusUpdate


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
        if isinstance(obj, ForumReport):
            obj.id = obj.id or 30
            obj.status = obj.status or "pending"
            obj.created_at = obj.created_at or datetime.now(timezone.utc)
        self.refreshed = obj


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/forum/reports",
            "headers": [(b"user-agent", b"pytest")],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-moderation"
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
    user.roles = [Role(name=role) for role in roles or ["user"]]
    return user


def patch_current_user(monkeypatch, user: User) -> None:
    async def fake_get_current_user(request: Request, db: FakeSession) -> User:
        return user

    monkeypatch.setattr(forum, "get_current_user", fake_get_current_user)


def make_thread() -> ForumThread:
    now = datetime.now(timezone.utc)
    thread = ForumThread(
        id=10,
        title="Thread",
        content="Content",
        author_id=7,
        category_id=1,
        status="normal",
        is_pinned=False,
        is_featured=False,
        is_locked=False,
        view_count=0,
        reply_count=0,
        like_count=0,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    thread.author = make_user(7)
    return thread


def make_reply() -> ForumReply:
    now = datetime.now(timezone.utc)
    reply = ForumReply(
        id=20,
        content="Reply",
        author_id=8,
        thread_id=10,
        status="normal",
        like_count=0,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    reply.author = make_user(8)
    return reply


def make_report(status: str = "pending") -> ForumReport:
    report = ForumReport(
        id=30,
        reporter_id=7,
        thread_id=10,
        reason="spam",
        description="Spam content",
        status=status,
        created_at=datetime.now(timezone.utc),
    )
    return report


@pytest.mark.asyncio
async def test_verified_user_can_report_thread_and_audit_target_is_valid(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(7))
    db = FakeSession([FakeScalarResult(make_thread())])

    response = await forum.create_report(make_request(), ForumReportCreate(thread_id=10, reason="spam", description="Off topic"), db)

    report = db.added[0]
    assert isinstance(report, ForumReport)
    assert report.thread_id == 10
    assert report.reply_id is None
    assert response["data"].reason == "spam"


@pytest.mark.asyncio
async def test_report_requires_exactly_one_existing_target(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(7))

    with pytest.raises(HTTPException) as missing_target:
        await forum.create_report(make_request(), ForumReportCreate(reason="spam"), FakeSession([]))
    with pytest.raises(HTTPException) as two_targets:
        await forum.create_report(make_request(), ForumReportCreate(thread_id=10, reply_id=20, reason="spam"), FakeSession([]))
    with pytest.raises(HTTPException) as missing_entity:
        await forum.create_report(make_request(), ForumReportCreate(reply_id=999, reason="spam"), FakeSession([FakeScalarResult(None)]))

    assert missing_target.value.status_code == 400
    assert two_targets.value.status_code == 400
    assert missing_entity.value.status_code == 404


@pytest.mark.asyncio
async def test_only_moderator_can_pin_lock_feature_and_hide_threads(monkeypatch) -> None:
    thread = make_thread()
    patch_current_user(monkeypatch, make_user(3, ["user"]))
    with pytest.raises(HTTPException) as forbidden:
        await forum.pin_thread(10, make_request(), FakeSession([FakeScalarResult(thread)]))
    assert forbidden.value.status_code == 403

    patch_current_user(monkeypatch, make_user(4, ["moderator"]))
    db = FakeSession([FakeScalarResult(thread), FakeScalarResult(thread), FakeScalarResult(thread), FakeScalarResult(thread)])

    pinned = await forum.pin_thread(10, make_request(), db)
    locked = await forum.lock_thread(10, make_request(), db)
    featured = await forum.feature_thread(10, make_request(), db)
    hidden = await forum.hide_thread(10, make_request(), db)

    assert pinned["data"]["is_pinned"] is True
    assert locked["data"]["is_locked"] is True
    assert featured["data"]["is_featured"] is True
    assert hidden["data"]["status"] == "hidden"
    assert len([item for item in db.added if isinstance(item, AuditLog)]) == 4


@pytest.mark.asyncio
async def test_moderator_can_list_and_handle_reports(monkeypatch) -> None:
    patch_current_user(monkeypatch, make_user(4, ["admin"]))
    report = make_report()
    db = FakeSession([FakeScalarResult(values=[report]), FakeScalarResult(report)])

    listed = await forum.list_reports(make_request(), "pending", db)
    handled = await forum.update_report_status(30, make_request(), ForumReportStatusUpdate(status="resolved", handler_note="Handled"), db)

    assert listed["data"][0].id == 30
    assert report.status == "resolved"
    assert report.handler_note == "Handled"
    assert report.handler_id == 4
    assert report.handled_at is not None
    assert handled["data"].status == "resolved"
    assert any(isinstance(item, AuditLog) and item.action == "forum_report_status_updated" for item in db.added)
