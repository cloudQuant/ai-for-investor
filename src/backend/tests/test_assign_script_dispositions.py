"""Fixture-driven tests for the AC11 script disposition ledger tool.

Everything runs against temporary trees: no database, no network and no import of any
collection script.  Each guard is paired with a counterfactual that flips exactly one
evidence axis, so a disposition can only appear when its evidence is really present.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]
TOOL_PATH = BACKEND_ROOT / "scripts" / "ops" / "assign_script_dispositions.py"

_INVENTORY_HEADER = [
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

_SCRIPT_TEMPLATE = '''"""Sample collection script."""

import pandas as pd

from app.data_fetch.providers.akshare_to_mysql import AkshareToMySql


class SampleScript(AkshareToMySql):
    """Sample script."""

    def __init__(self):
        super().__init__()
        self.table_name = "{table}"

    def fetch_data(self, **kwargs):
        """Fetch one AkShare function into one table."""
        df = self.fetch_ak_data("{function}", **kwargs)
        self.save_data(df, self.table_name, ignore_duplicates=True)
        return df


def main():
    """Entrypoint used by the scheduler."""
    return SampleScript().fetch_data()


if __name__ == "__main__":
    main()
'''

_HELPER_TEMPLATE = '''"""Shared helper without a business entrypoint."""


def normalize_rows(rows):
    """Return the rows unchanged."""
    return list(rows)
'''


def _load_tool() -> ModuleType:
    """Import the ops tool from its file path."""
    name = "assign_script_dispositions_under_test"
    spec = importlib.util.spec_from_file_location(name, TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool()


def _sha(path: Path) -> str:
    """sha256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_script(root: Path, relative: str, *, function: str, table: str) -> Path:
    """Create one entrypoint collection script."""
    path = root / "src/backend/app/data_fetch/scripts" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_SCRIPT_TEMPLATE.format(function=function, table=table), encoding="utf-8")
    return path


def _write_helper(root: Path, relative: str) -> Path:
    """Create a module without fetch_data/run/main/execute."""
    path = root / "src/backend/app/data_fetch/scripts" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_HELPER_TEMPLATE, encoding="utf-8")
    return path


def _write_inventory(root: Path, rows: list[dict[str, str]]) -> Path:
    """Write a temporary inventory CSV shaped like the pinned 2026-10-26 baseline."""
    path = root / "inventory.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_INVENTORY_HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _inventory_row(rel_path: str, sha: str, **overrides: str) -> dict[str, str]:
    """One live inventory row with the placeholder vocabulary of the pinned CSV."""
    row = {
        "source_path": rel_path,
        "source_sha256": sha,
        "asset_family": overrides.get("asset_family", "bond"),
        "legacy_frequency": overrides.get("legacy_frequency", "daily"),
        "static_role": overrides.get("static_role", "entrypoint_fetch_data"),
        "akshare_usage": "shared_akshare_to_mysql",
        "migration_route": "PENDING_PROVIDER_MAPPING",
        "target_dataset": "待数据契约与目标映射",
        "status": "待盘点/待映射",
        "owner": "B",
        "notes": "static snapshot only",
    }
    row.update(overrides)
    return row


def _write_opendata(
    root: Path,
    *,
    vendor_functions: tuple[str, ...] = (),
    adapter_files: dict[str, tuple[str, ...]] | None = None,
    migrated: dict[str, tuple[str, str]] | None = None,
) -> Path:
    """Create a minimal opendata tree: vendor facade, provider descriptor and models."""
    od = root / "opendata"
    provider_pkg = od / "opendata/data/providers/akshare"
    vendor = provider_pkg / "_vendor/__init__.py"
    vendor.parent.mkdir(parents=True, exist_ok=True)
    entries = "\n".join(
        f"    {name!r}: ('opendata.data.providers.akshare._vendor.m', {name!r}, False),"
        for name in vendor_functions
    )
    vendor.write_text(f"_EXPORTS = {{\n{entries}\n}}\n", encoding="utf-8")
    provider = provider_pkg / "provider.py"
    provider.write_text(
        "from opendata.data.provider import LazyFetcherBinding, Provider\n"
        "PROVIDER = Provider(\n"
        '    source="akshare",\n'
        "    fetcher_bindings=(\n"
        "        LazyFetcherBinding(\n"
        '            "opendata.data.providers.akshare.models.daily", "AkshareDailyFetcher",\n'
        "        ),\n"
        "    ),\n"
        ")\n",
        encoding="utf-8",
    )
    for name, referenced in (adapter_files or {}).items():
        model = provider_pkg / "models" / f"{name}.py"
        model.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(
            f"def _fetch_{index}():\n    return ak.{function}()\n"
            for index, function in enumerate(referenced)
        )
        model.write_text(
            f'"""Fetcher module."""\n\nimport akshare as ak\n\n{body}\n', encoding="utf-8"
        )
    for table, (function, _) in (migrated or {}).items():
        script = od / "opendata/data_fetch/scripts/stocks/daily" / f"{function}.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            _SCRIPT_TEMPLATE.replace("app.data_fetch.providers.akshare_to_mysql", "x").format(
                function=function, table=table
            ),
            encoding="utf-8",
        )
    return od


