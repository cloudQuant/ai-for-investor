"""Read-only AC14 accrual + entrypoint-failure attribution for iteration-204 wave 29 evidence."""

import re
from pathlib import Path

import pymysql

ENV = Path("/home/yun/Documents/ai-for-investor/src/backend/.env")


def env_value(key):
    for line in ENV.read_text().splitlines():
        m = re.match(rf"^\s*{key}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


u = re.match(r"^[+a-z]*://([^:]+):([^@]*)@([^:/]+):?(\d*)/([^?]+)", env_value("DATABASE_URL"))
conn = pymysql.connect(host=u.group(3), port=int(u.group(4) or 3306), user=u.group(1),
                       password=u.group(2), database=u.group(5),
                       cursorclass=pymysql.cursors.DictCursor, read_timeout=90)


def q(sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


W = "2026-11-05 14:03:00"
print("=== AC14 accrual: completed runs per task, bucketed (window since clock start) ===")
print(q("SELECT COUNT(*) tasks_with_any, SUM(s>=48) ge48, SUM(s>=24) ge24, SUM(s>=7) ge7, SUM(s>=2) ge2, SUM(s>=1) ge1 "
        "FROM (SELECT task_id, COUNT(*) s FROM ak_task_executions WHERE created_at>=%s AND status='completed' GROUP BY task_id) t", (W,)))

print("\n=== per-frequency outcome in window (joined to registered script) ===")
rows = q("SELECT d.frequency, e.status, COUNT(*) c, COUNT(DISTINCT e.task_id) tasks "
        "FROM ak_task_executions e JOIN ak_data_scripts d ON d.id=e.script_id "
        "WHERE e.created_at>=%s GROUP BY 1,2 ORDER BY 1,2", (W,))
for r in rows:
    print(f"  {str(r['frequency']):<10} {r['status']:<10} runs={r['c']:<6} tasks={r['tasks']}")

print("\n=== entrypoint failures: which scripts, how often, first/last ===")
for r in q("SELECT d.script_id, d.module_path, d.function_name, e.error_message, COUNT(*) c, "
           "MIN(e.created_at) first, MAX(e.created_at) last FROM ak_task_executions e "
           "JOIN ak_data_scripts d ON d.id=e.script_id WHERE e.created_at>=%s AND e.status='failed' "
           "GROUP BY 1,2,3,4 ORDER BY c DESC LIMIT 12", (W,)):
    print(f"  {r['c']:>4}x  {r['script_id']:<28} fn={r['function_name']:<12} {r['error_message'][:58]}")
    print(f"        module={r['module_path']}  window={str(r['first'])[:16]}..{str(r['last'])[:16]}")

print("\n=== does the armed surface still match wave 28? ===")
print(q("SELECT COUNT(*) rows, SUM(is_active=1) armed FROM ak_scheduled_tasks"))
print(q("SELECT COUNT(*) ledger_rows FROM md_capability_ledger_entries"))
conn.close()
