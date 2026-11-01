"""Read-only AST inventory of AFI market-data consumers and bypass paths.

This module deliberately does not import application configuration or execute
project code.  It reports literal source SDK imports/calls, direct warehouse
access patterns, local shared-data file paths, and the statically resolvable
Python call edges that connect those findings to application entry points.
Dynamic dependency injection and string-built paths remain explicit limits of
the report rather than being treated as clean results.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter, defaultdict, deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

_SOURCE_MODULES = frozenset(
    {
        "akshare",
        "baostock",
        "ccxt",
        "efinance",
        "futu",
        "jqdatasdk",
        "openbb",
        "rqdatac",
        "tqsdk",
        "tushare",
        "yfinance",
    }
)
_SOURCE_ADAPTER_MODULES = (
    "app.services.market_data.akshare_provider",
    "app.services.market_data.openbb_subprocess_provider",
    "app.services.market_data.opendata_provider",
    "app.services.market_data.ths_provider",
)
_WAREHOUSE_MODULES = (
    "mysql.connector",
    "pymysql",
    "psycopg",
    "psycopg2",
    "app.data_fetch.mysql",
    "app.data_fetch.database",
)
_WAREHOUSE_NAMES = frozenset(
    {
        "AkshareToMySql",
        "MysqlBase",
        "save_to_mysql",
        "fetch_ak_data",
        "save_data_to_mysql",
    }
)
_FILE_SUFFIXES = frozenset(
    {".csv", ".tsv", ".parquet", ".pq", ".feather", ".sqlite", ".sqlite3", ".db", ".pkl"}
)
_DATA_PATH_PATTERN = re.compile(
    r"(?:^|[/\\])(?:data|dataset|datasets|market_data|data_fetch)(?:[/\\]|$)|"
    r"(?:shared|warehouse|export|cache)[_/\\]",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class BoundaryHit:
    """One source-level finding with a stable location and classification."""

    path: str
    line: int
    category: str
    scope: str
    expression: str
    role: str


@dataclass(frozen=True, slots=True)
class CallEdge:
    """A locally resolvable Python call edge; dynamic calls are omitted."""

    caller: str
    callee: str
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Deterministic scan output suitable for review or JSON serialization."""

    root: str
    python_files: int
    parse_errors: tuple[str, ...]
    hits: tuple[BoundaryHit, ...]
    edges: tuple[CallEdge, ...]
    entrypoints: tuple[str, ...]
    source_reachable_entrypoints: tuple[str, ...]

    def summary(self) -> dict[str, object]:
        """Return countable findings without losing per-file evidence."""
        counts = Counter(hit.category for hit in self.hits)
        by_role = Counter(hit.role for hit in self.hits)
        by_file: dict[str, Counter[str]] = defaultdict(Counter)
        for hit in self.hits:
            by_file[hit.path][hit.category] += 1
        return {
            "root": self.root,
            "python_files": self.python_files,
            "parse_errors": list(self.parse_errors),
            "hit_count": len(self.hits),
            "category_counts": dict(sorted(counts.items())),
            "role_counts": dict(sorted(by_role.items())),
            "files_with_findings": len(by_file),
            "entrypoints": list(self.entrypoints),
            "source_reachable_entrypoints": list(self.source_reachable_entrypoints),
            "findings_by_file": {
                path: dict(sorted(file_counts.items()))
                for path, file_counts in sorted(by_file.items())
            },
        }


