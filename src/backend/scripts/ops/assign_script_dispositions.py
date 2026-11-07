"""Propose and record 迭代204 §5 migration dispositions for AFI collection scripts.

The tool is read-only over its inputs (``script_migration_inventory.csv``, the AFI
working tree, the opendata working tree, an optional upstream AKShare export list and
optional registration / source-verification / review exports) and writes a new ledger
(JSON + CSV).  It never mutates the inventory CSV and never imports a collection script:
all per-script facts come from AST parsing, so no network or database code executes.

Two states are kept strictly apart:

* ``proposed`` -- produced by this tool from evidence it actually read.
* ``assigned`` -- a proposal that a named human reviewer approved in ``--review-file``
  for the exact same file hash.  A proposal never becomes an assignment by itself, and
  the summary counts them separately.

Rows whose evidence is insufficient are reported in the
``UNDECIDED_INSUFFICIENT_EVIDENCE`` bucket, which is a *report* bucket and is not one of
the seven §5 dispositions; they are never force-fitted into a disposition.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Final

TOOL_NAME: Final = "assign_script_dispositions"
TOOL_VERSION: Final = "1"

#: The seven dispositions defined by IMPLEMENTATION_PLAN.md §5, verbatim.
DISPOSITIONS: Final[tuple[str, ...]] = (
    "REUSE_PROVIDER",
    "EXTEND_PROVIDER",
    "CONSOLIDATE",
    "HELPER_ONLY",
    "REPLACE_SOURCE",
    "SOURCE_LIMITED",
    "RETIRE_PROPOSED",
)

#: Report bucket, not a §5 disposition.
UNDECIDED: Final = "UNDECIDED_INSUFFICIENT_EVIDENCE"

SCRIPT_ROOT_REL: Final = PurePosixPath("src/backend/app/data_fetch/scripts")
DEFAULT_INVENTORY: Final = PurePosixPath(
    "docs/iterations/迭代204-OpenData数据中台拆分与五人并行迁移/script_migration_inventory.csv"
)
DEFAULT_OPENDATA_ROOT: Final = Path("/home/yun/Documents/opendata")
#: Editable upstream AKShare checkout used, when present, to test whether a source function
#: name still exists.  Absent means the source-reachability axis was not read.
DEFAULT_AKSHARE_INIT: Final = Path("/home/yun/Documents/akshare/akshare/__init__.py")
_ENTRYPOINT_NAMES: Final = frozenset({"fetch_data", "run", "main", "execute"})
_ID_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OPENBB_ENTRY_RE: Final = re.compile(
    r"^\s*-\s*\{provider:\s*(?P<provider>[A-Za-z0-9_]+),\s*domain:\s*(?P<domain>[A-Za-z0-9_-]+),"
    r"\s*contract:\s*(?P<contract>[A-Za-z0-9_]+),\s*status:\s*(?P<status>[a-z_]+)\}"
)
LEDGER_COLUMNS: Final[tuple[str, ...]] = (
    "path",
    "sha256",
    "disposition",
    "evidence",
    "batch_id",
    "decided_by",
    "decided_at_utc",
    "decision_state",
    "in_batch",
    "review_reviewer",
    "review_decision",
    "review_disposition",
    "review_file_sha256",
    "missing_axes",
    "inventory_sha_matches_current",
    "target_table",
    "source_functions",
    "entrypoints",
    "asset_family",
    "legacy_frequency",
    "static_role",
    "akshare_usage",
    "owner",
    "inventory_migration_route",
    "inventory_status",
)


def sha256_file(path: Path) -> str:
    """Return the sha256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now_stamp() -> str:
    """Second-precision UTC stamp used for ``decided_at_utc``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_rev_parse(rev: str, cwd: Path) -> str | None:
    """Resolve a git revision, returning ``None`` when git is unavailable."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", rev],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - defensive
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def git_tracked_scripts(repo_root: Path) -> list[str] | None:
    """List tracked non-``__init__`` scripts via ``git ls-files``; ``None`` if git fails."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z", "--", str(SCRIPT_ROOT_REL) + "/*.py"],
            cwd=repo_root,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - defensive
        return None
    if proc.returncode != 0:
        return None
    paths = [
        entry.decode("utf-8", "surrogateescape") for entry in proc.stdout.split(b"\0") if entry
    ]
    return sorted(
        path
        for path in paths
        if PurePosixPath(path).name.endswith(".py") and PurePosixPath(path).name != "__init__.py"
    )


def filesystem_scripts(repo_root: Path) -> list[str]:
    """List non-``__init__`` scripts by walking the working tree."""
    root = repo_root / Path(SCRIPT_ROOT_REL)
    if not root.is_dir():
        return []
    return sorted(
        str(PurePosixPath(path.relative_to(repo_root)))
        for path in root.rglob("*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    )


@dataclass(frozen=True)
class InventoryRow:
    """One live row of ``script_migration_inventory.csv``."""

    source_path: str
    source_sha256: str
    asset_family: str
    legacy_frequency: str
    static_role: str
    akshare_usage: str
    migration_route: str
    target_dataset: str
    status: str
    owner: str
    notes: str

    @property
    def is_placeholder_route(self) -> bool:
        """True when the route is one of the two undefined 2026-10-26 placeholders."""
        return self.migration_route in {"PENDING_PROVIDER_MAPPING", "HELPER_REVIEW"}


def load_inventory(path: Path) -> list[InventoryRow]:
    """Parse the inventory CSV (tolerating a UTF-8 BOM) into ordered rows."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows: list[InventoryRow] = []
        for record in csv.DictReader(handle):
            rows.append(
                InventoryRow(
                    source_path=(record.get("source_path") or "").strip(),
                    source_sha256=(record.get("source_sha256") or "").strip(),
                    asset_family=(record.get("asset_family") or "").strip(),
                    legacy_frequency=(record.get("legacy_frequency") or "").strip(),
                    static_role=(record.get("static_role") or "").strip(),
                    akshare_usage=(record.get("akshare_usage") or "").strip(),
                    migration_route=(record.get("migration_route") or "").strip(),
                    target_dataset=(record.get("target_dataset") or "").strip(),
                    status=(record.get("status") or "").strip(),
                    owner=(record.get("owner") or "").strip(),
                    notes=(record.get("notes") or "").strip(),
                )
            )
    return rows


