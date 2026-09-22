from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.paper_runtime import (
    create_paper_runtime_review,
    decide_paper_runtime_handoff,
)
from app.schemas.paper_runtime import LiveHandoffDecisionRequest, PaperRuntimeReviewRequest


class _ReviewService:
    def __init__(self, review: SimpleNamespace | None) -> None:
        self.review = review
        self.owner_id: str | None = None
        self.instance_id: str | None = None

    async def create_review(
        self,
        owner_id: str,
        instance_id: str,
        _data: dict[str, object],
    ) -> SimpleNamespace | None:
        self.owner_id = owner_id
        self.instance_id = instance_id
        return self.review

    async def decide_handoff(
        self,
        owner_id: str,
        instance_id: str,
        _data: dict[str, object],
    ) -> SimpleNamespace | None:
        self.owner_id = owner_id
        self.instance_id = instance_id
        return self.review


@pytest.mark.asyncio
async def test_paper_runtime_review_routes_return_persisted_string_fields() -> None:
    current_user = SimpleNamespace(sub="owner-1")
    review_service = _ReviewService(SimpleNamespace(id="review-1", status="completed"))
    handoff_service = _ReviewService(SimpleNamespace(id="handoff-1", decision="approved"))

    review = await create_paper_runtime_review(
        "runtime-1",
        PaperRuntimeReviewRequest(),
        current_user,
        review_service,
    )
    handoff = await decide_paper_runtime_handoff(
        "runtime-1",
        LiveHandoffDecisionRequest(decision="approved"),
        current_user,
        handoff_service,
    )

    assert review == {"id": "review-1", "status": "completed"}
    assert handoff == {"id": "handoff-1", "decision": "approved"}
    assert review_service.owner_id == handoff_service.owner_id == "owner-1"
    assert review_service.instance_id == handoff_service.instance_id == "runtime-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["review", "handoff"])
async def test_paper_runtime_review_routes_keep_not_found_for_missing_record(route: str) -> None:
    service = _ReviewService(None)
    current_user = SimpleNamespace(sub="owner-1")

    with pytest.raises(HTTPException) as exc_info:
        if route == "review":
            await create_paper_runtime_review(
                "runtime-1",
                PaperRuntimeReviewRequest(),
                current_user,
                service,
            )
        else:
            await decide_paper_runtime_handoff(
                "runtime-1",
                LiveHandoffDecisionRequest(decision="approved"),
                current_user,
                service,
            )

    assert exc_info.value.status_code == 404
