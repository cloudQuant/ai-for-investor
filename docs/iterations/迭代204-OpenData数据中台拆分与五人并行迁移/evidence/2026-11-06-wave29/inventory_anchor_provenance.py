"""Partition the migration inventory's content anchors by whether they ever described a commit.

Why this exists: `script_migration_inventory.csv` is cited as the AC01 baseline, and its
`source_sha256` column is read as "the content this row was reviewed against". This script shows
that reading is only partly true, and it separates the two failure kinds, which need different fixes:

  match                 the anchor equals today's bytes.
  drifted               the anchor differs, but equals some committed version across --all refs,
                        so the row was generated from versioned content and later work moved it.
  never_versioned       the anchor equals no committed version at all, so that row was generated
                        against content that is not, and never was, in version control.
  missing_file          the row names a path that does not exist in the tree.

Read-only: it only runs `git log` / `git show` / `git cat-file` and reads files.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import os
import subprocess
import sys

REPO = os.environ.get("AFI_REPO", "/home/yun/Documents/ai-for-investor")
CSVREL = "docs/iterations/迭代204-OpenData数据中台拆分与五人并行迁移/script_migration_inventory.csv"


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True)


def classify(path: str, want: str, max_commits: int) -> tuple[str, str, str]:
    """Return (bucket, last_touching_commit, matching_commit)."""
    last = git("log", "-1", "--format=%H|%ad", "--date=short", "--", path)
    last_touch = last.stdout.decode().strip() if last.returncode == 0 else ""
    if not os.path.exists(os.path.join(REPO, path)):
        return "missing_file", last_touch, ""
    with open(os.path.join(REPO, path), "rb") as fh:
        if hashlib.sha256(fh.read()).hexdigest() == want:
            return "match", last_touch, ""
    shas = git("log", "--all", "--format=%H", "--", path).stdout.decode().split()[:max_commits]
    for c in shas:
        shown = git("show", f"{c}:{path}")
        if shown.returncode == 0 and hashlib.sha256(shown.stdout).hexdigest() == want:
            return "drifted", last_touch, c[:9]
    return "never_versioned", last_touch, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-commits", type=int, default=40)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    with io.open(os.path.join(REPO, CSVREL), encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    buckets: collections.Counter = collections.Counter()
    never: list[dict[str, str]] = []
    drift_by_commit: collections.Counter = collections.Counter()
    for r in rows:
        bucket, last_touch, hit = classify(r["source_path"], r["source_sha256"], args.max_commits)
        buckets[bucket] += 1
        if bucket == "never_versioned":
            never.append({
                "path": os.path.relpath(r["source_path"], "src/backend/app/data_fetch/scripts"),
                "last_touching_commit": last_touch,
                "asset_family": r.get("asset_family", ""),
            })
        elif bucket == "drifted":
            drift_by_commit[hit] += 1

    doc = {
        "rows": len(rows),
        "buckets": dict(buckets),
        "drifted_anchor_commit_counts": dict(drift_by_commit.most_common(10)),
        "never_versioned_rows": sorted(never, key=lambda item: item["path"]),
        "meaning": (
            "never_versioned anchors cannot be reproduced from any ref, so the AC01 baseline for "
            "those rows has no provenance; drifted anchors are re-derivable from history."
        ),
    }
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    if args.out:
        io.open(args.out, "w", encoding="utf-8").write(text)
    print(text, file=sys.stderr if args.out else sys.stdout)


if __name__ == "__main__":
    main()
