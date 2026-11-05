"""Report how much natural-cycle evidence has actually accrued for iteration 204.

AC14 needs consecutive *expected* occurrences (48 hourly, 7 daily, 2 weekly, 1
monthly) traced per cycle, and §6 forbids reading a successful run, a table MAX
or a row count as coverage. So this tool answers one narrow question and refuses
the rest: for each armed task, how many consecutive expected occurrence slots are
backed by a completed execution, and where the run is broken or unverifiable.

Read-only. It never prints the connection string or any credential, and it never
infers a slot it cannot compute (an unsupported schedule shape is reported as
``slot_check_unavailable`` instead of guessed).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

UTC = timezone.utc

# AC14 thresholds, from ACCEPTANCE_AND_CUTOVER.md §1 and §70's note that they are
# this iteration's own proposal and may only be changed by an M0 record.
# ``weekday_daily`` scores against the daily target because AC14's "7 个应运行交易/发布
# 周期" counts occurrences on days the source is expected to publish, not calendar days.
# ``sub_daily`` and ``weekday_sub_daily`` get no target: four runs a day satisfy neither
# 48 hourly occurrences nor one daily occurrence, and inventing one would be a false claim.
CYCLE_TARGETS = {"hourly": 48, "daily": 7, "weekday_daily": 7, "weekly": 2, "monthly": 1}

_COMPLETED = "completed"
_FAILED = "failed"
_RUNNING_STATES = frozenset({"running", "pending"})
# ``params``/``result`` may carry operator input; this tool must never echo them.
_MAX_ERROR_CHARS = 160


@dataclass(frozen=True)
class TaskRow:
    task_id: int
    script_id: str
    schedule_type: str
    schedule_expression: str | None
    next_execution_at: datetime | None
    is_active: bool


@dataclass
class SlotCheck:
    cadence: str
    expected_slots: list[datetime]
    unsupported_reason: str | None = None


@dataclass
class TaskReport:
    task_id: int
    script_id: str
    cadence: str | None
    slot_check: str
    observed: int = 0
    completed: int = 0
    failed: int = 0
    running: int = 0
    wrote_rows: int = 0
    idempotent_zero_row_runs: int = 0
    consecutive_completed_slots: int = 0
    first_occurrence: datetime | None = None
    last_occurrence: datetime | None = None
    last_failure_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "script_id": self.script_id,
            "cadence": self.cadence,
            "slot_check": self.slot_check,
            "observed": self.observed,
            "completed": self.completed,
            "failed": self.failed,
            "running": self.running,
            "wrote_rows": self.wrote_rows,
            "idempotent_zero_row_runs": self.idempotent_zero_row_runs,
            "consecutive_completed_slots": self.consecutive_completed_slots,
            "target": CYCLE_TARGETS.get(str(self.cadence)),
            "target_met": bool(
                self.cadence in CYCLE_TARGETS
                and self.slot_check == "computed"
                and self.consecutive_completed_slots >= CYCLE_TARGETS[self.cadence]
            ),
            "first_occurrence": _iso(self.first_occurrence),
            "last_occurrence": _iso(self.last_occurrence),
            "last_failure_reason": self.last_failure_reason,
            "notes": self.notes,
        }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _as_utc(value: datetime | None) -> datetime | None:
    """Ledger times are stored in UTC; treat naive values as UTC, never as local."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


_DOW_NAMES = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
_WEEKDAYS = frozenset({1, 2, 3, 4, 5})


def _cron_field_count(token: str, bound: int) -> int | None:
    """How many values a cron field admits, or None when the shape is not supported."""
    lowered = token.lower()
    for name, value in _DOW_NAMES.items():
        lowered = lowered.replace(name, str(value))
    if lowered == "*":
        return bound
    values = _field_values(lowered, bound)
    return len(values) if values is not None else None


