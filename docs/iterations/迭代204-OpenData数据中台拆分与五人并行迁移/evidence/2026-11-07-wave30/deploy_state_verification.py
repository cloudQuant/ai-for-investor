"""State a deployment in terms that can be re-checked: code identity, schema identity, clock identity.

Written for iteration-204 wave 30, where "deployed" had been used loosely for two days. Four
questions, four answers, all read-only:

1. Is the running service's working tree the same commit as the branch it claims to run?
2. Does the database's Alembic revision equal the code's head? (The 2026-11-07 restart proved this is
   not cosmetic: the API refused to start, exit 3, no traceback, when the two disagreed.)
3. Do newly written rows put UTC in the scheduler columns, or wall-clock? (Before #306 the two
   writers disagreed by +8h.)
4. Does the deactivated-task population stay out of the execution ledger? (The unregister bug let
   inactive tasks keep firing for a day after `is_active=0`.)

Nothing here writes: one `git rev-parse`, one `alembic` read, and SELECTs inside a read-only session.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone


def dsn(env_path: str) -> dict:
    from urllib.parse import urlparse

    text = io.open(env_path, encoding="utf-8").read()
    match = re.search(r"^DATABASE_URL=(.*)$", text, re.MULTILINE)
    if not match:
        raise SystemExit("DATABASE_URL not found in backend .env")
    u = urlparse(match.group(1).strip())
    return {
        "host": u.hostname, "port": int(u.port or 3306), "user": u.username,
        "password": u.password, "database": (u.path or "/").lstrip("/"),
    }


def _revision_lines(output: str) -> list[str]:
    """alembic prints INFO chatter to stderr; only the revision line is an answer."""
    return [line.strip() for line in output.splitlines()
            if line.strip() and not line.strip().startswith("INFO")]


def git(repo: str, *args: str) -> str:
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def alembic(backend: str, *args: str) -> str:
    r = subprocess.run([os.path.join(backend, ".venv/bin/python"), "-m", "alembic", *args],
                       cwd=backend, capture_output=True, text=True, timeout=120)
    return (r.stdout + r.stderr).strip()


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/home/yun/Documents/ai-for-investor")
    ap.add_argument("--env", default=os.environ.get("AFI_BACKEND_ENV", ""))
    ap.add_argument("--since-minutes", type=int, default=30,
                    help="window of executions to judge the clock on")
    args = ap.parse_args()
    backend = os.path.join(args.repo, "src/backend")
    env_path = args.env or os.path.join(backend, ".env")

    import pymysql

    report: dict[str, object] = {
        "checked_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo_head": git(args.repo, "rev-parse", "HEAD")[:12],
        "repo_branch": git(args.repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "origin_dev_head": git(args.repo, "rev-parse", "origin/dev")[:12],
        "deployed_head_is_branch_tip": git(args.repo, "rev-parse", "HEAD")
        == git(args.repo, "rev-parse", "origin/dev"),
        "worktree_dirty_entries": [
            line for line in git(args.repo, "status", "--porcelain").splitlines() if line
        ][:6],
        "alembic_code_heads": _revision_lines(alembic(backend, "heads")),
        "alembic_db_current": _revision_lines(alembic(backend, "current")),
    }

    conn = pymysql.connect(connect_timeout=8, read_timeout=60, **dsn(env_path))
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            since = (datetime.now(timezone.utc).replace(tzinfo=None)
                     - timedelta(minutes=args.since_minutes)).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute(
                "SELECT status, COUNT(*) FROM ak_task_executions WHERE created_at>=%s GROUP BY status",
                (since,),
            )
            report["executions_since_window"] = {s: n for s, n in cur.fetchall()}
            cur.execute(
                """
                SELECT COUNT(*) FROM ak_scheduled_tasks t
                WHERE t.is_active = 1 AND t.last_execution_at IS NOT NULL
                  AND t.last_execution_at >= %s
                  AND ABS(TIMESTAMPDIFF(MINUTE, t.last_execution_at,
                        (SELECT MAX(e.created_at) FROM ak_task_executions e WHERE e.task_id = t.id))) > 60
                """,
                (since,),
            )
            report["active_tasks_with_clock_skew_over_60min"] = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM ak_task_executions WHERE created_at>=%s "
                "AND error_message LIKE 'No callable entrypoint found for script%%'",
                (since,),
            )
            report["ghost_entrypoint_failures_since_window"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM ak_scheduled_tasks WHERE is_active=1")
            report["armed_tasks"] = cur.fetchone()[0]
    finally:
        conn.rollback()
        conn.close()

    report["meaning"] = (
        "deployed_head_is_branch_tip false means the tree is running older code than the branch names -- "
        "report it, do not call the deployment current; worktree_dirty_entries should only contain "
        "expected untracked paths (var/); the two alembic lines must name the same revision or startup "
        "will refuse, exit 3, with no traceback; the two alembic lines must name the same revision or startup will refuse "
        "(exit 3, no traceback); clock skew over 60 minutes on a recently-run task means a wall-clock "
        "writer is back; ghost entrypoint failures must be 0 once the deactivated jobs are unregistered."
    )
    import json
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
