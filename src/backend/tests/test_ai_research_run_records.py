"""Direct contracts for raw AI research run record helpers."""

import pytest

from app.services.research.run_records import _raw_run_record_needs_freshness_persist


@pytest.mark.parametrize(
    ("raw", "force", "expected"),
    [
        pytest.param(
            {
                "paper_review_status": "live_readiness_expired",
                "paper_review_ready_for_live": False,
            },
            False,
            False,
            id="missing-pipeline",
        ),
        pytest.param(
            {
                "paper_review_status": "live_readiness_expired",
                "paper_review_ready_for_live": False,
                "pipeline": None,
            },
            False,
            False,
            id="null-pipeline",
        ),
        pytest.param(
            {
                "paper_review_status": "live_readiness_expired",
                "paper_review_ready_for_live": False,
                "pipeline": "not-a-mapping",
            },
            False,
            False,
            id="non-dict-pipeline",
        ),
        pytest.param(
            {
                "paper_review_status": "live_readiness_expired",
                "paper_review_ready_for_live": False,
                "pipeline": {},
            },
            False,
            False,
            id="empty-dict-pipeline",
        ),
        pytest.param(
            {
                "paper_review_status": "live_readiness_expired",
                "paper_review_ready_for_live": False,
                "pipeline": {"current_stage": "live_candidate"},
            },
            False,
            True,
            id="live-candidate-pipeline",
        ),
        pytest.param(
            {
                "paper_review_status": "live_readiness_expired",
                "paper_review_ready_for_live": True,
                "pipeline": None,
            },
            False,
            True,
            id="ready-status",
        ),
        pytest.param({}, True, True, id="force-refresh"),
        pytest.param({"paper_review_status": "pending"}, False, True, id="non-expired-status"),
    ],
)
def test_raw_run_record_freshness_persist_semantics(
    raw: dict[str, object],
    force: bool,
    expected: bool,
) -> None:
    """Malformed pipelines default empty while existing freshness triggers remain stable."""

    assert _raw_run_record_needs_freshness_persist(raw, force=force) is expected
