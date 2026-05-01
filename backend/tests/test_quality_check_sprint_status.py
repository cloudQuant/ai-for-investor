import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUALITY_CHECK_PATH = PROJECT_ROOT / "scripts" / "quality_check.py"


def load_quality_check():
    spec = importlib.util.spec_from_file_location("quality_check", QUALITY_CHECK_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_sprint_status(root: Path, source: str) -> None:
    path = root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")


def result_map(results):
    return {result.name: result for result in results}


def test_quality_check_accepts_valid_bmad_sprint_status(monkeypatch, tmp_path: Path) -> None:
    quality_check = load_quality_check()
    monkeypatch.setattr(quality_check, "ROOT", tmp_path)
    write_sprint_status(
        tmp_path,
        """
generated: 2026-05-01
last_updated: 2026-05-01
project: ai-for-investor
project_key: NOKEY
tracking_system: file-system
story_location: /tmp/stories

development_status:
  epic-1: done
  1-1-first-story: done
  epic-1-retrospective: optional
""".strip(),
    )

    results = quality_check.parse_status_values()

    assert all(result.ok for result in results)


def test_quality_check_detects_sprint_status_structure_drift(monkeypatch, tmp_path: Path) -> None:
    quality_check = load_quality_check()
    monkeypatch.setattr(quality_check, "ROOT", tmp_path)
    write_sprint_status(
        tmp_path,
        """
generated: 2026-05-01
project: ai-for-investor
tracking_system: file-system
story_location: /tmp/stories

development_status:
  epic-1: done
  1-1-first-story: review
  epic-2-retrospective: optional
  malformed-key: done
""".strip(),
    )

    results = result_map(quality_check.parse_status_values())

    assert results["bmad:metadata:project_key"].ok is False
    assert results["bmad:epic-retrospective:epic-1"].ok is False
    assert results["bmad:epic-completion:epic-1"].ok is False
    assert results["bmad:retrospective-epic:epic-2-retrospective"].ok is False
    assert results["bmad:key:malformed-key"].ok is False


def test_quality_check_rejects_status_values_for_wrong_item_kind(monkeypatch, tmp_path: Path) -> None:
    quality_check = load_quality_check()
    monkeypatch.setattr(quality_check, "ROOT", tmp_path)
    write_sprint_status(
        tmp_path,
        """
generated: 2026-05-01
project: ai-for-investor
project_key: NOKEY
tracking_system: file-system
story_location: /tmp/stories

development_status:
  epic-1: review
  1-1-first-story: optional
  epic-1-retrospective: review
""".strip(),
    )

    results = result_map(quality_check.parse_status_values())

    assert results["bmad:status:epic-1"].ok is False
    assert results["bmad:status:1-1-first-story"].ok is False
    assert results["bmad:status:epic-1-retrospective"].ok is False
