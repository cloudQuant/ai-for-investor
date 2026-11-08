"""Tests for the script-migration-inventory anchor explainer and re-derivation harness.

Two families of cases live here:

* Fixture-driven cases that build a throwaway git tree plus a miniature inventory, so match /
  mismatch / missing / attribution / ghost behaviour and the emit framing are exercised without
  depending on the real repository state.
* The faithfulness gate over the *real* committed inventory: for every row whose recorded
  ``source_sha256`` still equals the file's current digest, the recorded ``static_role`` and
  ``AST静态标记=`` segment must be reproduced exactly. Those rows are known-good derivation
  pairs, so the gate proves this module re-implements the original derivation.

No test here touches the database or the network.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_ROOT.parents[1]
_SCRIPT_PATH = _BACKEND_ROOT / "scripts" / "ops" / "refresh_script_migration_inventory.py"
_SPEC = importlib.util.spec_from_file_location("refresh_script_migration_inventory", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
inv = importlib.util.module_from_spec(_SPEC)
# Register before executing: the module defines dataclasses, and dataclasses resolves deferred
# annotations through sys.modules[cls.__module__].
sys.modules.setdefault(_SPEC.name, inv)
_SPEC.loader.exec_module(inv)

INVENTORY_PATH = _REPO_ROOT / inv.REPO_RELATIVE_INVENTORY

HEADER = [
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
NOTES_TAIL = "路径/名称分类仅作分工候选；不得据此当作DB任务/数据质量验收。"

_FETCH_SRC = '''"""A generated collection script."""


class BondSampleFetcher:
    """Collects bond samples."""

    def fetch_data(self, symbol: str) -> dict:
        return {"symbol": symbol}


def main() -> None:
    BondSampleFetcher().fetch_data("x")


if __name__ == "__main__":
    main()
'''

_RUN_SRC = '''"""A script exposing ``run`` only."""


class SinaSampleSource:
    """Wraps one upstream call."""

    def run(self, symbol: str) -> dict:
        return {"symbol": symbol}


def run(symbol: str) -> dict:
    return SinaSampleSource().run(symbol)


if __name__ == "__main__":
    run("x")
'''

_HELPER_SRC = '''"""A pure helper module with no entrypoint."""


def normalise(rows: list) -> list:
    """Return the rows unchanged."""
    return [dict(row) for row in rows]
'''

_CLASSES_ONLY_SRC = '''"""Exception types plus a collector that has no entrypoint."""


class ReleaseDateDecision:
    """Carries release metadata."""


class SampleCollector:
    """Collects nothing."""

    def collect(self) -> None:
        return None
'''


def _marker(static_role: str, flags: Sequence[str], classes: Sequence[str]) -> str:
    """Compose the full ``notes`` cell exactly as the inventory stores it."""
    return f"{inv.MARKER_PREFIX}{inv.render_marker(flags, classes)}；{NOTES_TAIL}"


def _write_inventory(path: Path, rows: Sequence[Sequence[str]]) -> None:
    """Serialise a fixture inventory with the committed framing (BOM + LF)."""
    inv.write_inventory(str(path), HEADER, [list(row) for row in rows], b"\xef\xbb\xbf", "\n")


@pytest.fixture
def git_tree(tmp_path: Path) -> Path:
    """A throwaway repository with identity configured and one empty commit."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    return tmp_path


def _commit_all(root: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message], check=True)
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _place(root: Path, rel: str, content: str) -> str:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _row(
    rel: str, sha: str, static_role: str, flags: Sequence[str], classes: Sequence[str]
) -> list[str]:
    return [
        rel,
        sha,
        "bond",
        "daily",
        static_role,
        "shared_akshare_to_mysql",
        "PENDING_PROVIDER_MAPPING",
        "待数据契约与目标映射",
        "待盘点/待映射",
        "B",
        _marker(static_role, flags, classes),
    ]


# --------------------------------------------------------------------------------------
# Derivation units
# --------------------------------------------------------------------------------------


