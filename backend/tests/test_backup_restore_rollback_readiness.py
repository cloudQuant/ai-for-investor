from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = PROJECT_ROOT / "docs" / "operations" / "backup-restore-rollback.md"
SCRIPT = PROJECT_ROOT / "scripts" / "backup_restore_rollback_check.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_story_7_5_runbook_exists() -> None:
    assert RUNBOOK.exists()
    assert SCRIPT.exists()


def test_story_7_5_database_backup_strategy_is_documented() -> None:
    source = read(RUNBOOK)

    assert "Database Backup Strategy" in source
    assert "mysqldump --single-transaction" in source
    assert "mongodump --uri" in source
    assert "Redis data is non-authoritative" in source
    assert "Retention" in source


def test_story_7_5_object_storage_backup_assumptions_are_documented() -> None:
    source = read(RUNBOOK)

    assert "File/Object Storage Backup Assumptions" in source
    assert "TENCENT_COS_*" in source
    assert "provider-side versioning" in source
    assert "launch assumption" in source


def test_story_7_5_restore_procedure_and_drill_are_documented() -> None:
    source = read(RUNBOOK)

    assert "Restore Drill Requirement" in source
    assert "tested at least once before public beta" in source
    assert "Restore Steps" in source
    assert "Run `/health` and admin observability checks." in source
    assert "Record restore timestamp, backup source, operator, verification commands, and result." in source


def test_story_7_5_deployment_rollback_and_release_checklist_are_documented() -> None:
    source = read(RUNBOOK)

    assert "Deployment Rollback Procedure" in source
    assert "previous stable backend and frontend images or commit" in source
    assert "schema changes" in source
    assert "Release Checklist Backup and Rollback Verification" in source
    assert "Deployment rollback target version is identified" in source


def test_story_7_5_readiness_script_is_non_destructive() -> None:
    source = read(SCRIPT)

    assert "--dry-run is required" in source
    assert "intentionally non-destructive" in source
    assert "restore-drill" in source
    assert "readiness_checks" in source