def parse_script(path: Path) -> tuple[tuple[str, ...], tuple[str, ...], str | None, str | None]:
    """Extract source functions, entrypoints and the target table from a script's AST.

    Returns ``(source_functions, entrypoints, target_table, parse_error)``.  The script is
    parsed, never imported.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover - defensive
        return (), (), None, f"{type(exc).__name__}"

    functions: set[str] = set()
    entrypoints: set[str] = set()
    table_name: str | None = None

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in _ENTRYPOINT_NAMES:
            entrypoints.add(node.name)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "fetch_ak_data":
                if node.args and isinstance(node.args[0], ast.Constant):
                    value = node.args[0].value
                    if isinstance(value, str) and value:
                        functions.add(value)
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id in {"ak", "akshare"} and isinstance(func.attr, str):
                    functions.add(func.attr)
            if isinstance(func, ast.Attribute) and func.attr == "getattr":
                for arg in node.args[1:2]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        functions.add(arg.value)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets: list[ast.expr] = (
                [node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)
            )
            value = getattr(node, "value", None)
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "table_name"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    table_name = value.value

    return tuple(sorted(functions)), tuple(sorted(entrypoints)), table_name, None


def identifier_scan(repo_root: Path, needles: Sequence[str]) -> dict[str, list[str]]:
    """Find identifier-bound references to ``needles`` outside the collection scripts.

    Scans ``src/backend/app`` plus ``src/backend/scripts`` and the frontend ``src`` tree,
    skipping the scripts directory itself, caches and virtual environments.  A missing
    reference is only a statement about this scan scope.
    """
    hits: dict[str, list[str]] = defaultdict(list)
    if not needles:
        return hits
    needle_set = set(needles)
    scan_roots = [
        repo_root / "src/backend/app",
        repo_root / "src/backend/scripts",
        repo_root / "src/frontend/src",
    ]
    scripts_dir = repo_root / Path(SCRIPT_ROOT_REL)
    for root in scan_roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".vue", ".js"}:
                continue
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            if scripts_dir in path.parents:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:  # pragma: no cover - defensive
                continue
            rel = PurePosixPath(path.relative_to(repo_root))
            for line_no, line in enumerate(text.splitlines(), start=1):
                for token in set(_ID_RE.findall(line)).intersection(needle_set):
                    if len(hits[token]) < 5:
                        hits[token].append(f"{rel}:{line_no}")
    return hits


@dataclass
class OpendataIndex:
    """Read-only index over the opendata working tree (AST/text only, never imported)."""

    root: Path | None
    vendor_exports: set[str] = field(default_factory=set)
    adapter_source_functions: dict[str, list[str]] = field(default_factory=dict)
    migrated_script_functions: dict[str, list[str]] = field(default_factory=dict)
    registered_bindings: list[str] = field(default_factory=list)
    akshare_bindings: list[str] = field(default_factory=list)
    openbb_domains: list[str] = field(default_factory=list)
    adapter_scan_scope: str = "opendata/data/providers/akshare (excluding _vendor)"
    scanned_files: int = 0
    error: str | None = None

    @property
    def available(self) -> bool:
        """True when the index was built from a readable opendata tree."""
        return self.root is not None and self.error is None


def _vendor_export_names(facade: Path) -> set[str]:
    """Read the ``_EXPORTS`` mapping keys of the bundled AKShare compatibility facade."""
    names: set[str] = set()
    try:
        tree = ast.parse(facade.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return names
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "_EXPORTS":
            names.update(key.value for key in node.value.keys if isinstance(key.value, str))
    return names


def _registered_fetcher_modules(akshare_root: Path) -> list[tuple[str, str]]:
    """Collect ``(module, class)`` fetcher bindings declared by provider descriptors."""
    bindings: list[tuple[str, str]] = []
    for provider_file in sorted(akshare_root.rglob("provider.py")):
        if "_vendor" in provider_file.parts or "__pycache__" in provider_file.parts:
            continue
        try:
            tree = ast.parse(provider_file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            func_name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else (func.id if isinstance(func, ast.Name) else None)
            )
            if func_name not in {"LazyFetcherBinding", "FetcherBinding"}:
                continue
            literals = [arg.value for arg in node.args if isinstance(arg, ast.Constant)]
            if len(literals) >= 2 and all(isinstance(item, str) for item in literals[:2]):
                bindings.append((str(literals[0]), str(literals[1])))
    return bindings


def _source_names_referenced_by(path: Path) -> set[str]:
    """Names a provider module references: attributes, string constants and imports."""
    names: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.attr, str):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
    return names


def build_opendata_index(root: Path | None) -> OpendataIndex:
    """Build the opendata adapter index, recording why it is unavailable when absent."""
    if root is None:
        return OpendataIndex(root=None, error="opendata root not provided")
    if not root.is_dir():
        return OpendataIndex(root=root, error=f"opendata root absent: {root}")
    index = OpendataIndex(root=root)
    providers_root = root / "opendata/data/providers"
    if not providers_root.is_dir():
        index.error = f"provider root absent: {providers_root}"
        return index
    facade = providers_root / "akshare/_vendor/__init__.py"
    index.vendor_exports = _vendor_export_names(facade)
    bindings = _registered_fetcher_modules(providers_root)
    index.registered_bindings = [f"{module}.{cls}" for module, cls in bindings]
    index.akshare_bindings = [
        f"{module}.{cls}" for module, cls in bindings if ".providers.akshare." in f".{module}."
    ]
    referenced: dict[str, list[str]] = defaultdict(list)
    akshare_root = providers_root / "akshare"
    for path in sorted(akshare_root.rglob("*.py")):
        if "_vendor" in path.parts or "__pycache__" in path.parts:
            continue
        index.scanned_files += 1
        for name in _source_names_referenced_by(path):
            # Only names that are AKShare source functions count as adapter coverage; the
            # vendor facade is the authoritative list of those names in this tree.
            if name in index.vendor_exports and name not in referenced:
                referenced[name].append(str(PurePosixPath(path.relative_to(root))))
    for name, files in referenced.items():
        index.adapter_source_functions[name] = sorted(set(files))[:3]
    scripts_root = root / "opendata/data_fetch/scripts"
    if scripts_root.is_dir():
        for path in sorted(scripts_root.rglob("*.py")):
            if path.name == "__init__.py" or "__pycache__" in path.parts:
                continue
            functions, _, table, _ = parse_script(path)
            for function in functions:
                index.migrated_script_functions.setdefault(function, []).append(
                    str(PurePosixPath(path.relative_to(root)))
                )
            if table:
                index.migrated_script_functions.setdefault(table, []).append(
                    str(PurePosixPath(path.relative_to(root)))
                )
    index.migrated_script_functions = {
        name: sorted(set(files)) for name, files in index.migrated_script_functions.items()
    }
    map_file = root / "opendata/data/openbb_map.yaml"
    if map_file.is_file():
        try:
            for line in map_file.read_text(encoding="utf-8").splitlines():
                match = _OPENBB_ENTRY_RE.match(line)
                if match:
                    parts = match.groupdict()
                    index.openbb_domains.append(
                        f"{parts['provider']}:{parts['domain']}:{parts['contract']}:{parts['status']}"
                    )
        except (OSError, UnicodeDecodeError):  # pragma: no cover - defensive
            pass
    return index


def load_upstream_exports(path: Path | None) -> tuple[set[str], dict[str, str], str | None]:
    """Read the upstream AKShare package's exported names and public aliases.

    AKShare re-exports some interfaces under a second name with a module-level
    ``alias = real_function`` assignment, so both are needed: a script calling the alias
    has not lost its source.  Returns ``(names, aliases, error)``.
    """
    if path is None:
        return set(), {}, None
    if not path.is_file():
        return set(), {}, f"akshare init absent: {path}"
    names: set[str] = set()
    aliases: dict[str, str] = {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        return set(), {}, f"akshare init unreadable: {type(exc).__name__}"
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Name):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id != node.value.id:
                aliases[target.id] = node.value.id
                names.add(target.id)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Assign) and isinstance(node.value, (ast.Tuple, ast.List)):
            target = node.targets[0] if node.targets else None
            if isinstance(target, ast.Name) and target.id == "__all__":
                names.update(
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                )
    return names, aliases, None


@dataclass
class ScriptFacts:
    """Everything the decision engine is allowed to read about one script."""

    rel_path: str
    abs_path: Path
    sha256: str
    inventory: InventoryRow | None
    source_functions: tuple[str, ...]
    entrypoints: tuple[str, ...]
    target_table: str | None
    consumer_refs: dict[str, list[str]]
    inventory_sha_matches_current: bool | None
    parse_error: str | None = None

    @property
    def stem(self) -> str:
        """Module stem of the script file."""
        return PurePosixPath(self.rel_path).stem

    @property
    def module_path(self) -> str:
        """Importable module path used by ``ak_data_scripts.module_path``."""
        parts = PurePosixPath(self.rel_path).parts
        backend_index = parts.index("backend")
        module_parts = parts[backend_index + 1 :]
        return ".".join(module_parts)[: -len(".py")]

    @property
    def is_private_helper_name(self) -> bool:
        """True for underscore-prefixed module names."""
        return self.stem.startswith("_")


def collect_facts(
    repo_root: Path,
    paths: Sequence[str],
    inventory_by_path: Mapping[str, InventoryRow],
) -> list[ScriptFacts]:
    """Read per-script facts for every tracked script (AST only, never imported)."""
    needles: set[str] = set()
    parsed: dict[str, tuple[tuple[str, ...], tuple[str, ...], str | None, str | None]] = {}
    for rel in paths:
        abs_path = repo_root / Path(rel)
        parsed[rel] = parse_script(abs_path)
        functions, _, _, _ = parsed[rel]
        needles.update(functions)
        needles.add(PurePosixPath(rel).stem)
    consumer_hits = identifier_scan(repo_root, sorted(needles))

    facts: list[ScriptFacts] = []
    for rel in paths:
        abs_path = repo_root / Path(rel)
        functions, entrypoints, table, parse_error = parsed[rel]
        row = inventory_by_path.get(rel)
        current_sha = sha256_file(abs_path)
        refs: dict[str, list[str]] = {}
        for needle in {*functions, PurePosixPath(rel).stem}:
            found = consumer_hits.get(needle)
            if found:
                refs[needle] = found[:5]
        facts.append(
            ScriptFacts(
                rel_path=rel,
                abs_path=abs_path,
                sha256=current_sha,
                inventory=row,
                source_functions=functions,
                entrypoints=entrypoints,
                target_table=table,
                consumer_refs=refs,
                inventory_sha_matches_current=((current_sha == row.source_sha256) if row else None),
                parse_error=parse_error,
            )
        )
    return facts


def load_json_export(path: Path | None) -> Any:
    """Load an optional JSON export, returning ``None`` when it is not provided."""
    if path is None:
        return None
    if not path.is_file():
        raise SystemExit(f"export file not found: {path}")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def registration_by_module(payload: Any) -> dict[str, dict[str, Any]]:
    """Index a read-only ``ak_data_scripts`` export by ``module_path``."""
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("module_path"), str):
            index[row["module_path"]] = row
    return index


def verification_keys(payload: Any) -> set[str]:
    """Collect ``source_function`` keys that already carry real-source verification."""
    if not isinstance(payload, dict):
        return set()
    keys: set[str] = set()
    for record in payload.get("records") or []:
        if not isinstance(record, dict):
            continue
        function = record.get("source_function")
        if isinstance(function, str) and record.get("verified_at_utc"):
            keys.add(function)
    return keys


def review_index(payload: Any) -> dict[str, dict[str, Any]]:
    """Index human review records by script path."""
    if not isinstance(payload, dict):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for record in payload.get("reviews") or []:
        if isinstance(record, dict) and isinstance(record.get("path"), str):
            index[record["path"]] = record
    return index


def _ev(items: Iterable[str]) -> list[str]:
    """De-duplicate evidence strings while preserving insertion order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


