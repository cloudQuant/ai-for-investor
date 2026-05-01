from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_file(path: str) -> CheckResult:
    target = ROOT / path
    return CheckResult(f"file:{path}", target.exists(), "exists" if target.exists() else "missing")


def check_readme() -> list[CheckResult]:
    path = ROOT / "README.md"
    if not path.exists():
        return [CheckResult("readme", False, "README.md is missing")]
    text = read_text(path)
    required = [
        "Local Setup",
        "Docker Compose",
        "Environment Configuration",
        "Database Initialization and Migrations",
        "Quality Checks",
        "BMad Recommended Next Steps",
        "backend/.env.example",
        "does not provide investment advice",
        "arbitrary user code execution",
    ]
    return [CheckResult(f"readme:{item}", item in text, "present" if item in text else "missing") for item in required]


def check_backend_requirements() -> list[CheckResult]:
    path = ROOT / "backend" / "requirements.txt"
    if not path.exists():
        return [CheckResult("backend:requirements", False, "requirements.txt is missing")]
    text = read_text(path)
    required = ["fastapi", "uvicorn", "sqlalchemy", "asyncmy", "motor", "redis", "pytest", "pytest-asyncio", "pytest-cov"]
    return [CheckResult(f"backend:req:{item}", item in text.lower(), "present" if item in text.lower() else "missing") for item in required]


def check_frontend_package() -> list[CheckResult]:
    path = ROOT / "frontend" / "package.json"
    if not path.exists():
        return [CheckResult("frontend:package", False, "package.json is missing")]
    package = json.loads(read_text(path))
    scripts = package.get("scripts", {})
    deps = package.get("dependencies", {}) | package.get("devDependencies", {})
    results = []
    for item in ["dev", "build", "preview", "lint", "typecheck"]:
        results.append(CheckResult(f"frontend:script:{item}", item in scripts, scripts.get(item, "missing")))
    for item in ["nuxt", "vue", "typescript", "vue-tsc", "@pinia/nuxt"]:
        results.append(CheckResult(f"frontend:dep:{item}", item in deps, "present" if item in deps else "missing"))
    return results


def check_docker_compose() -> list[CheckResult]:
    path = ROOT / "docker-compose.yml"
    if not path.exists():
        return [CheckResult("docker-compose", False, "docker-compose.yml is missing")]
    text = read_text(path)
    return [CheckResult(f"docker-compose:{service}", re.search(rf"^  {service}:", text, re.MULTILINE) is not None, "present" if service in text else "missing") for service in ["mysql", "mongodb", "redis", "backend", "frontend"]]


def parse_status_values() -> list[CheckResult]:
    path = ROOT / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
    if not path.exists():
        return [CheckResult("bmad:sprint-status", False, "sprint-status.yaml is missing")]
    text = read_text(path)
    required_metadata = {"generated", "project", "project_key", "tracking_system", "story_location"}
    metadata = set()
    entries: dict[str, str] = {}
    in_status = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        metadata_match = re.match(r"^([a-z_]+):(?:\s*(.*))?$", line)
        if metadata_match:
            key, _ = metadata_match.groups()
            metadata.add(key)
            in_status = key == "development_status"
            continue
        if in_status:
            entry_match = re.match(r"^  ([a-z0-9-]+): ([a-z-]+)$", line)
            if entry_match:
                key, value = entry_match.groups()
                entries[key] = value

    results: list[CheckResult] = []
    for key in sorted(required_metadata):
        results.append(CheckResult(f"bmad:metadata:{key}", key in metadata, "present" if key in metadata else "missing"))
    if not entries:
        results.append(CheckResult("bmad:sprint-status:entries", False, "no development_status entries found"))
        return results

    epics = {key for key in entries if re.fullmatch(r"epic-\d+", key)}
    retrospectives = {key for key in entries if re.fullmatch(r"epic-\d+-retrospective", key)}
    stories = {key for key in entries if re.fullmatch(r"\d+-\d+-[a-z0-9-]+", key)}
    known_keys = epics | retrospectives | stories
    legal_by_kind = {
        "epic": {"backlog", "in-progress", "done"},
        "story": {"backlog", "ready-for-dev", "in-progress", "review", "done", "drafted"},
        "retrospective": {"optional", "done"},
    }
    for line in text.splitlines():
        match = re.match(r"^  ([a-z0-9-]+): ([a-z-]+)$", line)
        if match:
            key, value = match.groups()
            if key in epics:
                ok = value in legal_by_kind["epic"]
            elif key in retrospectives:
                ok = value in legal_by_kind["retrospective"]
            elif key in stories:
                ok = value in legal_by_kind["story"]
            else:
                ok = False
            results.append(CheckResult(f"bmad:status:{key}", ok, value if ok else f"invalid status or key: {value}"))

    for key in sorted(entries.keys() - known_keys):
        results.append(CheckResult(f"bmad:key:{key}", False, "unrecognized key format"))
    for key in sorted(stories):
        epic_key = f"epic-{key.split('-', 1)[0]}"
        results.append(CheckResult(f"bmad:story-epic:{key}", epic_key in epics, epic_key if epic_key in epics else f"missing {epic_key}"))
    for key in sorted(retrospectives):
        epic_key = key.removesuffix("-retrospective")
        results.append(CheckResult(f"bmad:retrospective-epic:{key}", epic_key in epics, epic_key if epic_key in epics else f"missing {epic_key}"))
    for key in sorted(epics):
        retrospective_key = f"{key}-retrospective"
        results.append(CheckResult(f"bmad:epic-retrospective:{key}", retrospective_key in retrospectives, retrospective_key if retrospective_key in retrospectives else "missing retrospective"))
        story_prefix = key.replace("epic-", "")
        epic_stories = {story_key: entries[story_key] for story_key in stories if story_key.startswith(f"{story_prefix}-")}
        if entries[key] == "done":
            results.append(CheckResult(f"bmad:epic-completion:{key}", bool(epic_stories) and all(value == "done" for value in epic_stories.values()), "all stories done" if epic_stories and all(value == "done" for value in epic_stories.values()) else "done epic has incomplete or missing stories"))
    return results