class TestDeriveMarkers:
    @pytest.mark.parametrize(
        "source, expected_role, expected_flags, expected_classes",
        [
            (
                _FETCH_SRC,
                inv.ROLE_FETCH_DATA,
                ["fetch_data", "module_main", "__main___guard"],
                ["BondSampleFetcher"],
            ),
            (_RUN_SRC, inv.ROLE_RUN, ["run", "__main___guard"], ["SinaSampleSource"]),
            (_HELPER_SRC, inv.ROLE_HELPER, [], []),
            (_CLASSES_ONLY_SRC, inv.ROLE_HELPER, [], ["ReleaseDateDecision", "SampleCollector"]),
        ],
    )
    def test_roles_and_flags(
        self,
        source: str,
        expected_role: str,
        expected_flags: list[str],
        expected_classes: list[str],
    ) -> None:
        derived = inv.derive_markers(source)
        assert derived.static_role == expected_role
        assert derived.flags == expected_flags
        assert derived.classes == expected_classes
        assert derived.parse_error is None

    def test_fetch_data_takes_priority_over_run_and_main(self) -> None:
        derived = inv.derive_markers(_FETCH_SRC + "\ndef run() -> None:\n    return None\n")
        assert derived.static_role == inv.ROLE_FETCH_DATA
        assert derived.flags == ["fetch_data", "run", "module_main", "__main___guard"]

    def test_member_run_counts_as_run_role(self) -> None:
        derived = inv.derive_markers(_CLASSES_ONLY_SRC.replace("def collect", "def run"))
        assert derived.static_role == inv.ROLE_RUN
        assert derived.flags == ["run"]

    def test_method_main_is_not_module_main(self) -> None:
        src = "class A:\n    def main(self) -> None:\n        return None\n"
        derived = inv.derive_markers(src)
        assert "module_main" not in derived.flags
        assert derived.static_role == inv.ROLE_HELPER
        assert derived.classes == ["A"]

    def test_guard_detected_without_main_function(self) -> None:
        derived = inv.derive_markers('if __name__ == "__main__":\n    print(1)\n')
        assert derived.flags == ["__main___guard"]
        assert derived.static_role == inv.ROLE_HELPER

    def test_syntax_error_is_reported_not_raised(self) -> None:
        derived = inv.derive_markers("def broken(:\n")
        assert derived.parse_error is not None
        assert derived.static_role == inv.ROLE_HELPER


class TestMarkerGrammar:
    """The exact serialisation forms present in the committed inventory."""

    @pytest.mark.parametrize(
        "flags, classes, expected",
        [
            (
                ["fetch_data", "module_main", "__main___guard"],
                ["BondBuyBackHistEm"],
                "fetch_data,module_main,__main___guard,classes=BondBuyBackHistEm",
            ),
            ([], ["EndataYienClient"], "classes=EndataYienClient"),
            (["run"], [], "run"),
            (["module_main"], [], "module_main"),
            ([], [], inv.MARKER_ABSENT),
            (
                ["module_main", "fetch_data", "__main___guard"],
                ["A"],
                "fetch_data,module_main,__main___guard,classes=A",
            ),
            (["run"], ["A", "B"], "run,classes=A,B"),
        ],
    )
    def test_render(self, flags: list[str], classes: list[str], expected: str) -> None:
        assert inv.render_marker(flags, classes) == expected

    @pytest.mark.parametrize(
        "flags, classes",
        [
            (["fetch_data", "module_main", "__main___guard"], ["BondBuyBackHistEm"]),
            ([], ["EndataYienClient"]),
            (["run"], []),
            (["module_main"], []),
            ([], []),
            (
                ["fetch_data", "run", "module_main", "__main___guard"],
                ["SourceUnavailableError", "FxSpotQuote"],
            ),
        ],
    )
    def test_render_parse_roundtrip(self, flags: list[str], classes: list[str]) -> None:
        notes = _marker(inv.ROLE_FETCH_DATA, flags, classes)
        parsed = inv.parse_recorded_markers(inv.ROLE_FETCH_DATA, notes)
        # Flag order is canonicalised on render, so compare as ordered-derivation output.
        assert parsed.classes == classes
        assert parsed.flags == [f for f in inv.FLAG_ORDER if f in set(flags)]
        assert parsed.marker == inv.render_marker(flags, classes)
        assert parsed.tail == NOTES_TAIL

    def test_unparseable_notes_keep_static_role(self) -> None:
        parsed = inv.parse_recorded_markers(inv.ROLE_RUN, "完全人工写的备注")
        assert parsed.static_role == inv.ROLE_RUN
        assert parsed.marker == ""