@dataclass
class Decision:
    """Outcome for one script: a disposition, or the report bucket plus missing axes."""

    disposition: str
    evidence: list[str]
    missing_axes: list[str] = field(default_factory=list)


def decide(
    facts: ScriptFacts,
    opendata: OpendataIndex,
    upstream: set[str],
    upstream_aliases: Mapping[str, str],
    upstream_source: str | None,
    duplicates: Mapping[tuple[str, str], list[str]],
    corpus_by_function: Mapping[str, list[str]],
    registrations: Mapping[str, dict[str, Any]],
    verified: set[str],
    registration_read: bool,
) -> Decision:
    """Propose one §5 disposition from evidence that was actually read.

    Precedence (first match wins, so a script never receives two dispositions):
    ``HELPER_ONLY`` (no entrypoint) > ``SOURCE_LIMITED``/``REPLACE_SOURCE`` (source name
    resolves in neither the upstream AKShare package nor the bundled vendor tree) >
    ``CONSOLIDATE`` (identical source function *and* identical target table across
    scripts) > ``REUSE_PROVIDER`` (adapter present *and* a recorded real-source
    verification) > ``RETIRE_PROPOSED`` (registration export proves no row, no consumer
    reference) > ``EXTEND_PROVIDER``.  Anything still missing an axis at the point it is
    needed lands in ``UNDECIDED_INSUFFICIENT_EVIDENCE``.
    """
    evidence: list[str] = []
    missing: list[str] = []
    row = facts.inventory
    if row is None:
        missing.append("inventory_row")
    else:
        evidence.append(
            "inventory:route="
            f"{row.migration_route};status={row.status};role={row.static_role};"
            f"family={row.asset_family};frequency={row.legacy_frequency};owner={row.owner}"
        )
        if row.is_placeholder_route:
            evidence.append(f"inventory:placeholder_route_not_a_disposition({row.migration_route})")
    evidence.append(
        f"file:sha256={facts.sha256}:inventory_sha_matches_current="
        f"{facts.inventory_sha_matches_current}"
    )

    if facts.parse_error:
        missing.append("parseable_source")
        return Decision(UNDECIDED, _ev(evidence), sorted(set(missing)))

    functions = facts.source_functions
    if not functions:
        missing.append("source_function")
    if len(functions) > 1:
        missing.append("single_source_function")
    if facts.target_table is None:
        missing.append("target_table")

    evidence.append(f"ast:entrypoints={','.join(facts.entrypoints) or 'none'}")
    evidence.append(f"ast:source_functions={','.join(functions) or 'none'}")
    if facts.target_table:
        evidence.append(f"ast:target_table={facts.target_table}")
    for needle, refs in sorted(facts.consumer_refs.items()):
        for ref in refs:
            evidence.append(f"afi_consumer:identifier={needle}:at={ref}")
    if not facts.consumer_refs:
        evidence.append("afi_consumer:no_identifier_reference_in_scan_scope")

    registered = registrations.get(facts.module_path) if registration_read else None
    if registration_read:
        if registered is None:
            evidence.append(f"ak_data_scripts:no_registered_row({facts.module_path})")
        else:
            evidence.append(
                "ak_data_scripts:registered:is_active={active};function_name={function}".format(
                    active=registered.get("is_active"),
                    function=registered.get("function_name"),
                )
            )
    else:
        evidence.append("ak_data_scripts:not_read(no --registration-export)")
        missing.append("registration")

    if not opendata.available:
        evidence.append(f"opendata:not_read({opendata.error})")
        missing.append("opendata_adapter")

    # HELPER_ONLY: no independent business entrypoint (plan §5: 无独立业务入口).
    if not facts.entrypoints:
        evidence.append("decision:ast_shows_no_fetch_data/run/main/execute_entrypoint")
        if facts.is_private_helper_name:
            evidence.append("decision:module_name_is_underscore_private")
        evidence.append("outstanding:HELPER_ONLY_bans_scheduled_tasks_so_registration_still_open")
        return Decision("HELPER_ONLY", _ev(evidence), sorted(set(missing)))

    if len(functions) != 1:
        return Decision(UNDECIDED, _ev(evidence), sorted(set(missing)))
    if facts.target_table is None:
        return Decision(UNDECIDED, _ev(evidence), sorted(set(missing)))
    if not opendata.available:
        return Decision(UNDECIDED, _ev(evidence), sorted(set(missing)))

    function = functions[0]
    canonical = upstream_aliases.get(function, function) if upstream else function
    names_read = [function] if canonical == function else [function, canonical]
    in_vendor = any(name in opendata.vendor_exports for name in names_read)
    in_upstream = bool(upstream) and any(name in upstream for name in names_read)
    adapter_files = sorted(
        {found for name in names_read for found in opendata.adapter_source_functions.get(name, [])}
    )
    migrated_by_function = sorted(
        {found for name in names_read for found in opendata.migrated_script_functions.get(name, [])}
    )
    migrated_by_sink = opendata.migrated_script_functions.get(facts.target_table, [])
    if canonical != function:
        evidence.append(
            f"upstream_akshare:called_name_is_alias_to={canonical}:alias_read_from={upstream_source}"
        )
    evidence.append(f"opendata:vendor_akshare_export_present={in_vendor}")
    if adapter_files:
        evidence.append(
            f"opendata:registered_fetcher_references_source_function:files={','.join(adapter_files)}"
        )
    else:
        evidence.append(
            f"opendata:no_fetcher_module_references_source_function:scope={opendata.adapter_scan_scope}"
        )
    if migrated_by_function:
        evidence.append(
            "opendata:migrated_data_fetch_script_present:matched_by=source_function:files="
            + ",".join(sorted(set(migrated_by_function)))
        )
    if migrated_by_sink and set(migrated_by_sink) != set(migrated_by_function or ()):
        evidence.append(
            "opendata:migrated_data_fetch_script_present:matched_by=target_table:files="
            + ",".join(sorted(set(migrated_by_sink)))
        )
    if upstream_source:
        evidence.append(f"upstream_akshare:function_present={in_upstream}:{upstream_source}")
    else:
        evidence.append("upstream_akshare:not_read")

    if not in_vendor and not upstream:
        missing.append("source_reachability")
        evidence.append("decision:cannot_tell_extend_from_source_limited_without_upstream_read")
        return Decision(UNDECIDED, _ev(evidence), sorted(set(missing)))

    siblings = [
        path
        for path in duplicates.get((function, facts.target_table), [])
        if path != facts.rel_path
    ]
    others = [path for path in corpus_by_function.get(function, []) if path != facts.rel_path]
    if others:
        evidence.append(
            f"corpus:same_source_function_also_called_by={len(others)}_scripts:"
            + ";".join(others[:6])
            + (";..." if len(others) > 6 else "")
        )

    if not in_vendor and not in_upstream:
        # Source name resolves nowhere readable offline: the source itself is in question.
        evidence.append("decision:source_function_unresolvable_in_upstream_and_vendor_tree")
        if migrated_by_sink:
            evidence.append(
                "decision:opendata_covers_same_target_table_under_other_source_function"
                f":files={','.join(sorted(set(migrated_by_sink)))}"
            )
            return Decision("REPLACE_SOURCE", _ev(evidence), sorted(set(missing)))
        evidence.append("decision:recheck_condition_owner_must_probe_real_source_availability")
        return Decision("SOURCE_LIMITED", _ev(evidence), sorted(set(missing)))

    if siblings:
        evidence.append(
            "decision:same_source_function_and_target_table_shared_by=" + ";".join(siblings[:8])
        )
        evidence.append("decision:per_old_task_parameter_mapping_still_required")
        return Decision("CONSOLIDATE", _ev(evidence), sorted(set(missing)))

    if adapter_files or migrated_by_function:
        if function in verified:
            evidence.append("source_verification:recorded")
            return Decision("REUSE_PROVIDER", _ev(evidence), sorted(set(missing)))
        evidence.append("source_verification:none_recorded_so_semantic_and_source_gap_open")
        evidence.append("decision:adapter_exists_but_mapping_quality_recovery_work_remains")
        return Decision("EXTEND_PROVIDER", _ev(evidence), sorted(set(missing)))

    if registration_read and registered is None and not facts.consumer_refs:
        evidence.append("decision:no_registered_row_and_no_consumer_reference_in_scan_scope")
        evidence.append("decision:impact_list_pending_product_owner_confirmation")
        return Decision("RETIRE_PROPOSED", _ev(evidence), sorted(set(missing)))

    evidence.append("decision:no_opendata_fetcher_for_dataset_so_new_or_extended_fetcher_needed")
    return Decision("EXTEND_PROVIDER", _ev(evidence), sorted(set(missing)))


