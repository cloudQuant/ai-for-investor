from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = PROJECT_ROOT / "_bmad-output" / "implementation-artifacts"
SPRINT_STATUS = ARTIFACTS / "sprint-status.yaml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_all_epic_retrospectives_exist_and_are_marked_done() -> None:
    status = read(SPRINT_STATUS)
    missing = []

    for epic in range(1, 8):
        path = ARTIFACTS / f"epic-{epic}-retrospective.md"
        if not path.exists():
            missing.append(f"epic-{epic}:file")
            continue
        source = read(path)
        if "**Epic Status:** done" not in source:
            missing.append(f"epic-{epic}:status")
        if "## Risks and Follow-Ups" not in source:
            missing.append(f"epic-{epic}:risks")
        if f"epic-{epic}-retrospective: done" not in status:
            missing.append(f"epic-{epic}:sprint-status")

    assert missing == []
