from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_architecture_baseline_documents_mvp_architecture_and_adr_location() -> None:
    text = read("docs/architecture/README.md")

    assert "modular monolith" in text
    assert "async workers" in text
    assert "docs/architecture/adr/" in text
    assert "NNNN-short-kebab-case-title.md" in text


def test_adr_directory_documents_record_convention() -> None:
    text = read("docs/architecture/adr/README.md")

    assert "Architecture Decision Records" in text
    assert "Status" in text
    assert "Context" in text
    assert "Decision" in text
    assert "Consequences" in text
    assert "Do not rewrite accepted ADRs" in text


def test_migration_policy_requires_migration_or_documented_exception() -> None:
    text = read("docs/architecture/migration-policy.md")

    assert "Every schema-changing backend story" in text
    assert "Migration" in text
    assert "Temporary exception" in text
    assert "rollback guidance" in text
    assert "verification command or test" in text
    assert "Data compatibility note" in text
    assert "20260501_0001_initial_schema_baseline" in text
    assert "future schema-changing stories must create a new Alembic revision" in text


def test_readme_clarifies_init_db_is_not_production_migration() -> None:
    text = read("README.md")

    assert "modular monolith with async workers" in text
    assert "docs/architecture/README.md" in text
    assert "docs/architecture/migration-policy.md" in text
    assert "init_db.py` is a development bootstrap only" in text
    assert "not a replacement for production migrations" in text
    assert "New database changes require migrations or an explicit documented temporary exception" in text
    assert "Sprint work items that change schema must include migration and rollback acceptance criteria" in text
    assert "Alembic is initialized with baseline revision `20260501_0001_initial_schema_baseline`" in text


def test_alembic_baseline_files_exist_and_reference_current_schema() -> None:
    expected_tables = {
        "users",
        "roles",
        "user_roles",
        "categories",
        "tags",
        "tag_relations",
        "blog_posts",
        "forum_categories",
        "forum_threads",
        "forum_replies",
        "forum_reports",
        "tools",
        "tool_manifests",
        "tool_jobs",
        "open_source_projects",
        "project_snapshots",
        "project_scores",
        "weekly_report_candidates",
        "discovery_keywords",
        "audit_logs",
        "user_preferences",
    }
    baseline = read("backend/alembic/versions/20260501_0001_initial_schema_baseline.py")

    assert (ROOT / "backend/alembic.ini").exists()
    assert (ROOT / "backend/alembic/env.py").exists()
    assert (ROOT / "backend/alembic/script.py.mako").exists()
    assert "revision: str = \"20260501_0001\"" in baseline
    assert "down_revision: Union[str, None] = None" in baseline
    assert "def upgrade() -> None:" in baseline
    assert "def downgrade() -> None:" in baseline
    for table in expected_tables:
        assert f'"{table}"' in baseline
