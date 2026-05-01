from pathlib import Path

from app.content.forum_seed import SEED_DISCUSSION_TOPICS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = PROJECT_ROOT / "_bmad-output" / "implementation-artifacts" / "7-6-launch-content-and-community-seed-package-package.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def table_rows_between(source: str, heading: str, next_heading: str) -> list[str]:
    section = source.split(heading, 1)[1].split(next_heading, 1)[0]
    return [line for line in section.splitlines() if line.startswith("|") and "---" not in line]


def test_story_7_6_launch_package_exists() -> None:
    assert PACKAGE.exists()


def test_story_7_6_homepage_has_selected_launch_content() -> None:
    source = read(PACKAGE)
    rows = table_rows_between(source, "## Homepage Selected Launch Content", "## Launch Blog Drafts")

    assert len(rows) >= 7
    assert "AI 投资与量化开源研究导航" in source
    assert "/open-source" in source
    assert "AI 投资与量化开源周报 2026-W18" in source


def test_story_7_6_has_at_least_ten_blog_drafts() -> None:
    source = read(PACKAGE)
    rows = table_rows_between(source, "## Launch Blog Drafts", "## Forum Seed Topics")
    draft_rows = [row for row in rows if "draft-ready" in row or "ready-to-publish" in row]

    assert len(draft_rows) >= 10
    assert "tradingagents-research-boundaries" in source
    assert "safe-open-source-quant-first-run" in source
    assert "weekly-ai-investing-open-source-2026-w18" in source


def test_story_7_6_has_at_least_twenty_forum_seed_topics() -> None:
    source = read(PACKAGE)

    assert len(SEED_DISCUSSION_TOPICS) >= 20
    assert "Minimum launch count: 24 prepared topics" in source
    assert "Project Discussion" in source
    assert "Beginner Q&A" in source


def test_story_7_6_has_three_to_five_launch_tool_entries() -> None:
    source = read(PACKAGE)
    rows = table_rows_between(source, "## Launch Tool Entries", "## First Weekly Report Ready to Publish")
    tool_rows = [row for row in rows if "ready" in row]

    assert 3 <= len(tool_rows) <= 5
    assert "runnable" in source
    assert "external" in source
    assert "documentation-only" in source
    assert "Configured launch count: 5 tool entries" in source


def test_story_7_6_first_weekly_report_is_ready_to_publish() -> None:
    source = read(PACKAGE)

    assert "## First Weekly Report Ready to Publish" in source
    assert "status: \"ready-to-publish\"" in source
    assert "TradingAgents" in source
    assert "Qlib" in source
    assert "OpenBB" in source
    assert "QuantStats" in source
    assert "vectorbt" in source
    assert "不构成投资建议" in source


def test_story_7_6_launch_content_preserves_compliance_boundaries() -> None:
    source = read(PACKAGE)

    assert "personalized investment advice" in source
    assert "return promises" in source
    assert "buy/sell/hold instructions" in source
    assert "real-funds trading workflows" in source
