#!/usr/bin/env python3
"""Fail-closed checks for backend dependency sources and canonical locks.

Run from any directory with:
    python scripts/ci/check_deps_sync.py

The legacy ``src/backend/requirements.txt`` is a marker-aware PEP 508 projection
of core dependencies and the production extras. It must not forward to a
Python-version-specific lock file.
"""

from __future__ import annotations

import re
import shlex
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

try:
    import tomllib as toml_module
except ModuleNotFoundError:  # Python 3.10
    try:
        import tomli as toml_module
    except ModuleNotFoundError:
        toml_module = None

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = PROJECT_ROOT / "src" / "backend" / "pyproject.toml"
REQUIREMENTS = PROJECT_ROOT / "src" / "backend" / "requirements.txt"
PRODUCTION_LOCK = PROJECT_ROOT / "config" / "requirements-prod.lock"
PRODUCTION_EXTRAS = ("prod", "postgres", "mysql", "redis", "backtrader", "data")

# Core runtime deps that must remain in pyproject.toml [project.dependencies].
REQUIRED_DEPS = {
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic-settings",
    "slowapi",
    "sqlalchemy",
    "aiosqlite",
    "PyJWT",
    "PyMySQL",
    "passlib",
    "loguru",
    "python-multipart",
    "PyYAML",
    "fincore",
}

RequirementKey = tuple[str, tuple[str, ...], str, str, str]


class DependencySyncError(ValueError):
    """Raised when a dependency manifest cannot be parsed safely."""


def parse_pyproject_requirements(
    path: Path = PYPROJECT,
    *,
    extras: Sequence[str] = (),
) -> list[Requirement]:
    """Read core runtime requirements and selected optional dependency groups."""
    if toml_module is None:
        raise DependencySyncError(
            "TOML parsing requires tomli when running under Python 3.10"
        )
    if not path.is_file():
        raise DependencySyncError(f"pyproject.toml not found: {path}")

    try:
        document = toml_module.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DependencySyncError(f"cannot parse {path}: {exc}") from exc

    project = document.get("project")
    if not isinstance(project, dict):
        raise DependencySyncError(f"[project] table missing in {path}")
    raw_requirements = project.get("dependencies")
    if not isinstance(raw_requirements, list) or not raw_requirements:
        raise DependencySyncError(
            f"[project].dependencies must be a non-empty array in {path}"
        )

    requirements: list[Requirement] = []
    requirement_groups: list[tuple[str, list[object]]] = [
        ("[project].dependencies", raw_requirements)
    ]
    if extras:
        optional_dependencies = project.get("optional-dependencies")
        if not isinstance(optional_dependencies, dict):
            raise DependencySyncError(
                f"[project.optional-dependencies] table missing in {path}"
            )
        for extra in extras:
            extra_requirements = optional_dependencies.get(extra)
            if not isinstance(extra_requirements, list) or not extra_requirements:
                raise DependencySyncError(
                    f"[project.optional-dependencies].{extra} must be a non-empty "
                    f"array in {path}"
                )
            requirement_groups.append(
                (f"[project.optional-dependencies].{extra}", extra_requirements)
            )

    for group, group_requirements in requirement_groups:
        for index, raw_requirement in enumerate(group_requirements, start=1):
            if not isinstance(raw_requirement, str):
                raise DependencySyncError(
                    f"dependency #{index} in {group} in {path} is not a requirement string"
                )
            try:
                requirements.append(Requirement(raw_requirement))
            except InvalidRequirement as exc:
                raise DependencySyncError(
                    f"invalid dependency #{index} in {group} in {path}: "
                    f"{raw_requirement!r}"
                ) from exc
    return requirements


def _requirement_include(line: str, source: Path, line_number: int) -> str | None:
    """Return a recursive -r target, or reject unsupported requirement options."""
    try:
        tokens = shlex.split(line)
    except ValueError as exc:
        raise DependencySyncError(
            f"invalid include at {source}:{line_number}: {exc}"
        ) from exc
    if not tokens:
        return None

    first = tokens[0]
    if first in {"-r", "--requirement"}:
        if len(tokens) != 2:
            raise DependencySyncError(
                f"expected one include path at {source}:{line_number}: {line}"
            )
        return tokens[1]
    if first.startswith("--requirement="):
        if len(tokens) != 1 or not first.partition("=")[2]:
            raise DependencySyncError(
                f"invalid include at {source}:{line_number}: {line}"
            )
        return first.partition("=")[2]
    if first.startswith("-r="):
        if len(tokens) != 1 or not first[3:]:
            raise DependencySyncError(
                f"invalid include at {source}:{line_number}: {line}"
            )
        return first[3:]
    if first.startswith("-r") and first != "-r":
        if len(tokens) != 1 or not first[2:]:
            raise DependencySyncError(
                f"invalid include at {source}:{line_number}: {line}"
            )
        return first[2:]
    if first.startswith("-"):
        raise DependencySyncError(
            f"unsupported requirements option at {source}:{line_number}: {line}"
        )
    return None


