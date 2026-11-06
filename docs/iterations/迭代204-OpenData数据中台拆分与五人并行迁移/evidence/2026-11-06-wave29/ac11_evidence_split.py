"""AC11 evidence split: cross the #284 static census with post-repair runtime behaviour.

Read-only. The static census says 886 armed tasks bind into an `**kwargs` entrypoint and are
therefore statically unverifiable. Runtime rows can still answer the narrower question:
did that task actually run, finish, and write rows, on the repaired collector?
"""

import json
import pathlib
import re
import sys

import pymysql

BACKEND = pathlib.Path("/home/yun/Documents/ai-for-investor/src/backend")
POST_REPAIR = "2026-11-05 14:03:00"


def ev(k):
    for line in (BACKEND / ".env").read_text().splitlines():
        m = re.match(rf"^\s*{k}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")


u = re.match(r"^[+a-z]*://([^:]+):([^@]*)@([^:/]+):?(\d*)/([^?]+)", ev("DATABASE_URL"))
conn = pymysql.connect(host=u.group(3), port=int(u.group(4)), user=u.group(1), password=u.group(2),
                       database=u.group(5), cursorclass=pymysql.cursors.DictCursor, read_timeout=180)
with conn.cursor() as cur:
    cur.execute(
        "SELECT task_id, COUNT(*) n, SUM(status='completed') ok, SUM(status='failed') bad, "
        "SUM(rows_after > rows_before) grew, MAX(created_at) last FROM ak_task_executions "
        "WHERE created_at >= %s GROUP BY task_id", (POST_REPAIR,))
    runtime = {r["task_id"]: r for r in cur.fetchall()}
conn.close()

audit = json.load(open(sys.argv[1]))  # task_param_bind_audit.json from scripts/task_param_audit.py
tasks = audit["tasks"]

buckets = {}
for t in tasks:
    fam = t["family"]
    rt = runtime.get(t["task_id"])
    if rt is None:
        state = "no_run_post_repair"
    elif rt["ok"]:
        state = "completed_post_repair" + ("_wrote_rows" if rt["grew"] else "_no_row_delta")
    else:
        state = "failed_only_post_repair"
    buckets.setdefault(fam, {}).setdefault(state, 0)
    buckets[fam][state] += 1

print(f"tasks audited: {len(tasks)}; tasks with any post-repair execution: {len(runtime)}")
print(f"\n=== AC11: static family x post-repair runtime evidence (since {POST_REPAIR} UTC) ===")
for fam in sorted(buckets):
    total = sum(buckets[fam].values())
    print(f"\n{fam}  (n={total})")
    for state, n in sorted(buckets[fam].items(), key=lambda x: -x[1]):
        print(f"    {state:<34} {n:>5}  ({n / total * 100:.1f}%)")

# the honest numerator AC11 asks for: tasks whose disposition is evidenced, not assumed
evidenced = sum(
    n for fam, d in buckets.items()
    for state, n in d.items() if state.startswith("completed_post_repair_wrote_rows")
)
print(f"\n=== AC11 分派进度（按『运行态已证明绑定且写入了行』口径）: {evidenced} / {len(tasks)} ===")
loose = sum(n for d in buckets.values() for state, n in d.items() if state.startswith("completed_post_repair"))
print(f"    放宽到『完成即可，不要求行增量』: {loose} / {len(tasks)}")
print(f"    静态可证 binds: {audit['family_counts'].get('binds')}")
print(f"    从未在修复后运行过: {sum(n for d in buckets.values() for s, n in d.items() if s == 'no_run_post_repair')}")
