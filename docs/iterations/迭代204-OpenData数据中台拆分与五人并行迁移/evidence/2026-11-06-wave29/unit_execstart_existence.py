"""Read-only audit of user-level units whose ExecStart target exists nowhere.

Why: a systemd unit can be enabled, have a live timer, and still be permanently unable to run
because the file named in ExecStart is neither in version control nor on disk. No CI job and no
ledger row sees that; the only artefact is a failure counter, or a restart count in the thousands
for a template unit. This produces the numbers so AC01's runtime-asset surface and AC05's backfill
lanes can be stated as measurements rather than impressions.

Uses only `systemctl show` / `list-timers` / `list-units` reads, os.path.exists, and
`git ls-files --error-unmatch`. It changes nothing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

UNIT_DIR = os.path.expanduser("~/.config/systemd/user")
PREFIX = "ai-for-investor-"
REPO = "/home/yun/Documents/ai-for-investor"
PROPS = ("ActiveState", "UnitFileState", "ExecMainStartTimestamp", "NRestarts", "Result")
WORKING_DIR_RE = re.compile(r"^WorkingDirectory=(.+)$", re.MULTILINE)


def systemctl(args: list[str]) -> str:
    r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=60)
    return r.stdout


def show(unit: str) -> dict[str, str]:
    flags: list[str] = []
    for prop in PROPS:
        flags += ["-p", prop]
    raw = systemctl(["show", unit, *flags])
    return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)


def exec_targets(text: str) -> list[str]:
    """Repo file paths named by ExecStart, resolving %h and relative-path WorkingDirectory forms."""
    out: list[str] = []
    for line in text.splitlines():
        if not line.strip().startswith("ExecStart="):
            continue
        rhs = line.split("=", 1)[1].strip().lstrip("-+")
        for token in rhs.split():
            token = token.replace("%h", os.path.expanduser("~"))
            # relative forms such as `scripts/ops/x.py` (resolved via WorkingDirectory) have no
            # leading slash, so match the directory component rather than the absolute spelling.
            if not re.search(r"(^|/)(src|scripts)/", token):
                continue
            if not token.startswith("/"):
                wd = WORKING_DIR_RE.search(text)
                if wd is None:
                    continue
                token = os.path.join(wd.group(1).replace("%h", os.path.expanduser("~")), token)
            if token not in out:
                out.append(token)
    return out


def main() -> None:
    next_fire: dict[str, str] = {}
    for line in systemctl(["list-timers", "--all", "--no-pager", "--no-legend"]).splitlines():
        cols = line.split()
        for cell in cols:
            if cell.startswith(PREFIX) and cell.endswith(".timer"):
                next_fire[cell[:-6] + ".service"] = " ".join(cols[:2])

    loaded = systemctl(["list-units", "--all", "--no-pager", "--no-legend", PREFIX + "*"])
    instances = [line.split()[0] for line in loaded.splitlines() if line.split()]

    report = []
    for fname in sorted(os.listdir(UNIT_DIR)):
        if not fname.endswith(".service") or not fname.startswith(PREFIX):
            continue
        text = open(os.path.join(UNIT_DIR, fname), encoding="utf-8").read()
        targets = exec_targets(text)
        missing = [t for t in targets if not os.path.exists(t)]
        if not missing:
            continue

        if "@." in fname:
            base = fname.split("@")[0] + "@"
            queried = [u for u in instances if u.startswith(base)]
            state, best = {}, -1
            for unit in queried:
                one = show(unit)
                count = int(one.get("NRestarts") or 0)
                if count >= best:
                    best, state = count, one
        else:
            queried, state = [fname], show(fname)

        in_git = {}
        for path in missing:
            rel = path.split("/ai-for-investor/", 1)[-1] if "/ai-for-investor/" in path else path
            r = subprocess.run(["git", "-C", REPO, "ls-files", "--error-unmatch", rel],
                               capture_output=True, text=True)
            in_git[rel] = r.returncode == 0

        report.append({
            "unit": fname,
            "queried_units": queried,
            "state": state,
            "timer_next_elapse": next_fire.get(fname),
            "exec_targets_total": len(targets),
            "missing_on_disk": missing,
            "missing_path_in_git_index": in_git,
        })

    doc = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo_root": REPO,
        "units_with_missing_exec_targets": len(report),
        "units_still_on_a_live_timer": sum(1 for r in report if r["timer_next_elapse"]),
        "max_restarts_observed": max([int(r["state"].get("NRestarts") or 0) for r in report], default=0),
        "loaded_units_matching_prefix": len(instances),
        "missing_targets_also_absent_from_git": sum(
            1 for r in report if not any(r["missing_path_in_git_index"].values())
        ),
        "units": report,
        "meaning": ("A target missing from both disk and the git index cannot be run or rebuilt from "
                    "this repository. A live timer on such a unit keeps producing failure counters and "
                    "no data, so AC05 cannot treat these lanes as running."),
    }
    print(json.dumps(doc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
