"""Fixture-driven tests for the systemd runtime asset auditor.

No systemctl, no network, no application imports: every case builds a throwaway unit directory
plus a throwaway git checkout under ``tmp_path``.  Each guard is paired with a counterfactual so
that loosening the check (assuming tracked-from-existence, skipping ``%i``, printing environment
values) makes at least one test fail.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_CHECKER_PATH = _BACKEND_ROOT / "scripts" / "ops" / "check_service_runtime_assets.py"
_SPEC = importlib.util.spec_from_file_location("check_service_runtime_assets", _CHECKER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
checker = importlib.util.module_from_spec(_SPEC)
# Register before exec: dataclasses resolve `X | None` string annotations via sys.modules.
sys.modules[_SPEC.name] = checker
_SPEC.loader.exec_module(checker)

SECRET_SENTINEL = "sup3r-s3cret-do-not-print"
ENV_FILE_SENTINEL = "runtime-overrides.env"
OPS_SUBPATH = "src/backend/scripts/ops"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def _write(path: Path, text: str = "#!/usr/bin/env bash\nexit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def unit_dir(tmp_path: Path) -> Path:
    path = tmp_path / "units"
    path.mkdir()
    return path


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A minimal git checkout holding one committed worker script."""

    repo = tmp_path / "checkout"
    script = repo / OPS_SUBPATH / "tracked_worker.py"
    _write(script, "print('tracked worker')\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "guard@example.invalid")
    _git(repo, "config", "user.name", "Guard")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _audit(
    unit_dir: Path,
    home: Path,
    *,
    repo_scope: Path | None = None,
    instance: str | None = None,
    statuses: dict[str, dict[str, str]] | None = None,
) -> Any:
    return checker.audit_units(
        unit_dir,
        home=home,
        repo_scope=repo_scope,
        instance=instance,
        use_systemctl=False,
        statuses=statuses if statuses is not None else {},
    )


def _findings_by_path(summary: Any) -> dict[str, str]:
    return {
        finding.path: finding.classification
        for report in summary.reports
        for finding in report.findings
    }


def _paths(summary: Any) -> list[str]:
    return [finding.path for report in summary.reports for finding in report.findings]


# --------------------------------------------------------------------------- unit name parsing


def test_parse_unit_name_distinguishes_template_from_instantiated() -> None:
    template = checker.parse_unit_name("ai-for-investor-etf-nav-backfill@.service")
    instantiated = checker.parse_unit_name("ai-for-investor-etf-nav-backfill@0.service")
    plain = checker.parse_unit_name("ai-for-investor.service")

    assert template.is_template is True
    # Counterfactual: treating a template as a concrete unit would expand %i to "" and invent a
    # path that no instance ever runs.
    assert instantiated.is_template is False
    assert plain.is_template is False
    assert template.prefix == "ai-for-investor-etf-nav-backfill"
    assert template.instantiated("2") == "ai-for-investor-etf-nav-backfill@2.service"
    assert plain.instantiated("2") == "ai-for-investor.service"


# --------------------------------------------------------------------------- tracked vs assumed


def test_committed_exec_target_is_ok(unit_dir: Path, home: Path, checkout: Path) -> None:
    _write(
        unit_dir / "good.service",
        "[Service]\n"
        f"WorkingDirectory={home}/checkout/{OPS_SUBPATH}\n"
        f"ExecStart={home}/checkout/{OPS_SUBPATH}/tracked_worker.py --apply\n",
    )

    summary = _audit(unit_dir, home)

    assert _findings_by_path(summary) == {
        f"{home}/checkout/{OPS_SUBPATH}/tracked_worker.py": checker.CLASSIFICATION_OK
    }
    assert summary.counts[checker.CLASSIFICATION_OK] == 1
    assert summary.non_green_units == []
    # Counterfactual for "never assume tracked": the identical auditor on an uncommitted file must
    # not report ok, see test_present_but_untracked_is_flagged.


def test_present_but_untracked_is_flagged(unit_dir: Path, home: Path, checkout: Path) -> None:
    ghost = _write(checkout / OPS_SUBPATH / "ghost_worker.py", "print('never committed')\n")

    _write(
        unit_dir / "ghost.service",
        f"[Service]\nExecStart={home}/checkout/{OPS_SUBPATH}/ghost_worker.py\n",
    )

    summary = _audit(unit_dir, home)

    assert _findings_by_path(summary) == {str(ghost): checker.CLASSIFICATION_UNTRACKED_BUT_PRESENT}
    assert summary.counts[checker.CLASSIFICATION_UNTRACKED_BUT_PRESENT] == 1
    assert summary.non_green_units == ["ghost.service"]
    # Counterfactual: existence-only classification would call this ok, because the file is on disk.


def test_gitignored_path_present_but_untracked_is_not_a_finding(
    unit_dir: Path, home: Path, checkout: Path
) -> None:
    _write(checkout / ".gitignore", ".venv/\n")
    _git(checkout, "add", ".gitignore")
    _git(checkout, "commit", "-q", "-m", "ignore venv")
    _write(checkout / ".venv" / "bin" / "python", "")

    _write(
        unit_dir / "venv.service",
        "[Service]\n"
        f"ExecStart={home}/checkout/.venv/bin/python "
        f"{home}/checkout/{OPS_SUBPATH}/tracked_worker.py\n",
    )

    summary = _audit(unit_dir, home)

    # Counterfactual: skipping `git check-ignore` would flag the interpreter as a lost asset and
    # bury the real signal in every python-based unit.
    assert checker.REASON_GITIGNORED in summary.reports[0].skipped
    assert _findings_by_path(summary) == {
        f"{home}/checkout/{OPS_SUBPATH}/tracked_worker.py": checker.CLASSIFICATION_OK
    }
    assert summary.non_green_units == []


# --------------------------------------------------------------------------- missing targets


def test_missing_exec_target_is_flagged(unit_dir: Path, home: Path, checkout: Path) -> None:
    missing = f"{home}/checkout/{OPS_SUBPATH}/run_full_history_recovery_worker.py"
    _write(
        unit_dir / "recovery.service",
        "[Service]\n"
        f"ExecStart={home}/checkout/{OPS_SUBPATH}/tracked_worker.py "
        f"{missing} --apply --assets stock crypto bond etf option\n",
    )

    summary = _audit(unit_dir, home)

    assert _findings_by_path(summary)[missing] == checker.CLASSIFICATION_MISSING_FILE
    finding = next(item for item in summary.reports[0].findings if item.path == missing)
    assert finding.exists is False
    assert finding.tracked is False
    assert summary.counts[checker.CLASSIFICATION_MISSING_FILE] == 1
    assert summary.counts[checker.CLASSIFICATION_OK] == 1
    # A file that is committed but deleted from the worktree is still a broken runtime asset;
    # see test_tracked_in_index_but_absent_is_still_a_missing_file.


def test_tracked_in_index_but_absent_is_still_a_missing_file(
    unit_dir: Path, home: Path, checkout: Path
) -> None:
    _write(checkout / OPS_SUBPATH / "deleted_worker.py", "print('committed then deleted')\n")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-q", "-m", "add worker")
    (checkout / OPS_SUBPATH / "deleted_worker.py").unlink()

    _write(
        unit_dir / "deleted.service",
        f"[Service]\nExecStart={home}/checkout/{OPS_SUBPATH}/deleted_worker.py\n",
    )

    summary = _audit(unit_dir, home)

    finding = summary.reports[0].findings[0]
    assert finding.classification == checker.CLASSIFICATION_MISSING_FILE
    assert finding.tracked is True
    assert "index" in finding.note


# --------------------------------------------------------------------------- specifiers


def test_template_percent_i_expands_only_with_an_instance(
    unit_dir: Path, home: Path, checkout: Path
) -> None:
    _write(checkout / OPS_SUBPATH / "run_etf_nav_0_shard.sh")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-q", "-m", "add shard 0")
    unit_text = (
        "[Service]\n"
        f"ExecStart={home}/checkout/.venv/bin/sh "
        f"{home}/checkout/{OPS_SUBPATH}/run_etf_nav_%i_shard.sh %i 4\n"
    )
    _write(unit_dir / "etf-nav-backfill@.service", unit_text)

    unexpanded = _audit(unit_dir, home)
    expanded = _audit(unit_dir, home, instance="0")

    # Counterfactual: expanding %i to "" would probe `run_etf_nav__shard.sh` and report a
    # missing_file that no real instance ever referenced.
    assert unexpanded.counts.get(checker.REASON_UNRESOLVED_INSTANCE) == 1
    assert _findings_by_path(unexpanded) == {}
    assert unexpanded.non_green_units == ["etf-nav-backfill@.service"]
    assert not any("%i" in path for path in _paths(expanded))
    assert _findings_by_path(expanded)[f"{home}/checkout/{OPS_SUBPATH}/run_etf_nav_0_shard.sh"] == (
        checker.CLASSIFICATION_OK
    )
    # The uncommitted shard 3 is a genuine backlog item, not an artefact of expansion.
    expanded_three = _audit(unit_dir, home, instance="3")
    assert (
        _findings_by_path(expanded_three)[f"{home}/checkout/{OPS_SUBPATH}/run_etf_nav_3_shard.sh"]
        == checker.CLASSIFICATION_MISSING_FILE
    )


def test_percent_h_percent_n_and_double_percent_are_expanded(
    unit_dir: Path, home: Path, checkout: Path
) -> None:
    _write(checkout / OPS_SUBPATH / "worker.py", "print('ok')\n")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-q", "-m", "add worker")
    _write(
        unit_dir / "worker.service",
        f"[Service]\nExecStart={home}/checkout/{OPS_SUBPATH}/worker.py --unit %n --literal %%h\n",
    )

    summary = _audit(unit_dir, home)
    resolved = summary.reports[0].exec_lines[0].resolved

    assert resolved == f"{home}/checkout/{OPS_SUBPATH}/worker.py --unit worker.service --literal %h"
    assert _findings_by_path(summary) == {
        f"{home}/checkout/{OPS_SUBPATH}/worker.py": checker.CLASSIFICATION_OK
    }
    # Counterfactual: expanding `%%` twice would turn the literal `%h` back into the home
    # directory and invent a referenced path.
    assert "%h" in resolved.split("--literal")[1]


def test_relative_target_resolves_against_working_directory(
    unit_dir: Path, home: Path, checkout: Path
) -> None:
    _write(
        unit_dir / "relative.service",
        "[Service]\n"
        f"WorkingDirectory={home}/checkout/{OPS_SUBPATH}\n"
        "ExecStart=bash scripts/missing_runner.py\n",
    )

    summary = _audit(unit_dir, home)

    # Counterfactual: absolute-only scanning would report this unit green.
    assert _findings_by_path(summary) == {
        f"{home}/checkout/{OPS_SUBPATH}/scripts/missing_runner.py": checker.CLASSIFICATION_MISSING_FILE
    }


def test_multiple_exec_lines_and_quoted_arguments(
    unit_dir: Path, home: Path, checkout: Path
) -> None:
    spaced = _write(checkout / OPS_SUBPATH / "run with space.py", "print('spaced')\n")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-q", "-m", "add spaced worker")
    _write(
        unit_dir / "multi.service",
        "[Service]\n"
        f"WorkingDirectory={home}/checkout/{OPS_SUBPATH}\n"
        f"ExecStartPre=/bin/sh -c 'echo %n'\n"
        f'ExecStart="{home}/checkout/{OPS_SUBPATH}/run with space.py" --label "hello world/folder"\n'
        f"ExecStartPost={home}/checkout/{OPS_SUBPATH}/tracked_worker.py --note 'tail /log'\n",
    )

    summary = _audit(unit_dir, home)
    report = summary.reports[0]

    assert [line.key for line in report.exec_lines] == [
        "ExecStartPre",
        "ExecStart",
        "ExecStartPost",
    ]
    assert _findings_by_path(summary) == {
        str(spaced): checker.CLASSIFICATION_OK,
        f"{home}/checkout/{OPS_SUBPATH}/tracked_worker.py": checker.CLASSIFICATION_OK,
    }
    # Counterfactual: without shell-aware splitting the argument `hello world/folder` and the
    # `tail /log` fragment would be reported as missing repository paths.
    assert not any("hello world" in path for path in _paths(summary))
    assert not any(path.endswith("/log") for path in _paths(summary))


def test_execution_modifier_prefixes_are_stripped(
    unit_dir: Path, home: Path, checkout: Path
) -> None:
    _write(
        unit_dir / "prefixed.service",
        "[Service]\n"
        f"ExecStartPre=-{home}/checkout/{OPS_SUBPATH}/absent_preparer.sh\n"
        f"ExecStart=@{home}/checkout/{OPS_SUBPATH}/tracked_worker.py\n",
    )

    summary = _audit(unit_dir, home)

    # Counterfactual: keeping the '-' in the token would make an absolute path look relative.
    assert _findings_by_path(summary) == {
        f"{home}/checkout/{OPS_SUBPATH}/absent_preparer.sh": checker.CLASSIFICATION_MISSING_FILE,
        f"{home}/checkout/{OPS_SUBPATH}/tracked_worker.py": checker.CLASSIFICATION_OK,
    }


# --------------------------------------------------------------------------- scope boundaries


def test_paths_outside_any_checkout_are_ignored_not_misreported(
    unit_dir: Path, home: Path, checkout: Path, tmp_path: Path
) -> None:
    outside = _write(tmp_path / "outside-repo" / OPS_SUBPATH / "node_worker.py", "x\n")
    _write(
        unit_dir / "frontend.service",
        "[Service]\n"
        "ExecStart=/usr/bin/env node "
        f"{outside} --host 127.0.0.1 --port 3000 --strictPort\n",
    )

    scoped = _audit(unit_dir, home, repo_scope=checkout)
    auto = _audit(unit_dir, home)

    # Counterfactual: reporting `/usr/bin/env` or a non-repo path as a lost repo asset would make
    # every unit look broken and destroy the missing_file signal.
    for summary in (scoped, auto):
        assert _findings_by_path(summary) == {}
        assert checker.REASON_OUTSIDE_REPO in summary.reports[0].skipped
        assert summary.non_green_units == []
    assert f"{outside}" in auto.reports[0].skipped[checker.REASON_OUTSIDE_REPO]


def test_repo_scope_limits_findings_to_one_checkout(
    unit_dir: Path, home: Path, checkout: Path
) -> None:
    missing = f"{home}/checkout/{OPS_SUBPATH}/absent.py"
    _write(unit_dir / "scoped.service", f"[Service]\nExecStart={missing}\n")

    assert len(_findings_by_path(_audit(unit_dir, home))) == 1
    # Counterfactual: a scope that matches nothing must not silently report the unit green.
    other_scope = home / "some-other-checkout"
    other_scope.mkdir()
    _git(other_scope, "init", "-q", "-b", "main")
    empty = _audit(unit_dir, home, repo_scope=other_scope)
    assert _findings_by_path(empty) == {}
    assert empty.counts[checker.REASON_OUTSIDE_REPO] == 1


# --------------------------------------------------------------------------- credential safety


def test_environment_values_are_never_read_or_printed(
    unit_dir: Path, home: Path, checkout: Path
) -> None:
    _write(
        unit_dir / "secretive.service",
        "[Service]\n"
        f"Environment=DATABASE_URL=postgresql://user:{SECRET_SENTINEL}@localhost/db\n"
        f"Environment=DB_PASSWORD={SECRET_SENTINEL}\n"
        f"EnvironmentFile=-{home}/.config/ai-for-investor/{ENV_FILE_SENTINEL}\n"
        f"ExecStart={home}/checkout/{OPS_SUBPATH}/tracked_worker.py\n",
    )

    summary = _audit(unit_dir, home)
    rendered = "\n".join(checker.render_summary(summary))

    assert SECRET_SENTINEL not in rendered
    assert ENV_FILE_SENTINEL not in rendered
    assert not any(line.lstrip().startswith("Environment") for line in rendered.splitlines())
    assert not any(line.lstrip().startswith("EnvironmentFile") for line in rendered.splitlines())
    assert _findings_by_path(summary) == {
        f"{home}/checkout/{OPS_SUBPATH}/tracked_worker.py": checker.CLASSIFICATION_OK
    }
    # Counterfactual: the suppression is key-based, not string-based -- a legitimate repo path is
    # still printed even when its name looks credential-adjacent.
    loud = _write(
        checkout / OPS_SUBPATH / "load_runtime-overrides_secret_worker.py",
        "print('loud')\n",
    )
    _write(
        unit_dir / "loud.service",
        f"[Service]\nExecStart={loud}\n",
    )
    loud_rendered = "\n".join(checker.render_summary(_audit(unit_dir, home)))
    assert str(loud) in loud_rendered


# --------------------------------------------------------------------------- status plumbing


def test_systemctl_status_is_attached_per_unit(unit_dir: Path, home: Path, checkout: Path) -> None:
    _write(
        unit_dir / "etf-nav-backfill@.service",
        f"[Service]\nExecStart={home}/checkout/{OPS_SUBPATH}/absent.sh %i 4\n",
    )
    statuses = {
        "etf-nav-backfill@0.service": {
            "ActiveState": "activating",
            "Result": "timeout",
            "ExecMainStatus": "203",
        }
    }

    summary = _audit(unit_dir, home, instance="0", statuses=statuses)

    assert summary.reports[0].status["ActiveState"] == "activating"
    assert "ActiveState=activating" in "\n".join(checker.render_summary(summary))
    assert "ExecMainStatus=203" in "\n".join(checker.render_summary(summary))


def test_missing_status_is_counted_not_invented(unit_dir: Path, home: Path, checkout: Path) -> None:
    _write(
        unit_dir / "plain.service",
        f"[Service]\nExecStart={home}/checkout/{OPS_SUBPATH}/tracked_worker.py\n",
    )

    summary = _audit(unit_dir, home, statuses={})

    assert summary.counts["status_unavailable"] == 1
    assert summary.reports[0].status == {}
    # Counterfactual: an unread status must never be rendered as an active/healthy unit.
    assert "ActiveState=unknown" in "\n".join(checker.render_summary(summary))


# --------------------------------------------------------------------------- aggregation / CLI


def test_timers_without_exec_lines_are_counted_separately(unit_dir: Path, home: Path) -> None:
    _write(
        unit_dir / "recovery.timer",
        "[Timer]\nOnCalendar=*:0/1\nAccuracySec=1s\n[Install]\nWantedBy=timers.target\n",
    )

    summary = _audit(unit_dir, home)

    assert summary.counts["unit_files_scanned"] == 1
    assert summary.counts["units_without_exec"] == 1
    assert summary.reports == []


def test_aggregate_counts_and_non_green_list(unit_dir: Path, home: Path, checkout: Path) -> None:
    _write(
        unit_dir / "a-good.service",
        f"[Service]\nExecStart={home}/checkout/{OPS_SUBPATH}/tracked_worker.py\n",
    )
    _write(
        unit_dir / "b-missing.service",
        f"[Service]\nExecStart={home}/checkout/{OPS_SUBPATH}/gone.py\n",
    )
    _write(
        unit_dir / "c-untracked.service",
        f"[Service]\nExecStart={_write(checkout / OPS_SUBPATH / 'ghost.py')}\n",
    )

    summary = _audit(unit_dir, home)
    rendered = "\n".join(checker.render_summary(summary))

    assert summary.counts["units_audited"] == 3
    assert summary.counts["green_units"] == 1
    assert summary.counts["units_with_findings"] == 2
    assert summary.counts[checker.CLASSIFICATION_MISSING_FILE] == 1
    assert summary.counts[checker.CLASSIFICATION_UNTRACKED_BUT_PRESENT] == 1
    assert summary.counts[checker.CLASSIFICATION_OK] == 1
    assert summary.non_green_units == ["b-missing.service", "c-untracked.service"]
    assert "non-green units: b-missing.service, c-untracked.service" in rendered
    assert "units_audited=3" in rendered


def test_main_exits_zero_without_the_flag_and_one_with_it(
    unit_dir: Path, home: Path, checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(
        unit_dir / "flagged.service",
        f"[Service]\nExecStart={home}/checkout/{OPS_SUBPATH}/gone.py\n",
    )
    base = [
        "--unit-dir",
        str(unit_dir),
        "--home",
        str(home),
        "--repo",
        str(checkout),
        "--no-systemctl",
    ]

    assert checker.main(base) == 0
    assert checker.main([*base, "--fail-on-findings"]) == 1
    out = capsys.readouterr().out
    assert "missing_file" in out
    # Counterfactual: a default exit code of 1 would have turned the known owner-tracked backlog
    # into a red build the moment this ran in CI.


def test_main_reports_the_real_template_shape(
    home: Path, unit_dir: Path, checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(
        unit_dir / "ai-for-investor-etf-nav-backfill@.service",
        "[Service]\n"
        f"WorkingDirectory={home}/checkout/{OPS_SUBPATH}\n"
        "Environment=PYTHONUNBUFFERED=1\n"
        f"ExecStart={home}/checkout/{OPS_SUBPATH}/run_etf_nav_shard.sh %i 4\n",
    )

    assert (
        checker.main(
            [
                "--unit-dir",
                str(unit_dir),
                "--home",
                str(home),
                "--no-systemctl",
                "--repo",
                str(checkout),
                "--instance",
                "0",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "missing_file" in out
    assert "run_etf_nav_shard.sh" in out
    assert "PYTHONUNBUFFERED" not in out
    # The instantiated name, not just the template file, is what an operator has to act on.
    assert "etf-nav-backfill@0.service" in out


def test_repo_flag_and_all_repos_flag_choose_the_scope(
    home: Path, unit_dir: Path, checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if checker.own_checkout(timeout=1.0) is None:
        pytest.skip("the auditor script is not inside a git checkout in this environment")
    ghost = _write(checkout / OPS_SUBPATH / "ghost.py", "print('untracked')\n")
    _write(unit_dir / "ghost.service", f"[Service]\nExecStart={ghost}\n")
    common = ["--unit-dir", str(unit_dir), "--home", str(home), "--no-systemctl"]

    # Default scope is the repository holding the auditor, so the throwaway checkout is ignored...
    assert checker.main(common) == 0
    default_out = capsys.readouterr().out
    assert checker.REASON_OUTSIDE_REPO in default_out
    # ...while --all-repos audits every checkout a unit references and finds the ghost asset, and
    # --repo pins the scope to the checkout the operator is asking about.
    assert checker.main([*common, "--all-repos", "--fail-on-findings"]) == 1
    assert checker.CLASSIFICATION_UNTRACKED_BUT_PRESENT in capsys.readouterr().out
    assert checker.main([*common, "--repo", str(checkout), "--fail-on-findings"]) == 1
    assert checker.REASON_OUTSIDE_REPO not in capsys.readouterr().out


def test_template_instances_are_discovered_from_wanted_by_links(
    unit_dir: Path, home: Path, checkout: Path
) -> None:
    for instance in ("0", "1"):
        script = checkout / OPS_SUBPATH / f"run_etf_nav_{instance}_shard.sh"
        _write(script)
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-q", "-m", "add shards 0 and 1")
    _write(checkout / OPS_SUBPATH / "run_etf_nav_2_shard.sh")  # exists but untracked
    _write(
        unit_dir / "etf-nav-backfill@.service",
        f"[Service]\nExecStart={home}/checkout/{OPS_SUBPATH}/run_etf_nav_%i_shard.sh %i 4\n",
    )
    wants = unit_dir / "default.target.wants"
    wants.mkdir()
    for instance in ("0", "1", "2"):
        (wants / f"etf-nav-backfill@{instance}.service").symlink_to(
            unit_dir / "etf-nav-backfill@.service"
        )

    summary = _audit(unit_dir, home)

    # Counterfactual: without instance discovery the template stays a single unresolved report and
    # the untracked shard 2 -- the actual defect -- never appears.
    assert [report.unit_name for report in summary.reports] == [
        "etf-nav-backfill@0.service",
        "etf-nav-backfill@1.service",
        "etf-nav-backfill@2.service",
    ]
    assert _findings_by_path(summary) == {
        f"{home}/checkout/{OPS_SUBPATH}/run_etf_nav_0_shard.sh": checker.CLASSIFICATION_OK,
        f"{home}/checkout/{OPS_SUBPATH}/run_etf_nav_1_shard.sh": checker.CLASSIFICATION_OK,
        f"{home}/checkout/{OPS_SUBPATH}/run_etf_nav_2_shard.sh": (
            checker.CLASSIFICATION_UNTRACKED_BUT_PRESENT
        ),
    }
    assert summary.non_green_units == ["etf-nav-backfill@2.service"]
    assert summary.counts.get(checker.REASON_UNRESOLVED_INSTANCE, 0) == 0


def test_linked_worktree_paths_share_the_repository_scope(
    unit_dir: Path, home: Path, checkout: Path, tmp_path: Path
) -> None:
    worktree = tmp_path / "wt"
    _git(checkout, "worktree", "add", "-q", str(worktree), "-b", "wt-branch")
    _write(
        unit_dir / "worktree.service",
        f"[Service]\nExecStart={worktree}/{OPS_SUBPATH}/ghost_in_worktree.py\n",
    )

    summary = _audit(unit_dir, home, repo_scope=checkout)

    # Counterfactual: comparing checkout *paths* instead of repository identity would call the
    # linked worktree "outside the repo" and report a clean unit.
    assert _findings_by_path(summary) == {
        f"{worktree}/{OPS_SUBPATH}/ghost_in_worktree.py": checker.CLASSIFICATION_MISSING_FILE
    }


def test_main_fails_on_missing_unit_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert checker.main(["--unit-dir", str(tmp_path / "nope"), "--no-systemctl"]) == 2
    assert "unit directory does not exist" in capsys.readouterr().err


def test_classifications_constant_matches_reported_values() -> None:
    assert checker.CLASSIFICATIONS == ("missing_file", "untracked_but_present", "ok")
    for classification in checker.CLASSIFICATIONS:
        assert classification in _CHECKER_PATH.read_text(encoding="utf-8")
