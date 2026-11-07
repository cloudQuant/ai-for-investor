"""Owner ruling 2026-11-06: deactivate the 50 armed tasks whose registered script file has never
existed in the tree (AC11 queue A). Backs up the exact prior row state first; refuses to write if
the cohort cannot be reproduced from the #284 census.

Usage: run with --apply to write, without it the script is read-only and prints the plan.
"""

import argparse
import datetime
import json
import pathlib
import re

import pymysql

BACKEND = pathlib.Path("/home/yun/Documents/ai-for-investor/src/backend")
OUT = pathlib.Path("/tmp/it204")
CENSUS = OUT / "param-audit" / "task_param_bind_audit.json"


def env_value(key):
    for line in (BACKEND / ".env").read_text().splitlines():
        m = re.match(rf"^\s*{key}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="perform the UPDATE (default: dry-run)")
    args = ap.parse_args()

    census = json.loads(CENSUS.read_text())
    cohort = sorted(int(t["task_id"]) for t in census["tasks"] if t["family"] == "script_file_absent")
    assert cohort, "census produced no script_file_absent tasks -- refusing"
    print(f"cohort from #284 census: {len(cohort)} tasks")

    u = re.match(r"^[+a-z]*://([^:]+):([^@]*)@([^:/]+):?(\d*)/([^?]+)", env_value("DATABASE_URL"))
    conn = pymysql.connect(host=u.group(3), port=int(u.group(4)), user=u.group(1), password=u.group(2),
                           database=u.group(5), cursorclass=pymysql.cursors.DictCursor,
                           autocommit=False, read_timeout=120)
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, script_id, is_active, last_execution_at, next_execution_at, updated_at "
                    "FROM ak_scheduled_tasks WHERE id IN %s ORDER BY id", (tuple(cohort),))
        before = cur.fetchall()
    assert len(before) == len(cohort), f"expected {len(cohort)} rows, read {len(before)}"

    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = OUT / f"ac11-queue-a-before-{stamp}.json"
    backup.write_text(json.dumps([{k: str(v) for k, v in r.items()} for r in before],
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"backup written: {backup}  ({len(before)} rows)")

    armed = [r for r in before if r["is_active"] == 1]
    print(f"currently armed: {len(armed)}; already inactive: {len(before) - len(armed)}")
    if not args.apply:
        print("dry-run: no UPDATE issued. Re-run with --apply.")
        conn.close()
        return

    with conn.cursor() as cur:
        cur.execute("UPDATE ak_scheduled_tasks SET is_active=0, updated_at=UTC_TIMESTAMP() "
                    "WHERE id IN %s AND is_active=1", (tuple(cohort),))
        changed = cur.rowcount
        conn.commit()
        print(f"rows flipped to inactive: {changed}")
        cur.execute("SELECT COUNT(*) n FROM ak_scheduled_tasks WHERE id IN %s AND is_active=1", (tuple(cohort),))
        print(f"still armed after write: {cur.fetchone()['n']}")
        cur.execute("SELECT COUNT(*) n FROM ak_scheduled_tasks WHERE is_active=1")
        print(f"total armed surface now: {cur.fetchone()['n']}")
    conn.close()


if __name__ == "__main__":
    main()