def check_bmad_artifacts() -> list[CheckResult]:
    results = [
        check_file("_bmad-output/planning-artifacts/epics.md"),
        check_file("_bmad-output/implementation-artifacts/sprint-status.yaml"),
        check_file("_bmad-output/implementation-artifacts/1-3-development-environment-and-quality-commands.md"),
    ]
    results.extend(parse_status_values())
    return results


def check_alembic_baseline() -> list[CheckResult]:
    baseline = ROOT / "backend" / "alembic" / "versions" / "20260501_0001_initial_schema_baseline.py"
    results = [
        check_file("backend/alembic.ini"),
        check_file("backend/alembic/env.py"),
        check_file("backend/alembic/script.py.mako"),
        check_file("backend/alembic/versions/20260501_0001_initial_schema_baseline.py"),
    ]
    if not baseline.exists():
        return results
    text = read_text(baseline)
    required_tables = [
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
    ]
    results.extend(CheckResult(f"alembic:baseline-table:{table}", f'"{table}"' in text, "present" if f'"{table}"' in text else "missing") for table in required_tables)
    results.append(CheckResult("alembic:baseline-upgrade", "def upgrade() -> None:" in text and "op.create_table" in text, "present"))
    results.append(CheckResult("alembic:baseline-downgrade", "def downgrade() -> None:" in text and "op.drop_table" in text, "present"))
    return results


def run_command(name: str, command: list[str], cwd: Path, timeout: int) -> CheckResult:
    try:
        completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return CheckResult(name, False, f"timed out after {timeout}s")
    output = (completed.stdout + completed.stderr).strip().splitlines()
    detail = output[-1] if output else f"exit {completed.returncode}"
    return CheckResult(name, completed.returncode == 0, detail)


def print_results(results: list[CheckResult]) -> int:
    failed = [result for result in results if not result.ok]
    for result in results:
        prefix = "PASS" if result.ok else "FAIL"
        print(f"{prefix} {result.name}: {result.detail}")
    print(f"SUMMARY total={len(results)} passed={len(results) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--run-backend-tests", action="store_true")
    parser.add_argument("--run-frontend-lint", action="store_true")
    parser.add_argument("--run-frontend-typecheck", action="store_true")
    parser.add_argument("--run-frontend-build", action="store_true")
    args = parser.parse_args()

    results: list[CheckResult] = []
    for path in ["backend/.env.example", "backend/requirements.txt", "frontend/package.json", "frontend/tsconfig.json", "docker-compose.yml"]:
        results.append(check_file(path))
    results.extend(check_readme())
    results.extend(check_backend_requirements())
    results.extend(check_frontend_package())
    results.extend(check_docker_compose())
    results.extend(check_bmad_artifacts())
    results.extend(check_alembic_baseline())

    if args.run_backend_tests:
        results.append(run_command("cmd:backend:pytest", [sys.executable, "-m", "pytest"], ROOT / "backend", args.timeout))
    if args.run_frontend_lint:
        results.append(run_command("cmd:frontend:lint", ["npm", "run", "lint"], ROOT / "frontend", args.timeout))
    if args.run_frontend_typecheck:
        results.append(run_command("cmd:frontend:typecheck", ["npm", "run", "typecheck"], ROOT / "frontend", args.timeout))
    if args.run_frontend_build:
        results.append(run_command("cmd:frontend:build", ["npm", "run", "build"], ROOT / "frontend", args.timeout))

    return print_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