def classify_cadence(expression: str | None) -> str | None:
    """Map a 5-field cron expression onto an AC14-scoreable cadence, or None.

    AC14 only targets hourly / daily / weekly / monthly, so anything else gets its
    own honest label rather than being folded into a target it does not satisfy:
    `sub_daily` (several fixed hours a day) and `weekday_*` (a dow list) are real
    shapes in this ledger — `57 3,9,15,21 * * mon-fri` is four runs on five days,
    which is neither 24 hourly occurrences nor one daily one. An expression whose
    fields cannot be enumerated returns None so the caller reports the slot check
    as unavailable instead of guessing.
    """
    if not expression:
        return None
    parts = expression.split()
    if len(parts) != 5:
        return None
    minute, hour, day, month, dow = parts
    if month != "*" or not _is_fixed_number(minute):
        return None
    hour_count = _cron_field_count(hour, 24)
    dow_count = _cron_field_count(dow, 7)
    if hour_count is None or dow_count is None:
        return None
    if day != "*":
        return "monthly" if _is_fixed_number(day) and dow == "*" else None
    if dow == "*":
        if hour_count == 24:
            return "hourly"
        return "daily" if hour_count == 1 else "sub_daily"
    weekday_set = _field_values(_expand_dow_names(dow), 7)
    if weekday_set is None:
        return None
    if dow_count == 1 and hour_count == 1:
        # One named or numeric weekday is a weekly occurrence, even when that day
        # happens to fall inside Mon-Fri.
        return "weekly"
    if len(weekday_set) > 1 and weekday_set <= _WEEKDAYS:
        # A dow list spanning several weekdays is "once per trading day", which
        # AC14 scores as a daily occurrence rather than a weekly one.
        return "weekday_daily" if hour_count == 1 else "weekday_sub_daily"
    return None


def _expand_dow_names(token: str) -> str:
    """Translate `mon-fri` style day names into the numbers the field parser reads."""
    return re.sub(r"[a-z]+", lambda m: str(_DOW_NAMES.get(m.group(0), m.group(0))), token.lower())


def _is_fixed_number(token: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}", token))


def _field_values(token: str, bound: int) -> set[int] | None:
    """Enumerate one cron field, supporting only `*`, */N, single ints and lists.

    Anything else returns None, which the caller turns into slot_check_unavailable
    rather than a guess.
    """
    if token == "*":
        return set(range(0, bound))
    if token.startswith("*/"):
        step = token[2:]
        if not step.isdigit() or int(step) == 0:
            return None
        return set(range(0, bound, int(step)))
    if "," in token:
        pieces = token.split(",")
    else:
        pieces = [token]
    out: set[int] = set()
    for piece in pieces:
        if "-" in piece:
            lo, _, hi = piece.partition("-")
            if not (lo.isdigit() and hi.isdigit()):
                return None
            out.update(range(int(lo), int(hi) + 1))
        elif piece.isdigit():
            out.add(int(piece))
        else:
            return None
    return out if out else None


def expected_slots(expression: str | None, start: datetime, end: datetime) -> SlotCheck:
    """Enumerate the occurrence times a 5-field cron expression should have fired."""
    cadence = classify_cadence(expression)
    if cadence is None or expression is None:
        return SlotCheck(
            cadence=str(cadence or "unknown"),
            expected_slots=[],
            unsupported_reason="expression_not_5_field_or_cadence_ambiguous",
        )
    parts = expression.split()
    minute, hour, day, month, dow = parts
    m_vals = _field_values(minute, 60)
    h_vals = _field_values(hour, 24)
    dom_vals = _field_values(day, 32)
    month_vals = _field_values(month, 13)
    dow_vals = _field_values(_expand_dow_names(dow), 7)
    if None in (m_vals, h_vals, dom_vals, month_vals, dow_vals):
        return SlotCheck(
            cadence=cadence, expected_slots=[], unsupported_reason="cron_field_shape_not_supported"
        )
    slots: list[datetime] = []
    cursor = start.replace(second=0, microsecond=0, minute=0, hour=0)
    one_day = timedelta(days=1)
    while cursor <= end:
        if (
            cursor.month in month_vals
            and (cursor.day in dom_vals or day == "*")
            and ((cursor.weekday() + 1) % 7 in dow_vals or dow == "*")
        ):
            for h in sorted(h_vals):
                for m in sorted(m_vals):
                    moment = cursor.replace(hour=h, minute=m)
                    if start <= moment <= end:
                        slots.append(moment)
        cursor += one_day
    slots.sort()
    return SlotCheck(cadence=cadence, expected_slots=slots)