def _write_akshare_init(path: Path, functions: tuple[str, ...]) -> Path:
    """Create a stand-in upstream ``akshare/__init__.py`` exporting the given names."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"from akshare.module import {name}" for name in functions)
    path.write_text(f'"""Upstream akshare stand-in."""\n\n{body}\n', encoding="utf-8")
    return path


def _base_args(
    root: Path,
    inventory: Path,
    opendata: Path,
    akshare_init: Path,
    extra: list[str] | None = None,
) -> list[str]:
    """Common CLI arguments for a run against temporary trees."""
    args = [
        "--repo-root",
        str(root),
        "--inventory",
        str(inventory),
        "--opendata-root",
        str(opendata),
        "--akshare-init",
        str(akshare_init),
        "--script-listing",
        "filesystem",
        "--out-dir",
        str(root / "out"),
        "--as-of-utc",
        "2026-11-06T00:00:00Z",
        "--batch-id",
        "test-batch",
        "--limit",
        "0",
    ]
    if extra:
        args.extend(extra)
    return args


def _document(root: Path) -> dict:
    """Read back the produced JSON ledger."""
    return json.loads((root / "out/script_disposition_ledger.json").read_text(encoding="utf-8"))


def _rows_by_path(root: Path) -> dict[str, dict]:
    """Index ledger rows by script path."""
    return {row["path"]: row for row in _document(root)["rows"]}


def _csv_rows(root: Path) -> list[dict[str, str]]:
    """Read back the produced CSV ledger."""
    with (root / "out/script_disposition_ledger.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_disposition_vocabulary_is_the_seven_plan_words() -> None:
    """The tool may only emit the seven §5 dispositions, verbatim and in plan order."""
    assert TOOL.DISPOSITIONS == (
        "REUSE_PROVIDER",
        "EXTEND_PROVIDER",
        "CONSOLIDATE",
        "HELPER_ONLY",
        "REPLACE_SOURCE",
        "SOURCE_LIMITED",
        "RETIRE_PROPOSED",
    )
    assert TOOL.UNDECIDED == "UNDECIDED_INSUFFICIENT_EVIDENCE"
    assert TOOL.UNDECIDED not in TOOL.DISPOSITIONS


def test_adapter_present_in_opendata_proposes_extend_not_reuse(tmp_path: Path) -> None:
    """A dataset with an opendata fetcher still lacks real-source proof, so REUSE is withheld."""
    rel = "src/backend/app/data_fetch/scripts/bonds/daily/bond_zh_hs_cov_daily.py"
    _write_script(
        tmp_path,
        "bonds/daily/bond_zh_hs_cov_daily.py",
        function="bond_zh_hs_cov_daily",
        table="BOND_ZH_HS_COV_DAILY",
    )
    inventory = _write_inventory(tmp_path, [_inventory_row(rel, _sha(tmp_path / rel))])
    opendata = _write_opendata(
        tmp_path,
        vendor_functions=("bond_zh_hs_cov_daily",),
        adapter_files={"daily": ("bond_zh_hs_cov_daily",)},
    )
    akshare_init = _write_akshare_init(
        tmp_path / "akshare_pkg/akshare/__init__.py", ("bond_zh_hs_cov_daily",)
    )

    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    row = _rows_by_path(tmp_path)[rel]
    assert row["disposition"] == "EXTEND_PROVIDER"
    assert row["decision_state"] == "proposed"
    assert "opendata:registered_fetcher_references_source_function" in row["evidence"]
    assert "source_verification:none_recorded" in row["evidence"]

    # Counterfactual: recorded real-source verification promotes the same evidence to REUSE.
    verification = tmp_path / "verification.json"
    verification.write_text(
        json.dumps(
            {"records": [{"source_function": "bond_zh_hs_cov_daily", "verified_at_utc": "x"}]}
        ),
        encoding="utf-8",
    )
    args = _base_args(
        tmp_path,
        inventory,
        opendata,
        akshare_init,
        ["--source-verification-export", str(verification)],
    )
    assert TOOL.run(args) == 0
    promoted = _rows_by_path(tmp_path)[rel]
    assert promoted["disposition"] == "REUSE_PROVIDER"
    assert promoted["decision_state"] == "proposed"


def test_missing_opendata_root_keeps_the_adapter_axis_open(tmp_path: Path) -> None:
    """Without the opendata read no provider-side disposition may be claimed."""
    rel = "src/backend/app/data_fetch/scripts/bonds/daily/bond_x.py"
    _write_script(tmp_path, "bonds/daily/bond_x.py", function="bond_x", table="BOND_X")
    inventory = _write_inventory(tmp_path, [_inventory_row(rel, _sha(tmp_path / rel))])
    _write_opendata(tmp_path, vendor_functions=("bond_x",))
    akshare_init = _write_akshare_init(tmp_path / "akshare_pkg/akshare/__init__.py", ("bond_x",))

    args = _base_args(tmp_path, inventory, tmp_path / "absent-opendata", akshare_init)
    assert TOOL.run(args) == 0
    row = _rows_by_path(tmp_path)[rel]
    assert row["disposition"] == "UNDECIDED_INSUFFICIENT_EVIDENCE"
    assert "opendata_adapter" in row["missing_axes"]
    assert "opendata:not_read" in row["evidence"]


def test_helper_without_entrypoint_is_helper_only(tmp_path: Path) -> None:
    """No fetch_data/run/main means HELPER_ONLY, still proposed rather than assigned."""
    rel = "src/backend/app/data_fetch/scripts/common/_shared_rows.py"
    _write_helper(tmp_path, "common/_shared_rows.py")
    inventory = _write_inventory(tmp_path, [_inventory_row(rel, _sha(tmp_path / rel))])
    opendata = _write_opendata(tmp_path)
    akshare_init = _write_akshare_init(tmp_path / "akshare_pkg/akshare/__init__.py", ())

    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    row = _rows_by_path(tmp_path)[rel]
    assert row["disposition"] == "HELPER_ONLY"
    assert row["decision_state"] == "proposed"
    assert "decision:ast_shows_no_fetch_data/run/main/execute_entrypoint" in row["evidence"]
    assert "registration" in row["missing_axes"]

    # Counterfactual: adding an entrypoint removes the HELPER_ONLY basis.
    _write_script(tmp_path, "common/_shared_rows.py", function="bond_live", table="BOND_NEW")
    inventory2 = _write_inventory(tmp_path, [_inventory_row(rel, _sha(tmp_path / rel))])
    opendata_live = _write_opendata(tmp_path, vendor_functions=("bond_live",))
    akshare_live = _write_akshare_init(
        tmp_path / "akshare_pkg2/akshare/__init__.py", ("bond_live",)
    )
    assert TOOL.run(_base_args(tmp_path, inventory2, opendata_live, akshare_live)) == 0
    assert _rows_by_path(tmp_path)[rel]["disposition"] == "EXTEND_PROVIDER"


def test_ghost_inventory_row_is_reported_but_never_dispositioned(tmp_path: Path) -> None:
    """The nine known ghosts stay in the anti-join report with no ledger row."""
    rel = "src/backend/app/data_fetch/scripts/options/daily/ghost_script.py"
    inventory = _write_inventory(tmp_path, [_inventory_row(rel, "0" * 64)])
    opendata = _write_opendata(tmp_path)
    akshare_init = _write_akshare_init(tmp_path / "akshare_pkg/akshare/__init__.py", ())

    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    document = _document(tmp_path)
    assert document["reconciliation"]["tracked_scripts"] == 0
    assert document["reconciliation"]["ledger_rows"] == 0
    assert document["reconciliation"]["inventory_rows_without_working_tree_file"] == [rel]
    assert rel not in _rows_by_path(tmp_path)

    # Counterfactual: once the file exists it becomes a ledger row and leaves the ghost list.
    _write_script(tmp_path, "options/daily/ghost_script.py", function="hf_x", table="HF_X")
    inventory2 = _write_inventory(
        tmp_path, [_inventory_row(rel, _sha(tmp_path / rel), asset_family="other")]
    )
    assert TOOL.run(_base_args(tmp_path, inventory2, opendata, akshare_init)) == 0
    document = _document(tmp_path)
    assert document["reconciliation"]["tracked_scripts"] == 1
    assert document["reconciliation"]["inventory_rows_without_working_tree_file"] == []


def test_proposal_is_not_an_assignment(tmp_path: Path) -> None:
    """No row counts as assigned without a named human review of the exact hash."""
    rel = "src/backend/app/data_fetch/scripts/bonds/daily/bond_a.py"
    _write_script(tmp_path, "bonds/daily/bond_a.py", function="bond_a", table="BOND_A")
    inventory = _write_inventory(tmp_path, [_inventory_row(rel, _sha(tmp_path / rel))])
    opendata = _write_opendata(tmp_path, vendor_functions=("bond_a",))
    akshare_init = _write_akshare_init(tmp_path / "akshare_pkg/akshare/__init__.py", ("bond_a",))

    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    report = _document(tmp_path)["reconciliation"]
    assert report["proposed_count"] == 1
    assert report["assigned_count"] == 0
    assert "proposed, unreviewed" in _rows_by_path(tmp_path)[rel]["decided_by"]

    # Counterfactual: an approved review naming the reviewer and the current hash assigns it.
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "reviews": [
                    {
                        "path": rel,
                        "disposition": "EXTEND_PROVIDER",
                        "reviewer": "owner-B",
                        "reviewed_at_utc": "2026-11-06T01:00:00Z",
                        "decision": "approve",
                        "file_sha256": _sha(tmp_path / rel),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    args = _base_args(tmp_path, inventory, opendata, akshare_init, ["--review-file", str(review)])
    assert TOOL.run(args) == 0
    assigned = _document(tmp_path)["reconciliation"]["assigned_count"]
    assert assigned == 1
    row = _rows_by_path(tmp_path)[rel]
    assert row["decision_state"] == "assigned"
    assert "assigned by owner-B" in row["decided_by"]


@pytest.mark.parametrize(
    ("field", "value", "expected_state"),
    [
        ("reviewer", "", "review_missing_reviewer_name"),
        ("decision", "reject", "review_reject"),
        ("disposition", "REUSE_PROVIDER", "review_disposition_mismatch"),
        ("file_sha256", "f" * 64, "review_stale_for_sha256"),
    ],
)
def test_defective_reviews_never_assign(
    tmp_path: Path, field: str, value: str, expected_state: str
) -> None:
    """Each review guard alone is enough to keep a row out of the assigned count."""
    rel = "src/backend/app/data_fetch/scripts/bonds/daily/bond_guard.py"
    _write_script(tmp_path, "bonds/daily/bond_guard.py", function="bond_guard", table="BOND_GUARD")
    inventory = _write_inventory(tmp_path, [_inventory_row(rel, _sha(tmp_path / rel))])
    opendata = _write_opendata(tmp_path, vendor_functions=("bond_guard",))
    akshare_init = _write_akshare_init(
        tmp_path / "akshare_pkg/akshare/__init__.py", ("bond_guard",)
    )
    record = {
        "path": rel,
        "disposition": "EXTEND_PROVIDER",
        "reviewer": "owner-B",
        "reviewed_at_utc": "2026-11-06T01:00:00Z",
        "decision": "approve",
        "file_sha256": _sha(tmp_path / rel),
    }
    record[field] = value
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"reviews": [record]}), encoding="utf-8")

    args = _base_args(tmp_path, inventory, opendata, akshare_init, ["--review-file", str(review)])
    assert TOOL.run(args) == 0
    assert _document(tmp_path)["reconciliation"]["assigned_count"] == 0
    assert _rows_by_path(tmp_path)[rel]["decision_state"] == expected_state


def test_ledger_has_exactly_one_row_per_tracked_script(tmp_path: Path) -> None:
    """The anti-join holds in both directions and the CSV mirrors the JSON."""
    entries = [
        ("bonds/daily/bond_one.py", "bond_one", "BOND_ONE"),
        ("bonds/daily/bond_two.py", "bond_two", "BOND_TWO"),
        ("common/daily/bond_three.py", "bond_three", "BOND_THREE"),
    ]
    rows = []
    for relative, function, table in entries:
        path = _write_script(tmp_path, relative, function=function, table=table)
        rows.append(_inventory_row(f"src/backend/app/data_fetch/scripts/{relative}", _sha(path)))
    inventory = _write_inventory(tmp_path, rows)
    opendata = _write_opendata(tmp_path, vendor_functions=("bond_one", "bond_two", "bond_three"))
    akshare_init = _write_akshare_init(
        tmp_path / "akshare_pkg/akshare/__init__.py", ("bond_one", "bond_two", "bond_three")
    )

    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    report = _document(tmp_path)["reconciliation"]
    assert report["tracked_scripts"] == 3
    assert report["ledger_rows"] == 3
    assert report["duplicate_ledger_paths"] == []
    assert report["tracked_scripts_missing_from_ledger"] == []
    assert report["ledger_paths_not_tracked"] == []
    assert report["ledger_rows_without_existing_file"] == []
    csv_rows = _csv_rows(tmp_path)
    assert {row["path"] for row in csv_rows} == {row["path"] for row in _document(tmp_path)["rows"]}

    # Counterfactual: an extra script file with no inventory row is surfaced, not hidden.
    extra = _write_script(
        tmp_path, "bonds/daily/bond_four.py", function="bond_four", table="BOND_4"
    )
    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    report = _document(tmp_path)["reconciliation"]
    assert report["tracked_scripts_without_inventory_row"] == [
        "src/backend/app/data_fetch/scripts/bonds/daily/bond_four.py"
    ]
    assert (tmp_path / "out/script_disposition_ledger.csv").is_file()
    assert extra.is_file()


def test_insufficient_evidence_lands_in_the_report_bucket(tmp_path: Path) -> None:
    """Two source functions in one script cannot be force-fitted into a disposition."""
    relative = "common/daily/forex_hist_em.py"
    rel = f"src/backend/app/data_fetch/scripts/{relative}"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _SCRIPT_TEMPLATE.format(function="forex_hist_em", table="FOREX_HIST_EM")
        + "\ndef fetch_other():\n    return ak.forex_spot_em()\n",
        encoding="utf-8",
    )
    inventory = _write_inventory(tmp_path, [_inventory_row(rel, _sha(path), asset_family="fx")])
    opendata = _write_opendata(tmp_path, vendor_functions=("forex_hist_em", "forex_spot_em"))
    akshare_init = _write_akshare_init(
        tmp_path / "akshare_pkg/akshare/__init__.py", ("forex_hist_em", "forex_spot_em")
    )

    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    row = _rows_by_path(tmp_path)[rel]
    assert row["disposition"] == "UNDECIDED_INSUFFICIENT_EVIDENCE"
    assert "single_source_function" in row["missing_axes"]
    assert "forex_hist_em;forex_spot_em" == row["source_functions"]
    assert row["disposition"] not in TOOL.DISPOSITIONS

    # Counterfactual: with one source function the same script is dispositioned.
    single = _write_script(tmp_path, relative, function="forex_hist_em", table="FOREX_HIST_EM")
    inventory2 = _write_inventory(tmp_path, [_inventory_row(rel, _sha(single), asset_family="fx")])
    assert TOOL.run(_base_args(tmp_path, inventory2, opendata, akshare_init)) == 0
    assert _rows_by_path(tmp_path)[rel]["disposition"] == "EXTEND_PROVIDER"


def test_consolidate_requires_same_function_and_same_table(tmp_path: Path) -> None:
    """Duplicate sinks merge; the same function written to different sinks does not."""
    twin = [
        ("futures/daily/fut_a.py", "fut_a", "SHARED_SINK"),
        ("futures/weekly/fut_b.py", "fut_a", "SHARED_SINK"),
    ]

    def build(entries: list[tuple[str, str, str]]) -> Path:
        rows = []
        for relative, function, table in entries:
            path = _write_script(tmp_path, relative, function=function, table=table)
            rows.append(
                _inventory_row(
                    f"src/backend/app/data_fetch/scripts/{relative}",
                    _sha(path),
                    asset_family="futures",
                )
            )
        return _write_inventory(tmp_path, rows)

    inventory = build(twin)
    opendata = _write_opendata(tmp_path, vendor_functions=("fut_a",))
    akshare_init = _write_akshare_init(tmp_path / "akshare_pkg/akshare/__init__.py", ("fut_a",))

    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    by_path = _rows_by_path(tmp_path)
    assert sorted(row["disposition"] for row in by_path.values()) == [
        "CONSOLIDATE",
        "CONSOLIDATE",
    ]
    for row in by_path.values():
        assert "decision:same_source_function_and_target_table_shared_by=" in row["evidence"]

    # Counterfactual: splitting the sink removes the CONSOLIDATE basis but keeps the note.
    split = [
        ("futures/daily/fut_a.py", "fut_a", "SINK_ONE"),
        ("futures/weekly/fut_b.py", "fut_a", "SINK_TWO"),
    ]
    inventory2 = build(split)
    assert TOOL.run(_base_args(tmp_path, inventory2, opendata, akshare_init)) == 0
    by_path = _rows_by_path(tmp_path)
    assert sorted(row["disposition"] for row in by_path.values()) == [
        "EXTEND_PROVIDER",
        "EXTEND_PROVIDER",
    ]
    for row in by_path.values():
        assert "corpus:same_source_function_also_called_by=1_scripts:" in row["evidence"]
        assert "decision:same_source_function_and_target_table_shared_by=" not in row["evidence"]


def test_unresolvable_source_function_proposes_source_limited(tmp_path: Path) -> None:
    """A function absent upstream and in the vendor tree keeps the history requirement open."""
    rel = "src/backend/app/data_fetch/scripts/common/weekly/hf_gone.py"
    path = _write_script(tmp_path, "common/weekly/hf_gone.py", function="hf_gone", table="HF_GONE")
    inventory = _write_inventory(
        tmp_path, [_inventory_row(rel, _sha(path), asset_family="other", legacy_frequency="weekly")]
    )
    opendata = _write_opendata(tmp_path, vendor_functions=("bond_live",))
    akshare_init = _write_akshare_init(tmp_path / "akshare_pkg/akshare/__init__.py", ("bond_live",))

    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    row = _rows_by_path(tmp_path)[rel]
    assert row["disposition"] == "SOURCE_LIMITED"
    assert "decision:recheck_condition_owner_must_probe_real_source_availability" in row["evidence"]

    # Counterfactual: an empty upstream read means no source-availability claim is possible.
    empty_init = _write_akshare_init(tmp_path / "other_akshare/akshare/__init__.py", ())
    assert TOOL.run(_base_args(tmp_path, inventory, opendata, empty_init)) == 0
    row = _rows_by_path(tmp_path)[rel]
    assert row["disposition"] == "UNDECIDED_INSUFFICIENT_EVIDENCE"
    assert "source_reachability" in row["missing_axes"]


def test_upstream_alias_call_is_resolved_not_declared_source_lost(tmp_path: Path) -> None:
    """AKShare re-exports some interfaces as `alias = real`; calling an alias kept its source.

    This is the measured 2026-11-05 regression: hf_subscribe_exchange_symbol was proposed
    SOURCE_LIMITED because the tool only knew the called name, while upstream line 5567
    binds it to futures_hq_subscribe_exchange_symbol, which the vendor tree exports.
    """
    rel = "src/backend/app/data_fetch/scripts/common/weekly/hf_subscribe_exchange_symbol.py"
    path = _write_script(
        tmp_path,
        "common/weekly/hf_subscribe_exchange_symbol.py",
        function="hf_subscribe_exchange_symbol",
        table="HF_SUBSCRIBE_EXCHANGE_SYMBOL",
    )
    inventory = _write_inventory(tmp_path, [_inventory_row(rel, _sha(path), asset_family="other")])
    opendata = _write_opendata(tmp_path, vendor_functions=("futures_hq_subscribe_exchange_symbol",))
    akshare_init = tmp_path / "akshare_pkg/akshare/__init__.py"
    akshare_init.parent.mkdir(parents=True, exist_ok=True)
    akshare_init.write_text(
        "from akshare.futures.futures_foreign import futures_hq_subscribe_exchange_symbol\n"
        "hf_subscribe_exchange_symbol = futures_hq_subscribe_exchange_symbol\n",
        encoding="utf-8",
    )

    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    row = _rows_by_path(tmp_path)[rel]
    assert row["disposition"] == "EXTEND_PROVIDER"
    assert (
        "upstream_akshare:called_name_is_alias_to=futures_hq_subscribe_exchange_symbol"
        in row["evidence"]
    )
    assert "opendata:vendor_akshare_export_present=True" in row["evidence"]
    assert "source_function_unresolvable" not in row["evidence"]

    # Counterfactual: without the alias binding the same call really is unresolvable.
    akshare_init.write_text(
        "from akshare.futures.futures_foreign import futures_hq_subscribe_exchange_symbol\n",
        encoding="utf-8",
    )
    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    assert _rows_by_path(tmp_path)[rel]["disposition"] == "SOURCE_LIMITED"


def test_replace_source_requires_an_opendata_path_for_the_same_sink(tmp_path: Path) -> None:
    """Only a proven same-sink alternative may be recorded as REPLACE_SOURCE."""
    rel = "src/backend/app/data_fetch/scripts/funds/daily/fund_gone.py"
    path = _write_script(
        tmp_path, "funds/daily/fund_gone.py", function="fund_gone", table="fund_etf_hist_em"
    )
    inventory = _write_inventory(tmp_path, [_inventory_row(rel, _sha(path), asset_family="fund")])
    opendata = _write_opendata(
        tmp_path,
        vendor_functions=("fund_etf_hist_em",),
        migrated={"fund_etf_hist_em": ("fund_etf_hist_em", "fund_etf_hist_em")},
    )
    akshare_init = _write_akshare_init(
        tmp_path / "akshare_pkg/akshare/__init__.py", ("fund_etf_hist_em",)
    )

    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    row = _rows_by_path(tmp_path)[rel]
    assert row["disposition"] == "REPLACE_SOURCE"
    assert "opendata:migrated_data_fetch_script_present" in row["evidence"]

    # Counterfactual: without the migrated same-sink script the claim drops to SOURCE_LIMITED.
    (opendata / "opendata/data_fetch/scripts/stocks/daily/fund_etf_hist_em.py").unlink()
    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    assert _rows_by_path(tmp_path)[rel]["disposition"] == "SOURCE_LIMITED"


def test_retire_proposal_needs_the_registration_export(tmp_path: Path) -> None:
    """RETIRE_PROPOSED is unreachable while the ak_data_scripts axis was never read."""
    rel = "src/backend/app/data_fetch/scripts/bonds/daily/bond_orphan.py"
    path = _write_script(tmp_path, "bonds/daily/bond_orphan.py", function="bond_orphan", table="T")
    inventory = _write_inventory(tmp_path, [_inventory_row(rel, _sha(path))])
    opendata = _write_opendata(tmp_path, vendor_functions=("bond_orphan",))
    akshare_init = _write_akshare_init(
        tmp_path / "akshare_pkg/akshare/__init__.py", ("bond_orphan",)
    )

    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    assert _rows_by_path(tmp_path)[rel]["disposition"] == "EXTEND_PROVIDER"

    # Counterfactual: a read-only export proving no registered row unlocks the proposal.
    export = tmp_path / "registration.json"
    export.write_text(
        json.dumps({"rows": [{"module_path": "app.data_fetch.scripts.other.kept.py"}]}),
        encoding="utf-8",
    )
    args = _base_args(
        tmp_path, inventory, opendata, akshare_init, ["--registration-export", str(export)]
    )
    assert TOOL.run(args) == 0
    row = _rows_by_path(tmp_path)[rel]
    assert row["disposition"] == "RETIRE_PROPOSED"
    assert "ak_data_scripts:no_registered_row" in row["evidence"]

    # Counterfactual: a registered row closes the retire path again.
    export.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "module_path": "app.data_fetch.scripts.bonds.daily.bond_orphan",
                        "is_active": 1,
                        "function_name": "main",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert TOOL.run(args) == 0
    row = _rows_by_path(tmp_path)[rel]
    assert row["disposition"] == "EXTEND_PROVIDER"
    assert "ak_data_scripts:registered" in row["evidence"]


def test_consumer_reference_is_recorded_from_the_scan(tmp_path: Path) -> None:
    """A reference in AFI service code is evidence; its absence is only a scan statement."""
    rel = "src/backend/app/data_fetch/scripts/bonds/daily/bond_used.py"
    path = _write_script(tmp_path, "bonds/daily/bond_used.py", function="bond_used", table="BOND")
    consumer = tmp_path / "src/backend/app/services/consumer.py"
    consumer.parent.mkdir(parents=True, exist_ok=True)
    consumer.write_text("DEFAULTS = {'bond_used': {'symbol': 'x'}}\n", encoding="utf-8")
    inventory = _write_inventory(tmp_path, [_inventory_row(rel, _sha(path))])
    opendata = _write_opendata(tmp_path, vendor_functions=("bond_used",))
    akshare_init = _write_akshare_init(tmp_path / "akshare_pkg/akshare/__init__.py", ("bond_used",))

    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    row = _rows_by_path(tmp_path)[rel]
    assert (
        "afi_consumer:identifier=bond_used:at=src/backend/app/services/consumer.py:1"
        in row["evidence"]
    )

    # Counterfactual: removing the consumer file changes the recorded consumer axis.
    consumer.unlink()
    assert TOOL.run(_base_args(tmp_path, inventory, opendata, akshare_init)) == 0
    assert (
        "afi_consumer:no_identifier_reference_in_scan_scope"
        in _rows_by_path(tmp_path)[rel]["evidence"]
    )


def test_out_of_batch_rows_stay_empty_and_counts_reproduce(tmp_path: Path) -> None:
    """A bounded batch leaves the rest untouched and the ratio stays auditable."""
    rows = []
    for index in range(4):
        relative = f"bonds/daily/bond_{index}.py"
        path = _write_script(tmp_path, relative, function=f"bond_{index}", table=f"T{index}")
        rows.append(
            _inventory_row(
                f"src/backend/app/data_fetch/scripts/{relative}",
                _sha(path),
                asset_family="bond" if index < 3 else "fx",
            )
        )
    inventory = _write_inventory(tmp_path, rows)
    opendata = _write_opendata(tmp_path, vendor_functions=("bond_0", "bond_1", "bond_2", "bond_3"))
    akshare_init = _write_akshare_init(
        tmp_path / "akshare_pkg/akshare/__init__.py", ("bond_0", "bond_1", "bond_2", "bond_3")
    )

    args = _base_args(
        tmp_path, inventory, opendata, akshare_init, ["--family", "bond", "--limit", "2"]
    )
    assert TOOL.run(args) == 0
    first = _document(tmp_path)
    report = first["reconciliation"]
    assert report["disposition_counts_in_batch"] == {"EXTEND_PROVIDER": 2}
    assert report["proposed_count"] == 2
    assert report["out_of_batch_count"] == 2
    assert sum(1 for row in first["rows"] if row["in_batch"] == "no") == 2
    for row in first["rows"]:
        if row["in_batch"] == "no":
            assert row["disposition"] == ""
            assert row["batch_id"] == ""
            assert row["evidence"] == "scope:not_selected_in_this_batch"

    # Counterfactual: the same arguments reproduce byte-identical ledgers.
    first_csv = (tmp_path / "out/script_disposition_ledger.csv").read_bytes()
    assert TOOL.run(args) == 0
    assert (tmp_path / "out/script_disposition_ledger.csv").read_bytes() == first_csv


def test_real_inventory_denominator_is_recomputed_not_asserted(tmp_path: Path) -> None:
    """Against the pinned CSV the tool re-derives 1057 tracked scripts and the 9 ghosts."""
    if not (REPO_ROOT / "src/backend/app/data_fetch/scripts").is_dir():
        pytest.skip("repository scripts tree unavailable")
    inventory = REPO_ROOT / PurePosixPath(TOOL.DEFAULT_INVENTORY)
    if not inventory.is_file():
        pytest.skip("pinned inventory CSV unavailable")
    out = tmp_path / "out"
    args = [
        "--repo-root",
        str(REPO_ROOT),
        "--inventory",
        str(inventory),
        "--opendata-root",
        str(Path("/home/yun/Documents/opendata")),
        "--out-dir",
        str(out),
        "--family",
        "crypto",
        "--as-of-utc",
        "2026-11-06T00:00:00Z",
        "--batch-id",
        "denominator-check",
    ]
    assert TOOL.run(args) == 0
    report = json.loads((out / "script_disposition_ledger.json").read_text(encoding="utf-8"))[
        "reconciliation"
    ]
    assert report["tracked_scripts"] == 1057
    assert report["ledger_rows"] == 1057
    assert len(report["inventory_rows_without_working_tree_file"]) == 9
    assert report["duplicate_ledger_paths"] == []
    assert report["ledger_rows_without_existing_file"] == []
