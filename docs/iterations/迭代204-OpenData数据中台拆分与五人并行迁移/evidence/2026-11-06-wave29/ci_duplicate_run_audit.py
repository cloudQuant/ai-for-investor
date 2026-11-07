"""Read-only audit: how many CI runs does each repo start twice for the same commit?

Reproduces wave-29 section 24. OpenData's ci.yml triggers on both `push` (including the PR branch
prefixes) and `pull_request`, and its concurrency group is keyed by `github.ref`, which differs
between the two events -- so the same sha runs the full gate twice. ai-for-investor's pr-check.yml
triggers only on `pull_request` and therefore should show zero duplicates.

Cost is reported in runs, not minutes: this org's API returns null for `run_duration_ms`, `timing`
and per-job durations, so a minutes figure cannot be measured from here and is deliberately absent.
"""

from __future__ import annotations

import json
import subprocess
import sys

HELPER = "/tmp/it204/gh.sh"


def gh(path: str):
    r = subprocess.run(["bash", HELPER, path], capture_output=True, text=True, timeout=120)
    try:
        return json.loads(r.stdout)
    except Exception:  # noqa: BLE001
        return {}


def runs_for(repo: str, event: str, pages: int = 3, completed_only: bool = False):
    out = []
    for page in range(1, pages + 1):
        url = (f"https://api.github.com/repos/cloudQuant/{repo}/actions/runs"
               f"?per_page=100&page={page}&event={event}")
        if completed_only:
            url += "&status=completed"
        d = gh(url)
        got = d.get("workflow_runs", [])
        out += got
        if len(got) < 100:
            break
    return out


def main() -> None:
    for repo in ("ai-for-investor", "opendata"):
        pr = runs_for(repo, "pull_request")
        push = runs_for(repo, "push")
        pr_shas = {r["head_sha"] for r in pr}
        both = [r for r in push if r["head_sha"] in pr_shas]
        distinct = pr_shas | {r["head_sha"] for r in push}
        pr_c = {r["head_sha"] for r in pr if r["status"] == "completed"}
        push_c = [r for r in runs_for(repo, "push", completed_only=True) if r["head_sha"] in pr_c]
        print(json.dumps({
            "repo": repo,
            "distinct_shas_sampled": len(distinct),
            "shas_with_both_push_and_pr": len({r["head_sha"] for r in both}),
            "push_runs_sampled": len(push),
            "completed_pairs": len(push_c),
            "note": "minutes not obtainable: run_duration_ms/timing/job durations all null via API",
        }, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