def _module_name(path: Path, source_root: Path) -> str:
    relative = path.relative_to(source_root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _role(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    if "/app/data_fetch/" in f"/{normalized}/":
        return "legacy_data_fetch_to_migrate"
    if normalized.startswith("src/backend/scripts/"):
        return "operational_script_review"
    if any(
        token in normalized
        for token in ("/api/live_trading/", "/api/broker", "/api/trade", "/api/orders")
    ):
        return "broker_control_preserve"
    if "/app/api/" in f"/{normalized}/":
        return "business_api_consumer"
    if "/app/services/market_data/" in f"/{normalized}/":
        return "market_data_boundary_or_service"
    if "/app/services/" in f"/{normalized}/" and Path(normalized).name not in {
        "gateway_specs.py",
        "monitoring_control.py",
        "reqdocs_migration_service.py",
    }:
        return "business_service_consumer_candidate"
    return "application_support"


def _name_parts(node: ast.expr) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (*_name_parts(node.value), node.attr)
    return ()


class _ModuleAnalyzer(ast.NodeVisitor):
    def __init__(self, *, path: str, module: str, role: str) -> None:
        self.path = path
        self.module = module
        self.role = role
        self.scope: list[str] = []
        self.imports: dict[str, str] = {}
        self.definitions: set[str] = set()
        self.calls: list[tuple[str, str, int]] = []
        self.hits: list[BoundaryHit] = []
        self.entries: set[str] = set()

    def _scope_name(self) -> str:
        return f"{self.module}::{'.'.join(self.scope) if self.scope else '<module>'}"

    def _add_hit(self, node: ast.AST, category: str, expression: str) -> None:
        self.hits.append(
            BoundaryHit(
                path=self.path,
                line=getattr(node, "lineno", 1),
                category=category,
                scope=self._scope_name(),
                expression=expression[:240],
                role=self.role,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.name
            bound = alias.asname or name.split(".")[0]
            self.imports[bound] = name if alias.asname else bound
            root = name.split(".")[0]
            if root in _SOURCE_MODULES:
                self._add_hit(node, "source_sdk_import", name)
            elif name.startswith(_SOURCE_ADAPTER_MODULES):
                self._add_hit(node, "source_adapter_import", name)
            elif any(
                name == prefix or name.startswith(prefix + ".") for prefix in _WAREHOUSE_MODULES
            ):
                self._add_hit(node, "warehouse_import", name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        for alias in node.names:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name
            imported = f"{module}.{alias.name}".lstrip(".")
            self.imports[bound] = imported
            first = imported.split(".")[0]
            if first in _SOURCE_MODULES:
                self._add_hit(node, "source_sdk_import", imported)
            elif any(
                imported == prefix or imported.startswith(prefix + ".")
                for prefix in _SOURCE_ADAPTER_MODULES
            ):
                self._add_hit(node, "source_adapter_import", imported)
            elif any(
                imported == prefix or imported.startswith(prefix + ".")
                for prefix in _WAREHOUSE_MODULES
            ):
                self._add_hit(node, "warehouse_import", imported)
            elif alias.name in _WAREHOUSE_NAMES:
                self._add_hit(node, "warehouse_import", imported)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.definitions.add(f"{self.module}::{'.'.join((*self.scope, node.name))}")
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualified = ".".join((*self.scope, node.name))
        self.definitions.add(f"{self.module}::{qualified}")
        if self.path.startswith("src/backend/app/api/") and any(
            "router." in ast.unparse(decorator) for decorator in node.decorator_list
        ):
            self.entries.add(f"{self.module}::{qualified}")
        self.scope.append(node.name)
        for child in node.body:
            self.visit(child)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        parts = _name_parts(node.func)
        raw = ".".join(parts)
        if parts:
            first = parts[0]
            resolved = self.imports.get(first)
            external = (
                f"{resolved}.{'.'.join(parts[1:])}" if resolved and len(parts) > 1 else resolved
            )
            source_name = external or raw
            source_root = source_name.split(".")[0]
            if source_root in _SOURCE_MODULES:
                self._add_hit(node, "source_sdk_call", source_name)
            if any(
                source_name == name or source_name.endswith(f".{name}") for name in _WAREHOUSE_NAMES
            ):
                self._add_hit(node, "warehouse_call", source_name)
            if source_name.endswith(("create_engine", "create_async_engine", "connect")) and any(
                token in source_name for token in ("mysql", "pymysql", "psycopg", "sqlite3")
            ):
                self._add_hit(node, "warehouse_connection", source_name)
            target = self._resolve_call_target(parts)
            if target:
                self.calls.append((self._scope_name(), target, node.lineno))
        if raw.endswith(
            ("read_csv", "read_parquet", "read_feather", "to_csv", "to_parquet", "to_feather")
        ):
            self._add_hit(node, "shared_file_io", raw)
        if raw.endswith(("connect",)) and parts and parts[0] in {"sqlite3", "duckdb"}:
            self._add_hit(node, "warehouse_connection", raw)
        self.generic_visit(node)

    def _resolve_call_target(self, parts: tuple[str, ...]) -> str | None:
        first = parts[0]
        imported = self.imports.get(first)
        if imported:
            return f"{imported}.{'.'.join(parts[1:])}" if len(parts) > 1 else imported
        if len(parts) == 1:
            return f"{self.module}.{first}"
        # Resolve self.method() to a method in the current class only.
        if len(parts) == 2 and first in {"self", "cls"}:
            class_scopes = self.scope[:-1]
            if class_scopes:
                return f"{self.module}.{'.'.join((*class_scopes, parts[1]))}"
        return None

    def visit_Constant(self, node: ast.Constant) -> None:
        value = node.value
        if isinstance(value, str):
            normalized = value.strip()
            suffix = Path(normalized.split("?", 1)[0]).suffix.lower()
            if suffix in _FILE_SUFFIXES and _DATA_PATH_PATTERN.search(normalized):
                self._add_hit(node, "shared_file_path", normalized)


def _iter_source_files(root: Path) -> Iterable[Path]:
    roots = (root / "src/backend/app", root / "src/backend/scripts")
    for source_root in roots:
        if not source_root.is_dir():
            continue
        yield from sorted(
            path
            for path in source_root.rglob("*.py")
            if "__pycache__" not in path.parts
            and ".venv" not in path.parts
            and "site-packages" not in path.parts
        )


def scan_repository(root: str | Path) -> ScanResult:
    """Scan AFI backend application and operational scripts without importing them."""
    base = Path(root).resolve()
    files = tuple(_iter_source_files(base))
    hits: list[BoundaryHit] = []
    edges: list[CallEdge] = []
    entries: set[str] = set()
    parse_errors: list[str] = []
    definitions_by_module: dict[str, set[str]] = defaultdict(set)
    analyzers: list[_ModuleAnalyzer] = []
    for path in files:
        relative = path.relative_to(base).as_posix()
        source_root = base / "src/backend"
        module = _module_name(path, source_root)
        role = _role(relative)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative)
        except (OSError, UnicodeError, SyntaxError) as exc:
            parse_errors.append(
                f"{relative}:{getattr(exc, 'lineno', '?')}:{exc.__class__.__name__}"
            )
            continue
        analyzer = _ModuleAnalyzer(path=relative, module=module, role=role)
        analyzer.visit(tree)
        analyzers.append(analyzer)
        hits.extend(analyzer.hits)
        entries.update(analyzer.entries)
        definitions_by_module[module].update(analyzer.definitions)

    all_definitions = (
        set().union(*definitions_by_module.values()) if definitions_by_module else set()
    )
    dotted_definitions = {
        definition.replace("::", "."): definition for definition in all_definitions
    }
    for analyzer in analyzers:
        for caller, target, line in analyzer.calls:
            definition = dotted_definitions.get(target)
            if definition is not None:
                edges.append(
                    CallEdge(caller=caller, callee=definition, path=analyzer.path, line=line)
                )

    sink_scopes = {
        hit.scope
        for hit in hits
        if hit.category
        in {"source_sdk_call", "warehouse_call", "warehouse_connection", "shared_file_io"}
    }
    outgoing: dict[str, set[str]] = defaultdict(set)
    reverse: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        outgoing[edge.caller].add(edge.callee)
        reverse[edge.callee].add(edge.caller)
    source_reachable = set(sink_scopes)
    queue: deque[str] = deque(sink_scopes)
    while queue:
        node = queue.popleft()
        for caller in reverse.get(node, ()):
            if caller not in source_reachable:
                source_reachable.add(caller)
                queue.append(caller)
    reaching_entries = tuple(sorted(entries.intersection(source_reachable)))
    normalized_hits = tuple(
        sorted(hits, key=lambda hit: (hit.path, hit.line, hit.category, hit.expression))
    )
    normalized_edges = tuple(
        sorted(edges, key=lambda edge: (edge.path, edge.line, edge.caller, edge.callee))
    )
    return ScanResult(
        root=str(base),
        python_files=len(files),
        parse_errors=tuple(sorted(parse_errors)),
        hits=normalized_hits,
        edges=normalized_edges,
        entrypoints=tuple(sorted(entries)),
        source_reachable_entrypoints=reaching_entries,
    )


def render_markdown(result: ScanResult, *, label: str) -> str:
    """Render a human-readable, reproducible boundary report."""
    summary = result.summary()
    lines = [
        f"### {label}",
        "",
        f"- Scan root: `{result.root}`",
        f"- Python files parsed: **{result.python_files}**; parse errors: **{len(result.parse_errors)}**.",
        f"- Findings: **{summary['hit_count']}** across **{summary['files_with_findings']}** files.",
        f"- Statically resolvable call edges: **{len(result.edges)}**; API entrypoints: **{len(result.entrypoints)}**; entrypoints reaching a direct source/database/file sink: **{len(result.source_reachable_entrypoints)}**.",
        "",
        "| Finding class | Count |",
        "| --- | ---: |",
    ]
    for category, count in summary["category_counts"].items():
        lines.append(f"| `{category}` | {count} |")
    lines.extend(["", "| Role | Finding count |", "| --- | ---: |"])
    for role, count in summary["role_counts"].items():
        lines.append(f"| `{role}` | {count} |")
    lines.extend(["", "#### Finding files", "", "| Path | Categories |", "| --- | --- |"])
    for path, counts in summary["findings_by_file"].items():
        counts_text = ", ".join(f"`{name}` × {count}" for name, count in counts.items())
        lines.append(f"| `{path}` | {counts_text} |")
    lines.extend(
        [
            "",
            "#### Direct finding details",
            "",
            "| Path:line | Category | Scope | Expression | Role |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for hit in result.hits:
        expression = hit.expression.replace("|", "\\|").replace("`", "\\`")
        lines.append(
            f"| `{hit.path}:{hit.line}` | `{hit.category}` | `{hit.scope}` | `{expression}` | `{hit.role}` |"
        )
    if result.parse_errors:
        lines.extend(["", "#### Parse errors", ""])
        lines.extend(f"- `{item}`" for item in result.parse_errors)
    lines.extend(
        [
            "",
            "Call edges use local definitions and explicit imports only. Provider dispatch through protocols, decorators, dependency injection, runtime configuration, dynamically built SQL, and computed file paths cannot be proven statically; absent hits do not establish absence of a bypass.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="AFI repository checkout to scan read-only")
    parser.add_argument("--label", default="AFI checkout", help="Report heading label")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    arguments = parser.parse_args()
    result = scan_repository(arguments.root)
    if arguments.format == "json":
        sys.stdout.write(
            json.dumps(
                {
                    "summary": result.summary(),
                    "hits": [asdict(hit) for hit in result.hits],
                    "edges": [asdict(edge) for edge in result.edges],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    else:
        sys.stdout.write(render_markdown(result, label=arguments.label) + "\n")


if __name__ == "__main__":
    main()


__all__ = ["BoundaryHit", "CallEdge", "ScanResult", "render_markdown", "scan_repository"]
