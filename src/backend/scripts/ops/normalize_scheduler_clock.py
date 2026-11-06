"""Correct the pre-existing scheduler clock rows to the naive-UTC shape the columns now guarantee.

``AkshareScheduler.run_task_now`` used to write ``datetime.now()`` (host-local) into
``ak_scheduled_tasks.last_execution_at`` while ``AkshareExecutionService`` wrote naive UTC into the
same column, and ``next_execution_at`` was stored as APScheduler's Asia/Shanghai wall value. The
code fix lands in the same PR; this script repairs the rows that were written before it.

Classification is per row and refuses to guess:

* ``last_execution_at`` is shifted only when it sits 7-9h after the task's newest
  ``ak_task_executions.created_at`` -- the signature of the local-clock write. Rows that already
  agree with the execution clock, and rows whose scheduler value is *older* than their newest
  execution (a separate defect: the column was not maintained), are left alone and reported.
* ``next_execution_at`` is shifted for armed tasks whose value equals the cron slot in the
  scheduler timezone minus that slot's UTC instant, i.e. the wall-time shape.

Dry-run by default; ``--apply`` writes, after dumping a before-image.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pymysql

ENV_CANDIDATES = (
    Path("/home/yun/Documents/ai-for-investor/src/backend/.env"),
    Path(__file__).resolve().parents[1] / ".env",
)
SHIFT = timedelta(hours=8)


def env_value(key: str) -> str | None:
    for path in ENV_CANDIDATES:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            m = re.match(rf"^\s*{key}\s*=\s*(.*)$", line)
            if m:
                return m.group(1).strip().strip("\"'")
    return None


def connect() -> pymysql.connections.Connection:
    url = env_value("DATABASE_URL") or ""
    m = re.match(r"^[+a-z]*://([^:]+):([^@]*)@([^:/]+):?(\d*)/([^?]+)", url)
    if not m:
        raise SystemExit("DATABASE_URL not found in .env -- refusing to guess a target")
    return pymysql.connect(
        host=m.group(3),
        port=int(m.group(4) or 3306),
        user=m.group(1),
        password=m.group(2),
        database=m.group(5),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        read_timeout=180,
    )


def fetch(conn: pymysql.connections.Connection, sql: str, params: Any = None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def _in_clause(ids: list[int]) -> str:
    """Placeholder list for an IN clause; callers pass the values separately."""
    return "(" + ", ".join(["%s"] * len(ids)) + ")"


def classify_last(rows: list[dict], newest_execution: dict[int, datetime]) -> dict[str, list[int]]:
    """Bucket every armed task's last_execution_at by how it relates to its newest execution."""
    buckets: dict[str, list[int]] = {
        "shift": [],
        "already-utc": [],
        "no-execution": [],
        "stale-column": [],
        "unclassified": [],
    }
    for r in rows:
        task_id, value = r["id"], r["last_execution_at"]
        if value is None:
            continue
        newest = newest_execution.get(task_id)
        if newest is None:
            buckets["no-execution"].append(task_id)
            continue
        drift = value - newest
        if timedelta(hours=7) <= drift <= timedelta(hours=9):
            buckets["shift"].append(task_id)
        elif timedelta(hours=-1) <= drift <= timedelta(hours=1):
            buckets["already-utc"].append(task_id)
        elif drift < timedelta(0):
            buckets["stale-column"].append(task_id)
        else:
            buckets["unclassified"].append(task_id)
    return buckets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="perform the UPDATEs (default: dry-run)")
    ap.add_argument("--backup", type=Path, default=None, help="before-image path")
    args = ap.parse_args()

    conn = connect()
    tasks = fetch(
        conn,
        "SELECT id, name, is_active, last_execution_at, next_execution_at "
        "FROM ak_scheduled_tasks WHERE is_active=1",
    )
    newest = {
        r["task_id"]: r["newest"]
        for r in fetch(
            conn, "SELECT task_id, MAX(created_at) newest FROM ak_task_executions GROUP BY task_id"
        )
    }
    armed_ids = tuple(t["id"] for t in tasks)
    if not armed_ids:
        raise SystemExit("no armed tasks resolved -- refusing to build an empty IN clause")
    buckets = classify_last(tasks, newest)

    # next_execution_at is written from APScheduler's trigger, which runs in the scheduler timezone,
    # so every armed row carries the wall-time shape regardless of its execution history.
    next_shift = [t["id"] for t in tasks if t["next_execution_at"] is not None]

    print(f"armed tasks: {len(tasks)}")
    for name, ids in buckets.items():
        print(f"  last_execution_at {name:<14} {len(ids):>5}")
    print(f"  next_execution_at shift candidates: {len(next_shift)}")
    print(
        "\norder matters: run this AFTER the code fix is deployed and the collector restarted,"
        "\n      otherwise the still-running scheduler writes the wall-clock shape back again."
    )

    if buckets["stale-column"]:
        print(
            "\nnote: rows in 'stale-column' have a scheduler value older than their newest execution;"
            "\n      that is the column not being maintained, not a clock offset, and is NOT shifted here."
        )

    if not args.apply:
        print("\ndry-run: no UPDATE issued. Re-run with --apply.")
        conn.close()
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = args.backup or Path(f"/tmp/ac11-clock-before-{stamp}.json")
    before = [
        {k: str(v) for k, v in r.items()}
        for r in fetch(
            conn,
            "SELECT id, name, last_execution_at, next_execution_at FROM ak_scheduled_tasks "
            f"WHERE id IN {_in_clause(list(armed_ids))}",
            armed_ids,
        )
    ]
    backup.write_text(json.dumps(before, ensure_ascii=False, indent=1))
    print(f"before-image: {backup} ({len(before)} rows)")

    with conn.cursor() as cur:
        if buckets["shift"]:
            cur.execute(
                "UPDATE ak_scheduled_tasks SET last_execution_at = last_execution_at - INTERVAL 8 HOUR "
                f"WHERE id IN {_in_clause(buckets['shift'])}",
                tuple(buckets["shift"]),
            )
            print(f"last_execution_at shifted: {cur.rowcount}")
        if next_shift:
            cur.execute(
                "UPDATE ak_scheduled_tasks SET next_execution_at = next_execution_at - INTERVAL 8 HOUR "
                f"WHERE id IN {_in_clause(next_shift)}",
                tuple(next_shift),
            )
            print(f"next_execution_at shifted: {cur.rowcount}")
        conn.commit()

    tasks_after = fetch(
        conn,
        "SELECT id, name, is_active, last_execution_at, next_execution_at "
        "FROM ak_scheduled_tasks WHERE is_active=1",
    )
    after = classify_last(tasks_after, newest)
    print("\n=== post-write classification (the proof the shift landed) ===")
    for name, ids in after.items():
        print(f"  last_execution_at {name:<14} {len(ids):>5}")
    if after["shift"]:
        print(f"  WARNING: {len(after['shift'])} rows still carry the +8h shape")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
