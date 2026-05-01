import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "public_beta_readiness_check.py"


def load_public_beta_readiness_check():
    spec = importlib.util.spec_from_file_location("public_beta_readiness_check", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def result_map(results):
    return {result.name: result for result in results}


def write_decision(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")


def test_public_beta_readiness_check_validates_go_no_go_decision_record(monkeypatch, tmp_path: Path) -> None:
    checker = load_public_beta_readiness_check()
    decision = tmp_path / "public-beta-go-no-go-decision.md"
    write_decision(
        decision,
        """
**Current Decision:** No-Go until manual blockers resolved
**Automated Readiness:** Pass
**Manual Readiness:** Pending
| Release candidate | TBD |
| Release owner | TBD |
| Rollback target | TBD |
| Communication channel | TBD |
| Deployment target | TBD |
| Monitoring owner | TBD |
Non-production restore drill
Launch content publication
Admin observability verification
Release and rollback ownership
Deployment and monitoring ownership
- **Go:** all automated checks pass and every manual blocker is marked `pass` with an evidence location.
- **Conditional Go:** all automated checks pass and manual blockers are scheduled with named owners and dates.
- **No-Go:** any manual blocker remains `pending`, owner is `TBD`, or evidence location is `TBD`.
""".strip(),
    )
    monkeypatch.setattr(checker, "GO_NO_GO_DECISION", decision)

    results = checker.check_go_no_go_decision()

    assert all(result.ok for result in results)


def test_public_beta_readiness_check_rejects_missing_no_go_safety_gate(monkeypatch, tmp_path: Path) -> None:
    checker = load_public_beta_readiness_check()
    decision = tmp_path / "public-beta-go-no-go-decision.md"
    write_decision(
        decision,
        """
**Current Decision:** Go
**Automated Readiness:** Pass
| Release candidate | rc-1 |
Non-production restore drill
Launch content publication
""".strip(),
    )
    monkeypatch.setattr(checker, "GO_NO_GO_DECISION", decision)

    results = result_map(checker.check_go_no_go_decision())

    assert results["go-no-go:Current Decision:** No-Go until manual blockers resolved"].ok is False
    assert results["go-no-go:Manual Readiness:** Pending"].ok is False
    assert results["go-no-go:rule:3"].ok is False
