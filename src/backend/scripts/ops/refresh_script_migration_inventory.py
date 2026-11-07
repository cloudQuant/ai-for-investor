#!/usr/bin/env python3
"""Drift explainer and faithful re-derivation harness for the migration inventory.

``docs/iterations/迭代204-.../script_migration_inventory.csv`` anchors every row with
``source_sha256``: the SHA-256 of ``source_path`` at the moment the row was derived. The
CSV was produced ad hoc on 2026-10-26 (``29afaeb47``, line endings normalised in
``ae1ed034d``) and no generator exists in the repository, so the anchor silently rotted as
the collection scripts were edited underneath it.

This tool closes that gap in two parts:

``--check``
    Recompute every anchor against the current tree and attribute each mismatch to the last
    commit touching the file, so the drift is *explained* rather than merely counted. Exits
    non-zero when any row is unexplained (acceptance item AC01: "no unexplained item").

``--emit``
    Rewrite the anchor plus the two derived columns (``static_role`` and the leading
    ``AST静态标记=...`` segment of ``notes``) from the AST, preserving every other column
    byte for byte. Refuses to run until the derivation has first reproduced the rows whose
    anchor still matches today's tree -- that gate is the proof that this module re-implements
    the original, lost derivation rather than inventing a new one.

Read-only apart from ``--emit``/``--json-out``; no database, no network.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field

REPO_RELATIVE_INVENTORY = os.path.join(
    "docs",
    "iterations",
    "迭代204-OpenData数据中台拆分与五人并行迁移",
    "script_migration_inventory.csv",
)

MARKER_PREFIX = "AST静态标记="
MARKER_ABSENT = "无fetch_data/run/main入口"
NOTES_TAIL_SEP = "；"
CLASSES_KEY = "classes="
FLAG_ORDER = ("fetch_data", "run", "module_main", "__main___guard")

ROLE_FETCH_DATA = "entrypoint_fetch_data"
ROLE_RUN = "entrypoint_run"
ROLE_MAIN = "entrypoint_main"
ROLE_HELPER = "helper_review_only"

STATUS_MATCHED = "matched"
STATUS_MISMATCHED = "mismatched"
STATUS_MISSING = "missing"

# Explanation kinds for a row that does not match its anchor.
KIND_IN_SYNC = "in_sync"
KIND_CONTENT_DRIFT = "content_drift"
KIND_PATH_DELETED = "path_deleted"
KIND_GHOST_REGISTRATION = "ghost_registration"
KIND_UNEXPLAINED = "unexplained"


# --------------------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------------------


@dataclass
class DerivedMarkers:
    """AST-derived view of one source file."""

    static_role: str
    flags: list[str]
    classes: list[str]
    marker: str
    parse_error: str | None = None


@dataclass
class RecordedMarkers:
    """Recorded view of one CSV row, parsed out of ``static_role`` + ``notes``."""

    static_role: str
    flags: list[str]
    classes: list[str]
    marker: str
    tail: str


@dataclass
class AnchorRow:
    row_number: int
    source_path: str
    recorded_sha256: str
    status: str
    observed_sha256: str | None = None
    attribution: dict[str, str] | None = None
    snapshot_match: bool | None = None
    kind: str = KIND_IN_SYNC


@dataclass
class AnchorReport:
    inventory_path: str
    repo_root: str
    head_commit: str
    rows: list[AnchorRow] = field(default_factory=list)

    @property
    def kinds(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for anchor in self.rows:
            tally[anchor.kind] = tally.get(anchor.kind, 0) + 1
        return tally

    def by_status(self, status: str) -> list[AnchorRow]:
        return [row for row in self.rows if row.status == status]

    @property
    def counts(self) -> dict[str, int]:
        return {
            STATUS_MATCHED: len(self.by_status(STATUS_MATCHED)),
            STATUS_MISMATCHED: len(self.by_status(STATUS_MISMATCHED)),
            STATUS_MISSING: len(self.by_status(STATUS_MISSING)),
            "total": len(self.rows),
        }


@dataclass
class GateResult:
    """Outcome of the faithfulness gate over anchor-matched rows."""

    checked: int
    reproduced: int
    failures: list[dict[str, object]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.checked > 0 and not self.failures

    def summary(self) -> dict[str, object]:
        return {
            "checked": self.checked,
            "reproduced": self.reproduced,
            "failures": self.failures,
            "passed": self.passed,
        }


# --------------------------------------------------------------------------------------
# Inventory I/O
# --------------------------------------------------------------------------------------


def read_inventory(path: str) -> tuple[list[str], list[list[str]], bytes, str]:
    """Return (header, data_rows, bom, line_terminator) preserving the file's framing."""
    with open(path, "rb") as handle:
        raw = handle.read()
    bom = b""
    if raw.startswith(b"\xef\xbb\xbf"):
        bom = raw[:3]
        raw = raw[3:]
    line_terminator = "\r\n" if b"\r\n" in raw else "\n"
    parsed = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    if not parsed:
        raise ValueError(f"inventory is empty: {path}")
    return parsed[0], parsed[1:], bom, line_terminator