def parse_requirements_file(
    path: Path,
    *,
    included_files: set[Path] | None = None,
) -> list[Requirement]:
    """Recursively parse requirement files, resolving includes beside each file."""
    return _parse_requirements_file(path, (), included_files)


def _parse_requirements_file(
    path: Path,
    include_stack: tuple[Path, ...],
    included_files: set[Path] | None,
) -> list[Requirement]:
    resolved_path = path.resolve()
    if resolved_path in include_stack:
        cycle = " -> ".join(str(item) for item in (*include_stack, resolved_path))
        raise DependencySyncError(f"recursive requirements include cycle: {cycle}")
    if not resolved_path.is_file():
        raise DependencySyncError(f"requirements file not found: {resolved_path}")

    requirements: list[Requirement] = []
    try:
        lines = resolved_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DependencySyncError(
            f"cannot read requirements file {resolved_path}: {exc}"
        ) from exc

    current_stack = (*include_stack, resolved_path)
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.split(" #", 1)[0].strip()
        if not line or line.startswith(("--hash=", "--hash ")):
            continue

        include = _requirement_include(line, resolved_path, line_number)
        if include is not None:
            include_path = Path(include)
            if not include_path.is_absolute():
                include_path = resolved_path.parent / include_path
            include_path = include_path.resolve()
            if included_files is not None:
                included_files.add(include_path)
            requirements.extend(
                _parse_requirements_file(include_path, current_stack, included_files)
            )
            continue

        try:
            requirements.append(Requirement(line))
        except InvalidRequirement as exc:
            raise DependencySyncError(
                f"invalid requirement at {resolved_path}:{line_number}: {line!r}"
            ) from exc
    return requirements


def lock_environment(lock_path: Path) -> dict[str, str]:
    """Build marker environment using the Python version recorded in the lock header."""
    try:
        header = "\n".join(lock_path.read_text(encoding="utf-8").splitlines()[:8])
    except OSError as exc:
        raise DependencySyncError(
            f"cannot read production lock {lock_path}: {exc}"
        ) from exc
    match = re.search(r"--python-version(?:=|\s+)(\d+\.\d+(?:\.\d+)?)", header)
    if match is None:
        raise DependencySyncError(
            f"production lock has no --python-version header: {lock_path}"
        )

    version = match.group(1)
    parts = version.split(".")
    environment = default_environment()
    environment["python_version"] = ".".join(parts[:2])
    environment["python_full_version"] = version if len(parts) == 3 else f"{version}.0"
    return environment


def _exact_locked_version(requirement: Requirement) -> Version | None:
    """Return a concrete PEP 440 pin, rejecting ranges and wildcards."""
    if requirement.url is not None:
        return None
    specifiers = list(requirement.specifier)
    if len(specifiers) != 1:
        return None
    specifier = specifiers[0]
    if specifier.operator not in {"==", "==="} or specifier.version.endswith(".*"):
        return None
    try:
        return Version(specifier.version)
    except InvalidVersion:
        return None


