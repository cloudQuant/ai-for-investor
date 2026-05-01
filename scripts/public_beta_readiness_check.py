from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPRINT_STATUS = ROOT / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
READINESS = ROOT / "docs" / "operations" / "public-beta-release-readiness.md"
BACKUP_RUNBOOK = ROOT / "docs" / "operations" / "backup-restore-rollback.md"
OBSERVABILITY_ROADMAP = ROOT / "docs" / "operations" / "observability-roadmap.md"
LAUNCH_PACKAGE = ROOT / "_bmad-output" / "implementation-artifacts" / "7-6-launch-content-and-community-seed-package-package.md"
GO_NO_GO_DECISION = ROOT / "_bmad-output" / "implementation-artifacts" / "public-beta-go-no-go-decision.md"
LEGAL_DIR = ROOT / "frontend" / "pages" / "legal"
ADMIN_API = ROOT / "backend" / "app" / "api" / "v1" / "admin.py"
MAIN_API = ROOT / "backend" / "app" / "main.py"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_file(path: Path, name: str) -> CheckResult:
    return CheckResult(name, path.exists(), "exists" if path.exists() else "missing")


def check_epic_status() -> list[CheckResult]:
    if not SPRINT_STATUS.exists():
        return [CheckResult("sprint-status", False, "missing")]
    text = read_text(SPRINT_STATUS)
    keys = ["epic-1", "epic-2", "epic-3", "epic-4", "epic-5", "epic-6", "epic-7"]
    return [CheckResult(f"status:{key}", re.search(rf"^  {key}: done$", text, re.MULTILINE) is not None, "done" if f"  {key}: done" in text else "not done") for key in keys]


def check_release_readiness_sections() -> list[CheckResult]:
    if not READINESS.exists():
        return [CheckResult("readiness", False, "missing")]
    text = read_text(READINESS)
    sections = [
        "Automated Verification Commands",
        "Release Gate Checklist",
        "Code and Build Quality",
        "Recovery Readiness",
        "Launch Content Readiness",
        "Legal and Compliance Visibility",
        "Operations and Observability",
        "MVP Safety Boundary Confirmation",
        "Manual Release Blockers",
        "Go / No-Go Decision Template",
    ]
    return [CheckResult(f"readiness:{section}", section in text, "present" if section in text else "missing") for section in sections]


def check_legal_pages() -> list[CheckResult]:
    required = ["terms.vue", "privacy.vue", "risk-disclaimer.vue"]
    return [check_file(LEGAL_DIR / filename, f"legal:{filename}") for filename in required]


def check_operations_endpoints() -> list[CheckResult]:
    results = []
    main_text = read_text(MAIN_API) if MAIN_API.exists() else ""
    admin_text = read_text(ADMIN_API) if ADMIN_API.exists() else ""
    results.append(CheckResult("endpoint:/health", 'application.get("/health")' in main_text, "present" if 'application.get("/health")' in main_text else "missing"))
    results.append(CheckResult("endpoint:/api/v1/admin/observability", '@router.get("/observability")' in admin_text, "present" if '@router.get("/observability")' in admin_text else "missing"))
    return results


def check_observability_roadmap() -> list[CheckResult]:
    if not OBSERVABILITY_ROADMAP.exists():
        return [CheckResult("observability-roadmap", False, "missing")]
    text = read_text(OBSERVABILITY_ROADMAP)
    required = [
        "Current MVP State",
        "Public Beta Entry Requirements",
        "Production-Grade Direction",
        "Metrics",
        "Logs",
        "Tracing",
        "Alerting",
        "Post-Beta Implementation Sequence",
        "Ownership Checklist",
        "Safety Boundaries",
    ]
    return [CheckResult(f"observability:{item}", item in text, "present" if item in text else "missing") for item in required]