def corpus_groups(
    facts: Sequence[ScriptFacts],
) -> tuple[dict[tuple[str, str], list[str]], dict[str, list[str]]]:
    """Group entrypoint scripts by ``(source_function, target_table)`` and by function.

    The first map holds exact duplicates (same source function written into the same
    table) and drives the CONSOLIDATE proposal; the second only records that other
    scripts read the same source function, which is review context rather than a
    disposition.
    """
    by_function_table: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_function: dict[str, list[str]] = defaultdict(list)
    for item in facts:
        if len(item.source_functions) != 1 or not item.entrypoints:
            continue
        function = item.source_functions[0]
        by_function[function].append(item.rel_path)
        if item.target_table:
            by_function_table[(function, item.target_table)].append(item.rel_path)
    exact = {key: sorted(paths) for key, paths in by_function_table.items() if len(paths) > 1}
    shared = {key: sorted(paths) for key, paths in by_function.items() if len(paths) > 1}
    return exact, shared


def select_batch(
    facts: Sequence[ScriptFacts],
    families: Sequence[str],
    static_roles: Sequence[str],
    path_prefixes: Sequence[str],
    limit: int | None,
) -> set[str]:
    """Deterministically pick the bounded batch: filter, sort by path, then cap.

    With no filter flags at all every tracked script is in scope; a filter narrows the
    batch and ``--limit`` caps it after sorting by path, so repeated runs select the
    same set.
    """
    unfiltered = not (families or static_roles or path_prefixes)
    selected: list[str] = []
    for item in sorted(facts, key=lambda fact: fact.rel_path):
        row = item.inventory
        matches = unfiltered
        if families and row is not None and row.asset_family in families:
            matches = True
        if static_roles and row is not None and row.static_role in static_roles:
            matches = True
        if path_prefixes and any(item.rel_path.startswith(prefix) for prefix in path_prefixes):
            matches = True
        if matches:
            selected.append(item.rel_path)
    return set(selected[:limit] if limit is not None else selected)


