"""Build the concrete AC11 disposition input lists from the #284 census + cron due-slot math.

Read-only. Produces the three cohorts that a disposition assignment must name, so that
'0/1057 已分派' can move forward on evidence instead of on a placeholder route value.
"""

import collections
import datetime
import json
import pathlib
import re

import pymysql

import sys

sys.path.insert(0, "/tmp/it204")
from ac14_accrual import ev, slots_for  # noqa: E402

BACKEND = pathlib.Path("/home/yun/Documents/ai-for-investor/src/backend")
u = re.match(r"^[+a-z]*://([^:]+):([^@]*)@([^:/]+):?(\d*)/([^?]+)", ev("DATABASE_URL"))
conn = pymysql.connect(host=u.group(3), port=int(u.group(4)), user=u.group(1), password=u.group(2),
                       database=u.group(5), cursorclass=pymysql.cursors.DictCursor, read_timeout=180)


def q(sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


audit = json.load(open(sys.argv[1]))  # task_param_bind_audit.json from scripts/task_param_audit.py
tasks = {int(t["task_id"]): t for t in audit["tasks"]}
rows = q("SELECT id, name, script_id, schedule_expression, next_execution_at, last_execution_at "
         "FROM ak_scheduled_tasks WHERE is_active=1")
byid = {r["id"]: r for r in rows}
ran = {r["task_id"]: r for r in q("SELECT task_id, SUM(status='completed') ok, SUM(status='failed') bad "
                                  "FROM ak_task_executions WHERE created_at>=%s GROUP BY task_id",
                                  ("2026-11-05 14:03:00",))}

out = []
A = collections.defaultdict(list)
B = collections.defaultdict(list)
C = []
for r in rows:
    t = tasks.get(r["id"])
    fam = t["family"] if t else "(not-in-audit)"
    if fam == "script_file_absent":
        A[t["script_id"]].append(r["id"])
    elif fam == "unexpected_param":
        B[(t["script_id"], ",".join(t.get("offending_keys") or [t.get("detail_key", "")]))].append(r["id"])
    n, cad = slots_for(r["schedule_expression"])
    if n and r["id"] not in ran:
        C.append((r["id"], r["name"][:44], r["schedule_expression"], cad, n))

out.append(f"# AC11 处置输入清单（由 #284 普查 + cron 应跑槽位计算得出，只读，2026-11-06）\n")
out.append(f"armed tasks: {len(rows)}; audit rows: {len(tasks)}; tasks with a post-repair execution: {len(ran)}\n")

out.append("\n## 队列 A：注册指向树中不存在文件的 armed 任务（静态不可运行）")
if not A:
    out.append(
        "共 0 个任务 —— 这是**预期结果**：本查询只遍历 `is_active=1` 的任务，而属主 2026-11-06 "
        "13:47:56 UTC 的裁定已用 `ac11_retire_queue_a.py` 把当时的 50 个队列 A 任务停用。\n"
        "  停用前的队列构成（50 任务 / 7 脚本）见 RUNTIME_READOUT_20261106.md §3 与 before-image；\n"
        "  把本脚本改成同时统计 inactive 任务才能复现该队列，此处不改动口径，只说明它为何为空。"
    )
else:
    out.append(f"共 {sum(len(v) for v in A.values())} 个任务，涉及 {len(A)} 个 script_id\n")
    for sid, ids in sorted(A.items(), key=lambda x: -len(x[1])):
        out.append(f"- {sid}: {len(ids)} task(s) -> ids {ids[:12]}{'...' if len(ids) > 12 else ''}")

out.append("\n## 队列 B：调度注入的参数不被目标 entrypoint 接受的 armed 任务")
out.append(f"共 {sum(len(v) for v in B.values())} 个任务\n")
for (sid, keys), ids in sorted(B.items(), key=lambda x: -len(x[1])):
    out.append(f"- {sid} offending_keys=[{keys}]: {len(ids)} task(s) -> ids {ids}")

out.append("\n## 队列 C：窗口内按其 cron 应当至少触发一次、但修复后从未记录执行的 armed 任务")
out.append(f"共 {len(C)} 个\n")
for tid, name, expr, cad, n in sorted(C, key=lambda x: -x[4])[:60]:
    out.append(f"- id={tid} due_slots={n} cadence={cad} cron='{expr}' name={name}")
if len(C) > 60:
    out.append(f"- ...（其余 {len(C) - 60} 条同形，完整清单可由同一脚本重生成）")

out.append("\n## 队列 D：静态分类合计（与上面三队不重叠的部分）")
cnt = collections.Counter(t["family"] for t in audit["tasks"])
for fam, n in cnt.most_common():
    out.append(f"- {fam}: {n}")
pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "ac11-disposition-input.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out[:1]))
print(f"written: /tmp/it204/ac11-disposition-input.md")
print(f"A={sum(len(v) for v in A.values())} tasks / {len(A)} scripts; "
      f"B={sum(len(v) for v in B.values())} tasks; C={len(C)} tasks; families={dict(cnt)}")
conn.close()
