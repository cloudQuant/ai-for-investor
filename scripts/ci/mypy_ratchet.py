#!/usr/bin/env python3
"""Repo-wide mypy error ratchet (iteration 177 §E).

Background
----------
``backend-lint`` runs a *blocking* ``mypy app`` step, but because CI never
fired on the ``dev`` branch (the F1 root cause fixed in 177 §A) the global
type-error count silently rotted to >1000. The per-package strict overrides in
``pyproject.toml`` only guard the enrolled packages; everything else is
unchecked. This script closes that gap *without* pretending the 1000+ existing
errors are fixed:

- It records the current whole-``app`` error count as a frozen baseline.
- CI fails only when the count *increases* (a regression / new debt).
- When the count drops, it nudges you to lower the baseline (the ratchet).

This is deliberately count-based (not a per-error allowlist) to stay simple and
fast. It is only meaningful when the mypy version matches the one used to
generate the baseline, so the baseline file pins that version and this script
fails on mismatch.

Usage
-----
    python scripts/ci/mypy_ratchet.py                       # check `mypy app`
    python scripts/ci/mypy_ratchet.py --scope collection    # check the data-fetch scripts
    python scripts/ci/mypy_ratchet.py --update              # rewrite baseline to current
    python scripts/ci/mypy_ratchet.py --advisory            # never exit non-zero

Exit codes: 0 = ok / drop-allowed, 1 = regression (more errors than baseline, or fewer
source files checked than the baseline records).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from baseline_update_guard import assert_update_allowed  # noqa: E402

# Run mypy over the whole backend app package from the backend root.
_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "src" / "backend"
_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Scope:
    """One type-checked plane: what mypy is pointed at, and where its ratchet lives.

    ``collection`` exists because ``pyproject.toml`` excludes ``scripts/``, and mypy matches
    that as a substring, which also swallowed ``app/data_fetch/scripts`` - 1108 tracked files
    no gate ever read. It gets its own config (same options, narrowed exclude) and its own
    baseline so the repo-wide ``app`` count keeps its own meaning.
    """

    name: str
    target: str
    config: Path | None
    baseline: Path

    @property
    def argv(self) -> list[str]:
        argv = [sys.executable, "-m", "mypy"]
        if self.config is not None:
            argv += ["--config-file", str(self.config)]
        return argv + [self.target]


_SCOPES: dict[str, Scope] = {
    "app": Scope(
        name="app",
        target="app",
        config=None,
        baseline=Path(__file__).resolve().parent / "mypy_app_baseline.json",
    ),
    "collection": Scope(
        name="collection",
        target="app/data_fetch/scripts",
        config=_REPO_ROOT / "config" / "mypy_collection.ini",
        baseline=Path(__file__).resolve().parent / "mypy_collection_baseline.json",
    ),
}

# mypy summary line, e.g. "Found 1055 errors in 103 files (checked 355 ...)".
_SUMMARY_RE = re.compile(r"Found (\d+) errors? in \d+ files?")
# The size of the plane, so a narrowing that hides files is a failure rather than a win.
_CHECKED_RE = re.compile(r"checked (\d+) source files?")
_SUCCESS_RE = re.compile(r"Success: no issues found in (\d+) source files?")


def _run_mypy(scope: Scope) -> tuple[int, int, str]:
    """Return (error_count, files_checked, raw_output). 0 errors when mypy prints Success."""
    proc = subprocess.run(scope.argv, cwd=_BACKEND_ROOT, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    match = _SUMMARY_RE.search(out)
    checked = _CHECKED_RE.search(out) or _SUCCESS_RE.search(out)
    files_checked = int(checked.group(1)) if checked else 0
    if match:
        return int(match.group(1)), files_checked, out
    if "Success: no issues found" in out:
        return 0, files_checked, out
    # No recognizable summary — surface mypy's own output and treat as failure.
    print(out, file=sys.stderr)
    raise SystemExit("mypy_ratchet: could not parse mypy output (see above)")


def _mypy_version() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "--version"],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() or "unknown"


def _load_baseline(scope: Scope) -> dict:
    return json.loads(scope.baseline.read_text("utf-8"))


def _write_baseline(scope: Scope, count: int, files_checked: int, version: str) -> None:
    config_name = (
        None if scope.config is None else str(scope.config.relative_to(_REPO_ROOT))
    )
    payload = {
        "_comment": (
            f"mypy ratchet baseline for scope {scope.name!r} (`mypy {scope.target}`). "
            "CI fails when the plane reports MORE errors than baseline_errors, or when it "
            "checks FEWER source files than scope_files - a narrowed plane would otherwise "
            "read as progress. Lower the number whenever the count drops (the ratchet only "
            "turns one way); regenerate with the pinned mypy version via --update, which "
            "needs ALLOW_BASELINE_UPDATE=1."
        ),
        "scope": scope.name,
        "target": scope.target,
        "config": config_name,
        "baseline_errors": count,
        "scope_files": files_checked,
        "mypy_version": version,
        "baseline_date": date.today().isoformat(),
    }
    scope.baseline.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        choices=sorted(_SCOPES),
        default="app",
        help="which plane to check; 'app' is the repo-wide count, 'collection' is the "
        "data-fetch scripts that pyproject's `scripts/` exclude never reached",
    )
    parser.add_argument(
        "--update", action="store_true", help="rewrite baseline to current count"
    )
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="report only; always exit 0 (use while stabilising)",
    )
    args = parser.parse_args()
    scope = _SCOPES[args.scope]

    count, files_checked, _ = _run_mypy(scope)
    version = _mypy_version()

    if args.update:
        assert_update_allowed("mypy_ratchet")
        _write_baseline(scope, count, files_checked, version)
        print(
            f"mypy_ratchet[{scope.name}]: baseline updated -> {count} errors "
            f"in {files_checked} files checked ({version})"
        )
        return 0

    if not scope.baseline.is_file():
        if args.advisory:
            # Introducing a plane: report what it measures today, and let the reviewed
            # `--update` that freezes it come from this number rather than a local run.
            print(
                f"mypy_ratchet[{scope.name}]: advisory, no baseline yet - "
                f"errors={count} checked={files_checked} ({version})"
            )
            return 0
        raise SystemExit(
            f"mypy_ratchet: baseline file missing ({scope.baseline}). "
            "Run with --update to create it."
        )

    baseline = _load_baseline(scope)
    expected = int(baseline["baseline_errors"])
    base_version = str(baseline.get("mypy_version", "unknown"))

    if base_version != version:
        print(
            f"::error::mypy_ratchet: mypy version mismatch "
            f"(baseline={base_version!r}, running={version!r}); "
            "install the pinned version or regenerate the baseline intentionally."
        )
        return 0 if args.advisory else 1

    recorded_files = baseline.get("scope_files")
    if recorded_files is not None and files_checked < int(recorded_files):
        print(
            f"::error::mypy_ratchet[{scope.name}]: the plane shrank "
            f"({recorded_files} -> {files_checked} source files checked). A narrowed scope "
            "hides debt rather than fixing it: restore the files, or re-baseline through a "
            "reviewed `--update`."
        )
        return 0 if args.advisory else 1

    delta = count - expected
    print(
        f"mypy_ratchet[{scope.name}]: errors={count} baseline={expected} "
        f"delta={delta:+d} checked={files_checked}"
    )

    if count > expected:
        print(
            f"::error::mypy_ratchet[{scope.name}]: type errors increased by {delta} "
            f"({expected} -> {count}). Fix the new errors or justify a baseline bump."
        )
        return 0 if args.advisory else 1

    if count < expected:
        print(
            f"mypy_ratchet[{scope.name}]: errors dropped by {-delta}. Ratchet down by "
            f"running `python scripts/ci/mypy_ratchet.py --scope {scope.name} --update` "
            "and commit the baseline."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
