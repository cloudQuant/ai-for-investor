from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "operations" / "backup-restore-rollback.md"
SPRINT_STATUS = ROOT / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
DOCKER_COMPOSE = ROOT / "docker-compose.yml"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_file(path: Path, label: str) -> CheckResult:
    return CheckResult(label, path.exists(), "exists" if path.exists() else "missing")


def check_runbook_keywords() -> list[CheckResult]:
    if not RUNBOOK.exists():
        return [CheckResult("runbook", False, "missing")]
    text = read_text(RUNBOOK)
    required = [
        "Database Backup Strategy",
        "MySQL",
        "MongoDB",
        "Redis",
        "File/Object Storage Backup Assumptions",
        "Restore Drill Requirement",
        "Restore Procedure",
        "Deployment Rollback Procedure",
        "Release Checklist Backup and Rollback Verification",
        "python3 scripts/backup_restore_rollback_check.py --mode restore-drill --dry-run",
    ]
    return [CheckResult(f"runbook:{item}", item in text, "present" if item in text else "missing") for item in required]


def check_docker_services() -> list[CheckResult]:
    if not DOCKER_COMPOSE.exists():
        return [CheckResult("docker-compose", False, "missing")]
    text = read_text(DOCKER_COMPOSE)
    required = ["mysql", "mongodb", "redis", "backend", "frontend"]
    return [CheckResult(f"docker:{service}", f"  {service}:" in text, "present" if f"  {service}:" in text else "missing") for service in required]


def check_sprint_story_status() -> CheckResult:
    if not SPRINT_STATUS.exists():
        return CheckResult("sprint-status", False, "missing")
    text = read_text(SPRINT_STATUS)
    target = "7-5-backup-restore-and-rollback-readiness"
    return CheckResult("sprint-status:7-5", target in text, "present" if target in text else "missing")


def readiness_checks() -> list[CheckResult]:
    results = [
        check_file(RUNBOOK, "file:runbook"),
        check_file(DOCKER_COMPOSE, "file:docker-compose"),
        check_sprint_story_status(),
    ]
    results.extend(check_runbook_keywords())
    results.extend(check_docker_services())
    return results


def restore_drill_checks() -> list[CheckResult]:
    results = readiness_checks()
    if RUNBOOK.exists():
        text = read_text(RUNBOOK)
        required = [
            "Run `/health` and admin observability checks.",
            "Run smoke tests covering auth, blog, forum, tools, and open-source project pages.",
            "Record restore timestamp, backup source, operator, verification commands, and result.",
        ]
        results.extend(CheckResult(f"restore-drill:{item}", item in text, "present" if item in text else "missing") for item in required)
    return results


def print_results(results: list[CheckResult]) -> int:
    failed = [result for result in results if not result.ok]
    for result in results:
        prefix = "PASS" if result.ok else "FAIL"
        print(f"{prefix} {result.name}: {result.detail}")
    print(f"SUMMARY total={len(results)} passed={len(results) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Non-destructive backup, restore, and rollback readiness checks")
    parser.add_argument("--mode", choices=["readiness", "restore-drill"], default="readiness")
    parser.add_argument("--dry-run", action="store_true", help="Required: only validate procedures; never execute backup/restore/rollback")
    args = parser.parse_args()

    if not args.dry_run:
        print("ERROR --dry-run is required; this script is intentionally non-destructive", file=sys.stderr)
        return 2

    if args.mode == "restore-drill":
        return print_results(restore_drill_checks())
    return print_results(readiness_checks())


if __name__ == "__main__":
    raise SystemExit(main())
