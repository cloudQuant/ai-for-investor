#!/usr/bin/env python3
"""Audit every armed akshare task's parameters against its resolved entrypoint.

Static and read-only. Collection scripts are parsed with :mod:`ast`, never imported,
so running this cannot execute a network call or a database write. The metadata query
is ``SELECT`` only and the session is opened ``READ ONLY`` where the driver supports it.

Usage:

    cd src/backend
    .venv/bin/python scripts/task_param_audit.py                 # live .env from this tree
    .venv/bin/python scripts/task_param_audit.py --env-file /path/to/running/.env \
        --out-dir var/reports/iteration204

Exit codes: 0 = every armed task resolved and bound, 1 = at least one task failed to
bind or could not be resolved statically. Credentials and connection URLs are never
printed, logged or embedded in the report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import dotenv_values  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine.url import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.services.akshare.param_bind_audit import (  # noqa: E402
    CLASS_ACCEPTS_VAR_KWARGS,
    CLASS_BINDS,
    CLASS_MISSING_REQUIRED_PARAM,
    CLASS_SCRIPT_FILE_ABSENT,
    CLASS_UNEXPECTED_PARAM,
    CLASS_UNRESOLVABLE,
    InterfaceRow,
    PythonTreeSource,
    TaskAuditResult,
    TaskRecord,
    audit_task,
    driver_safe_default_param_keys,
)

DEFAULT_OUT_DIR = BACKEND_DIR / "var" / "reports" / "iteration204"
DRIVER_FILE = BACKEND_DIR / "app" / "services" / "akshare" / "script.py"
SCRIPT_PACKAGE = "app.data_fetch.scripts"

_TASK_SQL = (
    "SELECT t.id AS task_id, t.script_id AS script_id, t.name AS task_name, "
    "t.parameters AS task_parameters, t.schedule_type AS schedule_type, "
    "t.schedule_expression AS schedule_expression, s.module_path AS module_path, "
    "s.function_name AS function_name, s.source AS source, s.is_custom AS is_custom, "
    "s.frequency AS frequency, s.target_table AS target_table "
    "FROM ak_scheduled_tasks t JOIN ak_data_scripts s ON s.script_id = t.script_id "
    "WHERE t.is_active = 1 ORDER BY t.id"
)
_ORPHAN_SQL = "SELECT COUNT(*) AS n FROM ak_scheduled_tasks WHERE is_active = 1"
_SCRIPT_SQL = "SELECT COUNT(*) AS n, SUM(is_active = 1) AS active FROM ak_data_scripts"
_INTERFACE_SQL = (
    "SELECT name AS name, function_name AS function_name, module_path AS module_path "
    "FROM ak_data_interfaces WHERE is_active = 1"
)
_ALL_SCRIPTS_SQL = (
    "SELECT script_id AS script_id, module_path AS module_path, is_active AS is_active "
    "FROM ak_data_scripts ORDER BY script_id"
)
# Read-only cross-check: parameter binding errors the runtime already produced. Used as
# evidence that the static classification predicts real failures, never as a source of truth.
_BINDING_ERROR_SQL = (
    "SELECT script_id AS script_id, error_message AS error_message FROM ak_task_executions "
    "WHERE error_message LIKE '%unexpected keyword argument%' "
    "OR error_message LIKE '%missing%required argument%' "
    "OR error_message LIKE '%positional-only argument%'"
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--env-file",
        type=Path,
        default=BACKEND_DIR / ".env",
        help="path to the running app's .env (read for DATABASE_URL only)",
    )
    parser.add_argument(
        "--tree",
        type=Path,
        default=BACKEND_DIR,
        help="backend tree whose scripts are audited (the tree the driver imports)",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--max-rows", type=int, default=0, help="limit per-task rows kept in the JSON report"
    )
    parser.add_argument(
        "--only-failures", action="store_true", help="keep only non-binding tasks in the JSON"
    )
    return parser.parse_args(argv)


def database_url_from_env(env_file: Path) -> str:
    if not env_file.is_file():
        raise SystemExit(f"env file not found: {env_file} (pass --env-file)")
    values = dotenv_values(env_file)
    url = values.get("DATABASE_URL") or ""
    if not url:
        raise SystemExit(f"DATABASE_URL missing in {env_file.name}")
    return url


async def load_rows(
    url: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    int,
    str,
    str,
]:
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            readonly = False
            try:
                await conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
                readonly = True
            except Exception:  # dialect without a read-only session pragma
                pass
            tasks = [dict(row) for row in (await conn.execute(text(_TASK_SQL))).mappings().all()]
            scripts = dict((await conn.execute(text(_SCRIPT_SQL))).mappings().one())
            interfaces = [
                dict(row) for row in (await conn.execute(text(_INTERFACE_SQL))).mappings().all()
            ]
            armed = int((await conn.execute(text(_ORPHAN_SQL))).scalar_one())
            all_scripts = [
                dict(row) for row in (await conn.execute(text(_ALL_SCRIPTS_SQL))).mappings().all()
            ]
            try:
                binding_errors = [
                    dict(row)
                    for row in (await conn.execute(text(_BINDING_ERROR_SQL))).mappings().all()
                ]
            except Exception:  # table absent on a minimal metadata DB
                binding_errors = []
            parsed = make_url(url)
            return (
                tasks,
                interfaces,
                scripts,
                all_scripts,
                binding_errors,
                armed,
                f"{parsed.drivername}/{parsed.database}",
                "session_read_only" if readonly else "select_only",
            )
    finally:
        await engine.dispose()


def script_file_for(tree: Path, module_path: str | None) -> Path | None:
    if not module_path:
        return None
    if not module_path.startswith(f"{SCRIPT_PACKAGE}."):
        return None
    relative = module_path[len(SCRIPT_PACKAGE) + 1 :].replace(".", "/")
    return tree / "app" / "data_fetch" / "scripts" / f"{relative}.py"


def _file_exists(path: Path | None) -> bool:
    return path is not None and path.is_file()


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


def _key_named_in_error(message: str) -> str:
    match = re.search(r"unexpected keyword argument '?\"?([A-Za-z_][A-Za-z0-9_]*)", message)
    if match:
        return match.group(1)
    match = re.search(
        r"missing \d+ required positional argument: '?\"?([A-Za-z_][A-Za-z0-9_]*)", message
    )
    if match:
        return match.group(1)
    match = re.search(
        r"positional-only arguments passed as keyword arguments: '?\"?([A-Za-z_][A-Za-z0-9_]*)",
        message,
    )
    return match.group(1) if match else ""


def runtime_binding_evidence(
    rows: Sequence[dict[str, Any]], results: Sequence[TaskAuditResult]
) -> dict[str, Any]:
    """Cross-tab past runtime binding errors against the static verdicts."""
    by_script: dict[str, list[TaskAuditResult]] = {}
    for result in results:
        by_script.setdefault(result.script_id, []).append(result)
    observed: Counter[tuple[str, str]] = Counter()
    for row in rows:
        message = str(row.get("error_message") or "")
        observed[(str(row.get("script_id") or ""), _key_named_in_error(message))] += 1

    items: list[dict[str, Any]] = []
    predicted = 0
    unexplained: list[str] = []
    for (script_id, key), executions in observed.items():
        classes = sorted({result.classification for result in by_script.get(script_id, [])})
        static_flags_the_key = any(
            key in result.offending_keys for result in by_script.get(script_id, [])
        )
        if static_flags_the_key:
            predicted += 1
        else:
            unexplained.append(f"{script_id}:{key}")
        items.append(
            {
                "script_id": script_id,
                "key": key,
                "executions": executions,
                "static_classes": classes,
                "predicted_by_audit": static_flags_the_key,
            }
        )
    items.sort(key=lambda item: (-item["executions"], item["script_id"]))
    return {
        "executions_with_binding_errors": len(rows),
        "distinct_script_key_pairs": len(items),
        "script_key_pairs_predicted_by_this_audit": predicted,
        "unexplained_script_key_pairs": sorted(unexplained),
        "items": items,
    }


def build_report(
    results: Sequence[TaskAuditResult],
    *,
    armed_tasks: int,
    joined_tasks: int,
    script_rows: Mapping[str, Any],
    interface_rows: int,
    database_label: str,
    read_only_mode: str,
    tree: Path,
    default_injections: int,
    max_rows: int = 0,
    only_failures: bool = False,
) -> dict[str, Any]:
    family_counts = Counter(result.family for result in results)
    exact_counts = Counter(result.classification for result in results)
    reasons = Counter(result.reason for result in results if result.family == CLASS_UNRESOLVABLE)
    per_script: dict[str, dict[str, Any]] = {}
    for result in results:
        if result.family in (CLASS_BINDS, CLASS_ACCEPTS_VAR_KWARGS):
            continue
        entry = per_script.setdefault(
            result.script_id,
            {
                "script_id": result.script_id,
                "task_count": 0,
                "classes": Counter(),
                "signature": f"{result.signature_file}:{result.signature_line}"
                if result.signature_file
                else "",
                "entrypoint": result.signature_callable,
            },
        )
        entry["task_count"] += 1
        entry["classes"][result.classification] += 1
    offenders = sorted(
        (
            {
                "script_id": row["script_id"],
                "task_count": row["task_count"],
                "classes": dict(row["classes"]),
                "signature": row["signature"],
                "entrypoint": row["entrypoint"],
            }
            for row in per_script.values()
        ),
        key=lambda row: (-row["task_count"], row["script_id"]),
    )

    kept = [result for result in results if not only_failures or result.family != CLASS_BINDS]
    if max_rows > 0:
        kept = kept[:max_rows]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": {
            "database": database_label,
            "read_only_mode": read_only_mode,
            "audited_tree": str(tree),
            "script_package": SCRIPT_PACKAGE,
            "interface_rows": interface_rows,
            "safe_default_injected_scripts": default_injections,
            "ak_data_script_rows": int(script_rows.get("n") or 0),
            "ak_data_script_rows_active": int(script_rows.get("active") or 0),
            "armed_tasks": armed_tasks,
            "tasks_joined_to_script_rows": joined_tasks,
            "tasks_without_script_row": armed_tasks - joined_tasks,
            "tasks_audited": len(results),
        },
        "family_counts": dict(sorted(family_counts.items())),
        "exact_classification_counts": dict(sorted(exact_counts.items())),
        "unresolvable_reason_counts": dict(sorted(reasons.items())),
        "offending_scripts": offenders,
        "tasks": [jsonable(result) for result in kept],
    }


def human_summary(report: Mapping[str, Any], results: Sequence[TaskAuditResult]) -> str:
    scope = report["scope"]
    families = report["family_counts"]
    lines: list[str] = ["# akshare task parameter binder audit", ""]
    lines.append(f"- generated (UTC): {report['generated_at_utc']}")
    lines.append(
        f"- armed tasks: {scope['armed_tasks']} (joined to a script row: "
        f"{scope['tasks_joined_to_script_rows']}, without one: "
        f"{scope['tasks_without_script_row']}, audited: {scope['tasks_audited']})"
    )
    lines.append(
        f"- ak_data_scripts rows: {scope['ak_data_script_rows']} "
        f"(active {scope['ak_data_script_rows_active']}); of those audited, "
        f"{scope['registered_script_rows_without_file']} name a file absent from the tree; "
        f"ak_data_interfaces rows: {scope['interface_rows']}"
    )
    lines.append(f"- audited tree: {scope['audited_tree']}")
    lines.append("")
    lines.append("## Per-class counts")
    for name in (
        CLASS_BINDS,
        CLASS_UNEXPECTED_PARAM,
        CLASS_MISSING_REQUIRED_PARAM,
        CLASS_ACCEPTS_VAR_KWARGS,
        CLASS_SCRIPT_FILE_ABSENT,
        CLASS_UNRESOLVABLE,
    ):
        lines.append(f"- {name}: {families.get(name, 0)}")
    lines.append("")
    lines.append("## Unresolvable reasons")
    reasons: Mapping[str, int] = report["unresolvable_reason_counts"]
    if not reasons:
        lines.append("- (none)")
    for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {reason}: {count}")
    lines.append("")
    lines.append("## Top offending scripts (tasks that do not bind)")
    offenders = report["offending_scripts"]
    if not offenders:
        lines.append("- (none)")
    for row in offenders[:25]:
        classes = ", ".join(f"{key} x{value}" for key, value in row["classes"].items())
        lines.append(f"- {row['script_id']}: {row['task_count']} task(s) [{classes}]")
    lines.append("")
    lines.append("## Exact classifications")
    for classification, count in sorted(
        report["exact_classification_counts"].items(), key=lambda item: (-item[1], item[0])
    ):
        lines.append(f"- {classification}: {count}")
    decorated = sum(
        1 for result in results if any(n.startswith("decorated_by_") for n in result.notes)
    )
    evidence: Mapping[str, Any] = report.get("runtime_binding_evidence", {})
    lines += [
        "",
        "## Runtime binding errors already recorded",
        f"- executions carrying a binding error: "
        f"{evidence.get('executions_with_binding_errors', 0)}",
        f"- distinct (script, key) pairs: {evidence.get('distinct_script_key_pairs', 0)}; "
        f"predicted by this audit: "
        f"{evidence.get('script_key_pairs_predicted_by_this_audit', 0)}",
    ]
    for item in list(evidence.get("items", []))[:10]:
        lines.append(
            f"- {item['script_id']} key={item['key'] or '(unparsed)'} "
            f"executions={item['executions']} audit={item['static_classes']}"
        )
    unexplained = evidence.get("unexplained_script_key_pairs") or []
    if unexplained:
        lines.append(
            f"- recorded but not predicted from the CURRENT rows: {', '.join(unexplained)}"
        )
    lines.append(
        "- the runtime cross-check compares history with today's task rows and this tree's "
        "script source; a since-fixed script or a since-edited parameter row shows up as "
        "recorded-but-not-predicted, which is not an audit miss"
    )
    lines += [
        "",
        "## Caveats",
        f"- entrypoints classified from an undecorated `def` signature (decorated: {decorated})",
        "- `accepts_var_kwargs` tasks are unverifiable statically, not proven safe",
        "- positional-only parameters are reported as unbindable by keyword, per CPython",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    tree: Path = args.tree.resolve()
    env_file: Path = args.env_file
    url = database_url_from_env(env_file)
    (
        tasks,
        interfaces,
        scripts,
        all_scripts,
        binding_errors,
        armed,
        database_label,
        read_only_mode,
    ) = asyncio.run(load_rows(url))
    source = PythonTreeSource(tree)
    defaults = driver_safe_default_param_keys(tree / "app" / "services" / "akshare" / "script.py")
    interface_index: dict[tuple[str, str], InterfaceRow] = {}
    for row in interfaces:
        name = str(row["name"])
        function = str(row["function_name"] or "")
        module = str(row["module_path"] or "akshare")
        interface_index[(name, function)] = InterfaceRow(module_path=module, function_name=function)

    results: list[TaskAuditResult] = []
    for row in tasks:
        module_path = row["module_path"]
        script_id = str(row["script_id"])
        record = TaskRecord(
            task_id=int(row["task_id"]),
            script_id=script_id,
            module_path=str(module_path) if module_path else None,
            function_name=str(row["function_name"]) if row["function_name"] else None,
            source=str(row["source"]) if row["source"] else None,
            is_custom=bool(row["is_custom"]),
            parameters=row["task_parameters"],
            interface_row=interface_index.get((script_id, str(row["function_name"] or ""))),
        )
        results.append(
            audit_task(
                record,
                source,
                script_file=script_file_for(tree, record.module_path),
                default_keys=defaults,
            )
        )

    ghost_scripts = [
        str(row["script_id"])
        for row in all_scripts
        if not _file_exists(
            script_file_for(tree, str(row["module_path"]) if row["module_path"] else None)
        )
    ]

    report = build_report(
        results,
        armed_tasks=armed,
        joined_tasks=len(tasks),
        script_rows=scripts,
        interface_rows=len(interfaces),
        database_label=database_label,
        read_only_mode=read_only_mode,
        tree=tree,
        default_injections=len(defaults),
        max_rows=int(args.max_rows),
        only_failures=bool(args.only_failures),
    )
    report["scope"]["registered_script_rows_without_file"] = len(ghost_scripts)
    report["scope"]["registered_script_rows_audited"] = len(all_scripts)
    report["ghost_script_ids"] = sorted(ghost_scripts)
    report["runtime_binding_evidence"] = runtime_binding_evidence(binding_errors, results)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "task_param_bind_audit.json"
    summary_path = args.out_dir / "task_param_bind_audit.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(human_summary(report, results), encoding="utf-8")

    families = report["family_counts"]
    print(
        json.dumps({"family_counts": families, "scope": report["scope"]}, indent=2, sort_keys=True)
    )
    print(f"report: {json_path}")
    print(f"summary: {summary_path}")
    unbound = sum(count for name, count in families.items() if name != CLASS_BINDS)
    return 1 if unbound else 0


if __name__ == "__main__":
    raise SystemExit(main())