def check_launch_package() -> list[CheckResult]:
    if not LAUNCH_PACKAGE.exists():
        return [CheckResult("launch-package", False, "missing")]
    text = read_text(LAUNCH_PACKAGE)
    required = [
        "Homepage Selected Launch Content",
        "Launch Blog Drafts",
        "Minimum launch count: 24 prepared topics",
        "Configured launch count: 5 tool entries",
        "First Weekly Report Ready to Publish",
        "不构成投资建议",
    ]
    return [CheckResult(f"launch:{item}", item in text, "present" if item in text else "missing") for item in required]


def check_safety_boundaries() -> list[CheckResult]:
    if not READINESS.exists():
        return [CheckResult("safety-boundaries", False, "missing")]
    text = read_text(READINESS)
    required = [
        "Real trading APIs",
        "Broker or exchange account binding",
        "User fund custody or movement",
        "Arbitrary user code execution",
        "Personalized investment advice",
        "Return promises",
    ]
    return [CheckResult(f"safety:{item}", item in text, "present" if item in text else "missing") for item in required]


def check_go_no_go_decision() -> list[CheckResult]:
    if not GO_NO_GO_DECISION.exists():
        return [CheckResult("go-no-go-decision", False, "missing")]
    text = read_text(GO_NO_GO_DECISION)
    required_fields = [
        "Current Decision:** No-Go until manual blockers resolved",
        "Automated Readiness:** Pass",
        "Manual Readiness:** Pending",
        "Release candidate | TBD",
        "Release owner | TBD",
        "Rollback target | TBD",
        "Communication channel | TBD",
        "Deployment target | TBD",
        "Monitoring owner | TBD",
    ]
    manual_blockers = [
        "Non-production restore drill",
        "Launch content publication",
        "Admin observability verification",
        "Release and rollback ownership",
        "Deployment and monitoring ownership",
    ]
    decision_rules = [
        "**Go:** all automated checks pass and every manual blocker is marked `pass` with an evidence location.",
        "**Conditional Go:** all automated checks pass and manual blockers are scheduled with named owners and dates.",
        "**No-Go:** any manual blocker remains `pending`, owner is `TBD`, or evidence location is `TBD`.",
    ]
    results = [CheckResult(f"go-no-go:{item}", item in text, "present" if item in text else "missing") for item in required_fields]
    results.extend(CheckResult(f"go-no-go:blocker:{item}", item in text, "present" if item in text else "missing") for item in manual_blockers)
    results.extend(CheckResult(f"go-no-go:rule:{index}", item in text, "present" if item in text else "missing") for index, item in enumerate(decision_rules, start=1))
    return results


def readiness_checks() -> list[CheckResult]:
    results = [
        check_file(READINESS, "file:public-beta-readiness"),
        check_file(BACKUP_RUNBOOK, "file:backup-runbook"),
        check_file(OBSERVABILITY_ROADMAP, "file:observability-roadmap"),
        check_file(LAUNCH_PACKAGE, "file:launch-package"),
        check_file(GO_NO_GO_DECISION, "file:go-no-go-decision"),
    ]
    results.extend(check_epic_status())
    results.extend(check_release_readiness_sections())
    results.extend(check_legal_pages())
    results.extend(check_operations_endpoints())
    results.extend(check_observability_roadmap())
    results.extend(check_launch_package())
    results.extend(check_safety_boundaries())
    results.extend(check_go_no_go_decision())
    return results


def print_results(results: list[CheckResult]) -> int:
    failed = [result for result in results if not result.ok]
    for result in results:
        prefix = "PASS" if result.ok else "FAIL"
        print(f"{prefix} {result.name}: {result.detail}")
    print(f"SUMMARY total={len(results)} passed={len(results) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Non-destructive public beta release readiness checks")
    parser.add_argument("--dry-run", action="store_true", help="Required: validate repository readiness artifacts without mutating state")
    args = parser.parse_args()

    if not args.dry_run:
        print("ERROR --dry-run is required; this script is intentionally non-destructive", file=sys.stderr)
        return 2

    return print_results(readiness_checks())


if __name__ == "__main__":
    raise SystemExit(main())
