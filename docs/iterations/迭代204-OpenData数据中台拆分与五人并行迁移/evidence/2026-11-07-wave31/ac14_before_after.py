"""AC14 paired measurement: one armed task's executions, before and after a fix is deployed.

Read-only. Reports the shape that matters for AC14: how many runs end in the platform timeout
(`duration >= 599s`, status failed), how many write rows, and the start/end distribution. Run it
with the same arguments before and after the deploy so the two readings are comparable.

Usage:
    python ac14_before_after.py --task-id 1049 --since 2026-11-06T19:00:00Z --json-out before.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re

import pymysql

BACKEND = pathlib.Path("/home/yun/Documents/ai-for-investor/src/backend")


def env_value(key: str) -> str | None:
    for line in (BACKEND / ".env").read_text().splitlines():
        m = re.match(rf"^\s*{key}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def connect():
    u = re.match(r"^[+a-z]*://([^:]+):([^@]*)@([^:/]+):?(\d*)/([^?]+)", env_value("DATABASE_URL"))
    conn = pymysql.connect(
        host=u.group(3),
        port=int(u.group(4) or 3306),
        user=u.group(1),
        password=u.group(2),
        database=u.group(5),
        cursorclass=pymysql.cursors.DictCursor,
        read_timeout=120,
    )
    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
        cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
    return conn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", type=int, required=True)
    ap.add_argument("--since", required=True)
    ap.add_argument("--json-out", required=True)
    args = ap.parse_args()

    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, COUNT(*) AS n, MIN(duration) AS min_s, MAX(duration) AS max_s, "
            "AVG(duration) AS avg_s, SUM(rows_after > rows_before) AS grew, "
            "MIN(start_time) AS first_at, MAX(start_time) AS last_at "
            "FROM ak_task_executions WHERE task_id=%s AND start_time >= %s GROUP BY status",
            (args.task_id, args.since),
        )
        by_status = cur.fetchall()
        cur.execute(
            "SELECT start_time, end_time, duration, status, rows_before, rows_after, "
            "LEFT(COALESCE(error_message,''), 160) AS err "
            "FROM ak_task_executions WHERE task_id=%s AND start_time >= %s "
            "ORDER BY start_time DESC LIMIT 20",
            (args.task_id, args.since),
        )
        recent = cur.fetchall()
        cur.execute(
            "SELECT COUNT(*) AS n FROM ak_task_executions WHERE task_id=%s AND start_time >= %s "
            "AND duration >= 599",
            (args.task_id, args.since),
        )
        timeouts = cur.fetchone()["n"]
        cur.execute(
            "SELECT id, name, is_active, schedule_expression, timeout, last_execution_at, next_execution_at "
            "FROM ak_scheduled_tasks WHERE id=%s",
            (args.task_id,),
        )
        task = cur.fetchone()

    doc = {
        "task_id": args.task_id,
        "since": args.since,
        "task": {k: str(v) for k, v in (task or {}).items()},
        "timeout_runs_duration_ge_599": timeouts,
        "by_status": [
            {
                **{k: str(v) for k, v in row.items() if k not in ("n", "grew")},
                "n": int(row["n"]),
                "grew": int(row["grew"] or 0),
            }
            for row in by_status
        ],
        "recent": [{k: str(v) for k, v in row.items()} for row in recent],
    }
    pathlib.Path(args.json_out).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(
        f"task {args.task_id}: runs={sum(r['n'] for r in doc['by_status'])} "
        f"timeouts(>=599s)={timeouts} statuses={[ (r['status'], r['n']) for r in doc['by_status'] ]} "
        f"-> {args.json_out}"
    )


if __name__ == "__main__":
    main()