def write_inventory(
    path: str,
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    bom: bytes,
    line_terminator: str,
) -> None:
    """Serialise with the framing the committed CSV uses (BOM + ``\\n``, minimal quoting)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=line_terminator)
    writer.writerow(list(header))
    writer.writerows([list(row) for row in rows])
    with open(path, "wb") as handle:
        handle.write(bom + buffer.getvalue().encode("utf-8"))


class InventoryColumns:
    """Column index lookup that fails loudly when the schema drifts."""

    def __init__(self, header: Sequence[str]) -> None:
        expected = [
            "source_path",
            "source_sha256",
            "asset_family",
            "legacy_frequency",
            "static_role",
            "akshare_usage",
            "migration_route",
            "target_dataset",
            "status",
            "owner",
            "notes",
        ]
        if list(header) != expected:
            raise ValueError(f"unexpected inventory header: {header!r}")
        self.index = {name: position for position, name in enumerate(header)}

    def get(self, row: Sequence[str], name: str) -> str:
        return row[self.index[name]]

    def source_path(self, row: Sequence[str]) -> str:
        return self.get(row, "source_path")

    def sha256(self, row: Sequence[str]) -> str:
        return self.get(row, "source_sha256")


# --------------------------------------------------------------------------------------
# Anchor recomputation and attribution
# --------------------------------------------------------------------------------------


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(repo_root: str, args: Sequence[str]) -> str | None:
    result = subprocess.run(
        ["git", "-C", repo_root, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def last_touching_commit(repo_root: str, source_path: str) -> dict[str, str] | None:
    """Attribute a path to the last commit touching it (for deleted paths: the deletion)."""
    line = git_output(
        repo_root,
        ["log", "-1", "--format=%h|%ad|%s", "--date=short", "--", source_path],
    )
    if not line:
        return None
    short_sha, date, subject = line.split("|", 2)
    return {"commit": short_sha, "date": date, "subject": subject}


def blob_matches_commit(
    repo_root: str, commit: str, source_path: str, expected: str
) -> bool | None:
    """True/False when the path is resolvable at ``commit``, None when it is absent."""
    result = subprocess.run(
        ["git", "-C", repo_root, "show", f"{commit}:{source_path}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout).hexdigest() == expected


def path_history_count(repo_root: str, source_path: str) -> int:
    """How many commits on any reachable ref ever touched this path."""
    out = git_output(repo_root, ["log", "--all", "--format=%H", "--", source_path])
    return len(out.split()) if out else 0


def classify_anchors(
    repo_root: str,
    inventory_path: str,
    snapshot_commit: str | None = None,
) -> AnchorReport:
    """Recompute every ``source_sha256`` against the current working tree."""
    header, rows, _, _ = read_inventory(inventory_path)
    columns = InventoryColumns(header)
    report = AnchorReport(
        inventory_path=inventory_path,
        repo_root=repo_root,
        head_commit=git_output(repo_root, ["rev-parse", "--short", "HEAD"]) or "unknown",
    )
    for offset, row in enumerate(rows):
        source_path = columns.source_path(row)
        expected = columns.sha256(row)
        absolute = os.path.join(repo_root, source_path)
        if not os.path.isfile(absolute):
            status = STATUS_MISSING
            observed: str | None = None
        else:
            observed = sha256_file(absolute)
            status = STATUS_MATCHED if observed == expected else STATUS_MISMATCHED
        anchor = AnchorRow(
            row_number=offset + 2,  # +1 header, +1 one-based
            source_path=source_path,
            recorded_sha256=expected,
            status=status,
            observed_sha256=observed,
        )
        if status != STATUS_MATCHED:
            anchor.attribution = last_touching_commit(repo_root, source_path)
            if anchor.attribution is not None:
                anchor.kind = KIND_PATH_DELETED if status == STATUS_MISSING else KIND_CONTENT_DRIFT
            elif status == STATUS_MISSING and path_history_count(repo_root, source_path) == 0:
                # The path never existed in this repository: a ghost registration, explained by
                # the wave-29 producer-binding finding rather than by any commit here.
                anchor.kind = KIND_GHOST_REGISTRATION
            else:
                anchor.kind = KIND_UNEXPLAINED
            if snapshot_commit is not None:
                anchor.snapshot_match = blob_matches_commit(
                    repo_root, snapshot_commit, source_path, expected
                )
        report.rows.append(anchor)
    return report


def group_by_commit(report: AnchorReport) -> list[dict[str, object]]:
    """Group every drifted row by its last-touching commit, largest drift first.

    Ghost registrations (paths this repository never contained) have no commit to attribute to,
    so they form their own labelled group instead of polluting the commit buckets.
    """
    buckets: dict[str, dict[str, object]] = {}

    def bucket_for(key: str, info: dict[str, str]) -> dict[str, object]:
        return buckets.setdefault(
            key,
            {
                "commit": key,
                "date": info.get("date", ""),
                "subject": info.get("subject", ""),
                "kind": info.get("kind", KIND_CONTENT_DRIFT),
                "mismatched": 0,
                "missing": 0,
                "never_recorded": 0,
            },
        )

    for anchor in report.rows:
        if anchor.status == STATUS_MATCHED:
            continue
        info = dict(anchor.attribution or {})
        info.setdefault("kind", anchor.kind)
        if anchor.kind == KIND_GHOST_REGISTRATION:
            key = "GHOST(no commit ever touched the path)"
        elif anchor.kind == KIND_UNEXPLAINED:
            key = "UNATTRIBUTED"
        else:
            key = info.get("commit", "UNATTRIBUTED")
        bucket = bucket_for(key, info)
        if anchor.status == STATUS_MISMATCHED:
            bucket["mismatched"] = int(bucket["mismatched"]) + 1
        else:
            bucket["missing"] = int(bucket["missing"]) + 1
        if anchor.snapshot_match is False:
            bucket["never_recorded"] = int(bucket["never_recorded"]) + 1
    return sorted(
        buckets.values(),
        key=lambda item: (-int(item["mismatched"]) - int(item["missing"]), str(item["commit"])),
    )


def unexplained_rows(report: AnchorReport) -> list[AnchorRow]:
    """Rows that drifted but cannot be tied to any commit -- the AC01 violation."""
    return [anchor for anchor in report.rows if anchor.kind == KIND_UNEXPLAINED]


# --------------------------------------------------------------------------------------
# AST derivation
# --------------------------------------------------------------------------------------


def _functions_in(nodes: Sequence[ast.stmt]) -> list[ast.stmt]:
    return [node for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _has_main_guard(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            if isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__":
                return True
    return False


def render_marker(flags: Sequence[str], classes: Sequence[str]) -> str:
    """Serialise the ``AST静态标记=`` payload exactly as the inventory records it."""
    ordered = [flag for flag in FLAG_ORDER if flag in set(flags)]
    if not ordered and not classes:
        return MARKER_ABSENT
    parts = list(ordered)
    if classes:
        parts.append(f"{CLASSES_KEY}{','.join(classes)}")
    return ",".join(parts)


def derive_markers(source: str) -> DerivedMarkers:
    """Re-derive ``static_role`` and the AST marker segment from file content."""
    try:
        tree = ast.parse(source)
    except SyntaxError as error:  # pragma: no cover - defensive, repo files parse
        return DerivedMarkers(ROLE_HELPER, [], [], MARKER_ABSENT, parse_error=str(error))

    module_functions = {node.name for node in _functions_in(tree.body)}
    class_nodes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    member_functions = {node.name for cls in class_nodes for node in _functions_in(cls.body)}
    entrypoint_names = module_functions | member_functions

    flags: list[str] = []
    if "fetch_data" in entrypoint_names:
        flags.append("fetch_data")
    if "run" in entrypoint_names:
        flags.append("run")
    if "main" in module_functions:
        flags.append("module_main")
    if _has_main_guard(tree):
        flags.append("__main___guard")

    if "fetch_data" in flags:
        role = ROLE_FETCH_DATA
    elif "run" in flags:
        role = ROLE_RUN
    elif "module_main" in flags:
        role = ROLE_MAIN
    else:
        role = ROLE_HELPER

    classes = [node.name for node in class_nodes]
    return DerivedMarkers(role, flags, classes, render_marker(flags, classes))


def parse_recorded_markers(static_role: str, notes: str) -> RecordedMarkers:
    """Split ``notes`` into the derived marker segment and the verbatim human tail."""
    head, separator, tail = notes.partition(NOTES_TAIL_SEP)
    if not head.startswith(MARKER_PREFIX):
        return RecordedMarkers(static_role, [], [], "", notes if not separator else tail)
    marker = head[len(MARKER_PREFIX) :]
    flags: list[str] = []
    classes: list[str] = []
    if marker != MARKER_ABSENT and CLASSES_KEY in marker:
        # Either "<flags>,classes=A,B" or, when no flag fired, the bare "classes=A".
        if marker.startswith(CLASSES_KEY):
            flag_part, class_part = "", marker[len(CLASSES_KEY) :]
        else:
            flag_part, _, class_part = marker.partition(f",{CLASSES_KEY}")
        flags = [token for token in flag_part.split(",") if token]
        classes = [token for token in class_part.split(",") if token]
    elif marker != MARKER_ABSENT:
        flags = [token for token in marker.split(",") if token]
    return RecordedMarkers(static_role, flags, classes, marker, tail if separator else "")


def faithfulness_gate(
    repo_root: str,
    inventory_path: str,
    report: AnchorReport | None = None,
) -> tuple[GateResult, AnchorReport]:
    """Require the derivation to reproduce every anchor-matched row exactly.

    For a row whose recorded ``source_sha256`` still equals the file's current digest, the
    recorded markers and the current content provably belong together, so the derivation is
    being tested against known-good pairs that need no history lookup.
    """
    header, rows, _, _ = read_inventory(inventory_path)
    columns = InventoryColumns(header)
    if report is None:
        report = classify_anchors(repo_root, inventory_path)
    matched = {anchor.source_path for anchor in report.by_status(STATUS_MATCHED)}

    result = GateResult(checked=0, reproduced=0)
    for row in rows:
        source_path = columns.source_path(row)
        if source_path not in matched:
            continue
        absolute = os.path.join(repo_root, source_path)
        if not os.path.isfile(absolute):  # pragma: no cover - guarded by status
            continue
        result.checked += 1
        with open(absolute, encoding="utf-8") as handle:
            derived = derive_markers(handle.read())
        recorded = parse_recorded_markers(
            columns.get(row, "static_role"), columns.get(row, "notes")
        )
        differences: dict[str, object] = {}
        if derived.static_role != recorded.static_role:
            differences["static_role"] = {
                "recorded": recorded.static_role,
                "derived": derived.static_role,
            }
        if derived.flags != recorded.flags:
            differences["flags"] = {"recorded": recorded.flags, "derived": derived.flags}
        if derived.classes != recorded.classes:
            differences["classes"] = {"recorded": recorded.classes, "derived": derived.classes}
        if derived.marker != recorded.marker:
            differences["marker"] = {"recorded": recorded.marker, "derived": derived.marker}
        if derived.parse_error is not None:
            differences["parse_error"] = derived.parse_error
        if differences:
            result.failures.append(
                {"row_number": result.checked, "source_path": source_path, **differences}
            )
        else:
            result.reproduced += 1
    return result, report


def marker_diff(
    repo_root: str,
    inventory_path: str,
    only_status: Sequence[str] | None = (STATUS_MISMATCHED,),
    report: AnchorReport | None = None,
) -> dict[str, object]:
    """Measure what re-derivation changes per row, for the rows still drifting."""
    header, rows, _, _ = read_inventory(inventory_path)
    columns = InventoryColumns(header)
    if report is None:
        report = classify_anchors(repo_root, inventory_path)
    status_of = {anchor.source_path: anchor.status for anchor in report.rows}
    snapshot_match_of = {anchor.source_path: anchor.snapshot_match for anchor in report.rows}

    changed: list[dict[str, object]] = []
    counts = {
        "examined": 0,
        "static_role_changed": 0,
        "flags_added": 0,
        "flags_removed": 0,
        "classes_changed": 0,
        "marker_changed": 0,
        "parse_errors": 0,
        "unchanged": 0,
        # Cross-tab for the marker-changed rows: a row whose anchor already failed against the
        # commit the CSV was derived from had stale derived columns before any later edit.
        "marker_changed_anchor_valid_at_snapshot": 0,
        "marker_changed_anchor_never_valid": 0,
        "marker_changed_anchor_unknown": 0,
    }
    role_transitions: dict[str, int] = {}

    for row in rows:
        source_path = columns.source_path(row)
        if only_status is not None and status_of.get(source_path) not in only_status:
            continue
        counts["examined"] += 1
        absolute = os.path.join(repo_root, source_path)
        if not os.path.isfile(absolute):
            continue
        with open(absolute, encoding="utf-8") as handle:
            derived = derive_markers(handle.read())
        recorded = parse_recorded_markers(
            columns.get(row, "static_role"), columns.get(row, "notes")
        )
        if derived.parse_error is not None:
            counts["parse_errors"] += 1
        added = [flag for flag in derived.flags if flag not in recorded.flags]
        removed = [flag for flag in recorded.flags if flag not in derived.flags]
        role_changed = derived.static_role != recorded.static_role
        classes_changed = derived.classes != recorded.classes
        marker_changed = derived.marker != recorded.marker
        if added:
            counts["flags_added"] += 1
        if removed:
            counts["flags_removed"] += 1
        if role_changed:
            counts["static_role_changed"] += 1
            key = f"{recorded.static_role} -> {derived.static_role}"
            role_transitions[key] = role_transitions.get(key, 0) + 1
        if classes_changed:
            counts["classes_changed"] += 1
        if marker_changed:
            counts["marker_changed"] += 1
        if role_changed or added or removed or classes_changed:
            anchor_snapshot = snapshot_match_of.get(source_path)
            if marker_changed:
                if anchor_snapshot is True:
                    counts["marker_changed_anchor_valid_at_snapshot"] += 1
                elif anchor_snapshot is False:
                    counts["marker_changed_anchor_never_valid"] += 1
                else:
                    counts["marker_changed_anchor_unknown"] += 1
            entry: dict[str, object] = {
                "source_path": source_path,
                "status": status_of.get(source_path),
                "anchor_matched_at_snapshot_commit": anchor_snapshot,
            }
            if role_changed:
                entry["static_role"] = f"{recorded.static_role} -> {derived.static_role}"
            if added:
                entry["flags_added"] = added
            if removed:
                entry["flags_removed"] = removed
            if classes_changed:
                entry["classes"] = f"{','.join(recorded.classes)} -> {','.join(derived.classes)}"
            changed.append(entry)
        else:
            counts["unchanged"] += 1

    counts["role_transitions"] = role_transitions  # type: ignore[assignment]
    return {"counts": counts, "changed_rows": changed}


# --------------------------------------------------------------------------------------
# Emission
# --------------------------------------------------------------------------------------


def regenerate(
    repo_root: str,
    inventory_path: str,
) -> tuple[list[list[str]], dict[str, int]]:
    """Rewrite anchor + derived columns only; every other cell is carried over verbatim."""
    header, rows, _, _ = read_inventory(inventory_path)
    columns = InventoryColumns(header)
    out_columns = columns.index["source_sha256"]
    out_role = columns.index["static_role"]
    out_notes = columns.index["notes"]

    stats = {"anchor_updated": 0, "role_updated": 0, "marker_updated": 0, "unchanged": 0}
    emitted: list[list[str]] = []
    for row in rows:
        new_row = list(row)
        source_path = columns.source_path(row)
        absolute = os.path.join(repo_root, source_path)
        if not os.path.isfile(absolute):
            emitted.append(new_row)
            continue
        digest = sha256_file(absolute)
        with open(absolute, encoding="utf-8") as handle:
            derived = derive_markers(handle.read())
        changed = False
        if new_row[out_columns] != digest:
            new_row[out_columns] = digest
            stats["anchor_updated"] += 1
            changed = True
        if new_row[out_role] != derived.static_role:
            new_row[out_role] = derived.static_role
            stats["role_updated"] += 1
            changed = True
        notes = new_row[out_notes]
        head, separator, tail = notes.partition(NOTES_TAIL_SEP)
        new_marker = f"{MARKER_PREFIX}{derived.marker}"
        if head != new_marker:
            new_row[out_notes] = new_marker + (separator or NOTES_TAIL_SEP) + tail
            stats["marker_updated"] += 1
            changed = True
        if not changed:
            stats["unchanged"] += 1
        emitted.append(new_row)
    return emitted, stats


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def render_check_text(
    report: AnchorReport, gate: GateResult, groups: list[dict[str, object]]
) -> str:
    counts = report.counts
    lines = [
        f"inventory: {report.inventory_path}",
        f"tree head: {report.head_commit}",
        (
            f"anchors: {counts['matched']} matched / {counts['mismatched']} mismatched / "
            f"{counts['missing']} missing (of {counts['total']} rows)"
        ),
        "",
        "drift attribution (last commit touching the file):",
    ]
    for group in groups:
        never = group.get("never_recorded") or 0
        extra = f", {never} anchored to content absent from this repo's history" if never else ""
        lines.append(
            f"  {group['mismatched'] + group['missing']:>4} row(s)  {group['commit']} {group['date']}  "
            f"{str(group['subject'])[:68]}  [mismatch {group['mismatched']}, "
            f"missing {group['missing']}{extra}]"
        )
    unexplained = unexplained_rows(report)
    lines.append("")
    lines.append(
        "explanation kinds: " + ", ".join(f"{k}={v}" for k, v in sorted(report.kinds.items()))
    )
    lines.append(f"invariant: {len(unexplained)} unexplained row(s) -- expected 0")
    lines.append(
        f"derivation gate: {gate.reproduced}/{gate.checked} anchor-matched rows reproduced "
        f"({'PASS' if gate.passed else 'FAIL'})"
    )
    for failure in gate.failures[:10]:
        lines.append(f"  NOT REPRODUCED {failure['source_path']}: {failure}")
    return "\n".join(lines)


def build_summary(
    report: AnchorReport, gate: GateResult, groups: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "inventory_path": report.inventory_path,
        "repo_root": report.repo_root,
        "head_commit": report.head_commit,
        "counts": report.counts,
        "kinds": report.kinds,
        "attribution_groups": groups,
        "unexplained_rows": [
            {"row_number": row.row_number, "source_path": row.source_path, "status": row.status}
            for row in unexplained_rows(report)
        ],
        "derivation_gate": gate.summary(),
        "mismatch_detail": [
            {
                "row_number": row.row_number,
                "source_path": row.source_path,
                "status": row.status,
                "kind": row.kind,
                "recorded_sha256": row.recorded_sha256,
                "observed_sha256": row.observed_sha256,
                "last_touch": row.attribution,
                "matched_at_snapshot_commit": row.snapshot_match,
            }
            for row in report.rows
            if row.status != STATUS_MATCHED
        ],
    }


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explain and regenerate the script migration inventory content anchor."
    )
    parser.add_argument("--repo-root", default=os.getcwd(), help="repository root to measure")
    parser.add_argument("--inventory", help="path to script_migration_inventory.csv")
    parser.add_argument(
        "--snapshot-commit",
        help="commit the CSV was derived from; used to separate rotted anchors from anchors "
        "that never matched this repository",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="recompute anchors, attribute every mismatch, fail on any unexplained row",
    )
    mode.add_argument(
        "--verify-derivation",
        action="store_true",
        help="only run the AST faithfulness gate over anchor-matched rows",
    )
    mode.add_argument(
        "--emit",
        action="store_true",
        help="gate, then write a regenerated CSV to --out with anchors and derived columns updated",
    )
    parser.add_argument("--out", help="destination for --emit (never written in place)")
    parser.add_argument("--json-out", help="destination for the machine-readable summary")
    parser.add_argument(
        "--max-detail", type=int, default=0, help="how many changed rows to print (0 = all)"
    )
    return parser


def resolve_inventory(repo_root: str, explicit: str | None) -> str:
    if explicit:
        return os.path.abspath(explicit)
    return os.path.join(repo_root, REPO_RELATIVE_INVENTORY)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = os.path.abspath(args.repo_root)
    inventory_path = resolve_inventory(repo_root, args.inventory)
    if not os.path.isfile(inventory_path):
        print(f"inventory not found: {inventory_path}", file=sys.stderr)
        return 2

    report = classify_anchors(repo_root, inventory_path, args.snapshot_commit)
    gate, _ = faithfulness_gate(repo_root, inventory_path, report)
    groups = group_by_commit(report)
    unexplained = unexplained_rows(report)

    if args.verify_derivation:
        print(render_check_text(report, gate, groups))
        return 0 if gate.passed else 1

    if args.check:
        print(render_check_text(report, gate, groups))
        if args.json_out:
            payload = build_summary(report, gate, groups)
            with open(args.json_out, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            print(f"json summary written: {args.json_out}")
        if unexplained:
            print(f"FAIL: {len(unexplained)} unexplained row(s)", file=sys.stderr)
            return 1
        if not gate.passed:
            print("FAIL: AST derivation is not faithful to the recorded markers", file=sys.stderr)
            return 1
        drifted = report.counts["mismatched"] + report.counts["missing"]
        print(f"OK: all {drifted} drifted rows are attributed to a last-touching commit")
        return 0

    # --emit
    if not gate.passed:
        print(
            "REFUSING to emit: the derivation reproduced "
            f"{gate.reproduced}/{gate.checked} anchor-matched rows; the algorithm is not the "
            "original one. First failures:",
            file=sys.stderr,
        )
        for failure in gate.failures[:10]:
            print(f"  {failure}", file=sys.stderr)
        return 1
    if not args.out:
        print(
            "REFUSING to emit: --out is required; the committed CSV is never rewritten here",
            file=sys.stderr,
        )
        return 2
    if os.path.abspath(args.out) == os.path.abspath(inventory_path):
        print(
            "REFUSING to emit: --out resolves to the committed inventory; regenerate to a "
            "separate path and review the diff first",
            file=sys.stderr,
        )
        return 2

    diff = marker_diff(
        repo_root, inventory_path, only_status=(STATUS_MISMATCHED, STATUS_MISSING), report=report
    )
    emitted, stats = regenerate(repo_root, inventory_path)
    # Reuse the committed framing exactly (BOM + LF, minimal quoting) for the new file.
    header, _old_rows, bom, line_terminator = read_inventory(inventory_path)
    write_inventory(args.out, header, emitted, bom, line_terminator)

    counts = diff["counts"]
    print(
        f"faithfulness gate: PASS ({gate.reproduced}/{gate.checked} anchor-matched rows reproduced)"
    )
    print(f"regenerated CSV written to: {args.out} (NOT the committed inventory)")
    print("emit stats: " + ", ".join(f"{key}={value}" for key, value in sorted(stats.items())))
    print("")
    print("marker diff over rows currently drifting from their anchor:")
    print(
        f"  examined={counts['examined']} unchanged={counts['unchanged']} "
        f"marker_changed={counts['marker_changed']} "
        f"static_role_changed={counts['static_role_changed']} "
        f"flags_added={counts['flags_added']} flags_removed={counts['flags_removed']} "
        f"classes_changed={counts['classes_changed']} parse_errors={counts['parse_errors']}"
    )
    transitions = counts.get("role_transitions") or {}
    if transitions:
        print("  static_role transitions:")
        for key, value in sorted(transitions.items(), key=lambda item: -item[1]):
            print(f"    {value:>4}  {key}")
    else:
        print("  static_role transitions: none")
    changed_rows = diff["changed_rows"]
    if changed_rows:
        print(
            "  anchor provenance of the marker-changed rows: "
            f"{counts['marker_changed_anchor_valid_at_snapshot']} had an anchor that DID match the "
            f"snapshot commit (real post-snapshot code change), "
            f"{counts['marker_changed_anchor_never_valid']} had an anchor that already failed against "
            "the snapshot commit (derived column was stale when the CSV was written), "
            f"{counts['marker_changed_anchor_unknown']} unknown (pass --snapshot-commit)"
        )
    limit = args.max_detail if args.max_detail > 0 else len(changed_rows)
    if changed_rows:
        print(f"  rows whose derived markers change ({len(changed_rows)} total, showing {limit}):")
        for entry in changed_rows[:limit]:
            bits = []
            if "static_role" in entry:
                bits.append(str(entry["static_role"]))
            if "flags_added" in entry:
                bits.append("+[" + ",".join(entry["flags_added"]) + "]")  # type: ignore[arg-type]
            if "flags_removed" in entry:
                bits.append("-[" + ",".join(entry["flags_removed"]) + "]")  # type: ignore[arg-type]
            if "classes" in entry:
                bits.append(f"classes {entry['classes']}")
            prov = entry.get("anchor_matched_at_snapshot_commit")
            bits.append(
                f"anchor@snapshot={'match' if prov else ('stale' if prov is False else 'unknown')}"
            )
            print(f"    {entry['source_path']}  ({entry['status']})  {' | '.join(bits)}")
    else:
        print("  no derived marker changes -- the drift is purely content-level")

    if args.json_out:
        payload = build_summary(report, gate, groups)
        payload["marker_diff"] = diff
        payload["emit"] = {"out": os.path.abspath(args.out), "stats": stats}
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(f"json summary written: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
