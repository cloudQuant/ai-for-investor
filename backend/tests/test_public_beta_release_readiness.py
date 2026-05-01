from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
READINESS = PROJECT_ROOT / "docs" / "operations" / "public-beta-release-readiness.md"
SCRIPT = PROJECT_ROOT / "scripts" / "public_beta_readiness_check.py"
SPRINT_STATUS = PROJECT_ROOT / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
OBSERVABILITY_ROADMAP = PROJECT_ROOT / "docs" / "operations" / "observability-roadmap.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_public_beta_readiness_artifacts_exist() -> None:
    assert READINESS.exists()
    assert SCRIPT.exists()
    assert OBSERVABILITY_ROADMAP.exists()


def test_public_beta_readiness_includes_release_gate_sections() -> None:
    source = read(READINESS)

    assert "Code and Build Quality" in source
    assert "Recovery Readiness" in source
    assert "Launch Content Readiness" in source
    assert "Legal and Compliance Visibility" in source
    assert "Operations and Observability" in source
    assert "MVP Safety Boundary Confirmation" in source
    assert "Go / No-Go Decision Template" in source
    assert "Production observability roadmap exists at `docs/operations/observability-roadmap.md`" in source


def test_public_beta_readiness_lists_required_verification_commands() -> None:
    source = read(READINESS)

    assert "python3 scripts/quality_check.py --timeout 120 --run-backend-tests --run-frontend-typecheck --run-frontend-build" in source
    assert "python3 scripts/backup_restore_rollback_check.py --mode readiness --dry-run" in source
    assert "python3 scripts/backup_restore_rollback_check.py --mode restore-drill --dry-run" in source
    assert "python3 scripts/public_beta_readiness_check.py --dry-run" in source


def test_public_beta_readiness_tracks_manual_release_blockers() -> None:
    source = read(READINESS)

    assert "Non-production restore drill has been executed and recorded." in source
    assert "Launch content has been published or scheduled through the admin workflow." in source
    assert "Admin observability access has been verified with an actual admin account." in source
    assert "rollback target version" in source
    assert "Deployment target and monitoring ownership" in source


def test_public_beta_readiness_confirms_mvp_safety_boundaries() -> None:
    source = read(READINESS)

    assert "Real trading APIs" in source
    assert "Broker or exchange account binding" in source
    assert "User fund custody or movement" in source
    assert "Arbitrary user code execution" in source
    assert "Personalized investment advice" in source
    assert "Return promises" in source


def test_public_beta_readiness_script_is_dry_run_only() -> None:
    source = read(SCRIPT)

    assert "--dry-run is required" in source
    assert "intentionally non-destructive" in source
    assert "readiness_checks" in source
    assert "check_epic_status" in source


def test_public_beta_readiness_requires_epics_done() -> None:
    source = read(SPRINT_STATUS)

    for epic in range(1, 8):
        assert f"epic-{epic}: done" in source


def test_observability_roadmap_tracks_production_hardening_sequence() -> None:
    source = read(OBSERVABILITY_ROADMAP)

    assert "Current MVP State" in source
    assert "Public Beta Entry Requirements" in source
    assert "Production-Grade Direction" in source
    assert "Metrics" in source
    assert "Logs" in source
    assert "Tracing" in source
    assert "Alerting" in source
    assert "Post-Beta Implementation Sequence" in source
    assert "Ownership Checklist" in source
    assert "Safety Boundaries" in source