# --------------------------------------------------------------------------------------
# Anchor classification and attribution
# --------------------------------------------------------------------------------------


class TestClassifyAnchors:
    def test_match_mismatch_and_attribution(self, git_tree: Path) -> None:
        root = git_tree
        good_sha = _place(root, "pkg/good.py", _FETCH_SRC)
        bad_sha = _place(root, "pkg/bad.py", _FETCH_SRC)
        _commit_all(root, "feat: add two collection scripts")
        # Drift pkg/bad.py after the anchor was recorded.
        _place(root, "pkg/bad.py", _RUN_SRC)

        inventory = root / "inv.csv"
        _write_inventory(
            inventory,
            [
                _row(
                    "pkg/good.py",
                    good_sha,
                    inv.ROLE_FETCH_DATA,
                    ["fetch_data", "module_main", "__main___guard"],
                    ["BondSampleFetcher"],
                ),
                _row(
                    "pkg/bad.py",
                    bad_sha,
                    inv.ROLE_FETCH_DATA,
                    ["fetch_data", "module_main", "__main___guard"],
                    ["BondSampleFetcher"],
                ),
            ],
        )

        report = inv.classify_anchors(str(root), str(inventory))
        assert report.counts == {"matched": 1, "mismatched": 1, "missing": 0, "total": 2}
        assert inv.unexplained_rows(report) == []
        groups = inv.group_by_commit(report)
        assert len(groups) == 1
        assert groups[0]["mismatched"] == 1
        assert groups[0]["subject"] == "feat: add two collection scripts"
        assert groups[0]["date"]
        # Row numbers are 1-based with the header occupying line 1.
        drifted = report.by_status(inv.STATUS_MISMATCHED)[0]
        assert drifted.row_number == 3
        assert drifted.kind == inv.KIND_CONTENT_DRIFT
        assert drifted.observed_sha256 == hashlib.sha256(_RUN_SRC.encode("utf-8")).hexdigest()

    def test_deleted_path_is_attributed_to_its_removal(self, git_tree: Path) -> None:
        root = git_tree
        sha = _place(root, "pkg/gone.py", _FETCH_SRC)
        _commit_all(root, "feat: add a script that later disappears")
        os.remove(root / "pkg/gone.py")
        removal = _commit_all(root, "fix: remove the script")

        inventory = root / "inv.csv"
        _write_inventory(
            inventory,
            [_row("pkg/gone.py", sha, inv.ROLE_FETCH_DATA, ["fetch_data"], ["BondSampleFetcher"])],
        )

        report = inv.classify_anchors(str(root), str(inventory))
        assert report.counts["missing"] == 1
        assert inv.unexplained_rows(report) == []
        anchor = report.by_status(inv.STATUS_MISSING)[0]
        assert anchor.kind == inv.KIND_PATH_DELETED
        assert anchor.attribution is not None
        assert anchor.attribution["commit"] == removal

    def test_ghost_registration_is_explained_without_a_commit(self, git_tree: Path) -> None:
        root = git_tree
        _place(root, "pkg/keep.py", _FETCH_SRC)
        _commit_all(root, "feat: baseline")

        inventory = root / "inv.csv"
        _write_inventory(
            inventory, [_row("pkg/never_existed.py", "0" * 64, inv.ROLE_RUN, ["run"], [])]
        )

        report = inv.classify_anchors(str(root), str(inventory))
        anchor = report.by_status(inv.STATUS_MISSING)[0]
        assert anchor.kind == inv.KIND_GHOST_REGISTRATION
        # A path this repository never contained is explained by the producer-binding finding,
        # so it must not be counted as unexplained drift.
        assert inv.unexplained_rows(report) == []
        groups = inv.group_by_commit(report)
        assert any(str(group["commit"]).startswith("GHOST") for group in groups)

    def test_untracked_drift_is_unexplained(self, git_tree: Path) -> None:
        """A file that differs from its anchor but was never committed has no attribution."""
        root = git_tree
        _place(root, "pkg/keep.py", _FETCH_SRC)
        _commit_all(root, "feat: baseline")
        (root / "pkg/ghost.py").write_text(_FETCH_SRC, encoding="utf-8")

        inventory = root / "inv.csv"
        digest = hashlib.sha256(_FETCH_SRC.encode("utf-8")).hexdigest()
        _write_inventory(
            inventory, [_row("pkg/ghost.py", "f" * 64, inv.ROLE_FETCH_DATA, ["fetch_data"], ["A"])]
        )

        report = inv.classify_anchors(str(root), str(inventory))
        assert report.by_status(inv.STATUS_MISMATCHED)[0].kind == inv.KIND_UNEXPLAINED
        # Sanity: the anchor digest really is the file's content, just never committed.
        assert digest != "f" * 64
        assert len(inv.unexplained_rows(report)) == 1

    def test_snapshot_commit_separates_rotted_from_never_recorded(self, git_tree: Path) -> None:
        root = git_tree
        sha = _place(root, "pkg/a.py", _FETCH_SRC)
        snapshot = _commit_all(root, "feat: recorded here")
        _place(root, "pkg/a.py", _RUN_SRC)
        _commit_all(root, "fix: annotate the script")

        inventory = root / "inv.csv"
        _write_inventory(
            inventory,
            [
                _row(
                    "pkg/a.py",
                    sha,
                    inv.ROLE_FETCH_DATA,
                    ["fetch_data", "module_main", "__main___guard"],
                    ["BondSampleFetcher"],
                ),
                _row(
                    "pkg/a.py", "a" * 64, inv.ROLE_FETCH_DATA, ["fetch_data"], ["BondSampleFetcher"]
                ),
            ],
        )
        report = inv.classify_anchors(str(root), str(inventory), snapshot_commit=snapshot)
        matches = [anchor.snapshot_match for anchor in report.rows]
        assert matches == [True, False]
        groups = inv.group_by_commit(report)
        assert groups[0]["never_recorded"] == 1

    def test_header_validation(self, git_tree: Path) -> None:
        inventory = git_tree / "inv.csv"
        inventory.write_text("source_path,source_sha256\nx,0\n", encoding="utf-8")
        with pytest.raises(ValueError, match="unexpected inventory header"):
            inv.classify_anchors(str(git_tree), str(inventory))


