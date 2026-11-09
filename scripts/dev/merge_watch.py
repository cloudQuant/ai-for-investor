#!/usr/bin/env python3
"""Merge open pull requests whose gates are green and whose author self-review is bound.

This is the versioned form of the throwaway watcher the iteration-204 merge queue was run with.
It is DRY-RUN by default: it prints what it would merge and why it would wait, and only touches
GitHub when ``--apply`` is given. The token is read from ``GITHUB_TOKEN``/``GH_TOKEN`` or
``~/.git-credentials`` and handed to curl through the environment — never argv, never stdout.

Why it exists rather than "just click merge": the gate state of a PR is not the raw check-run
list. A re-run appends a *new* check run for the same name instead of replacing the old one, so a
PR that was re-run and is now green still looks red forever if you read the list naively. It also
has to refuse a PR whose self-review is bound to an older commit than the head, which is easy to
miss by eye after a force-push or an amend.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

API = "https://api.github.com"
LEDGER_COLUMNS = (
    "utc",
    "repo",
    "pr",
    "head_sha",
    "verdict",
    "checks",
    "detail",
)


def _token() -> str | None:
    """CI exports GITHUB_TOKEN; a maintainer shell keeps it in ~/.git-credentials."""
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value
    path = os.path.expanduser("~/.git-credentials")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                match = re.match(r"https://[^:@/]+:([^@]+)@github\.com", line.strip())
                if match:
                    return match.group(1)
    return None


def _api(path: str, method: str = "GET", payload: dict | None = None) -> object:
    """Call the REST API with the token in the environment, never in argv."""
    token = _token()
    script = 'curl -s --max-time 90 -X "$GH_METHOD"'
    if token:
        script += ' -H "Authorization: Bearer $GITHUB_TOKEN"'
    script += (
        ' -H "Accept: application/vnd.github+json" -H "Content-Type: application/json"'
    )
    script += ' ${GH_DATA:+-d "$GH_DATA"} "$GH_URL"'
    env = {**os.environ, "GH_URL": f"{API}{path}", "GH_METHOD": method}
    if token:
        env["GITHUB_TOKEN"] = token
    if payload is not None:
        env["GH_DATA"] = json.dumps(payload)
    proc = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env, timeout=120
    )
    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        return {"__raw__": proc.stdout[:200], "__err__": proc.stderr[:200]}


def latest_check_runs(check_runs: list[dict]) -> list[dict]:
    """Keep only the newest run per (app, name) — a re-run appends, it does not replace."""
    latest: dict[tuple[str, str], dict] = {}
    for run in check_runs:
        key = ((run.get("app") or {}).get("name", ""), run.get("name", ""))
        if key not in latest or run.get("id", 0) > latest[key].get("id", 0):
            latest[key] = run
    return list(latest.values())


def self_review_is_bound(reviews: list[dict], head_sha: str) -> bool:
    """The author self-review must name the exact current head and be a COMMENTED review."""
    for review in reviews:
        body = review.get("body") or ""
        if review.get("commit_id") != head_sha:
            continue
        if review.get("state") not in ("COMMENTED", "APPROVED"):
            continue
        if "Author self-review" in body and "Decision: APPROVED" in body:
            return True
    return False


def blocking_reasons(
    *, check_runs: list[dict], reviews: list[dict], head_sha: str, mergeable: object
) -> list[str]:
    """Return every reason this PR must not be merged right now; empty means safe."""
    reasons: list[str] = []
    current = latest_check_runs(check_runs)
    pending = [run["name"] for run in current if run.get("status") != "completed"]
    red = [
        f"{run['name']}={run.get('conclusion')}"
        for run in current
        if run.get("status") == "completed"
        and run.get("conclusion") not in ("success", "skipped", "neutral")
    ]
    if red:
        reasons.append("red=" + ",".join(sorted(red)[:3]))
    if pending:
        reasons.append(f"pending={len(pending)}/{len(current)}")
    if not self_review_is_bound(reviews, head_sha):
        reasons.append("self-review-not-bound")
    if mergeable is not True:
        reasons.append("mergeable!=true")
    return reasons


def _all_check_runs(repo: str, sha: str) -> list[dict]:
    runs: list[dict] = []
    page = 1
    while True:
        payload = _api(
            f"/repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}"
        )
        if not isinstance(payload, dict):
            break
        runs.extend(payload.get("check_runs") or [])
        if page * 100 >= int(payload.get("total_count") or 0):
            break
        page += 1
    return runs


def inspect(repo: str, number: int) -> dict | None:
    """Return the decision state for one PR, or None when it is no longer open."""
    pr = _api(f"/repos/{repo}/pulls/{number}")
    if not isinstance(pr, dict) or pr.get("state") != "open":
        return None
    head_sha = (pr.get("head") or {}).get("sha", "")
    reviews = _api(f"/repos/{repo}/pulls/{number}/reviews?per_page=100")
    check_runs = _all_check_runs(repo, head_sha)
    return {
        "number": number,
        "head_sha": head_sha,
        "checks": len(check_runs),
        "reasons": blocking_reasons(
            check_runs=check_runs,
            reviews=reviews if isinstance(reviews, list) else [],
            head_sha=head_sha,
            mergeable=pr.get("mergeable"),
        ),
    }


def write_ledger(path: str, rows: list[list[str]]) -> None:
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as handle:
        if new:
            handle.write("\t".join(LEDGER_COLUMNS) + "\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        action="append",
        required=True,
        help="owner/name; repeat for several repositories",
    )
    parser.add_argument("--minutes", type=int, default=60, help="how long to watch")
    parser.add_argument("--poll-seconds", type=int, default=240)
    parser.add_argument(
        "--exclude",
        type=int,
        action="append",
        default=[],
        help="PR number to leave alone (repeatable)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually merge; without it this is a dry run",
    )
    parser.add_argument("--ledger", default=None, help="optional TSV path to append to")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    deadline = time.time() + args.minutes * 60
    merged: list[tuple[str, int, str]] = []
    while True:
        blocked = 0
        rows: list[list[str]] = []
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        for repo in args.repo:
            pulls = _api(f"/repos/{repo}/pulls?state=open&per_page=100")
            if not isinstance(pulls, list):
                print(f"{repo}: could not list pulls", file=sys.stderr)
                continue
            for pull in sorted(pulls, key=lambda item: item.get("number", 0)):
                number = int(pull.get("number", 0))
                if number in args.exclude:
                    continue
                state = inspect(repo, number)
                if state is None:
                    continue
                if state["reasons"]:
                    blocked += 1
                    detail = "; ".join(state["reasons"])
                    rows.append(
                        [
                            stamp,
                            repo,
                            str(number),
                            state["head_sha"][:10],
                            "WAIT",
                            str(state["checks"]),
                            detail,
                        ]
                    )
                    print(f"{repo}#{number}: WAIT {detail}")
                    continue
                if not args.apply:
                    rows.append(
                        [
                            stamp,
                            repo,
                            str(number),
                            state["head_sha"][:10],
                            "WOULD-MERGE",
                            str(state["checks"]),
                            "dry run",
                        ]
                    )
                    print(f"{repo}#{number}: WOULD-MERGE (dry run; pass --apply)")
                    continue
                result = _api(
                    f"/repos/{repo}/pulls/{number}/merge",
                    "PUT",
                    {"merge_method": "squash"},
                )
                ok = isinstance(result, dict) and result.get("merged")
                detail = str(result.get("sha") or result.get("message") or "")[:80]
                rows.append(
                    [
                        stamp,
                        repo,
                        str(number),
                        state["head_sha"][:10],
                        "MERGED" if ok else "REFUSED",
                        str(state["checks"]),
                        detail,
                    ]
                )
                print(
                    f"{repo}#{number}: {'MERGED ' + detail[:10] if ok else 'REFUSED ' + detail}"
                )
                if ok:
                    merged.append((repo, number, detail[:10]))
        if args.ledger and rows:
            write_ledger(args.ledger, rows)
        if time.time() >= deadline:
            print(f"deadline reached; merged={len(merged)} blocked={blocked}")
            return 0
        if blocked == 0:
            print(f"nothing blocked; merged={len(merged)}")
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
