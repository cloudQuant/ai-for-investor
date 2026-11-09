"""Regression tests for the secret-scan gate's own preflight.

Two failures these lock out:

* A truncated scanner download reaching ``tar`` through a pipe. The pipeline
  then exits as a corrupt-archive error with zero findings, so the gate reads
  as "secret scan failed" rather than "the binary never arrived".
* The pinned scanner in the workflow drifting away from the version the
  audited fingerprint baseline was produced with. Fingerprints are
  scanner-specific, so a silent version change invalidates every accepted
  finding at once.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER_PATH = REPO_ROOT / "scripts" / "ci" / "check_gitleaks_history_baseline.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_gitleaks_history_baseline_under_test", CHECKER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _write_workflow(path: Path, version: str | None) -> None:
    """Write a workflow shaped like the real one, pinning ``version``."""
    pin = (
        f"          GITLEAKS_VERSION={version}\n" if version else "          echo hi\n"
    )
    path.write_text(
        "jobs:\n"
        "  secret-scan:\n"
        "    steps:\n"
        "      - name: Install gitleaks\n"
        "        run: |\n" + pin,
        encoding="utf-8",
    )


def _install_step() -> str:
    """Return the shell body of the secret-scan job's "Install gitleaks" step."""
    workflow = yaml.load(
        CI_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )
    jobs = workflow["jobs"] if isinstance(workflow, dict) else {}
    assert isinstance(jobs, dict), "workflow must declare jobs as a mapping"
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, dict) and step.get("name") == "Install gitleaks":
                run = step.get("run")
                assert isinstance(run, str), "Install gitleaks must be a run step"
                return run
    raise AssertionError("no Install gitleaks step found")


def test_install_step_never_pipes_the_download_into_tar() -> None:
    run = _install_step()
    assert "| tar" not in run, "download must land in a file before it is unpacked"
    assert "--fail" in run, "an HTTP error page must not be handed to tar as an archive"
    assert "--retry" in run and "--retry-all-errors" in run, (
        "a transient release-host failure must not turn the gate red with zero findings"
    )
    assert "--output" in run, "the archive needs an explicit path to be unpacked"


def test_install_step_unpacks_the_file_it_downloaded() -> None:
    run = _install_step()
    downloaded = [token for token in run.split() if token.endswith("gitleaks.tar.gz")]
    assert downloaded, "install step must download to a named archive"
    archive_path = downloaded[0]
    tar_lines = [
        line.strip() for line in run.splitlines() if line.strip().startswith("tar ")
    ]
    assert tar_lines, "install step must unpack the archive"
    assert all(archive_path in line for line in tar_lines), (
        f"tar must read {archive_path}, got {tar_lines}"
    )


def test_checker_accepts_the_repository_as_it_stands() -> None:
    checker = _load_checker()
    assert checker.main() == 0


def test_checker_reads_exactly_one_pinned_version() -> None:
    checker = _load_checker()
    assert set(checker.load_workflow_versions()) == {"8.30.1"}


def test_checker_fails_when_workflow_and_audit_versions_drift(
    tmp_path: Path, capsys
) -> None:
    checker = _load_checker()
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "gitleaks_version": "8.30.1",
                "accepted_fingerprints": 1,
                "unresolved_findings": 0,
                "blocking_ready": True,
            }
        ),
        encoding="utf-8",
    )
    ignore = tmp_path / ".gitleaksignore"
    ignore.write_text(
        "0000000000000000000000000000000000000000:path:rule:1\n", encoding="utf-8"
    )
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    _write_workflow(workflows / "ci.yml", "9.9.9")
    checker.IGNORE_PATH = ignore
    checker.BASELINE_PATH = baseline
    checker.WORKFLOW_DIR = workflows

    assert checker.main() == 1
    report = capsys.readouterr().out
    assert "workflows install gitleaks 9.9.9" in report
    assert "produced with 8.30.1" in report


def test_checker_fails_when_no_workflow_pins_the_scanner(
    tmp_path: Path, capsys
) -> None:
    checker = _load_checker()
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "gitleaks_version": "8.30.1",
                "accepted_fingerprints": 0,
                "unresolved_findings": 0,
                "blocking_ready": True,
            }
        ),
        encoding="utf-8",
    )
    ignore = tmp_path / ".gitleaksignore"
    ignore.write_text("", encoding="utf-8")
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    _write_workflow(workflows / "ci.yml", None)
    checker.IGNORE_PATH = ignore
    checker.BASELINE_PATH = baseline
    checker.WORKFLOW_DIR = workflows

    assert checker.main() == 1
    assert "exactly one gitleaks version" in capsys.readouterr().out
