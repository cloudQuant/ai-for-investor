"""Regression tests for Iteration 206 OCR-42 CI/test hygiene gates."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

CI_DIR = Path(__file__).resolve().parents[1]
if str(CI_DIR) not in sys.path:
    sys.path.insert(0, str(CI_DIR))

import check_alembic_heads  # noqa: E402
import check_doc_links  # noqa: E402
import check_migration_safety  # noqa: E402

REPO_ROOT = CI_DIR.parents[1]


def test_alembic_history_check_fails_closed_on_command_error(monkeypatch) -> None:
    monkeypatch.setattr(
        check_alembic_heads,
        "run_alembic_command",
        lambda _args: (1, "", "alembic env failed"),
    )
    assert check_alembic_heads.check_history_continuity() is False


def test_migration_safety_strict_blocks_high_risk_unless_acknowledged(
    tmp_path: Path, monkeypatch
) -> None:
    bad_migration = tmp_path / "0001_bad.py"
    bad_migration.write_text(
        "# alembic-meta: estimated_rows=10; lock_kind=short\n"
        "def upgrade():\n"
        "    op.drop_table('old_table')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_migration_safety,
        "_changed_migration_files",
        lambda _base_ref: [bad_migration],
    )
    monkeypatch.setattr(check_migration_safety, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    monkeypatch.setattr(sys, "argv", ["check_migration_safety.py"])
    assert check_migration_safety.main() == 0

    monkeypatch.setattr(sys, "argv", ["check_migration_safety.py", "--strict"])
    assert check_migration_safety.main() == 1

    acked_migration = tmp_path / "0002_acked.py"
    acked_migration.write_text(
        "# alembic-meta: estimated_rows=0; lock_kind=short\n"
        "# alembic-safety-ack: drop-table\n"
        "def upgrade():\n"
        "    op.drop_table('legacy_table')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_migration_safety,
        "_changed_migration_files",
        lambda _base_ref: [acked_migration],
    )
    assert check_migration_safety.main() == 0


def test_doc_links_and_single_pytest_config() -> None:
    assert check_doc_links.main() == 0
    pyproject = tomllib.loads((REPO_ROOT / "src/backend/pyproject.toml").read_text("utf-8"))
    assert "ini_options" not in pyproject.get("tool", {}).get("pytest", {})
    assert (REPO_ROOT / "src/backend/pytest.ini").is_file()
