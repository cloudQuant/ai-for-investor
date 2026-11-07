"""Classify the ghost ak_data_scripts registrations (registered, no file in tree) with evidence.

Read-only: SELECT from the DB + filesystem/git lookups in the AFI tree.
"""

import pathlib
import re
import subprocess

import pymysql

BACKEND = pathlib.Path("/home/yun/Documents/ai-for-investor/src/backend")
ENV = BACKEND / ".env"


def ev(k):
    for line in ENV.read_text().splitlines():
        m = re.match(rf"^\s*{k}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")


u = re.match(r"^[+a-z]*://([^:]+):([^@]*)@([^:/]+):?(\d*)/([^?]+)", ev("DATABASE_URL"))
conn = pymysql.connect(host=u.group(3), port=int(u.group(4)), user=u.group(1), password=u.group(2),
                       database=u.group(5), cursorclass=pymysql.cursors.DictCursor, read_timeout=90)


def q(sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def git(*args):
    r = subprocess.run(["git", "-C", "/home/yun/Documents/ai-for-investor", *args],
                       capture_output=True, text=True, timeout=120)
    return r.stdout.strip()


rows = q("SELECT id, script_id, module_path, function_name, is_active, is_custom, source, target_table "
         "FROM ak_data_scripts ORDER BY id")
print(f"ak_data_scripts rows total: {len(rows)}")

# every python file basename present in the current tree
tree = {p.stem: p for p in (BACKEND / "app" / "data_fetch" / "scripts").rglob("*.py")}
print(f"script files in tree: {len(tree)}")

ghosts = []
for r in rows:
    rel = str(r["module_path"]).replace(".", "/") + ".py"
    if (BACKEND / rel).exists():
        continue
    ghosts.append(r)

print(f"\n=== registered rows whose module_path does not resolve in the tree: {len(ghosts)} ===")
for r in ghosts:
    mp = str(r["module_path"])
    mod = mp.split(".")[-1]
    same_name = tree.get(mod)
    needs_app_prefix = mp.startswith("data_fetch.")
    ever_in_git = git("log", "--all", "--format=%h %ad", "--date=short", "--diff-filter=A",
                      "--", f"src/backend/{mp.replace('.', '/')}.py")
    basename_elsewhere = git("ls-files", f"*{mod}.py")
    cat = []
    if needs_app_prefix:
        cat.append("PREFIX: module_path lacks the 'app.' root")
    if same_name and not needs_app_prefix:
        cat.append(f"MOVED: same basename exists at {same_name.relative_to(BACKEND)}")
    if not same_name and basename_elsewhere:
        cat.append("NAME-ELSEWHERE")
    if not same_name and not basename_elsewhere:
        cat.append("NO-FILE-ANYWHERE")
    if ever_in_git:
        cat.append(f"WAS-ADDED-IN-GIT({ever_in_git.splitlines()[0]})")
    else:
        cat.append("NEVER-IN-GIT-HISTORY")
    armed = q("SELECT COUNT(*) n FROM ak_scheduled_tasks WHERE script_id=%s AND is_active=1", (r["id"],))[0]["n"]
    fails = q("SELECT COUNT(*) n FROM ak_task_executions e JOIN ak_scheduled_tasks t ON t.id=e.task_id "
              "WHERE t.script_id=%s AND e.status='failed' AND e.created_at>='2026-11-05 14:03:00'", (r["id"],))[0]["n"]
    print(f"\n  id={r['id']:<5} script_id={r['script_id']:<32} fn={r['function_name']:<11} "
          f"active={r['is_active']} custom={r['is_custom']} armed_tasks={armed} fails_in_window={fails}")
    print(f"        module_path={mp}")
    print(f"        target_table={r['target_table']} source={r['source']}")
    print(f"        evidence: {' | '.join(cat)}")
conn.close()
