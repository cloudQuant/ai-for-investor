"""AC13 verdict: did the 50 deactivated ghost tasks fire after deactivation?

Read-only. Prints a JSON verdict with:
  - the cohort (from the #284 census, family script_file_absent)
  - their is_active state now
  - execution rows before / after the deactivation instant
  - how many cron slots each task's own row says it should have crossed since, so
    "0 executions" can be separated from "no slot came due"
"""

import datetime
import json
import pathlib
import re

import pymysql

BACKEND = pathlib.Path("/home/yun/Documents/ai-for-investor/src/backend")
CENSUS = pathlib.Path("/tmp/it204/param-audit/task_param_bind_audit.json")
DEACTIVATED_AT = datetime.datetime(2026, 11, 6, 13, 47, 56)  # UTC, from the retrofit run


def env_value(key):
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


def main():
    census = json.loads(CENSUS.read_text())
    cohort = sorted(int(t["task_id"]) for t in census["tasks"] if t["family"] == "script_file_absent")
    assert len(cohort) == 50, len(cohort)

    conn = connect()
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, is_active, schedule_expression, last_execution_at, next_execution_at, updated_at "
            "FROM ak_scheduled_tasks WHERE id IN %s ORDER BY id",
            (tuple(cohort),),
        )
        tasks = cur.fetchall()

        cur.execute(
            "SELECT task_id, status, COUNT(*) AS n, MIN(start_time) AS first_at, MAX(start_time) AS last_at "
            "FROM ak_task_executions WHERE task_id IN %s AND start_time < %s "
            "GROUP BY task_id, status",
            (tuple(cohort), DEACTIVATED_AT),
        )
        before = cur.fetchall()

        cur.execute(
            "SELECT task_id, status, COUNT(*) AS n, MIN(start_time) AS first_at, MAX(start_time) AS last_at "
            "FROM ak_task_executions WHERE task_id IN %s AND start_time >= %s "
            "GROUP BY task_id, status",
            (tuple(cohort), DEACTIVATED_AT),
        )
        after = cur.fetchall()

        cur.execute("SELECT MAX(start_time) AS newest FROM ak_task_executions WHERE task_id IN %s", (tuple(cohort),))
        newest = cur.fetchone()

    # Slots crossed: every 5-field cron with a fixed minute fires at least daily, so for each task
    # count whole days since deactivation and add today's occurrence if its clock time already passed.
    crossed = []
    for t in tasks:
        cron = (t["schedule_expression"] or "").split()
        if len(cron) < 5 or not cron[0].isdigit() or not cron[1].isdigit():
            crossed.append({"id": t["id"], "cron": t["schedule_expression"], "slots": None, "why": "non-literal"})
            continue
        minute, hour = int(cron[0]), int(cron[1])
        day0 = DEACTIVATED_AT.date()
        slots = 0
        day = day0
        while day <= now.date():
            at = datetime.datetime.combine(day, datetime.time(hour, minute))
            if at > DEACTIVATED_AT and at <= now:
                slots += 1
            day += datetime.timedelta(days=1)
        crossed.append({"id": t["id"], "cron": t["schedule_expression"], "slots": slots})

    elapsed_h = (now - DEACTIVATED_AT).total_seconds() / 3600
    verdict = {
        "generated_at_utc": now.isoformat() + "Z",
        "deactivated_at_utc": DEACTIVATED_AT.isoformat() + "Z",
        "elapsed_hours": round(elapsed_h, 2),
        "cohort_size": len(cohort),
        "still_inactive": sum(1 for t in tasks if int(t["is_active"]) == 0),
        "executions_before": {
            "rows": sum(int(r["n"]) for r in before),
            "tasks_with_any": len({r["task_id"] for r in before}),
            "by_status": {},
            "first": str(min((r["first_at"] for r in before), default=None)),
            "last": str(max((r["last_at"] for r in before), default=None)),
        },
        "executions_after": {
            "rows": sum(int(r["n"]) for r in after),
            "tasks_with_any": len({r["task_id"] for r in after}),
            "by_status": {},
            "rows_detail": [{k: str(v) for k, v in r.items()} for r in after],
        },
        "newest_execution_ever": str(newest["newest"]),
        "slots_crossed_since_deactivation": {
            "total": sum(c["slots"] for c in crossed if c["slots"]),
            "tasks_with_at_least_one": sum(1 for c in crossed if c["slots"]),
            "non_literal_cron": [c for c in crossed if c["slots"] is None],
            "per_task": crossed,
        },
    }
    for r in before:
        key = r["status"]
        verdict["executions_before"]["by_status"][key] = verdict["executions_before"]["by_status"].get(key, 0) + int(r["n"])
    for r in after:
        key = r["status"]
        verdict["executions_after"]["by_status"][key] = verdict["executions_after"]["by_status"].get(key, 0) + int(r["n"])

    print(json.dumps(verdict, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