@dataclass
class LedgerRow:
    """One ledger record: exactly one tracked script."""

    values: dict[str, str]

    def as_csv(self) -> dict[str, str]:
        """Return the row keyed for CSV writing."""
        return self.values


def build_ledger_rows(
    facts: Sequence[ScriptFacts],
    decisions: Mapping[str, Decision],
    batch: set[str],
    reviews: Mapping[str, dict[str, Any]],
    batch_id: str,
    decided_at: str,
) -> list[LedgerRow]:
    """Combine proposals and review records into ledger rows, keeping states distinct."""
    rows: list[LedgerRow] = []
    for item in sorted(facts, key=lambda fact: fact.rel_path):
        decision = decisions[item.rel_path]
        row = item.inventory
        in_batch = item.rel_path in batch
        proposed = decision.disposition if in_batch else ""
        review = reviews.get(item.rel_path)
        disposition = proposed
        state = "proposed" if in_batch else "out_of_batch"
        reviewer = review_file_sha = ""
        review_decision = ""
        review_disposition = ""
        decided_by = f"{TOOL_NAME}/{TOOL_VERSION} (proposed, unreviewed)"
        if review is not None:
            reviewer = str(review.get("reviewer") or "")
            review_decision = str(review.get("decision") or "")
            review_disposition = str(review.get("disposition") or "")
            review_at = str(review.get("reviewed_at_utc") or "")
            review_file_sha = str(review.get("file_sha256") or "")
            if not in_batch:
                state = "review_without_batch"
            elif not reviewer:
                state = "review_missing_reviewer_name"
            elif review_decision != "approve":
                state = f"review_{review_decision or 'unspecified'}"
            elif review_disposition != proposed:
                state = "review_disposition_mismatch"
            elif review_file_sha and review_file_sha != item.sha256:
                state = "review_stale_for_sha256"
            else:
                state = "assigned"
                decided_by = (
                    f"{TOOL_NAME}/{TOOL_VERSION} proposed; assigned by {reviewer} at {review_at}"
                )
        values = {
            "path": item.rel_path,
            "sha256": item.sha256,
            "disposition": disposition,
            "evidence": "|".join(
                decision.evidence if in_batch else ["scope:not_selected_in_this_batch"]
            ),
            "batch_id": batch_id if in_batch else "",
            "decided_by": decided_by,
            "decided_at_utc": decided_at if in_batch else "",
            "decision_state": state,
            "in_batch": "yes" if in_batch else "no",
            "review_reviewer": reviewer,
            "review_decision": review_decision,
            "review_disposition": review_disposition,
            "review_file_sha256": review_file_sha,
            "missing_axes": ";".join(decision.missing_axes) if in_batch else "",
            "inventory_sha_matches_current": (
                "yes"
                if item.inventory_sha_matches_current is True
                else "no"
                if item.inventory_sha_matches_current is False
                else "unknown"
            ),
            "target_table": item.target_table or "",
            "source_functions": ";".join(item.source_functions),
            "entrypoints": ";".join(item.entrypoints),
            "asset_family": row.asset_family if row else "",
            "legacy_frequency": row.legacy_frequency if row else "",
            "static_role": row.static_role if row else "",
            "akshare_usage": row.akshare_usage if row else "",
            "owner": row.owner if row else "",
            "inventory_migration_route": row.migration_route if row else "",
            "inventory_status": row.status if row else "",
        }
        rows.append(LedgerRow(values))
    return rows


