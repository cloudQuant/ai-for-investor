"""Read-only runtime readout that produces the numbers in wave 29 §19.

Run from anywhere: python3 runtime_recovery_readout.py [--since UTC_ISO] [--deactivation UTC_ISO]

It opens a session-only read-only transaction and issues SELECTs only, so it cannot mutate the
collector database. Every number it prints is the number cited in DEVELOPMENT_STATUS wave 29.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

MESSAGE = "AKShare script worker exited with code 1 without a result"


def dsn_from_env(path: str) -> dict[str, str]:
    text = open(path, encoding="utf-8").read()
    match = re.search(r"^DATABASE_URL=(.*)$", text, re.MULTILINE)
    if not match:
        raise SystemExit("DATABASE_URL not found in the backend .env")
    from urllib.parse import urlparse

    u = urlparse(match.group(1).strip())
    return {
        "host": u.hostname or "127.0.0.1",
        "port": int(u.port or 3306),
        "user": u.username or "",
        "password": u.password or "",
        "database": (u.path or "/").lstrip("/"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument(
        "--env",
        default="",
        help="backend .env; defaults to $AFI_BACKEND_ENV, then the main checkout",
    )
    ap.add_argument("--since", default="2026-11-05 14:00:00")
    ap.add_argument("--deactivation", default="2026-11-06 13:47:56")
    args = ap.parse_args()

    if not args.env:
        candidates = [
            os.environ.get("AFI_BACKEND_ENV", ""),
            os.path.abspath(os.path.join(here, *[".."] * 5, "src", "backend", ".env")),
            os.path.expanduser("~/Documents/ai-for-investor/src/backend/.env"),
        ]
        args.env = next((c for c in candidates if c and os.path.exists(c)), "")
        if not args.env:
            raise SystemExit("backend .env not found; pass --env or set AFI_BACKEND_ENV")

    import pymysql

    conn = pymysql.connect(connect_timeout=8, read_timeout=90,
                           **dsn_from_env(args.env))
    out: dict[str, object] = {
        "read_at_utc": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "since_utc": args.since,
        "deactivation_utc": args.deactivation,
    }
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")

            cur.execute("SELECT MIN(created_at), MAX(created_at), COUNT(*), COUNT(DISTINCT task_id) "
                        "FROM ak_task_executions WHERE error_message=%s", (MESSAGE,))
            lo, hi, n, tasks = cur.fetchone()
            out["outage_window"] = {"first": str(lo), "last": str(hi), "runs": n, "tasks": tasks}

            cur.execute("SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM ak_task_executions "
                        "WHERE created_at BETWEEN %s AND %s",
                        (str(hi), args.since))
            rows, g0, g1 = cur.fetchone()
            out["gap_after_outage"] = {"runs": rows, "first": str(g0), "last": str(g1)}

            cur.execute("SELECT status, COUNT(*), COUNT(DISTINCT task_id), MIN(created_at), MAX(created_at) "
                        "FROM ak_task_executions WHERE created_at>=%s GROUP BY status", (args.since,))
            out["post_recovery_mix"] = [
                {"status": st, "runs": r, "tasks": t, "first": str(a), "last": str(b)}
                for st, r, t, a, b in cur.fetchall()
            ]

            cur.execute("SELECT LEFT(error_message,90), COUNT(*), COUNT(DISTINCT task_id) "
                        "FROM ak_task_executions WHERE status<>'completed' AND created_at>=%s "
                        "GROUP BY 1 ORDER BY 2 DESC LIMIT 15", (args.since,))
            out["post_recovery_failures"] = [
                {"message": m, "runs": r, "tasks": t} for m, r, t in cur.fetchall()
            ]

            cur.execute("SELECT error_message, COUNT(*), MIN(created_at), MAX(created_at), "
                        "SUM(created_at>=%s) FROM ak_task_executions "
                        "WHERE error_message LIKE 'No callable entrypoint found for script%%' "
                        "AND created_at>=%s GROUP BY 1 ORDER BY 2 DESC", (args.deactivation, args.since))
            out["ghost_slugs_since_deactivation"] = [
                {"script": m.split(" for script ")[-1], "runs": r, "first": str(a), "last": str(b), "after_deactivation": n}
                for m, r, a, b, n in cur.fetchall()
            ]

            cur.execute("SELECT COUNT(*) FROM ak_scheduled_tasks WHERE is_active=1")
            armed = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM ak_scheduled_tasks t WHERE t.is_active=1 AND NOT EXISTS "
                        "(SELECT 1 FROM ak_task_executions e WHERE e.task_id=t.id AND e.created_at>=%s)",
                        (args.since,))
            idle = cur.fetchone()[0]
            out["armed_coverage"] = {"armed": armed, "no_execution_since_recovery": idle}

            cur.execute("SELECT COUNT(*), MAX(created_at) FROM ak_task_executions")
            total, latest = cur.fetchone()
            out["ledger_tail"] = {"runs": total, "latest": str(latest)}
    finally:
        conn.rollback()
        conn.close()

    json.dump(out, sys.stdout, ensure_ascii=False, indent=2, default=lambda o: int(o))
    print()


if __name__ == "__main__":
    main()
