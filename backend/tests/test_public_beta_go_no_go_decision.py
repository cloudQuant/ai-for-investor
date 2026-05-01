from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DECISION = PROJECT_ROOT / "_bmad-output" / "implementation-artifacts" / "public-beta-go-no-go-decision.md"
READINESS_REVIEW = PROJECT_ROOT / "_bmad-output" / "implementation-artifacts" / "public-beta-release-readiness-review.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_public_beta_go_no_go_decision_record_exists() -> None:
    assert DECISION.exists()


def test_public_beta_decision_remains_no_go_until_manual_blockers_resolved() -> None:
    source = read(DECISION)

    assert "Current Decision:** No-Go until manual blockers resolved" in source
    assert "Manual Readiness:** Pending" in source
    assert "any manual blocker remains `pending`" in source


def test_public_beta_decision_tracks_required_manual_blockers() -> None:
    source = read(DECISION)

    assert "Non-production restore drill" in source
    assert "Launch content publication" in source
    assert "Admin observability verification" in source
    assert "Release and rollback ownership" in source
    assert "Deployment and monitoring ownership" in source


def test_public_beta_decision_requires_evidence_locations() -> None:
    source = read(DECISION)

    assert "Evidence Location" in source
    assert "Restore timestamp, backup source, operator, verification commands, and result" in source
    assert "Published URLs or scheduled publish plan from admin workflow" in source
    assert "Actual admin account test result for `/api/v1/admin/observability`" in source


def test_public_beta_decision_preserves_mvp_safety_boundaries() -> None:
    source = read(DECISION)

    assert "No real trading APIs are enabled." in source
    assert "No broker or exchange account binding is enabled." in source
    assert "No user fund custody or movement is enabled." in source
    assert "No arbitrary user code execution is enabled." in source
    assert "No personalized investment advice flow is enabled." in source
    assert "No return promises, buy/sell/hold instructions, or real-funds trading workflows are enabled." in source


def test_public_beta_decision_matches_conditional_go_review_context() -> None:
    review = read(READINESS_REVIEW)
    decision = read(DECISION)

    assert "Conditional Go" in review
    assert "Automated Readiness:** Pass" in decision
    assert "Manual Readiness:** Pending" in decision


def test_public_beta_decision_records_current_readiness_dry_run_scope() -> None:
    decision = read(DECISION)

    assert "python3 scripts/public_beta_readiness_check.py --dry-run" in decision
    assert "SUMMARY total=66 passed=66 failed=0" in decision