def _batch_split(ledger: Sequence[LedgerRow], batch_id: str) -> dict[str, int]:
    """Count batch rows by owner and asset family for the weekly report."""
    split: Counter[str] = Counter()
    for row in ledger:
        if row.values["batch_id"] != batch_id:
            continue
        split[f"owner:{row.values['owner'] or 'unknown'}"] += 1
        split[f"family:{row.values['asset_family'] or 'unknown'}"] += 1
    return dict(sorted(split.items()))


def anti_join(
    ledger: Sequence[LedgerRow],
    facts: Sequence[ScriptFacts],
    tracked: Sequence[str],
    inventory: Sequence[InventoryRow],
    repo_root: Path,
) -> dict[str, Any]:
    """Recompute the two-directional anti-join and the reproducibility counters."""
    paths = [row.values["path"] for row in ledger]
    counts = Counter(paths)
    duplicates = sorted(path for path, amount in counts.items() if amount > 1)
    missing_from_ledger = sorted(set(tracked) - set(paths))
    extra_in_ledger = sorted(set(paths) - set(tracked))
    dangling = [
        row.values["path"] for row in ledger if not (repo_root / Path(row.values["path"])).is_file()
    ]
    ghosts = sorted(
        row.source_path for row in inventory if not (repo_root / Path(row.source_path)).is_file()
    )
    tree_not_in_inventory = sorted(item.rel_path for item in facts if item.inventory is None)
    dispositions = Counter(
        row.values["disposition"] for row in ledger if row.values["in_batch"] == "yes"
    )
    states = Counter(row.values["decision_state"] for row in ledger)
    sha_agreement = Counter(row.values["inventory_sha_matches_current"] for row in ledger)
    return {
        "tracked_scripts": len(tracked),
        "ledger_rows": len(ledger),
        "duplicate_ledger_paths": duplicates,
        "tracked_scripts_missing_from_ledger": missing_from_ledger,
        "ledger_paths_not_tracked": extra_in_ledger,
        "ledger_rows_without_existing_file": dangling,
        "inventory_rows_without_working_tree_file": ghosts,
        "tracked_scripts_without_inventory_row": tree_not_in_inventory,
        "disposition_counts_in_batch": dict(sorted(dispositions.items())),
        "decision_state_counts": dict(sorted(states.items())),
        "inventory_sha_agreement": dict(sorted(sha_agreement.items())),
        "inventory_sha_note": (
            "The pinned CSV hashes come from the 2026-10-26 snapshot; AFI #270 rewrote most "
            "script files afterwards, so a differing hash is expected churn rather than a "
            "missing script. This tool records the agreement per row and does not resolve "
            "which revision a stale hash belongs to."
        ),
        "assigned_count": states["assigned"],
        "proposed_count": states["proposed"],
        "undecided_count": dispositions[UNDECIDED],
        "out_of_batch_count": len(tracked)
        - sum(1 for row in ledger if row.values["in_batch"] == "yes"),
    }


