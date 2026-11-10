#!/usr/bin/env python3
"""Join the #284 static census with post-repair executions into the AC11 runtime-evidence ratio.

Read-only. The census JSON (produced by ``scripts/task_param_audit.py``) supplies the static
family of every armed task; a ``SELECT``-only aggregate over ``ak_task_executions`` since the
repair marker supplies what actually ran, finished, and wrote rows. The session is opened
``READ ONLY`` where the driver supports it and no other table is touched.

Honesty requirement: a ``runtime_evidenced`` task is an INPUT to the AC11 disposition, not a
disposition. ``completed AND row delta > 0`` proves the task bound its parameters and wrote
something on the repaired collector; it does not prove a human reviewed the task. The
``assigned`` count AC11 reports as "已处置脚本 / 总脚本" comes from the disposition ledger and
is never computed here — this script only says so explicitly in its own output. The numerator
moves as the collector runs, which is why every report carries an as-of UTC timestamp.

Clock safety: ``ak_task_executions.created_at`` is stored in UTC, while
``ak_scheduled_tasks.last_execution_at``/``next_execution_at`` are host-local (Asia/Shanghai)
— a defect tracked in PR #306. This script therefore reads only ``ak_task_executions`` and
never compares across those two clocks.

Usage:

    cd src/backend
    .venv/bin/python scripts/ops/ac11_runtime_evidence.py \
        --census var/reports/iteration204/task_param_bind_audit.json \
        --out-dir var/reports/ac11

Exit codes: 0 = report written, 2 = census JSON missing or without a ``tasks`` array (the
script refuses before touching the database). Credentials and connection URLs are never
printed, logged or embedded in the report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import dotenv_values  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

DEFAULT_OUT_DIR = BACKEND_DIR / "var" / "reports" / "ac11"
# First successful post-repair collector run; executions before it ran the old broken code.
REPAIR_MARKER_UTC = "2026-11-05T14:03:00+00:00"
# Owner ruling that retired the 50 ``script_file_absent`` tasks; used only to label which
# population the census was read from, never to filter anything.
RETIREMENT_MARKER_UTC = "2026-11-06T13:47:56+00:00"

OUTCOME_GREW = "completed_and_grew"
OUTCOME_NO_DELTA = "completed_no_delta"
OUTCOME_FAILED_ONLY = "failed_only"
OUTCOME_NOT_RUN = "not_run"
OUTCOMES = (OUTCOME_GREW, OUTCOME_NO_DELTA, OUTCOME_FAILED_ONLY, OUTCOME_NOT_RUN)


def _executions_sql(triggered_by: str | None) -> str:
    """Build the aggregate query, optionally restricted to one trigger source.

    ``triggered_by`` separates scheduler-cadence evidence from manually
    triggered executions; the ratio must always name which one it measured.
    """
    sql = (
        "SELECT task_id AS task_id, "
        "COUNT(*) AS total_executions, "
        "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_executions, "
        "SUM(CASE WHEN status = 'completed' AND rows_after > rows_before THEN 1 ELSE 0 END) "
        "AS grew_executions, "
        "MAX(created_at) AS last_created_at "
        "FROM ak_task_executions "
        "WHERE created_at >= :window_start AND task_id IS NOT NULL "
    )
    if triggered_by:
        sql += "AND triggered_by = :triggered_by "
    return sql + "GROUP BY task_id"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--census",
        type=Path,
        required=True,
        help="task_param_bind_audit.json produced by scripts/task_param_audit.py",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=BACKEND_DIR / ".env",
        help="path to the running app's .env (read for DATABASE_URL only)",
    )
    parser.add_argument(
        "--triggered-by",
        choices=("scheduler", "manual", "api"),
        default=None,
        help=(
            "restrict evidence to one trigger source; pass scheduler to measure scheduler "
            "cadence, manual to measure hand-exercised scripts (default: every source)"
        ),
    )
    parser.add_argument(
        "--since",
        default=REPAIR_MARKER_UTC,
        help=(
            "UTC ISO timestamp; only ak_task_executions created_at at or after it count as "
            "runtime evidence (the scheduler's last/next_execution_at columns are local-time "
            "and are deliberately not read, see PR #306)"
        ),
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


def load_census(path: Path) -> dict[str, Any]:
    """Read and validate the census JSON; refuse anything unusable before the DB is touched."""
    if not path.is_file():
        raise SystemExit(f"census JSON not found: {path} (run scripts/task_param_audit.py first)")
    try:
        census = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"census JSON unreadable: {path}: {exc}") from exc
    tasks = census.get("tasks") if isinstance(census, dict) else None
    if not isinstance(tasks, list):
        raise SystemExit(f"census JSON has no `tasks` array: {path}")
    return census


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _to_naive_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def task_outcome(stat: Mapping[str, Any] | None, *, window_start: datetime) -> str:
    """Classify one census task from its aggregated execution stat."""
    if stat is None:
        return OUTCOME_NOT_RUN
    last = _to_naive_utc(stat.get("last_created_at"))
    if last is None or last < window_start.replace(tzinfo=None):
        # every recorded execution predates the evidence window -> no runtime evidence
        return OUTCOME_NOT_RUN
    completed = int(stat.get("completed_executions") or 0)
    grew = int(stat.get("grew_executions") or 0)
    if completed > 0:
        return OUTCOME_GREW if grew > 0 else OUTCOME_NO_DELTA
    return OUTCOME_FAILED_ONLY


def classify_census(
    census_tasks: Sequence[Mapping[str, Any]],
    executions_by_task: Mapping[int, Mapping[str, Any]],
    *,
    window_start: datetime,
) -> list[dict[str, Any]]:
    """Pure classification: every census row lands in exactly one outcome bucket, or vanishes
    never — a task absent from the executions table is ``not_run``, not dropped."""
    rows: list[dict[str, Any]] = []
    for task in census_tasks:
        task_id = int(task["task_id"])
        stat = executions_by_task.get(task_id)
        rows.append(
            {
                "task_id": task_id,
                "family": str(task.get("family") or "unknown"),
                "outcome": task_outcome(stat, window_start=window_start),
            }
        )
    return rows


def build_matrix(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """Family x outcome counts; keeps empty cells so every family/outcome pair is visible."""
    counts: Counter[tuple[str, str]] = Counter((row["family"], row["outcome"]) for row in rows)
    families = sorted({row["family"] for row in rows})
    return {
        family: {outcome: counts[(family, outcome)] for outcome in OUTCOMES} for family in families
    }


def population_label(census: Mapping[str, Any]) -> dict[str, Any]:
    """State which armed population the census was read from (pre/post the 13:47 retirement)."""
    scope = census.get("scope") or {}
    generated_at = census.get("generated_at_utc")
    label = "unknown"
    if generated_at:
        try:
            label = (
                "pre-retirement (census generated before the 2026-11-06T13:47:56Z owner ruling)"
                if parse_utc(str(generated_at)) < parse_utc(RETIREMENT_MARKER_UTC)
                else "post-retirement (census generated at/after the 2026-11-06T13:47:56Z ruling)"
            )
        except ValueError:
            label = "unknown (unparsable census timestamp)"
    return {
        "armed_tasks_in_census_scope": scope.get("armed_tasks"),
        "census_generated_at_utc": generated_at,
        "population_relative_to_retirement": label,
    }


def build_report(
    census: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    window_start: datetime,
    database_label: str,
    read_only_mode: str,
) -> dict[str, Any]:
    population = len(census.get("tasks") or [])
    if len(rows) != population:
        raise SystemExit(
            f"internal error: classified {len(rows)} tasks but the census holds "
            f"{population}; refusing to emit a ratio with a mismatched denominator"
        )
    matrix = build_matrix(rows)
    outcome_totals = Counter(row["outcome"] for row in rows)
    evidenced = outcome_totals[OUTCOME_GREW]
    if sum(sum(cell.values()) for cell in matrix.values()) != population:
        raise SystemExit("internal error: matrix cells do not sum to the population")
    return {
        "as_of_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "evidence_window_start_utc": window_start.isoformat(timespec="seconds"),
        "census": population_label(census),
        "scope": {
            "database": database_label,
            "read_only_mode": read_only_mode,
            "population_tasks_read_from_census": population,
            "denominator_note": (
                "the denominator below is exactly the census tasks read; AC11 must quote it "
                "with this as_of_utc timestamp, never as a bare sentence"
            ),
        },
        "outcome_totals": {outcome: outcome_totals[outcome] for outcome in OUTCOMES},
        "family_x_outcome": matrix,
        "numerator": {
            "AC11_RUNTIME_EVIDENCED": evidenced,
            "population": population,
            "ratio": f"{evidenced}/{population}",
            "definition": (
                "census task with at least one ak_task_executions row in the window with "
                "status='completed' AND rows_after > rows_before"
            ),
        },
        "assigned": {
            "value": "not computed here",
            "source": (
                "the human-reviewed `assigned` sign-off count comes from the AC11 disposition "
                "ledger; runtime evidence is an input to disposition, not a disposition"
            ),
        },
        "caveats": [
            "runtime_evidenced != assigned: no human sign-off is implied by a growing run",
            "the number moves as the collector runs; only valid at as_of_utc",
            "reads ak_task_executions only; the scheduler's host-local last/next_execution_at "
            "columns (PR #306) are never compared against this UTC window",
            "executions before the repair marker ran the old collector and are excluded",
        ],
        "tasks": rows,
    }


def human_summary(report: Mapping[str, Any]) -> str:
    numerator = report["numerator"]
    census = report["census"]
    lines: list[str] = ["# AC11 runtime evidence (read-only)", ""]
    lines.append(f"- as of (UTC): {report['as_of_utc']}")
    lines.append(f"- evidence window starts: {report['evidence_window_start_utc']} UTC")
    lines.append(
        f"- population: {numerator['population']} census tasks "
        f"(armed_tasks in census scope: {census['armed_tasks_in_census_scope']}; "
        f"{census['population_relative_to_retirement']})"
    )
    lines.append(f"- database: {report['scope']['database']} ({report['scope']['read_only_mode']})")
    lines.append("")
    lines.append("## Family x outcome matrix")
    lines.append(f"| family | {' | '.join(OUTCOMES)} |")
    lines.append(f"|---|{'---|' * len(OUTCOMES)}")
    for family, cells in report["family_x_outcome"].items():
        lines.append(f"| {family} | {' | '.join(str(cells[o]) for o in OUTCOMES)} |")
    totals = report["outcome_totals"]
    lines.append(f"| **total** | {' | '.join(str(totals[o]) for o in OUTCOMES)} |")
    lines.append("")
    lines.append("## AC11 numerator")
    lines.append(
        f"- AC11_RUNTIME_EVIDENCED / population = {numerator['AC11_RUNTIME_EVIDENCED']} / "
        f"{numerator['population']} (denominator is the population actually read from the census)"
    )
    lines.append(f"- definition: {numerator['definition']}")
    lines.append("")
    lines.append("## Assigned (NOT computed here)")
    lines.append(f"- assigned: {report['assigned']['value']} — {report['assigned']['source']}")
    lines.append("")
    lines.append("## Caveats")
    for caveat in report["caveats"]:
        lines.append(f"- {caveat}")
    return "\n".join(lines) + "\n"


async def load_executions(
    url: str, window_start: datetime, triggered_by: str | None = None
) -> tuple[dict[int, Any], str, str]:
    # MySQL has no timezone-aware DATETIME; bind the naive-UTC form of the window start.
    params: dict[str, Any] = {"window_start": _to_naive_utc(window_start)}
    if triggered_by:
        params["triggered_by"] = triggered_by
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            readonly = False
            try:
                await conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
                readonly = True
            except Exception:  # dialect without a read-only session pragma
                pass
            result = (await conn.execute(text(_executions_sql(triggered_by)), params)).mappings()
            stats = {int(row["task_id"]): dict(row) for row in result.all()}
            parsed_url = str(url).split("://", 1)[-1].split("@", 1)[-1].split("?", 1)[0]
            host_db = parsed_url.rsplit("/", 1)[-1] if "/" in parsed_url else parsed_url
            return (
                stats,
                f"select_only/ak_task_executions@{host_db}",
                ("session_read_only" if readonly else "select_only"),
            )
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    census = load_census(args.census)  # refuses (SystemExit, non-zero) before any DB touch
    window_start = parse_utc(args.since)
    url = database_url_from_env(args.env_file)
    stats, database_label, read_only_mode = asyncio.run(
        load_executions(url, window_start, args.triggered_by)
    )
    rows = classify_census(census["tasks"], stats, window_start=window_start)
    report = build_report(
        census,
        rows,
        window_start=window_start,
        database_label=database_label,
        read_only_mode=read_only_mode,
    )
    if args.triggered_by:
        scope = report.setdefault("scope", {})
        if isinstance(scope, dict):
            scope["triggered_by"] = args.triggered_by
        report.setdefault("caveats", []).append(
            f"evidence restricted to triggered_by={args.triggered_by}"
        )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "ac11_runtime_evidence.json"
    summary_path = args.out_dir / "ac11_runtime_evidence.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(human_summary(report), encoding="utf-8")
    print(
        json.dumps(
            {"numerator": report["numerator"], "outcome_totals": report["outcome_totals"]},
            indent=2,
            sort_keys=True,
        )
    )
    print(f"report: {json_path}")
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