def consecutive_completed_slots(slots: Sequence[datetime], completed: Iterable[datetime]) -> int:
    """Longest run of expected slots that each have a completed execution.

    A slot without one breaks the run, and a completed execution that does not
    line up with any expected slot is ignored: AC14 counts occurrences, not rows.
    """
    done = {_as_utc(value) for value in completed if value is not None}
    best = run = 0
    for slot in slots:
        moment = _as_utc(slot)
        if any(abs((done_at - moment).total_seconds()) <= 900 for done_at in done):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def summarize(
    tasks: Sequence[TaskRow],
    executions: dict[int, list[dict[str, Any]]],
    window_start: datetime,
    window_end: datetime,
) -> list[TaskReport]:
    reports: list[TaskReport] = []
    for task in tasks:
        check = expected_slots(task.schedule_expression, window_start, window_end)
        report = TaskReport(
            task_id=task.task_id,
            script_id=task.script_id,
            cadence=check.cadence,
            slot_check="computed" if check.unsupported_reason is None else "unavailable",
        )
        if check.unsupported_reason:
            report.notes.append(check.unsupported_reason)
        rows = executions.get(task.task_id, [])
        report.observed = len(rows)
        completed_at: list[datetime] = []
        for row in rows:
            status = row.get("status")
            if status == _COMPLETED:
                report.completed += 1
                if row.get("created_at"):
                    completed_at.append(row["created_at"])
            elif status == _FAILED:
                report.failed += 1
                reason = (row.get("error_message") or "").strip()
                if reason:
                    report.last_failure_reason = reason[:_MAX_ERROR_CHARS]
            elif status in _RUNNING_STATES:
                report.running += 1
            delta = row.get("rows_delta")
            if delta is not None and status == _COMPLETED:
                if delta > 0:
                    report.wrote_rows += 1
                elif delta == 0:
                    report.idempotent_zero_row_runs += 1
        stamps = [_as_utc(r.get("created_at")) for r in rows if r.get("created_at")]
        stamps = [value for value in stamps if value is not None]
        if stamps:
            report.first_occurrence = min(stamps)
            report.last_occurrence = max(stamps)
        if check.unsupported_reason is None:
            report.consecutive_completed_slots = consecutive_completed_slots(
                check.expected_slots, completed_at
            )
            if not check.expected_slots:
                report.notes.append("no_expected_slot_in_window")
        reports.append(report)
    return reports


def aggregate(reports: Sequence[TaskReport]) -> dict[str, Any]:
    by_cadence: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for report in reports:
        key = report.cadence or "unknown"
        bucket = by_cadence[key]
        bucket["tasks"] += 1
        bucket["completed"] += report.completed
        bucket["failed"] += report.failed
        bucket["running"] += report.running
        bucket["slot_check_unavailable"] += int(report.slot_check == "unavailable")
        bucket["target_met"] += int(
            report.cadence in CYCLE_TARGETS
            and report.slot_check == "computed"
            and report.consecutive_completed_slots >= CYCLE_TARGETS[str(report.cadence)]
        )
        bucket["max_consecutive"] = max(
            bucket["max_consecutive"], report.consecutive_completed_slots
        )
    return {
        "armed_tasks": len(reports),
        "targets": CYCLE_TARGETS,
        "by_cadence": {cadence: dict(values) for cadence, values in sorted(by_cadence.items())},
        "not_proven_by_this_tool": [
            "coverage / publication state per cycle (needs the warehouse and OpenData)",
            "field-level agreement with the source (AC10, real source required)",
            "single-writer and lease-recovery behaviour (AC13, deployment required)",
            "full-history completeness of any instrument (AC05)",
        ],
    }


