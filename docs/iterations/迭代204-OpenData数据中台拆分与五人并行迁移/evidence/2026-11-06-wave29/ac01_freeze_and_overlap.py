"""Reproduce AC01 surfaces 1 (repo freeze + uncommitted diff hashes) and 7 (OD overlap).

Read-only: git subcommands, file reads, information_schema queries only.
"""

from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import re
import subprocess

import pymysql

AFI = pathlib.Path("/home/yun/Documents/ai-for-investor")
OD = pathlib.Path("/home/yun/Documents/opendata")
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def sh(cwd: pathlib.Path, *args: str) -> str:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True).stdout


def freeze(root: pathlib.Path) -> dict:
    diff = sh(root, "git", "diff", "HEAD")
    porcelain = sh(root, "git", "status", "--porcelain=v1", "-uno")
    untracked = sh(root, "git", "ls-files", "--others", "--exclude-standard")
    return {
        "head": sh(root, "git", "rev-parse", "HEAD").strip(),
        "tracked_diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
        "status_porcelain_sha256": hashlib.sha256(porcelain.encode()).hexdigest(),
        "untracked_entries": len([x for x in untracked.splitlines() if x.strip()]),
        "untracked_list_sha256": hashlib.sha256(untracked.encode()).hexdigest(),
    }


def worktree_state(afi: pathlib.Path) -> dict:
    lines = [l.split()[0] for l in sh(afi, "git", "worktree", "list").splitlines() if l.strip()]
    dirty = []
    for wt in lines:
        p = pathlib.Path(wt)
        status = sh(p, "git", "status", "--porcelain=v1", "-uno")
        if status.strip():
            dirty.append({
                "worktree": wt,
                "head": sh(p, "git", "rev-parse", "HEAD").strip()[:12],
                "changed_files": len([x for x in status.splitlines() if x.strip()]),
                "diff_sha256_16": hashlib.sha256(sh(p, "git", "diff", "HEAD").encode()).hexdigest()[:16],
            })
    return {"worktrees": len(lines), "dirty": dirty}


def od_catalog_overlap(od: pathlib.Path, afi: pathlib.Path) -> dict:
    candidates = sorted(od.glob("var/reports/afi204/*/source/docs/afi204-migration-catalog.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return {"error": "no migration catalog snapshot found under opendata/var/reports/afi204"}
    newest = candidates[0]
    cat = json.loads(newest.read_text())
    files = cat.get("files") or []
    tracked = {p for p in sh(afi, "git", "ls-files", "src/backend/app/data_fetch/scripts").split()
               if p.endswith(".py") and not p.endswith("__init__.py")}
    cat_paths = {f.get("source_path") for f in files}
    models = cat.get("opendata_provider_models") or []
    akshare_models = [m for m in models if m.get("source") == "akshare"]
    akshare_fns = {fn for m in akshare_models for fn in (m.get("source_functions") or [])}
    eps = cat.get("provider_endpoint_catalog") or []
    return {
        "catalog_path": str(newest),
        "catalog_file_rows": len(files),
        "afi_tracked_scripts": len(tracked),
        "catalog_intersect_afi": len(cat_paths & tracked),
        "catalog_only": sorted(x.rsplit("/", 1)[-1] for x in cat_paths - tracked),
        "afi_only_count": len(tracked - cat_paths),
        "status_tally": dict(collections.Counter(f.get("status", "?") for f in files).most_common()),
        "sink_tally": dict(collections.Counter(str(f.get("sink_status")) for f in files).most_common(6)),
        "runtime_verification": dict(collections.Counter(str(f.get("runtime_verification")) for f in files).most_common(4)),
        "provider_models_total": len(models),
        "provider_models_akshare": len(akshare_models),
        "akshare_function_names_covered": sorted(akshare_fns),
        "endpoint_rows": len(eps),
        "endpoint_tally": dict(collections.Counter(str(e.get("classification") or e.get("status")) for e in eps).most_common(6)),
    }


def schemas() -> dict:
    env = (AFI / "src/backend/.env").read_text()

    def value(key: str) -> str | None:
        m = re.search(rf"^{key}\s*=\s*(.+)$", env, re.M)
        return m.group(1).strip().strip("\"'") if m else None

    u = re.match(r"^[+a-z]*://([^:]+):([^@]*)@([^:/]+):?(\d*)", value("DATABASE_URL") or "")
    assert u, "DATABASE_URL missing"
    conn = pymysql.connect(host=u.group(3), port=int(u.group(4) or 3306), user=u.group(1),
                           password=u.group(2), cursorclass=pymysql.cursors.DictCursor, read_timeout=120)
    with conn.cursor() as cur:
        cur.execute("SELECT table_schema, COUNT(*) n FROM information_schema.tables "
                    "WHERE table_schema IN ('ai_for_investor','akshare_data','backtrader_web') GROUP BY 1")
        counts = {r["TABLE_SCHEMA"]: r["n"] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) n FROM ai_for_investor.ak_scheduled_tasks WHERE is_active=1")
        armed = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM ai_for_investor.md_capability_ledger_entries")
        ledger = cur.fetchone()["n"]
    conn.close()
    return {"schema_table_counts": counts, "armed_tasks": armed, "capability_ledger_rows": ledger}


def main() -> None:
    out = {
        "empty_tree_sha256_reference": EMPTY_SHA,
        "repos": {str(p): freeze(p) for p in (AFI, OD)},
        "afi_worktrees": worktree_state(AFI),
        "od_overlap": od_catalog_overlap(OD, AFI),
        "db": schemas(),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
