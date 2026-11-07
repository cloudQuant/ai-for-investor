"""Freeze the collection-plane mypy baseline from CI's own reading, never from a laptop run.

Why this exists: the ratchet's baseline may only be lowered using the number CI itself printed
(`mypy_ratchet.py --update` needs ALLOW_BASELINE_UPDATE=1 and measures whatever environment it is
called from). Iteration-204 wave 29 measured the same commit twice and got two different answers --
101 in CI's environment (Python 3.11 + config/requirements-dev.lock, pandas 3) and 159 in a laptop
venv (Python 3.13 + pandas 2.3 + pandas-stubs) -- so an unlabelled local number is not evidence.
This tool reads the authoritative value straight out of the `Backend - Mypy Ratchet (collection
scripts, advisory)` job log of a run on a given ref, and only writes a baseline from it when the
provenance is complete.

Read-only against GitHub. It writes a file only with --write.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

API = "https://api.github.com"
JOB_NAME = "Backend - Mypy Ratchet (collection scripts, advisory)"
READING_RE = re.compile(
    r"mypy_ratchet\[collection\]:[^-\n]*-\s*errors=(\d+)\s+checked=(\d+)\s+\((mypy [^)]*)\)"
)
ADVISORY_RE = re.compile(r"advisory, no baseline yet")


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


def _fetch(url: str, follow: bool = False, timeout: int = 180) -> str:
    """curl with the token passed through the environment, never argv or stdout."""
    token = _token()
    script = 'curl -s --max-time "$GH_TIMEOUT" ${GH_FOLLOW:+-L}'
    if token:
        script += ' -H "Authorization: Bearer $GITHUB_TOKEN"'
    script += ' -H "Accept: application/vnd.github+json" "$GH_URL"'
    env = {**os.environ, "GH_URL": url, "GH_TIMEOUT": str(timeout)}
    if follow:
        env["GH_FOLLOW"] = "1"
    if token:
        env["GITHUB_TOKEN"] = token
    proc = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout + 60,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"GitHub request failed for {url}: {proc.stderr[:160]}")
    return proc.stdout


def gh_get(path: str, params: str = "") -> object:
    raw = _fetch(f"{API}{path}{params}")
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        raise SystemExit(f"GitHub request failed for {path}: {raw[:120]}")


def gh_raw(url: str) -> str:
    return _fetch(url, follow=True, timeout=300)


def resolve_ref(repo: str, ref: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    data = gh_get(f"/repos/{repo}/commits/{ref}")
    return data["sha"]


def find_run_and_job(repo: str, sha: str, name: str):
    """Return the (run, job) pair for the plane job.

    A sha has several push runs (one per workflow), and only the quality-checks one contains the
    ratchet job, so this walks the runs instead of assuming the newest is the right workflow.
    """
    checked = 0
    for page in (1, 2, 3):
        data = gh_get(
            f"/repos/{repo}/actions/runs", f"?head_sha={sha}&per_page=100&page={page}"
        )
        runs = [r for r in data.get("workflow_runs", []) if r.get("event") == "push"]
        runs.sort(key=lambda r: r["run_started_at"] or "", reverse=True)
        for run in runs:
            checked += 1
            jobs = gh_get(
                f"/repos/{repo}/actions/runs/{run['id']}/jobs", "?per_page=100"
            )
            matches = [j for j in jobs.get("jobs", []) if j["name"] == name]
            if not matches:
                continue
            job = sorted(matches, key=lambda j: j["id"])[-1]
            if job.get("status") != "completed" or job.get("conclusion") not in (
                "success",
                "skipped",
            ):
                raise SystemExit(
                    f"job {job['id']} in run {run['id']} is {job.get('status')}/"
                    f"{job.get('conclusion')}; a baseline may only be frozen from a completed "
                    "successful reading"
                )
            return run, job
        if len(data.get("workflow_runs", [])) < 100:
            break
    raise SystemExit(
        f"no push run for {repo}@{sha[:10]} contains a job named {name!r} (looked at {checked} runs)"
    )


def parse_readings(log: str) -> list[dict]:
    """Every plane reading in a job log, in order. Pure: no network, so it can be tested."""
    readings = []
    for line in log.splitlines():
        # Match the raw line: READING_RE already anchors on the "mypy_ratchet[collection]:" token,
        # and stripping one leading word first would eat that token on a log line without a
        # timestamp (a shape this parser used to drop silently).
        match = READING_RE.search(line)
        if match:
            readings.append(
                {
                    "errors": int(match.group(1)),
                    "scope_files": int(match.group(2)),
                    "mypy_version": match.group(3).strip(),
                    "advisory": bool(ADVISORY_RE.search(line)),
                    "line": line[match.start() :].strip()[:200],
                }
            )
    return readings


def read_plane_reading(repo: str, job: dict) -> dict:
    """The job's one authoritative reading, refusing to pick when the log measured more than once."""
    readings = parse_readings(
        gh_raw(f"{API}/repos/{repo}/actions/jobs/{job['id']}/logs")
    )
    if not readings:
        raise SystemExit(f"job {job['id']} log contains no parseable plane reading")
    distinct = {(r["errors"], r["scope_files"], r["mypy_version"]) for r in readings}
    if len(distinct) > 1:
        raise SystemExit(
            f"job {job['id']} printed {len(distinct)} different readings {sorted(distinct)}; "
            "refusing to choose one -- investigate why the job measured twice"
        )
    return readings[-1]


def build_payload(
    repo: str, sha: str, run: dict, job: dict, reading: dict, scope: str
) -> dict:
    return {
        "_comment": (
            f"mypy ratchet baseline for scope {scope!r}. Every value below is CI's own reading from "
            "the job named in `provenance` -- not a local run. The environment matters: this plane's "
            "count differs between CI's pinned dependency set and a laptop venv, so a locally "
            "generated number must never be written here."
        ),
        "scope": scope,
        "target": "app/data_fetch/scripts",
        "config": "config/mypy_collection.ini",
        "baseline_errors": reading["errors"],
        "scope_files": reading["scope_files"],
        "mypy_version": reading["mypy_version"],
        "baseline_date": datetime.now(timezone.utc).date().isoformat(),
        "provenance": {
            "repository": repo,
            "head_sha": sha,
            "run_id": run["id"],
            "run_url": run["html_url"],
            "job_id": job["id"],
            "job_url": job["html_url"],
            "job_name": job["name"],
            "reading_line": reading["line"],
            "fetched_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default="cloudQuant/ai-for-investor")
    ap.add_argument(
        "--ref", default="dev", help="branch or 40-char sha to take CI's reading from"
    )
    ap.add_argument("--job-name", default=JOB_NAME)
    ap.add_argument("--scope", default="collection")
    ap.add_argument("--out", default="config/mypy_collection_baseline.json")
    ap.add_argument(
        "--write",
        action="store_true",
        help="write the baseline file; default only prints the candidate payload",
    )
    args = ap.parse_args(argv)

    sha = resolve_ref(args.repo, args.ref)
    run, job = find_run_and_job(args.repo, sha, args.job_name)
    reading = read_plane_reading(args.repo, job)
    payload = build_payload(args.repo, sha, run, job, reading, args.scope)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.write:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(
            f"wrote {args.out} from CI run {run['id']} job {job['id']}", file=sys.stderr
        )
    else:
        print("(dry run: pass --write to create the file)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