def _assert_reconciliation(report: Mapping[str, Any]) -> list[str]:
    """Return reconciliation failures; the ledger must be auditable before writing."""
    problems: list[str] = []
    if report["duplicate_ledger_paths"]:
        problems.append(f"duplicate ledger paths: {report['duplicate_ledger_paths']}")
    if report["tracked_scripts_missing_from_ledger"]:
        problems.append(
            f"tracked scripts absent from ledger: {len(report['tracked_scripts_missing_from_ledger'])}"
        )
    if report["ledger_paths_not_tracked"]:
        problems.append(f"ledger rows not tracked: {report['ledger_paths_not_tracked']}")
    if report["ledger_rows_without_existing_file"]:
        problems.append(
            f"ledger rows without a file on disk: {report['ledger_rows_without_existing_file']}"
        )
    if report["ledger_rows"] != report["tracked_scripts"]:
        problems.append(
            f"ledger rows {report['ledger_rows']} != tracked scripts {report['tracked_scripts']}"
        )
    return problems


def write_outputs(
    out_dir: Path,
    ledger: Sequence[LedgerRow],
    document: Mapping[str, Any],
) -> tuple[Path, Path]:
    """Write the machine-readable JSON and CSV ledger next to each other."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "script_disposition_ledger.json"
    csv_path = out_dir / "script_disposition_ledger.csv"
    json_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LEDGER_COLUMNS))
        writer.writeheader()
        for row in ledger:
            writer.writerow(row.values)
    return json_path, csv_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """CLI surface for the disposition ledger run."""
    parser = argparse.ArgumentParser(
        prog=f"{TOOL_NAME}.py",
        description=(
            "Propose 迭代204 §5 dispositions for AFI collection scripts and write a "
            "machine-readable ledger. Proposals are never assignments."
        ),
    )
    parser.add_argument("--repo-root", type=Path, default=None, help="AFI repository root.")
    parser.add_argument("--inventory", type=Path, default=None, help="Inventory CSV path.")
    parser.add_argument(
        "--opendata-root", type=Path, default=DEFAULT_OPENDATA_ROOT, help="opendata work tree."
    )
    parser.add_argument(
        "--akshare-init",
        type=Path,
        default=None,
        help="Upstream akshare/__init__.py used for source-name resolution.",
    )
    parser.add_argument(
        "--registration-export",
        type=Path,
        default=None,
        help="JSON export of ak_data_scripts (read-only SELECT); required for RETIRE_PROPOSED.",
    )
    parser.add_argument(
        "--source-verification-export",
        type=Path,
        default=None,
        help="JSON records proving real-source verification; required for REUSE_PROVIDER.",
    )
    parser.add_argument(
        "--review-file",
        type=Path,
        default=None,
        help="JSON human review records that turn proposals into assignments.",
    )
    parser.add_argument(
        "--family",
        default="",
        help="Comma-separated asset_family batch filter (no filter flag = whole tree).",
    )
    parser.add_argument("--static-role", default="", help="Comma-separated static_role filter.")
    parser.add_argument(
        "--path-prefix", default="", help="Comma-separated relative-path prefix filter."
    )
    parser.add_argument("--limit", type=int, default=80, help="Batch cap; 0 means uncapped.")
    parser.add_argument("--batch-id", default="", help="Stable batch identifier.")
    parser.add_argument("--out-dir", type=Path, default=None, help="Ledger output directory.")
    parser.add_argument(
        "--as-of-utc", default=None, help="Override decided_at_utc (reproducibility)."
    )
    parser.add_argument(
        "--script-listing",
        choices=("auto", "filesystem"),
        default="auto",
        help="'auto' prefers git ls-files (tracked only) and falls back to a tree walk.",
    )
    parser.add_argument("--list-batch", action="store_true", help="Print the batch and exit.")
    return parser.parse_args(argv)


def _default_repo_root() -> Path:
    """Repo root found by walking up from this file until the AFI markers appear."""
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "src/backend/app/data_fetch/scripts").is_dir():
            return candidate
    return here.parents[4]


def run(argv: Sequence[str] | None = None) -> int:
    """Execute one ledger run and print the measured counts."""
    args = parse_args(argv)
    repo_root = (args.repo_root or _default_repo_root()).resolve()
    inventory_path = args.inventory or repo_root / Path(DEFAULT_INVENTORY)
    if not inventory_path.is_file():
        raise SystemExit(f"inventory CSV not found: {inventory_path}")

    tracked = git_tracked_scripts(repo_root) if args.script_listing == "auto" else None
    listing_method = "git_ls_files" if tracked is not None else "filesystem_walk"
    if tracked is None:
        tracked = filesystem_scripts(repo_root)
    tracked = [path for path in tracked if (repo_root / Path(path)).is_file()]

    inventory = load_inventory(inventory_path)
    inventory_by_path: dict[str, InventoryRow] = {}
    duplicate_inventory_paths: list[str] = []
    for row in inventory:
        if row.source_path in inventory_by_path:
            duplicate_inventory_paths.append(row.source_path)
        inventory_by_path[row.source_path] = row

    facts = collect_facts(repo_root, tracked, inventory_by_path)
    opendata = build_opendata_index(args.opendata_root if args.opendata_root else None)
    akshare_init = args.akshare_init or (
        DEFAULT_AKSHARE_INIT if DEFAULT_AKSHARE_INIT.is_file() else None
    )
    upstream, upstream_aliases, upstream_error = load_upstream_exports(akshare_init)
    registrations = registration_by_module(load_json_export(args.registration_export))
    registration_read = args.registration_export is not None
    verified = verification_keys(load_json_export(args.source_verification_export))
    reviews = review_index(load_json_export(args.review_file))

    families = [item.strip() for item in args.family.split(",") if item.strip()]
    static_roles = [item.strip() for item in args.static_role.split(",") if item.strip()]
    prefixes = [item.strip() for item in args.path_prefix.split(",") if item.strip()]
    limit = args.limit if args.limit else None
    batch = select_batch(facts, families, static_roles, prefixes, limit)

    duplicates, function_share = corpus_groups(facts)
    decided_at = args.as_of_utc or utc_now_stamp()
    batch_id = args.batch_id or (f"{'-'.join(families) or 'all'}|{len(batch)}|{decided_at[:10]}")
    decisions: dict[str, Decision] = {}
    for item in facts:
        if item.rel_path in batch:
            decisions[item.rel_path] = decide(
                item,
                opendata,
                upstream,
                upstream_aliases,
                str(akshare_init) if akshare_init else None,
                duplicates,
                function_share,
                registrations,
                verified,
                registration_read,
            )
        else:
            decisions[item.rel_path] = Decision("", [])

    ledger = build_ledger_rows(facts, decisions, batch, reviews, batch_id, decided_at)
    report = anti_join(ledger, facts, tracked, inventory, repo_root)
    problems = _assert_reconciliation(report)

    if args.list_batch:
        for path in sorted(batch):
            print(path)
        return 0

    document = {
        "meta": {
            "tool": f"{TOOL_NAME}/{TOOL_VERSION}",
            "decided_at_utc": decided_at,
            "batch_id": batch_id,
            "plane": "CODE/OFFLINE only: static reads of source text and two working trees; "
            "no script was imported, no database or network call was made.",
            "dispositions_vocabulary": list(DISPOSITIONS),
            "report_buckets": [UNDECIDED, "OUT_OF_BATCH_IN_THIS_RUN"],
            "vocabulary_source": "IMPLEMENTATION_PLAN.md §5 每个脚本和任务如何迁移",
            "notice": (
                "proposed is not assigned. A row is only assigned when a named human reviewer "
                "approved the exact disposition for the exact file sha256 in --review-file. "
                "Inventory values PENDING_PROVIDER_MAPPING and HELPER_REVIEW are placeholders, "
                "not §5 dispositions."
            ),
            "repo_root": str(repo_root),
            "repo_head": git_rev_parse("HEAD", repo_root),
            "opendata_head": (git_rev_parse("HEAD", opendata.root) if opendata.available else None),
            "python": sys.version.split()[0],
            "script_listing_method": listing_method,
            "inventory_path": str(inventory_path),
            "inventory_rows": len(inventory),
            "inventory_duplicate_paths": sorted(set(duplicate_inventory_paths)),
            "opendata_index": {
                "root": str(opendata.root) if opendata.root else None,
                "available": opendata.available,
                "error": opendata.error,
                "adapter_scan_scope": opendata.adapter_scan_scope,
                "provider_files_scanned": opendata.scanned_files,
                "vendor_export_count": len(opendata.vendor_exports),
                "registered_binding_count": len(opendata.registered_bindings),
                "akshare_binding_count": len(opendata.akshare_bindings),
                "akshare_bindings": sorted(opendata.akshare_bindings),
                "adapter_referenced_name_count": len(opendata.adapter_source_functions),
                "migrated_script_function_count": len(opendata.migrated_script_functions),
                "openbb_domain_entries": sorted(set(opendata.openbb_domains))[:40],
            },
            "upstream_akshare": {
                "path": str(akshare_init) if akshare_init else None,
                "export_count": len(upstream),
                "error": upstream_error,
            },
            "registration_export": {
                "read": registration_read,
                "rows": len(registrations),
                "note": None
                if registration_read
                else "not read: RETIRE_PROPOSED is unreachable without it",
            },
            "source_verification_export": {
                "read": args.source_verification_export is not None,
                "records": len(verified),
                "note": None
                if args.source_verification_export is not None
                else "not read: REUSE_PROVIDER is unreachable without it",
            },
            "review_file": {
                "read": args.review_file is not None,
                "records": len(reviews),
            },
        },
        "reconciliation": report,
        "batch_split": _batch_split(ledger, batch_id),
        "reconciliation_problems": problems,
        "rows": [row.values for row in ledger],
    }

    out_dir = args.out_dir or repo_root / "var/reports/afi204/dispositions"
    json_path, csv_path = write_outputs(out_dir, ledger, document)

    print(f"tracked non-__init__ scripts: {report['tracked_scripts']}")
    print(f"ledger rows: {report['ledger_rows']} (one per tracked script)")
    print(f"batch id: {batch_id}; in batch: {len(batch)}")
    print(f"assigned: {report['assigned_count']}")
    print(f"proposed (unreviewed): {report['proposed_count']}")
    print(f"proposed bucket detail: {report['disposition_counts_in_batch']}")
    print(f"UNDECIDED_INSUFFICIENT_EVIDENCE: {report['undecided_count']}")
    print(f"out of batch: {report['out_of_batch_count']}")
    print(f"batch owner/family split: {_batch_split(ledger, batch_id)}")
    print(f"inventory sha agreement: {report['inventory_sha_agreement']}")
    print(
        f"assigned ratio for §6: {report['assigned_count']}/{report['tracked_scripts']} "
        f"(proposed {report['proposed_count']}/{report['tracked_scripts']})"
    )
    print(
        f"inventory rows without a file on disk: {len(report['inventory_rows_without_working_tree_file'])}"
    )
    print(f"reconciliation problems: {problems or 'none'}")
    print(f"wrote {json_path}")
    print(f"wrote {csv_path}")
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
