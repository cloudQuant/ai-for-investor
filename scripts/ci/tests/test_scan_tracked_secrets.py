from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNER_PATH = REPO_ROOT / "scripts" / "ci" / "scan_tracked_secrets.py"
PLANTED = "ghp_3KQF7Z2V9M4R8T6W1Y5A7B9C2D4E6F8G0H"


def _load_scanner():
    spec = importlib.util.spec_from_file_location("scan_tracked_secrets_under_test", SCANNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_tracked_scan_hits_planted_secret_and_excludes_untracked_files(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    shutil.copy2(REPO_ROOT / ".gitleaks-tracked.toml", root / ".gitleaks-tracked.toml")
    (root / ".gitignore").write_text(".env\n", encoding="utf-8")
    (root / "positive.txt").write_text(f'github_token = "{PLANTED}"\n', encoding="utf-8")
    (root / "negative.txt").write_text("ordinary public text\n", encoding="utf-8")
    (root / ".env").write_text(f'github_token = "{PLANTED}"\n', encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore", ".gitleaks-tracked.toml", "positive.txt", "negative.txt"],
        cwd=root,
        check=True,
    )
    report = tmp_path / "positive-report.json"

    assert _load_scanner().main(["--root", str(root), "--report", str(report)]) == 1
    findings = json.loads(report.read_text("utf-8"))
    assert [(Path(item["File"]).name, item["RuleID"]) for item in findings] == [
        ("positive.txt", "generic-api-key")
    ]

    subprocess.run(["git", "rm", "--cached", "-q", "positive.txt"], cwd=root, check=True)
    clean_report = tmp_path / "clean-report.json"
    assert _load_scanner().main(["--root", str(root), "--report", str(clean_report)]) == 0
    assert json.loads(clean_report.read_text("utf-8")) == []


def test_gitleaks_allowlist_does_not_exempt_documentation_or_example_files() -> None:
    config = tomllib.loads((REPO_ROOT / ".gitleaks-tracked.toml").read_text("utf-8"))

    assert config["allowlist"]["paths"] == [
        r"\.gitleaks\.toml$",
        r"\.gitleaks-tracked\.toml$",
    ]


def test_ci_uses_strict_config_for_pr_commits_and_audited_config_for_history() -> None:
    workflow = yaml.load(
        (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"),
        Loader=yaml.BaseLoader,
    )
    steps = workflow["jobs"]["secret-scan"]["steps"]
    history = next(step for step in steps if step["name"].startswith("Scan full history"))
    pull_request = next(step for step in steps if step["name"].startswith("Scan PR commits"))

    assert "--config .gitleaks.toml" in history["run"]
    assert "--config .gitleaks-tracked.toml" in pull_request["run"]