def compare_direct_dependencies(
    source_requirements: Sequence[Requirement],
    locked_requirements: Sequence[Requirement],
    environment: Mapping[str, str],
) -> list[str]:
    """Check direct pyproject requirements against active, exact lock pins."""
    locked_by_name: dict[str, list[Requirement]] = defaultdict(list)
    for locked in locked_requirements:
        locked_by_name[canonicalize_name(locked.name)].append(locked)

    errors: list[str] = []
    for source in source_requirements:
        if source.marker is not None and not source.marker.evaluate(
            environment=dict(environment)
        ):
            continue

        name = canonicalize_name(source.name)
        candidates = [
            locked
            for locked in locked_by_name.get(name, [])
            if locked.marker is None
            or locked.marker.evaluate(environment=dict(environment))
        ]
        if not candidates:
            errors.append(f"{source.name}: missing from canonical production lock")
            continue
        if len(candidates) != 1:
            errors.append(
                f"{source.name}: expected one active lock entry, found {len(candidates)}"
            )
            continue

        locked = candidates[0]
        if source.url is not None:
            if locked.url != source.url:
                errors.append(
                    f"{source.name}: locked direct URL does not match pyproject"
                )
            continue
        if locked.url is not None:
            errors.append(
                f"{source.name}: canonical production lock entry is not version-pinned"
            )
            continue

        version = _exact_locked_version(locked)
        if version is None:
            errors.append(
                f"{source.name}: canonical production lock entry is not exactly pinned"
            )
            continue
        if not source.specifier.contains(version, prereleases=True):
            errors.append(
                f"{source.name}: locked version {version} does not satisfy {source.specifier}"
            )
    return errors


def _requirement_key(requirement: Requirement) -> RequirementKey:
    """Return a canonical key for semantic wrapper-versus-lock comparison."""
    return (
        canonicalize_name(requirement.name),
        tuple(sorted(canonicalize_name(extra) for extra in requirement.extras)),
        requirement.url or "",
        str(requirement.specifier),
        str(requirement.marker) if requirement.marker is not None else "",
    )


def _format_requirement_key(key: RequirementKey) -> str:
    name, extras, url, specifier, marker = key
    formatted_name = name + (f"[{','.join(extras)}]" if extras else "")
    target = f" @ {url}" if url else specifier
    suffix = f" ; {marker}" if marker else ""
    return f"{formatted_name}{target}{suffix}"


def check_sync(
    pyproject_path: Path = PYPROJECT,
    production_lock_path: Path = PRODUCTION_LOCK,
    legacy_requirements_path: Path = REQUIREMENTS,
) -> list[str]:
    """Return errors when core/prod dependencies, lock, or compatibility list drift."""
    try:
        core_requirements = parse_pyproject_requirements(pyproject_path)
        source_requirements = parse_pyproject_requirements(
            pyproject_path,
            extras=PRODUCTION_EXTRAS,
        )
        core_names = {
            canonicalize_name(requirement.name) for requirement in core_requirements
        }
        required_names = {canonicalize_name(name) for name in REQUIRED_DEPS}
        missing_required = sorted(required_names - core_names)
        if missing_required:
            return [
                "required runtime dependencies missing from pyproject.toml: "
                + ", ".join(missing_required)
            ]

        production_requirements = parse_requirements_file(production_lock_path)
        if not production_requirements:
            raise DependencySyncError(
                f"canonical production lock has no requirements: {production_lock_path}"
            )
        environment = lock_environment(production_lock_path)
        errors = compare_direct_dependencies(
            source_requirements, production_requirements, environment
        )

        included_files: set[Path] = set()
        legacy_requirements = parse_requirements_file(
            legacy_requirements_path,
            included_files=included_files,
        )
        if included_files:
            included_paths = ", ".join(
                str(path) for path in sorted(included_files)
            )
            errors.append(
                "legacy requirements.txt must contain direct PEP 508 requirements, "
                f"not recursive includes: {included_paths}"
            )

        source_counter = Counter(_requirement_key(req) for req in source_requirements)
        legacy_counter = Counter(
            _requirement_key(req) for req in legacy_requirements
        )
        extra_entries = legacy_counter - source_counter
        missing_entries = source_counter - legacy_counter
        if extra_entries or missing_entries:
            if extra_entries:
                entries = ", ".join(
                    _format_requirement_key(key) for key in sorted(extra_entries)
                )
                errors.append(
                    f"legacy requirements.txt has undeclared dependencies: {entries}"
                )
            if missing_entries:
                entries = ", ".join(
                    _format_requirement_key(key) for key in sorted(missing_entries)
                )
                errors.append(
                    f"legacy requirements.txt omits pyproject dependencies: {entries}"
                )
        return errors
    except DependencySyncError as exc:
        return [str(exc)]


def main() -> int:
    """Fail CI when production dependency sources or compatibility input drift."""
    errors = check_sync()
    if errors:
        print("ERROR: dependency synchronization failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        "OK: pyproject runtime dependencies and production extras satisfy the "
        "canonical lock; requirements.txt matches the marker-aware PEP 508 source list."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
