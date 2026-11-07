"""AC01 runtime-asset surface: every file a live user unit names in ExecStart, and where it lives.

The wave-29 instrument only asked "is the ExecStart target missing on disk". AC01's defect class is
wider: a unit can execute a file that exists on disk but in no git ref (unreviewable code running
in production), or a file in a ref that was never deployed. This audit answers all three questions
per target: on disk, in `origin/dev`, in *any* ref.

Read-only: `systemctl --user show`, os.path, and git plumbing (`cat-file -e`, `rev-list --all`).
Nothing is written outside --json-out.
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
PROPS = ("ActiveState", "SubState", "UnitFileState", "Result", "NRestarts", "ExecMainStartTimestamp")
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
    out: list[str] = []
    for line in text.splitlines():
        if not line.strip().startswith("ExecStart="):
            continue
        rhs = line.split("=", 1)[1].strip().lstrip("-+")
        for token in rhs.split():
            token = token.replace("%h", os.path.expanduser("~"))
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


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True, timeout=120)


def repo_relative(path: str) -> str | None:
    marker = "/ai-for-investor/"
    if marker not in path:
        return None
    return path.split(marker, 1)[1]


RUNTIME_DIR_MARKERS = ("/.venv/", "/node_modules/")


def is_source_asset(rel: str) -> bool:
    """Interpreter and package binaries legitimately live outside git; source assets do not."""
    if any(marker in rel for marker in RUNTIME_DIR_MARKERS):
        return False
    return rel.endswith((".py", ".sh", ".js", ".ts"))


def classify(path: str) -> dict[str, object]:
    rel = repo_relative(path)
    info: dict[str, object] = {"path": path, "repo_relative": rel, "exists_on_disk": os.path.exists(path)}
    if rel is None:
        return info
    info["source_asset"] = is_source_asset(rel)
    info["in_head"] = git("cat-file", "-e", f"HEAD:{rel}").returncode == 0
    info["in_dev"] = git("cat-file", "-e", f"origin/dev:{rel}").returncode == 0
    info["in_any_ref"] = bool(git("rev-list", "--all", "--", rel).stdout.strip())
    if info["exists_on_disk"]:
        info["sha256"] = subprocess.run(["sha256sum", path], capture_output=True, text=True).stdout.split()[0]
    return info


def main() -> None:
    out_path = sys.argv[1] if len(sys.argv) > 1 else "-"
    loaded = systemctl(["list-units", "--all", "--no-pager", "--no-legend", PREFIX + "*"])
    instances = [line.split()[0] for line in loaded.splitlines() if line.split()]

    units = []
    for fname in sorted(os.listdir(UNIT_DIR)):
        if not fname.endswith(".service") or not fname.startswith(PREFIX):
            continue
        text = open(os.path.join(UNIT_DIR, fname), encoding="utf-8").read()
        targets = exec_targets(text)
        if not targets:
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
        audited = [classify(t) for t in targets]
        units.append(
            {
                "unit_file": fname,
                "queried_units": queried,
                "state": state,
                "targets": audited,
                "targets_missing_on_disk": [t["path"] for t in audited if not t["exists_on_disk"]],
                "unversioned_source_on_disk": [
                    t["path"]
                    for t in audited
                    if t.get("source_asset") and t["exists_on_disk"] and not t.get("in_any_ref")
                ],
                "source_assets_not_in_any_ref": [
                    t["path"]
                    for t in audited
                    if t.get("source_asset") and not t.get("in_any_ref")
                ],
                "targets_in_ref_but_not_dev": [
                    t["path"] for t in audited if t.get("in_any_ref") and not t.get("in_dev")
                ],
            }
        )

    doc = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo_root": REPO,
        "units_audited": len(units),
        "units_with_missing_on_disk": sum(1 for u in units if u["targets_missing_on_disk"]),
        "units_executing_unversioned_source": sum(1 for u in units if u["unversioned_source_on_disk"]),
        "units": units,
    }
    text = json.dumps(doc, indent=2, ensure_ascii=False)
    if out_path == "-":
        print(text)
    else:
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print(
            f"units={doc['units_audited']} missing_on_disk={doc['units_with_missing_on_disk']} "
            f"unversioned_running={doc['units_executing_unversioned_source']} -> {out_path}"
        )


if __name__ == "__main__":
    main()
