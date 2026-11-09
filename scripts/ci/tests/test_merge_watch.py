"""Regression tests for scripts/dev/merge_watch.py.

The watcher decides whether a PR may be squashed into dev, so the two things that
went wrong by hand are pinned here: a re-run appends a new check run instead of
replacing the failed one (reading the raw list makes a green PR look red forever),
and a self-review that is bound to an older head must not count as the current
one (easy to miss after a force-push or an amend).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
WATCHER_PATH = REPO_ROOT / "scripts" / "dev" / "merge_watch.py"

HEAD = "a" * 40
OTHER = "b" * 40


def _load_watcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "merge_watch_under_test", WATCHER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _run(app: str, name: str, run_id: int, status: str, conclusion: str | None) -> dict:
    return {
        "id": run_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "app": {"name": app},
    }


def _review(sha: str, state: str = "COMMENTED", body: str | None = None) -> dict:
    return {
        "commit_id": sha,
        "state": state,
        "body": body
        if body is not None
        else "## Author self-review\n\n- Decision: APPROVED\n- [x] Code and scope reviewed\n",
    }


def test_a_rerun_appends_and_the_newest_attempt_wins() -> None:
    watcher = _load_watcher()
    runs = [
        _run("github-actions", "Backend", 10, "completed", "failure"),
        _run("github-actions", "Backend", 11, "completed", "success"),
    ]

    latest = watcher.latest_check_runs(runs)

    assert len(latest) == 1
    assert latest[0]["conclusion"] == "success"


def test_different_apps_with_the_same_name_are_kept_apart() -> None:
    watcher = _load_watcher()
    runs = [
        _run("github-actions", "Backend", 10, "completed", "success"),
        _run("some-other-app", "Backend", 11, "completed", "failure"),
    ]

    assert len(watcher.latest_check_runs(runs)) == 2


def test_all_green_and_bound_is_the_only_unblocked_state() -> None:
    watcher = _load_watcher()
    reasons = watcher.blocking_reasons(
        check_runs=[_run("github-actions", "Backend", 10, "completed", "success")],
        reviews=[_review(HEAD)],
        head_sha=HEAD,
        mergeable=True,
    )

    assert reasons == []


def test_pending_and_red_and_unmergeable_each_block() -> None:
    watcher = _load_watcher()
    pending = watcher.blocking_reasons(
        check_runs=[_run("github-actions", "Backend", 10, "queued", None)],
        reviews=[_review(HEAD)],
        head_sha=HEAD,
        mergeable=True,
    )
    red = watcher.blocking_reasons(
        check_runs=[_run("github-actions", "Backend", 10, "completed", "failure")],
        reviews=[_review(HEAD)],
        head_sha=HEAD,
        mergeable=True,
    )
    dirty = watcher.blocking_reasons(
        check_runs=[_run("github-actions", "Backend", 10, "completed", "success")],
        reviews=[_review(HEAD)],
        head_sha=HEAD,
        mergeable="dirty",
    )

    assert any(reason.startswith("pending=") for reason in pending)
    assert any(reason.startswith("red=") for reason in red)
    assert "mergeable!=true" in dirty


def test_a_self_review_bound_to_an_older_head_does_not_count() -> None:
    watcher = _load_watcher()
    reasons = watcher.blocking_reasons(
        check_runs=[_run("github-actions", "Backend", 10, "completed", "success")],
        reviews=[_review(OTHER)],
        head_sha=HEAD,
        mergeable=True,
    )

    assert "self-review-not-bound" in reasons


def test_a_self_review_without_the_markers_does_not_count() -> None:
    watcher = _load_watcher()
    reasons = watcher.blocking_reasons(
        check_runs=[_run("github-actions", "Backend", 10, "completed", "success")],
        reviews=[_review(HEAD, body="just a normal comment")],
        head_sha=HEAD,
        mergeable=True,
    )

    assert "self-review-not-bound" in reasons


def test_dry_run_is_the_default() -> None:
    watcher = _load_watcher()
    parser = watcher.build_parser()

    assert parser.parse_args(["--repo", "cloudQuant/ai-for-investor"]).apply is False
    assert (
        parser.parse_args(["--repo", "cloudQuant/ai-for-investor", "--apply"]).apply
        is True
    )


def test_the_token_prefers_the_environment_and_never_comes_from_argv(
    tmp_path: Path, monkeypatch
) -> None:
    watcher = _load_watcher()
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    monkeypatch.setattr(os.path, "expanduser", lambda _path: str(tmp_path / "missing"))

    assert watcher._token() == "from-env"

    monkeypatch.delenv("GITHUB_TOKEN")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert watcher._token() is None
