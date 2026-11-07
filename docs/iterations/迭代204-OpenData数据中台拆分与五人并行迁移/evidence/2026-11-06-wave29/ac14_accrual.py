"""AC14/AC11 accrual math: cron due-slots since the collector repair vs executions actually recorded.

Read-only. Wave 28 reported AC14's four targets (48 hourly / 7 daily / 2 weekly / 1 sub-daily) all
reading 0; this computes, per armed task, how many slots its own cron expression actually granted
between the repair timestamp and now, so 'not yet accrued' can be separated from 'never ran'.
"""

import datetime
import re
import pathlib

import pymysql

# The scheduler evaluates cron expressions against Asia/Shanghai wall time while execution rows
# are stored in UTC (see wave 28 / PR #282). Both bounds are therefore expressed in Shanghai time.
SH = datetime.timezone(datetime.timedelta(hours=8))
W_START = datetime.datetime(2026, 11, 5, 22, 3, tzinfo=SH)
NOW = datetime.datetime(2026, 11, 6, 21, 33, tzinfo=SH)
WD = {"sun": 6, "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5}
BACKEND = pathlib.Path("/home/yun/Documents/ai-for-investor/src/backend")


def ev(k):
    for line in (BACKEND / ".env").read_text().splitlines():
        m = re.match(rf"^\s*{k}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")


def parse_field(spec, lo, hi, names=None):
    """Expand a single cron field into the set of matching integer values."""
    out = set()
    for part in str(spec).split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, _, s = part.partition("/")
            step = max(int(s), 1)
        if part in ("*", "?"):
            a, b = lo, hi
        elif "-" in part:
            x, _, y = part.partition("-")
            a = int(names[x]) if names and x in names else int(x)
            b = int(names[y]) if names and y in names else int(y)
        else:
            a = int(names[part]) if names and part in names else int(part)
            b = a if step == 1 else hi
        out.update(range(a, b + 1, step))
    return {v for v in out if lo <= v <= hi}


def slots_for(expr, window_start=W_START, window_end=NOW):
    parts = (expr or "").split()
    if len(parts) != 5:
        return None, "bad-shape"
    mi, ho, dom, mo, wd = parts
    if dom != "*" or mo != "*":
        return 0, "dom/mo-restricted"
    minutes = parse_field(mi, 0, 59)
    hours = parse_field(ho, 0, 23)
    weekdays = parse_field(wd, 0, 6, WD) if wd != "*" else set(range(7))
    if ho == "*" or len(hours) >= 20:
        cadence = "hourly"
    elif len(hours) > 1:
        cadence = "sub-daily"
    elif wd == "*":
        cadence = "daily"
    else:
        cadence = "weekly"
    n = 0
    t = window_start.replace(minute=0, second=0, microsecond=0)
    while t < window_end:
        if t.weekday() in weekdays and t.hour in hours and t.minute in minutes:
            n += 1
        t += datetime.timedelta(minutes=1)
    return n, cadence


def main():
    u = re.match(r"^[+a-z]*://([^:]+):([^@]*)@([^:/]+):?(\d*)/([^?]+)", ev("DATABASE_URL"))
    conn = pymysql.connect(host=u.group(3), port=int(u.group(4)), user=u.group(1), password=u.group(2),
                           database=u.group(5), cursorclass=pymysql.cursors.DictCursor, read_timeout=180)
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, schedule_expression FROM ak_scheduled_tasks WHERE is_active=1 AND schedule_type='cron'")
        tasks = cur.fetchall()
        cur.execute("SELECT task_id, COUNT(*) n, SUM(status='completed') ok FROM ak_task_executions WHERE created_at>=%s GROUP BY task_id",
                    (W_START,))
        runs = {r["task_id"]: r for r in cur.fetchall()}
    conn.close()

    per = {}
    for t in tasks:
        n, cad = slots_for(t["schedule_expression"])
        per.setdefault(cad, {"tasks": 0, "due": 0, "ran": 0, "missed": 0, "slot_sum": 0})
        b = per[cad]
        b["tasks"] += 1
        if n:
            b["due"] += 1
            b["slot_sum"] += n
            if t["id"] in runs:
                b["ran"] += 1
            else:
                b["missed"] += 1

    print(f"window: {W_START} -> {NOW} UTC ({(NOW - W_START).total_seconds()/3600:.1f} h), "
          f"armed cron tasks: {len(tasks)}, tasks with >=1 execution: {len(runs)}")
    print("\ncadence      tasks   due-slots>0   ran   never-ran   mean-due-slots")
    for cad in ("sub-daily", "hourly", "daily", "weekly", "dom/mo-restricted", "bad-shape"):
        b = per.get(cad)
        if not b:
            continue
        mean = (b["slot_sum"] / b["due"]) if b["due"] else 0
        print(f"{cad:<12} {b['tasks']:>6} {b['due']:>10} {b['ran']:>8} {b['missed']:>11} {mean:>12.1f}")

    print("\n=== AC14 target check (48 hourly / 7 daily / 2 weekly / 1 sub-daily NATURAL runs) ===")
    for cad, target in (("hourly", 48), ("daily", 7), ("weekly", 2), ("sub-daily", 1)):
        best = 0
        who = None
        for t in tasks:
            n, c = slots_for(t["schedule_expression"])
            if c != cad:
                continue
            r = runs.get(t["id"])
            ok = int(r["ok"]) if r else 0
            if ok > best:
                best, who = ok, t["id"]
        print(f"  {cad:<10} target={target:<3} best observed completed in window={best} (task {who})")
    print("\n  note: 'best observed' is per-task completed executions inside a window shorter than the")
    print("  target itself, so a zero here is arithmetic, not a measurement of the collector.")

    # --- cross-check: ledger's declared frequency vs the cron actually armed for the same task ---
    import csv
    from collections import Counter
    csv_path = pathlib.Path("/home/yun/Documents/ai-for-investor/docs/iterations/"
                            "迭代204-OpenData数据中台拆分与五人并行迁移/script_migration_inventory.csv")
    legacy = {}
    if csv_path.exists():
        for row in csv.DictReader(csv_path.open(encoding="utf-8-sig")):
            legacy[pathlib.Path(row["source_path"].replace("\\", "/")).stem] = row.get("legacy_frequency")
    conn2 = pymysql.connect(host=u.group(3), port=int(u.group(4)), user=u.group(1), password=u.group(2),
                            database=u.group(5), cursorclass=pymysql.cursors.DictCursor, read_timeout=180)
    with conn2.cursor() as cur:
        cur.execute("SELECT t.id, t.schedule_expression, d.script_id AS business_key "
                    "FROM ak_scheduled_tasks t JOIN ak_data_scripts d ON d.id=t.script_id WHERE t.is_active=1")
        pairs = cur.fetchall()
    conn2.close()
    tally = Counter()
    for p in pairs:
        _, cad = slots_for(p["schedule_expression"])
        tally[(legacy.get(p["business_key"], "(not-in-csv)"), cad)] += 1
    print("\n=== declared legacy_frequency (migration CSV) vs cron-derived cadence, per armed task ===")
    cads = sorted({c for (_, c) in tally})
    print("csv\\cron".ljust(16), *[c[:10].rjust(11) for c in cads])
    freqs = sorted({f for (f, _) in tally})
    for f in freqs:
        print(f"{f:<16}", *[str(tally.get((f, c), 0)).rjust(11) for c in cads])
    agree = sum(v for (f, c), v in tally.items() if (f == "daily" and c in ("daily", "hourly", "sub-daily"))
                or (f == "weekly" and c == "weekly") or (f == "hourly" and c in ("hourly", "sub-daily"))
                or (f == "monthly" and c == "weekly"))
    print(f"\n  armed tasks compared: {sum(tally.values())}; loosely-consistent cells: {agree} "
          f"({agree / max(sum(tally.values()), 1) * 100:.1f}%)")


if __name__ == "__main__":
    main()