# --------------------------------------------------------------------------------------
# Faithfulness gate
# --------------------------------------------------------------------------------------


class TestFaithfulnessGate:
    def test_gate_passes_and_detects_sabotage(self, git_tree: Path) -> None:
        root = git_tree
        sha = _place(root, "pkg/a.py", _FETCH_SRC)
        _commit_all(root, "feat: add a")

        inventory = root / "inv.csv"
        _write_inventory(
            inventory,
            [
                _row(
                    "pkg/a.py",
                    sha,
                    inv.ROLE_FETCH_DATA,
                    ["fetch_data", "module_main", "__main___guard"],
                    ["BondSampleFetcher"],
                ),
            ],
        )
        gate, _ = inv.faithfulness_gate(str(root), str(inventory))
        assert gate.passed is True
        assert (gate.checked, gate.reproduced) == (1, 1)

        # A row whose anchor still matches but whose recorded role lies must fail the gate.
        wrong = _row("pkg/a.py", sha, inv.ROLE_RUN, ["run"], ["BondSampleFetcher"])
        _write_inventory(inventory, [wrong])
        gate, _ = inv.faithfulness_gate(str(root), str(inventory))
        assert gate.passed is False
        assert gate.reproduced == 0
        failure = gate.failures[0]
        assert failure["source_path"] == "pkg/a.py"
        assert failure["static_role"]["recorded"] == inv.ROLE_RUN
        assert failure["static_role"]["derived"] == inv.ROLE_FETCH_DATA

    def test_gate_ignores_rows_that_do_not_match_their_anchor(self, git_tree: Path) -> None:
        root = git_tree
        _place(root, "pkg/a.py", _FETCH_SRC)
        _commit_all(root, "feat: add a")
        inventory = root / "inv.csv"
        _write_inventory(inventory, [_row("pkg/a.py", "0" * 64, inv.ROLE_RUN, ["run"], [])])
        gate, _ = inv.faithfulness_gate(str(root), str(inventory))
        assert gate.checked == 0
        assert gate.passed is False  # an empty gate proves nothing, so it must not pass

    def test_cli_check_exits_zero_when_everything_is_attributed(self, git_tree: Path) -> None:
        root = git_tree
        sha = _place(root, "pkg/a.py", _FETCH_SRC)
        _commit_all(root, "feat: add a")
        inventory = root / "inv.csv"
        _write_inventory(
            inventory,
            [
                _row(
                    "pkg/a.py",
                    sha,
                    inv.ROLE_FETCH_DATA,
                    ["fetch_data", "module_main", "__main___guard"],
                    ["BondSampleFetcher"],
                ),
            ],
        )
        assert inv.main(["--repo-root", str(root), "--inventory", str(inventory), "--check"]) == 0

    def test_cli_check_exits_nonzero_on_unexplained_row(self, git_tree: Path) -> None:
        root = git_tree
        _place(root, "pkg/keep.py", _FETCH_SRC)
        _commit_all(root, "feat: baseline")
        (root / "pkg/untracked.py").write_text(_FETCH_SRC, encoding="utf-8")
        inventory = root / "inv.csv"
        _write_inventory(inventory, [_row("pkg/untracked.py", "e" * 64, inv.ROLE_RUN, ["run"], [])])
        assert inv.main(["--repo-root", str(root), "--inventory", str(inventory), "--check"]) == 1

    def test_cli_emits_only_after_the_gate_passes(self, git_tree: Path) -> None:
        root = git_tree
        sha = _place(root, "pkg/a.py", _FETCH_SRC)
        _commit_all(root, "feat: add a")
        inventory = root / "inv.csv"
        _write_inventory(
            inventory, [_row("pkg/a.py", sha, inv.ROLE_RUN, ["run"], ["BondSampleFetcher"])]
        )
        out = root / "regen.csv"
        assert (
            inv.main(
                [
                    "--repo-root",
                    str(root),
                    "--inventory",
                    str(inventory),
                    "--emit",
                    "--out",
                    str(out),
                ]
            )
            == 1
        )
        assert not out.exists()
        assert inv.read_inventory(str(inventory))[1][0][1] == sha  # committed file untouched


