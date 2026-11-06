"""Read-only instrument that reproduces wave-29 section 5's scheduler clock-duality numbers.

Two separate claims are measured, because they come from different places:

A. `last_execution_at` vs the newest `ak_task_executions.created_at` for the same task
   (buckets: shifted by ~+8h, agreeing within +-1h, older than any execution, no execution).
B. For tasks whose cron fixes a single hour, whether `next_execution_at` and
   `last_execution_at` each equal the cron's wall-clock slot.

Both are affected by the defect fixed in PR #306 (two writers, two clocks, one column), so the
distribution is a snapshot of the deployed writer, not a constant. Re-run it and cite the run time.
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

def dsn(env_path: str) -> dict:
    text = io.open(env_path, encoding="utf-8").read()
    from urllib.parse import urlparse

    u = urlparse(re.search(r"^DATABASE_URL=(.*)$", text, re.M).group(1).strip())
    return {
        "host": u.hostname, "port": int(u.port or 3306), "user": u.username,
        "password": u.password, "database": (u.path or "/").lstrip("/"),
    }


def cron_hour(slot: str):
    """Return the fixed hour set of a 5-field cron, or None when the hour field is a wildcard/list."""
    parts = slot.split()
    if len(parts) != 5:
        return None
    hour = parts[1]
    if not re.fullmatch(r"\d{1,2}", hour):
        return None
    h = int(hour)
    return {h} if 0 <= h <= 23 else None


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=os.environ.get("AFI_BACKEND_ENV") or
                    os.path.expanduser("~/Documents/ai-for-investor/src/backend/.env"))
    ap.add_argument("--tz-offset-hours", type=int, default=8,
                    help="host offset east of UTC; this machine is Asia/Shanghai (+8)")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import pymysql

    conn = pymysql.connect(connect_timeout=8, read_timeout=120, **dsn(args.env))
    buckets = collections.Counter()
    slot_hits = collections.Counter()
    daily = {"next_matches_slot": 0, "last_matches_slot": 0, "n": 0}
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute(
                """
                SELECT t.id, t.schedule_expression, t.last_execution_at, t.next_execution_at,
                       (SELECT MAX(e.created_at) FROM ak_task_executions e WHERE e.task_id = t.id)
                FROM ak_scheduled_tasks t WHERE t.is_active = 1
                """
            )
            for _tid, cron, last_at, next_at, newest_exec in cur.fetchall():
                if newest_exec is None:
                    buckets["no-execution"] += 1
                    continue
                if last_at is None:
                    buckets["column-null"] += 1
                    continue
                delta = (last_at - newest_exec).total_seconds() / 3600.0
                if abs(delta - args.tz_offset_hours) <= 1.5:
                    buckets["shifted-by-tz-offset"] += 1
                elif abs(delta) <= 1.0:
                    buckets["agrees-within-1h"] += 1
                elif delta < -1.0:
                    buckets["older-than-any-execution"] += 1
                else:
                    buckets["unclassified"] += 1

                hours = cron_hour(cron or "")
                if hours is None:
                    continue
                daily["n"] += 1
                if next_at is not None and next_at.hour in hours:
                    daily["next_matches_slot"] += 1
                if last_at.hour in hours:
                    daily["last_matches_slot"] += 1

            cur.execute("SELECT COUNT(*) FROM ak_scheduled_tasks WHERE is_active=1")
            armed = cur.fetchone()[0]
    finally:
        conn.rollback()
        conn.close()

    doc = {
        # datetime.now() on this host is Asia/Shanghai; labelling it UTC would reproduce the very
        # defect this instrument measures, so the stamp is taken in UTC explicitly.
        "read_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tz_offset_hours": args.tz_offset_hours,
        "armed_tasks": armed,
        "last_execution_at_vs_newest_created_at": dict(buckets),
        "single_hour_cron_tasks": {
            "n": daily["n"],
            "next_execution_at_in_cron_hour": daily["next_matches_slot"],
            "last_execution_at_in_cron_hour": daily["last_matches_slot"],
        },
        "note": ("Buckets A describe the deployed writer at read time. `shifted-by-tz-offset` is the "
                 "defect; PR #306 removes it for new rows, and scripts/ops/normalize_scheduler_clock.py "
                 "is the separate存量 correction. Do not compare this output across deploys."),
    }
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    if args.out:
        io.open(args.out, "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    sys.exit(main())
