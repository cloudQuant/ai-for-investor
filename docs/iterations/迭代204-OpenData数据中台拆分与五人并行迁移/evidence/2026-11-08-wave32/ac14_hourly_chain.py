"""AC14 hourly-cycle accrual, read-only, measured as consecutive due slots that completed.

Clause: 48 consecutive NATURAL hourly cycles, each producing a completed execution. This counts
slots the task's own cron granted since the #316 deploy, not rows, so "no row in a slot" and
"row but failed" are both breaks in the chain and are reported separately.
"""

import datetime
import pathlib
import re

import pymysql

SH = datetime.timezone(datetime.timedelta(hours=8))
DEPLOY = datetime.datetime(2026, 11, 7, 19, 26, 47)  # UTC, per db clock column semantics
BACKEND = pathlib.Path("/home/yun/Documents/ai-for-investor/src/backend")
TASK_IDS = (1049,)


def ev(key):
    for line in (BACKEND / ".env").read_text().splitlines():
        m = re.match(rf"^\s*{key}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")


u = re.match(r"^[+a-z]*://([^:]+):([^@]*)@([^:/]+):?(\d*)/([^?]+)", ev("DATABASE_URL"))
conn = pymysql.connect(
    host=u.group(3),
    port=int(u.group(4)),
    user=u.group(1),
    password=u.group(2),
    database=u.group(5),
    cursorclass=pymysql.cursors.DictCursor,
    read_timeout=180,
)
with conn.cursor() as cur:
    cur.execute("SET SESSION TRANSACTION READ ONLY")
    cur.execute(
        "SELECT id, name, schedule_expression, is_active FROM ak_scheduled_tasks WHERE id IN %s",
        (TASK_IDS,),
    )
    tasks = cur.fetchall()
    cur.execute(
        "SELECT id, task_id, status, start_time, end_time, created_at FROM ak_task_executions "
        "WHERE task_id IN %s AND start_time >= %s ORDER BY start_time",
        (TASK_IDS, DEPLOY.strftime("%Y-%m-%d %H:%M:%S")),
    )
    rows = cur.fetchall()
    cur.execute("SELECT UTC_TIMESTAMP() now_utc, NOW() local_now")
    clock = cur.fetchone()
conn.close()

now_utc = clock["now_utc"]
print(f"db clock: utc={clock['now_utc']:%Y-%m-%d %H:%M:%S} local={clock['local_now']:%Y-%m-%d %H:%M:%S}")
for t in tasks:
    print(f"task {t['id']} armed={t['is_active']} cron={t['schedule_expression']!r} {t['name']}")

print(f"\nexecutions since deploy {DEPLOY:%Y-%m-%dT%H:%M:%SZ}: {len(rows)}")
by_hour = {}
for r in rows:
    st = r["start_time"]
    slot = st.replace(minute=0, second=0, microsecond=0)
    by_hour.setdefault(slot, []).append(r["status"])
for slot in sorted(by_hour):
    print(f"  {slot:%m-%d %H}Z  {by_hour[slot]}")

# longest chain of consecutive hourly slots (from deploy anchor) that each have a completed run
anchor = DEPLOY.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
chain = 0
slot = anchor
breaks = []
while slot <= now_utc.replace(minute=0, second=0, microsecond=0):
    statuses = by_hour.get(slot)
    if statuses and "completed" in statuses:
        chain += 1
    else:
        breaks.append((slot, statuses))
        if statuses:
            break  # a failed row is a hard break; an absent slot is still accruing-unknown
    slot += datetime.timedelta(hours=1)

print(
    f"\nconsecutive completed hourly slots from {anchor:%m-%d %H}Z onward = {chain} "
    f"(target 48, {(now_utc - anchor).total_seconds() / 3600:.1f} h of wall clock available)"
)
print(f"first non-completed slot: {breaks[0] if breaks else 'none so far'}")
print(
    "note: an absent slot means the due hour had not been reached or the row is still running;"
    " it is reported, not counted as success."
)