# --------------------------------------------------------------------------------------
# Emission framing
# --------------------------------------------------------------------------------------


class TestEmission:
    def test_non_derived_columns_and_framing_are_preserved(self, git_tree: Path) -> None:
        root = git_tree
        old_sha = _place(root, "pkg/a.py", _FETCH_SRC)
        _commit_all(root, "feat: add a")
        # The gate needs at least one anchor-matched row to prove faithfulness before emitting,
        # so `pkg/ref.py` stays in sync with its anchor while `pkg/a.py` drifts.
        ref_sha = _place(root, "pkg/ref.py", _FETCH_SRC)
        _place(root, "pkg/a.py", _RUN_SRC)  # drift the content after the anchor was recorded

        inventory = root / "inv.csv"
        original_notes = _marker(
            inv.ROLE_FETCH_DATA,
            ["fetch_data", "module_main", "__main___guard"],
            ["BondSampleFetcher"],
        )
        row = [
            "pkg/a.py",
            old_sha,
            "bond",
            "daily",
            inv.ROLE_FETCH_DATA,
            "shared_akshare_to_mysql",
            "PENDING_PROVIDER_MAPPING",
            "待数据契约与目标映射",
            "待盘点/待映射",
            "B",
            original_notes,
        ]
        ref_row = _row(
            "pkg/ref.py",
            ref_sha,
            inv.ROLE_FETCH_DATA,
            ["fetch_data", "module_main", "__main___guard"],
            ["BondSampleFetcher"],
        )
        inv.write_inventory(str(inventory), HEADER, [row, ref_row], b"\xef\xbb\xbf", "\n")

        out = root / "regen.csv"
        assert (
            inv.main(
                [
                    "--repo-root",
                    str(root),
                    "--inventory",
                    str(inventory),
                    "--emit",
                    "--out",
                    str(out),
                ]
            )
            == 0
        )

        raw = out.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        assert b"\r\n" not in raw
        assert raw.endswith(b"\n")
        header, rows, bom, terminator = inv.read_inventory(str(out))
        assert header == HEADER
        assert (bom, terminator) == (b"\xef\xbb\xbf", "\n")
        assert len(rows) == 2
        emitted = rows[0]
        # Human/placeholder columns survive byte for byte.
        for index, name in enumerate(HEADER):
            if name not in ("source_sha256", "static_role", "notes"):
                assert emitted[index] == row[index], name
        assert (
            emitted[HEADER.index("source_sha256")]
            == hashlib.sha256(_RUN_SRC.encode("utf-8")).hexdigest()
        )
        assert emitted[HEADER.index("static_role")] == inv.ROLE_RUN
        assert emitted[HEADER.index("notes")].partition("；")[2] == NOTES_TAIL
        # The in-sync row is reproduced exactly.
        assert rows[1] == ref_row

    def test_emit_refuses_to_overwrite_the_committed_inventory(self, git_tree: Path) -> None:
        root = git_tree
        sha = _place(root, "pkg/a.py", _FETCH_SRC)
        _commit_all(root, "feat: add a")
        inventory = root / "inv.csv"
        row = _row(
            "pkg/a.py",
            sha,
            inv.ROLE_FETCH_DATA,
            ["fetch_data", "module_main", "__main___guard"],
            ["BondSampleFetcher"],
        )
        inv.write_inventory(str(inventory), HEADER, [row], b"\xef\xbb\xbf", "\n")
        before = inventory.read_bytes()
        assert (
            inv.main(
                [
                    "--repo-root",
                    str(root),
                    "--inventory",
                    str(inventory),
                    "--emit",
                    "--out",
                    str(inventory),
                ]
            )
            == 2
        )
        assert inventory.read_bytes() == before

    def test_ghost_rows_are_left_untouched(self, git_tree: Path) -> None:
        root = git_tree
        _place(root, "pkg/keep.py", _FETCH_SRC)
        _commit_all(root, "feat: baseline")
        inventory = root / "inv.csv"
        row = _row("pkg/ghost.py", "c" * 64, inv.ROLE_RUN, ["run"], ["Ghost"])
        inv.write_inventory(str(inventory), HEADER, [row], b"\xef\xbb\xbf", "\n")
        emitted, stats = inv.regenerate(str(root), str(inventory))
        assert emitted[0] == row
        assert stats["anchor_updated"] == 0


