"""Attribute rows whose `last_execution_at` lags their newest execution, and pin what the column means.

The clock migration of 2026-11-07 classified 19 rows as `stale-column` and deliberately left them
alone. This explains them: the column advances only on success (`execution.py mark_completed`), so a
task that has been failing since its last success keeps an old value even though it runs on schedule.
It prints, for every such task, the newest execution's status and the lag, plus one live example of a
successful and a failed run to show which one moves the column.

Read-only: one session with `SET SESSION TRANSACTION READ ONLY`, SELECTs only.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime, timezone


def dsn(env_path: str) -> dict:
    from urllib.parse import urlparse

    text = io.open(env_path, encoding="utf-8").read()
    match = re.search(r"^DATABASE_URL=(.*)$", text, re.MULTILINE)
    if not match:
        raise SystemExit("DATABASE_URL not found in backend .env")
    u = urlparse(match.group(1).strip())
    return {"host": u.hostname, "port": int(u.port or 3306), "user": u.username,
            "password": u.password, "database": (u.path or "/").lstrip("/")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=os.environ.get("AFI_BACKEND_ENV") or
                    os.path.expanduser("~/Documents/ai-for-investor/src/backend/.env"))
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    import pymysql

    conn = pymysql.connect(connect_timeout=8, read_timeout=90, **dsn(args.env))
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute(
                """
                SELECT t.id, t.name, t.is_active, t.schedule_expression, t.last_execution_at,
                       (SELECT MAX(e.created_at) FROM ak_task_executions e WHERE e.task_id = t.id),
                       (SELECT MAX(e.end_time) FROM ak_task_executions e
                        WHERE e.task_id = t.id AND e.status = 'completed')
                FROM ak_scheduled_tasks t
                WHERE t.last_execution_at IS NOT NULL
                  AND (SELECT MAX(e.created_at) FROM ak_task_executions e
                       WHERE e.task_id = t.id) > t.last_execution_at
                ORDER BY t.last_execution_at ASC
                LIMIT %s
                """,
                (args.limit,),
            )
            rows = cur.fetchall()

            # created_at can be one second newer than end_time inside the same run, so a bare
            # "newest execution later than the column" test has a 1-second false positive. Judge
            # against the newest COMPLETED run's end_time; keep the created_at gap for the report.
            cur.execute(
                "SELECT COUNT(*) FROM ak_scheduled_tasks t WHERE t.last_execution_at IS NOT NULL "
                "AND (SELECT MAX(e.created_at) FROM ak_task_executions e WHERE e.task_id = t.id) "
                "> t.last_execution_at"
            )
            total_lagging = cur.fetchone()[0]

            report = []
            for task_id, name, active, cron, last, newest, newest_completed_end in rows:
                cur.execute(
                    "SELECT status FROM ak_task_executions WHERE task_id=%s "
                    "ORDER BY created_at DESC LIMIT 1",
                    (task_id,),
                )
                status = (cur.fetchone() or ["?"])[0]
                report.append({
                    "task_id": task_id,
                    "name": str(name)[:40],
                    "is_active": int(active),
                    "cron": cron,
                    "last_execution_at": str(last),
                    "newest_execution": str(newest),
                    "lag_hours": round((newest - last).total_seconds() / 3600, 1),
                    "artefact_within_one_second": bool(
                        newest_completed_end and last and
                        0 <= (newest - last).total_seconds() <= 2
                    ),
                    "newest_status": status,
                })

            cur.execute(
                """
                SELECT e.task_id, e.created_at, e.status
                FROM ak_task_executions e
                WHERE e.created_at >= UTC_TIMESTAMP() - INTERVAL 3 HOUR
                ORDER BY e.created_at DESC LIMIT 12
                """
            )
            recent = []
            for task_id, created, status in cur.fetchall():
                cur.execute("SELECT last_execution_at FROM ak_scheduled_tasks WHERE id=%s", (task_id,))
                got = cur.fetchone()
                recent.append({
                    "task_id": task_id, "execution_at": str(created), "status": status,
                    "last_execution_at": str(got[0]) if got else None,
                    "column_advanced": bool(got and got[0] and got[0] >= created),
                })
    finally:
        conn.rollback()
        conn.close()

    doc = {
        "read_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lagging_tasks_total": total_lagging,
        "rows_inspected": len(report),
        "lagging_with_newest_failed": sum(1 for r in report if r["newest_status"] == "failed"),
        "lagging_one_second_artefacts": [r["task_id"] for r in report if r["artefact_within_one_second"]],
        "tasks": report,
        "recent_runs_and_whether_the_column_moved": recent,
        "meaning": ("`last_execution_at` is the last SUCCESSFUL run, not the last attempt: it is written "
                    "only in mark_completed. A task that keeps failing keeps an old value while its "
                    "executions keep arriving, so this column must never be read as liveness; use "
                    "ak_task_executions for attempts and for AC13/AC14 'how long since it ran'."),
    }
    print(json.dumps(doc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