def render_markdown(
    summary: dict[str, Any],
    reports: Sequence[TaskReport],
    window_start: datetime,
    window_end: datetime,
) -> str:
    lines = [
        "# 迭代204 自然周期累计（只读台账读数）",
        "",
        f"- 窗口：{_iso(window_start)} → {_iso(window_end)}（**UTC**；`ak_task_executions.created_at` 存的是 UTC）",
        f"- armed 任务：{summary['armed_tasks']}",
        "- 平面：本机 DEPLOYMENT 观测。**本工具不证明覆盖、不证明源侧一致、不证明 AC13/AC14/AC05。**",
        "",
        "| cadence | tasks | completed | failed | running | 最大连续槽位 | 达标 | 槽位检查不可用 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cadence, values in summary["by_cadence"].items():
        lines.append(
            f"| {cadence} | {values.get('tasks', 0)} | {values.get('completed', 0)} | "
            f"{values.get('failed', 0)} | {values.get('running', 0)} | "
            f"{values.get('max_consecutive', 0)} | {values.get('target_met', 0)} | "
            f"{values.get('slot_check_unavailable', 0)} |"
        )
    lines += ["", "## 未闭合的面（本工具无法证明）", ""]
    lines += [f"- {item}" for item in summary["not_proven_by_this_tool"]]
    return "\n".join(lines) + "\n"


def load_from_database(
    dsn_env: str, since: datetime
) -> tuple[list[TaskRow], dict[int, list[dict[str, Any]]]]:
    """Read armed tasks and their executions since a UTC boundary (parameterised, never built)."""
    import pymysql

    parts = (
        urlsplit(os.environ[dsn_env])
        if dsn_env in os.environ
        else urlsplit(_read_env_value(dsn_env))
    )
    if not parts.hostname:
        raise SystemExit("DATABASE_URL is missing or unparseable; nothing was queried")
    conn = pymysql.connect(
        host=parts.hostname,
        port=parts.port or 3306,
        user=parts.username,
        password=parts.password or "",
        database=(parts.path or "").lstrip("/"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        read_timeout=120,
    )
    tasks: list[TaskRow] = []
    executions: dict[int, list[dict[str, Any]]] = {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, script_id, schedule_type, schedule_expression, next_execution_at, is_active"
                " FROM ak_scheduled_tasks WHERE is_active = 1 ORDER BY id"
            )
            for row in cur.fetchall():
                tasks.append(
                    TaskRow(
                        task_id=int(row["id"]),
                        script_id=str(row["script_id"]),
                        schedule_type=str(row.get("schedule_type") or ""),
                        schedule_expression=row.get("schedule_expression"),
                        next_execution_at=row.get("next_execution_at"),
                        is_active=bool(row.get("is_active")),
                    )
                )
            cur.execute(
                "SELECT task_id, created_at, status,"
                " (rows_after - rows_before) AS rows_delta, error_message"
                " FROM ak_task_executions WHERE created_at >= %s",
                (since.replace(tzinfo=None),),
            )
            ids = {task.task_id for task in tasks}
            for row in cur.fetchall():
                if row["task_id"] in ids:
                    executions.setdefault(int(row["task_id"]), []).append(dict(row))
    finally:
        conn.close()
    return tasks, executions


def _read_env_value(key: str) -> str:
    """Find DATABASE_URL by walking up from this file, without printing it."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        try:
            with open(candidate, encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line.startswith(f"{key}="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=int, default=24, help="lookback window in UTC hours")
    parser.add_argument("--dsn-env", default="DATABASE_URL")
    parser.add_argument("--json-output", default=None)
    parser.add_argument("--markdown-output", default=None)
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now - timedelta(hours=args.hours)
    tasks, executions = load_from_database(args.dsn_env, start)
    reports = summarize(tasks, executions, start, now)
    summary = aggregate(reports)

    markdown = render_markdown(summary, reports, start, now)
    print(markdown)
    if args.markdown_output:
        with open(args.markdown_output, "w", encoding="utf-8") as handle:
            handle.write(markdown)
    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "window": {"start": _iso(start), "end": _iso(now)},
                    "summary": summary,
                    "tasks": [report.to_dict() for report in reports],
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