# --------------------------------------------------------------------------------------
# Gate over the real committed inventory
# --------------------------------------------------------------------------------------


def _real_anchor_matched_rows() -> list[tuple[str, str, str]]:
    """(source_path, recorded static_role, recorded notes) for rows still matching their anchor."""
    if not INVENTORY_PATH.is_file():
        return []
    header, rows, _, _ = inv.read_inventory(str(INVENTORY_PATH))
    columns = inv.InventoryColumns(header)
    picked: list[tuple[str, str, str]] = []
    for row in rows:
        source = _REPO_ROOT / columns.source_path(row)
        if not source.is_file():
            continue
        if hashlib.sha256(source.read_bytes()).hexdigest() != columns.sha256(row):
            continue
        picked.append((str(source), columns.get(row, "static_role"), columns.get(row, "notes")))
    return picked


REAL_MATCHED_ROWS = _real_anchor_matched_rows()


def _matched_row_ids() -> list[str]:
    return [os.path.basename(path) for path, _role, _notes in REAL_MATCHED_ROWS]


@pytest.mark.skipif(not REAL_MATCHED_ROWS, reason="migration inventory is not present")
class TestRealInventoryFaithfulness:
    """Each row whose anchor still matches is a known-good (content, markers) pair."""

    @pytest.mark.parametrize(
        "index",
        list(range(len(REAL_MATCHED_ROWS))),
        ids=_matched_row_ids(),
    )
    def test_reproduces_recorded_markers(self, index: int) -> None:
        path, static_role, notes = REAL_MATCHED_ROWS[index]
        derived = inv.derive_markers(Path(path).read_text(encoding="utf-8"))
        recorded = inv.parse_recorded_markers(static_role, notes)
        assert derived.static_role == recorded.static_role, "static_role"
        assert derived.flags == recorded.flags, "flags"
        assert derived.classes == recorded.classes, "classes"
        assert derived.marker == recorded.marker, "marker"

    def test_gate_reports_full_coverage(self) -> None:
        gate, report = inv.faithfulness_gate(str(_REPO_ROOT), str(INVENTORY_PATH))
        assert gate.checked == len(REAL_MATCHED_ROWS)
        assert gate.reproduced == gate.checked, gate.failures[:5]
        assert gate.passed is True
        # The three-way anchor split documented for AC01 must not silently change shape.
        counts: dict[str, int] = report.counts
        assert counts["total"] == len(REAL_MATCHED_ROWS) + counts["mismatched"] + counts["missing"]
        assert counts["matched"] == len(REAL_MATCHED_ROWS)

    def test_every_drifted_row_is_attributed(self) -> None:
        """AC01: no unexplained item. Any drifted row must resolve to a commit or a ghost."""
        report = inv.classify_anchors(str(_REPO_ROOT), str(INVENTORY_PATH))
        unexplained = inv.unexplained_rows(report)
        assert unexplained == [], [(row.source_path, row.kind) for row in unexplained]
        assert sum(report.kinds.values()) == report.counts["total"]

    def test_derived_columns_agree_with_generation_commit_apart_from_known_stale_rows(self) -> None:
        """The stale-row set is measured, not assumed away.

        The recorded columns now come from the re-anchored CSV (tree ``74e2a0570a``): deriving them
        from the generation commit ``29afaeb47`` reproduces every row except ``akshare_catalog_batch.py``,
        which gained the class ``_CatalogStats`` in between. Before the re-anchor the CSV carried four
        ``classes=`` values that existed in no ``.py`` file in this repository's history; those rows are
        gone because the recorded columns no longer come from that derivation. This test locks the
        exception set so a future re-anchor cannot silently widen it.
        """
        snapshot = os.environ.get("INVENTORY_SNAPSHOT_COMMIT", "29afaeb47")
        if (
            subprocess.run(
                ["git", "-C", str(_REPO_ROOT), "cat-file", "-e", snapshot], capture_output=True
            ).returncode
            != 0
        ):
            pytest.skip(f"snapshot commit {snapshot} is not reachable here")

        header, rows, _, _ = inv.read_inventory(str(INVENTORY_PATH))
        columns = inv.InventoryColumns(header)
        stale: list[str] = []
        checked = 0
        for row in rows:
            source_path = columns.source_path(row)
            result = subprocess.run(
                ["git", "-C", str(_REPO_ROOT), "show", f"{snapshot}:{source_path}"],
                capture_output=True,
            )
            if result.returncode != 0:
                continue
            try:
                source = result.stdout.decode("utf-8")
            except UnicodeDecodeError:  # pragma: no cover - all rows are UTF-8
                continue
            checked += 1
            derived = inv.derive_markers(source)
            recorded = inv.parse_recorded_markers(
                columns.get(row, "static_role"), columns.get(row, "notes")
            )
            if (derived.static_role, derived.flags, derived.classes) != (
                recorded.static_role,
                recorded.flags,
                recorded.classes,
            ):
                stale.append(source_path)

        assert checked == 1057
        assert sorted(Path(path).name for path in stale) == ["akshare_catalog_batch.py"]
