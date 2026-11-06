"""Report whether this process's runtime environment is the environment CI validated.

WHY THIS EXISTS
    The deployed unit runs ``.venv/bin/python scripts/ops/run_with_core_environment.py ...`` with
    ``TZ=Asia/Shanghai``, but that venv came from ``python3 -m venv --system-site-packages`` on an
    Anaconda interpreter and its own ``site-packages`` holds a couple of dozen distributions, so
    ``sys.path`` falls through to the user site and the base distribution: ``import akshare`` can
    land on an unmanaged source checkout whose ``__version__`` sits below the constraint the
    project declares, while CI only ever runs its own Python matrix.  Evidence produced on the
    host (collection success, row counts, import behaviour) is therefore measured against a
    dependency set nobody validated.  Iteration 204 AC12 requires package/environment/library
    identity to be established *before* a migration or cutover step, and the sibling
    ``scripts/ops/check_service_runtime_assets.py`` proves files exist but says nothing about which
    package version is importable.  This checker closes that gap and refuses closed.

WHAT IT READS
    ``config/requirements-dev.lock`` and the requirement tables of ``src/backend/pyproject.toml``
    (the comparison source of truth -- parsed, never hand-copied), the Python matrix of
    ``.github/workflows/ci.yml``, the declared collection scheduler timezone in
    ``src/backend/app/config.py``, the active venv's ``pyvenv.cfg`` plus its own ``site-packages``
    listing, and this interpreter's ``sys.version`` and loaded module objects.  Environment
    variables are read through one allowlist (``TZ``) plus a scan used only to build a strip-list.

WHAT IT REPORTS
    One sanitized JSON payload with explicit ``expected`` versus ``observed`` for: the interpreter
    against the CI matrix; venv isolation (``include-system-site-packages``, the creating command
    when recoverable, the distribution count inside the venv's own ``site-packages``); every
    collection-relevant pinned dependency (imported ``__version__``, resolved module path, whether
    that path lives inside the venv, and the lock's pinned value); and the timezone/UTC offset the
    process actually sees.

REFUSAL REASONS (each is a named reason, never a warning)
    Every entry of ``REFUSAL_REASONS`` below: interpreter, venv isolation, unpinned /
    outside-venv / out-of-constraint / not-importable / unparsable-version, timezone, and
    ``identity_source_unreadable`` for the sources of truth themselves.

NO SECRETS, EVER
    ``redact_secrets`` strips DSN userinfo, credential-shaped ``KEY=value`` assignments and every
    token collected from the environment, applied to each string leaf before serialization.  Guard
    failures repr ``argv`` and ``python -m venv ...`` command lines / DSNs appear in the files this
    checker reads, so no environment value is ever placed in the payload verbatim.

EXIT CODES
    ``0`` when every check matches, ``2`` when any named refusal fired (argparse also exits
    ``2`` on a malformed command line, which the payload then never reaches).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import site
import sys
import sysconfig
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:  # tomllib is stdlib from 3.11; the CI matrix and this host are both >=3.11.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on Python 3.10
    tomllib = None  # type: ignore[assignment]

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_ROOT.parents[1]

DEFAULT_LOCK_PATH = _REPO_ROOT / "config" / "requirements-dev.lock"
DEFAULT_PYPROJECT_PATH = _BACKEND_ROOT / "pyproject.toml"
DEFAULT_CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEFAULT_APP_CONFIG_PATH = _BACKEND_ROOT / "app" / "config.py"

PAYLOAD_SCHEMA = "afi-runtime-environment-identity/v1"
_REFUSAL_EXIT_CODE = 2
_MAX_MESSAGE_CHARS = 300
_REDACTION = "<redacted>"

#: The only environment keys whose values may reach the payload.  Everything else is read
#: solely to build the strip-list and is never echoed.
ENVIRONMENT_KEYS_ECHOED: frozenset[str] = frozenset({"TZ"})

#: pyproject requirement groups whose members the akshare/data-fetch collection plane imports.
COLLECTION_REQUIREMENT_GROUPS: tuple[str, ...] = ("data", "backtrader")

#: Core ``[project.dependencies]`` members that the collection plane also imports.  These are
#: NAMES only; every version/constraint used for comparison is parsed from the lock/pyproject.
COLLECTION_CORE_DISTRIBUTIONS: tuple[str, ...] = (
    "sqlalchemy",
    "apscheduler",
    "pydantic",
    "httpx",
    "pymysql",
    "pyyaml",
    "loguru",
    "python-multipart",
)

#: Distributions whose import name differs from the distribution name.
IMPORT_NAME_OVERRIDES: Mapping[str, str] = {
    "beautifulsoup4": "bs4",
    "mysql-connector-python": "mysql.connector",
    "pillow": "PIL",
    "pyyaml": "yaml",
    "python-multipart": "multipart",
    "python-dateutil": "dateutil",
    "pydantic-settings": "pydantic_settings",
}

REASON_INTERPRETER_OUTSIDE_MATRIX = "interpreter_version_outside_ci_matrix"
REASON_VIRTUAL_ENVIRONMENT_ABSENT = "virtual_environment_absent"
REASON_PYVENV_CFG_MISSING = "pyvenv_cfg_missing"
REASON_SYSTEM_SITE_PACKAGES = "venv_allows_system_site_packages"
REASON_DEPENDENCY_UNPINNED = "dependency_unpinned_in_lock"
REASON_DEPENDENCY_OUTSIDE_VENV = "dependency_resolves_outside_venv"
REASON_VERSION_OUTSIDE_CONSTRAINT = "dependency_version_outside_declared_constraint"
REASON_VERSION_DIFFERS_FROM_LOCK = "dependency_version_differs_from_lock_pin"
REASON_DEPENDENCY_NOT_IMPORTABLE = "collection_dependency_not_importable"
REASON_VERSION_UNPARSABLE = "version_string_unparsable"
REASON_TIMEZONE_MISMATCH = "timezone_differs_from_declared_expectation"
REASON_SOURCE_UNREADABLE = "identity_source_unreadable"

REFUSAL_REASONS: frozenset[str] = frozenset(
    {
        REASON_INTERPRETER_OUTSIDE_MATRIX,
        REASON_VIRTUAL_ENVIRONMENT_ABSENT,
        REASON_PYVENV_CFG_MISSING,
        REASON_SYSTEM_SITE_PACKAGES,
        REASON_DEPENDENCY_UNPINNED,
        REASON_DEPENDENCY_OUTSIDE_VENV,
        REASON_VERSION_OUTSIDE_CONSTRAINT,
        REASON_VERSION_DIFFERS_FROM_LOCK,
        REASON_DEPENDENCY_NOT_IMPORTABLE,
        REASON_VERSION_UNPARSABLE,
        REASON_TIMEZONE_MISMATCH,
        REASON_SOURCE_UNREADABLE,
    }
)

# A credentialed URL loses everything after its scheme: userinfo, host, port and database name.
# The userinfo may not contain "/" so a git direct reference (``git+https://host/repo@sha``),
# which is evidence rather than a credential, survives untouched.
_URL_USERINFO_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)(?:[^\s/@]*:)?[^\s/@]*@[^\s\"']*")
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([a-z0-9_]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|"
    r"accesskey|credential|dsn)[a-z0-9_]*)\s*[=:]\s*[^\s,;]+"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/-]{12,}")
_LOCK_PIN_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^#\s;]+)")
_LOCK_URL_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*@\s*(\S+)")
_CI_MATRIX_RE = re.compile(r"""^\s*python-version:\s*\[([^\]]*)\]""")
_CI_MATRIX_ITEM_RE = re.compile(r"""["']?(\d+\.\d+)["']?""")
_TIMEZONE_DEFAULT_RE = re.compile(
    r"(?P<name>AKSHARE_SCHEDULER_TIMEZONE|MARKET_DATA_THS_SCHEDULER_TIMEZONE"
    r"|STOCK_SIGNAL_SCHEDULE_TIMEZONE)\s*:\s*str\s*=\s*Field\(\s*default=\"(?P<tz>[^\"]+)\""
)
_VERSION_PREFIX_RE = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")


def normalize_distribution(name: str) -> str:
    """Return the PEP 503 style lookup key for a distribution name."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def import_name_for(distribution: str) -> str:
    """Best-effort import module name for a normalized distribution name."""
    override = IMPORT_NAME_OVERRIDES.get(distribution)
    if override:
        return override
    return re.sub(r"[-.]+", "_", distribution)


def redact_secrets(text: object, secrets: Iterable[str] = ()) -> str:
    """Strip credential material from arbitrary text (DSNs, argv reprs, driver errors).

    Any ``scheme://...`` URL substring loses its userinfo, every known secret token and
    credential-shaped ``KEY=value`` assignment is replaced, and the result is bounded.
    """
    message = " ".join(str(text).split())
    for token in sorted((str(item) for item in secrets), key=len, reverse=True):
        if len(token) >= 3:
            message = message.replace(token, _REDACTION)
    message = _URL_USERINFO_RE.sub(rf"\1{_REDACTION}", message)
    # Bearer-style tokens first: the assignment rule would otherwise stop at the space and
    # leave the token itself behind.
    message = _BEARER_RE.sub(rf"\1{_REDACTION}", message)
    message = _CREDENTIAL_ASSIGNMENT_RE.sub(rf"\1={_REDACTION}", message)
    if len(message) > _MAX_MESSAGE_CHARS:
        message = message[:_MAX_MESSAGE_CHARS] + "..."
    return message or _REDACTION


_SECRET_ENV_KEY_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key|credential|dsn)"
)


def _environment_secret_tokens(environ: Mapping[str, str]) -> tuple[str, ...]:
    """Collect credential-looking environment values as strip tokens; they are never echoed."""
    tokens: list[str] = []
    for key, value in environ.items():
        if not value:
            continue
        if _SECRET_ENV_KEY_RE.search(key) or "://" in value:
            tokens.append(value)
            try:
                parts = urlsplit(value)
            except ValueError:
                continue
            tokens.extend(
                str(item) for item in (parts.password, parts.username, parts.netloc) if item
            )
    return tuple(dict.fromkeys(tokens))


@dataclass(frozen=True)
class LockPin:
    """One parsed ``config/requirements-dev.lock`` entry (a version pin or a direct URL)."""

    distribution: str
    version: str | None
    direct_url: str | None


def parse_lock(text: str) -> dict[str, LockPin]:
    """Parse the uv-style dev lock into ``{normalized name: LockPin}``.

    Handles ``name==1.2.3`` pins and ``name @ url`` direct references and skips the ``# via``
    comment continuation lines, so no version string is ever hand-copied into this checker.
    """
    pins: dict[str, LockPin] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        pin_match = _LOCK_PIN_RE.match(line)
        if pin_match:
            name = normalize_distribution(pin_match.group(1))
            pins[name] = LockPin(distribution=name, version=pin_match.group(2), direct_url=None)
            continue
        url_match = _LOCK_URL_RE.match(line)
        if url_match:
            name = normalize_distribution(url_match.group(1))
            pins[name] = LockPin(
                distribution=name,
                version=None,
                direct_url=redact_secrets(url_match.group(2)),
            )
    return pins


@dataclass(frozen=True)
class DeclaredRequirement:
    """One parsed pyproject requirement: the constraint actually declared for a dist."""

    distribution: str
    specifier: str
    marker: str | None


def _split_requirement(entry: str) -> DeclaredRequirement | None:
    """Split one PEP 508 requirement string into distribution, specifier and marker.

    tomllib has already unquoted the array element, so only the enclosing pair (if any) is
    removed: stripping quote characters blindly would eat the closing quote of a marker.
    """
    text = entry.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    if not text:
        return None
    marker: str | None = None
    if ";" in text:
        text, marker = text.split(";", 1)
        marker = marker.strip() or None
    direct = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*@\s*(\S+)$", text.strip())
    if direct:
        return DeclaredRequirement(normalize_distribution(direct.group(1)), "", marker)
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*\s*(?:\[[^\]]*\])?)\s*(.*)$", text.strip())
    if not match:
        return None
    name = re.sub(r"\s*\[[^\]]*\]", "", match.group(1))
    return DeclaredRequirement(normalize_distribution(name), match.group(2).strip(), marker)


def _requirement_strings(table: Any) -> list[str]:
    """Collect requirement strings from a tomllib table, tolerating non-string entries."""
    values: list[str] = []
    if isinstance(table, str):
        return [table]
    if isinstance(table, (list, tuple)):
        for item in table:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str):
                    values.append(name)
    return values


def parse_pyproject_requirements(
    toml_tables: Mapping[str, Any],
    *,
    extra_groups: Sequence[str] = COLLECTION_REQUIREMENT_GROUPS,
    core_names: Sequence[str] = COLLECTION_CORE_DISTRIBUTIONS,
) -> dict[str, list[DeclaredRequirement]]:
    """Parse the declared constraints for the collection-relevant distributions.

    ``extra_groups`` members are all included by name (read from the file, not hard-coded) and
    ``core_names`` selects which ``[project.dependencies]`` entries matter; both keep the file's
    constraint strings and markers, and marker-qualified siblings are retained so the applicable
    one can be selected per interpreter.
    """
    project = toml_tables.get("project") or {}
    wanted = {normalize_distribution(name) for name in core_names}
    grouped: dict[str, list[DeclaredRequirement]] = {}

    for entry in _requirement_strings(project.get("dependencies") or []):
        requirement = _split_requirement(entry)
        if requirement is not None and requirement.distribution in wanted:
            grouped.setdefault(requirement.distribution, []).append(requirement)

    optional = project.get("optional-dependencies") or {}
    for group in extra_groups:
        for entry in _requirement_strings(optional.get(group) or []):
            requirement = _split_requirement(entry)
            if requirement is not None:
                grouped.setdefault(requirement.distribution, []).append(requirement)
    return grouped


_PYTHON_VERSION_MARKER_RE = re.compile(
    r"""python_version\s*(<=|>=|==|!=|<|>)\s*["'](\d+\.\d+)["']"""
)


def marker_matches(marker: str | None, *, python_version: str) -> bool:
    """Evaluate the ``python_version`` clauses of a PEP 508 marker.

    Non-``python_version`` clauses (platform, extras) are treated as satisfied: this checker
    only ever runs inside the environment whose interpreter it is reporting.
    """
    if not marker:
        return True
    clauses = _PYTHON_VERSION_MARKER_RE.findall(marker)
    if not clauses:
        return True
    observed = parse_version_tuple(python_version)
    if observed is None:
        return False
    for operator, target_text in clauses:
        target = parse_version_tuple(target_text)
        if target is None:
            return False
        if not _OPERATOR_OUTCOMES[operator](_compare_versions(observed, target)):
            return False
    return True


def applicable_requirement(
    requirements: Mapping[str, Sequence[DeclaredRequirement]],
    distribution: str,
    *,
    python_version: str,
) -> DeclaredRequirement | None:
    """Return the declared constraint whose marker matches this interpreter."""
    matches = [
        requirement
        for requirement in requirements.get(distribution, ())
        if marker_matches(requirement.marker, python_version=python_version)
    ]
    if not matches:
        return None
    return matches[-1]


def parse_ci_python_matrix(text: str) -> tuple[str, ...]:
    """Return the CI test-matrix Python versions declared in ``.github/workflows/ci.yml``."""
    versions: list[str] = []
    for line in text.splitlines():
        match = _CI_MATRIX_RE.search(line)
        if not match:
            continue
        for item in _CI_MATRIX_ITEM_RE.findall(match.group(1)):
            if item not in versions:
                versions.append(item)
    return tuple(versions)


def parse_declared_timezone(text: str) -> str | None:
    """Return the collection scheduler timezone the application declares as its default."""
    match = _TIMEZONE_DEFAULT_RE.search(text)
    return match.group("tz") if match else None


def parse_version_tuple(version: str | None) -> tuple[int, ...] | None:
    """Parse a leading numeric release, e.g. ``1.18.97.post0`` -> ``(1, 18, 97)``.

    Pre-release/local suffixes are not modelled; an unparsable string returns ``None`` and the
    caller records a named refusal rather than guessing.
    """
    if not version:
        return None
    match = _VERSION_PREFIX_RE.match(version)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _compare_versions(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    """Return -1/0/1 comparing two numeric release tuples of different length."""
    width = max(len(left), len(right))
    padded_left = left + (0,) * (width - len(left))
    padded_right = right + (0,) * (width - len(right))
    if padded_left < padded_right:
        return -1
    if padded_left > padded_right:
        return 1
    return 0


_SPECIFIER_RE = re.compile(r"(>=|<=|==|!=|~=|>|<)\s*v?([0-9][0-9A-Za-z._+-]*)")


def satisfies_specifier(version: str | None, specifier: str | None) -> bool | None:
    """Evaluate a PEP 440 subset; ``None`` means "undecidable", so the caller refuses."""
    if not specifier or not specifier.strip():
        return None
    observed = parse_version_tuple(version)
    if observed is None:
        return None
    for clause in (item.strip() for item in specifier.split(",") if item.strip()):
        match = _SPECIFIER_RE.match(clause)
        if not match:
            return None
        operator, target = match.group(1), parse_version_tuple(match.group(2))
        if target is None:
            return None
        comparison = _compare_versions(observed, target)
        if operator == "~=":  # compatible release: same major, not lower than the target.
            passed = comparison >= 0 and observed[:1] == target[:1]
        else:
            passed = _OPERATOR_OUTCOMES[operator](comparison)
        if not passed:
            return False
    return True


_OPERATOR_OUTCOMES: Mapping[str, Callable[[int], bool]] = {
    ">=": lambda comparison: comparison >= 0,
    ">": lambda comparison: comparison > 0,
    "<=": lambda comparison: comparison <= 0,
    "<": lambda comparison: comparison < 0,
    "==": lambda comparison: comparison == 0,
    "!=": lambda comparison: comparison != 0,
}


@dataclass(frozen=True)
class VenvIsolation:
    """Isolation facts about the virtual environment the process is actually running in."""

    running_in_venv: bool
    prefix: str
    base_prefix: str
    pyvenv_cfg_path: str | None
    include_system_site_packages: bool | None
    creating_command: str | None
    base_home: str | None
    recorded_version: str | None
    own_site_packages: str | None
    distribution_count: int

    def owns(self, path: str | None) -> bool | None:
        """True when a module file resolves inside the venv's own site-packages."""
        if not path or not self.own_site_packages:
            return None
        try:
            Path(path).resolve().relative_to(Path(self.own_site_packages).resolve())
        except (ValueError, OSError):
            return False
        return True

    def as_evidence(self) -> dict[str, Any]:
        return {
            "running_in_venv": self.running_in_venv,
            "prefix": redact_secrets(self.prefix),
            "base_prefix": redact_secrets(self.base_prefix),
            "pyvenv_cfg_path": redact_secrets(self.pyvenv_cfg_path or ""),
            "include_system_site_packages": self.include_system_site_packages,
            "creating_command": redact_secrets(self.creating_command or "") or None,
            "cfg_home": redact_secrets(self.base_home or "") or None,
            "cfg_version": self.recorded_version,
            "venv_site_packages": redact_secrets(self.own_site_packages or "") or None,
            "venv_distribution_count": self.distribution_count,
        }


def _pyvenv_cfg_values(text: str) -> dict[str, str]:
    """Parse ``pyvenv.cfg`` ``key = value`` lines, tolerating the spaceless ``key=value`` form."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            values[key.strip().lower()] = value.strip()
    return values


def _true_false(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in {"true", "1", "yes", "on"}


def inspect_venv(*, prefix: str, base_prefix: str, site_packages_dir: str) -> VenvIsolation:
    """Read the active venv's ``pyvenv.cfg`` and count distributions inside its site-packages."""
    running_in_venv = Path(prefix).resolve() != Path(base_prefix).resolve()
    cfg_path = Path(prefix) / "pyvenv.cfg"
    values: dict[str, str] = {}
    if cfg_path.is_file():
        try:
            values = _pyvenv_cfg_values(cfg_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            values = {}
    own_site = Path(site_packages_dir)
    entries = sorted(own_site.iterdir()) if own_site.is_dir() else []
    distribution_count = sum(
        1
        for entry in entries
        if (entry.name.endswith((".dist-info", ".egg-info")) and entry.is_dir())
        or (entry.name.endswith((".egg-link", ".pth")) and entry.is_file())
    )
    return VenvIsolation(
        running_in_venv=running_in_venv,
        prefix=prefix,
        base_prefix=base_prefix,
        pyvenv_cfg_path=str(cfg_path) if cfg_path.is_file() else None,
        include_system_site_packages=_true_false(values.get("include-system-site-packages")),
        creating_command=values.get("command"),
        base_home=values.get("home"),
        recorded_version=values.get("version"),
        own_site_packages=str(own_site),
        distribution_count=distribution_count,
    )


def _default_importer(module_name: str) -> Any:
    return importlib.import_module(module_name)


@dataclass(frozen=True)
class DependencyObservation:
    """Expected versus observed identity for one collection-relevant distribution."""

    distribution: str
    module: str
    lock_version: str | None
    lock_direct_url: str | None
    declared_specifier: str | None
    declared_marker: str | None = None
    observed_version: str | None = None
    module_path: str | None = None
    inside_venv: bool | None = None
    resolution_channel: str = "unknown"
    import_error: str | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def expected(self) -> dict[str, Any]:
        return {
            "lock_pin": self.lock_version,
            "lock_direct_url": self.lock_direct_url,
            "pyproject_constraint": self.declared_specifier,
            "pyproject_marker": self.declared_marker,
            "must_resolve_inside_venv": True,
        }

    @property
    def observed(self) -> dict[str, Any]:
        return {
            "imported_version": self.observed_version,
            "module_path": redact_secrets(self.module_path or "") or None,
            "inside_venv": self.inside_venv,
            "resolution_channel": self.resolution_channel,
            "import_error": redact_secrets(self.import_error or "") or None,
        }

    @property
    def refused(self) -> bool:
        return bool(self.reasons)


def classify_path_channel(path: str | None, venv: VenvIsolation) -> str:
    """Name the ``sys.path`` channel a module file resolved through.

    ``venv_site_packages`` is the only channel CI's evidence applies to; every other channel
    means the deployed process is importing something the validated environment never pinned.
    """
    if not path:
        return "namespace_or_builtin"
    if venv.owns(path):
        return "venv_site_packages"
    try:
        resolved = Path(path).resolve()
    except OSError:
        resolved = Path(path)
    for root in _sitepackage_roots():
        try:
            if _within(resolved, Path(root)):
                return "base_prefix_site_packages"
        except OSError:
            continue
    user_root = _user_site_root()
    if user_root is not None:
        try:
            if _within(resolved, user_root):
                return "user_site"
        except OSError:
            pass
    return "editable_or_foreign_source"


def _within(candidate: Path, root: Path) -> bool:
    """True when ``candidate`` is ``root`` itself or lives beneath it."""
    resolved_root = root.resolve()
    return candidate == resolved_root or resolved_root in candidate.parents


def _sitepackage_roots() -> tuple[str, ...]:
    """Base-distribution site-packages directories, tolerating interpreters without ``site``."""
    try:
        return tuple(site.getsitepackages())
    except (AttributeError, OSError):
        return ()


def _user_site_root() -> Path | None:
    try:
        return Path(site.getusersitepackages())
    except (AttributeError, OSError):
        return None


def probe_dependency(
    distribution: str,
    *,
    lock: Mapping[str, LockPin],
    requirements: Mapping[str, Sequence[DeclaredRequirement]],
    venv: VenvIsolation,
    importer: Callable[[str], Any] | None = None,
    python_version: str = f"{sys.version_info.major}.{sys.version_info.minor}",
) -> DependencyObservation:
    """Import one collection dependency and compare it with the parsed expectation.

    ``importer`` defaults to ``importlib.import_module`` (resolved at call time) and is
    injectable so the tests can fabricate a module resolving anywhere; ``python_version``
    selects the marker-applicable declared constraint.
    """
    module_name = import_name_for(distribution)
    load = importer or _default_importer
    pin = lock.get(distribution)
    requirement = applicable_requirement(requirements, distribution, python_version=python_version)
    specifier = requirement.specifier if requirement and requirement.specifier else None
    expected = {
        "distribution": distribution,
        "module": module_name,
        "lock_version": pin.version if pin else None,
        "lock_direct_url": pin.direct_url if pin else None,
        "declared_specifier": specifier,
        "declared_marker": requirement.marker if requirement else None,
    }
    try:
        module = load(module_name)
    except Exception as error:  # noqa: BLE001 - any import failure is a named refusal
        return DependencyObservation(
            **expected,
            resolution_channel="import_failed",
            import_error=f"{type(error).__name__}: {error}",
            reasons=[REASON_DEPENDENCY_NOT_IMPORTABLE],
        )
    raw_version = getattr(module, "__version__", None)
    observed_version = str(raw_version) if raw_version is not None else None
    module_path = getattr(module, "__file__", None)
    module_path = str(module_path) if module_path else None
    inside_venv = venv.owns(module_path)
    reasons: list[str] = []
    if pin is None or (pin.version is None and pin.direct_url is None):
        reasons.append(REASON_DEPENDENCY_UNPINNED)
    if inside_venv is not True:
        reasons.append(REASON_DEPENDENCY_OUTSIDE_VENV)
    observed_parsed = parse_version_tuple(observed_version)
    if specifier:
        satisfied = satisfies_specifier(observed_version, specifier)
        if satisfied is False:
            reasons.append(REASON_VERSION_OUTSIDE_CONSTRAINT)
        elif satisfied is None:
            reasons.append(REASON_VERSION_UNPARSABLE)
    elif observed_parsed is None:
        reasons.append(REASON_VERSION_UNPARSABLE)
    if pin and pin.version and observed_parsed is not None:
        if _compare_versions(observed_parsed, parse_version_tuple(pin.version) or ()) != 0:
            reasons.append(REASON_VERSION_DIFFERS_FROM_LOCK)
    return DependencyObservation(
        **expected,
        observed_version=observed_version,
        module_path=module_path,
        inside_venv=inside_venv,
        resolution_channel=classify_path_channel(module_path, venv),
        reasons=reasons,
    )


def collection_distributions(
    lock: Mapping[str, LockPin], requirements: Mapping[str, Sequence[DeclaredRequirement]]
) -> tuple[str, ...]:
    """Return the collection-relevant distributions: parsed extras members plus locked core names.

    Only NAMES are curated here; every version expectation stays in the lock and pyproject.
    """
    names = set(requirements) | {name for name in COLLECTION_CORE_DISTRIBUTIONS if name in lock}
    return tuple(sorted(name for name in names if name))


def echoed_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """Keep only the allowlisted environment entries; nothing else is ever echoed."""
    return {key: value for key, value in environ.items() if key in ENVIRONMENT_KEYS_ECHOED}


def observed_timezone(environ: Mapping[str, str]) -> dict[str, Any]:
    """Record the timezone the process actually sees, echoing only the ``TZ`` allowlist key."""
    tz_env = environ.get("TZ")
    offset_seconds = time.localtime().tm_gmtoff
    return {
        "tz_environment_value": redact_secrets(tz_env) if tz_env else None,
        "tzname": list(time.tzname),
        "utc_offset_seconds": offset_seconds if offset_seconds is not None else -time.timezone,
        "utc_offset_hours": round(offset_seconds / 3600, 2) if offset_seconds is not None else None,
    }


def check_interpreter(*, python_version: str, matrix: Sequence[str]) -> dict[str, Any]:
    """Compare the running interpreter with the CI matrix parsed from ``ci.yml``."""
    minor = ".".join(python_version.split(".")[:2])
    reasons: list[str] = []
    if not matrix:
        reasons.append(REASON_SOURCE_UNREADABLE)
    elif minor not in matrix:
        reasons.append(REASON_INTERPRETER_OUTSIDE_MATRIX)
    return {
        "expected": {"ci_python_versions": list(matrix), "source": str(DEFAULT_CI_WORKFLOW_PATH)},
        "observed": {
            "interpreter_version": python_version,
            "minor": minor,
            "executable": redact_secrets(sys.executable),
        },
        "reasons": reasons,
    }


def check_venv(venv: VenvIsolation) -> dict[str, Any]:
    """Refuse when the venv is absent, unreadable, or deliberately not isolated."""
    reasons: list[str] = []
    if not venv.running_in_venv:
        reasons.append(REASON_VIRTUAL_ENVIRONMENT_ABSENT)
    if venv.pyvenv_cfg_path is None:
        reasons.append(REASON_PYVENV_CFG_MISSING)
    if venv.include_system_site_packages is not False:
        reasons.append(REASON_SYSTEM_SITE_PACKAGES)
    return {
        "expected": {
            "running_in_venv": True,
            "include_system_site_packages": False,
            "distributions_inside_venv": "all collection dependencies",
        },
        "observed": venv.as_evidence(),
        "reasons": reasons,
    }


def check_timezone(*, expected_tz: str | None, observed: Mapping[str, Any]) -> dict[str, Any]:
    """Compare the process timezone with the one the application declares for collection.

    A POSIX-style ``TZ`` (``CST-8``) carries no zone *name*, so it is recorded but not
    compared; only a name-bearing value can be shown to disagree with the declared default.
    """
    reasons: list[str] = []
    raw = str(observed.get("tz_environment_value") or "").strip().lstrip(":")
    comparable = bool(raw) and ("/" in raw or raw == expected_tz)
    if expected_tz and comparable and raw != expected_tz:
        reasons.append(REASON_TIMEZONE_MISMATCH)
    return {
        "expected": {
            "declared_collection_timezone": expected_tz,
            "source": str(DEFAULT_APP_CONFIG_PATH),
        },
        "observed": {**dict(observed), "name_comparable": comparable},
        "reasons": reasons,
    }


@dataclass(frozen=True)
class EnvironmentVerdict:
    """Actionable identity verdict; callers read ``reasons`` instead of parsing prose."""

    allowed: bool
    status: str
    exit_code: int
    reasons: tuple[str, ...]
    checks: dict[str, Any]

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema": PAYLOAD_SCHEMA,
            "allowed": self.allowed,
            "status": self.status,
            "exit_code": self.exit_code,
            "reasons": list(self.reasons),
            "checks": self.checks,
        }


def build_verdict(
    *,
    interpreter: Mapping[str, Any],
    venv_check: Mapping[str, Any],
    timezone_check: Mapping[str, Any],
    observations: Sequence[DependencyObservation],
    unreadable_sources: Sequence[str] = (),
) -> EnvironmentVerdict:
    """Aggregate every named refusal into one verdict."""
    reasons: list[str] = []
    for section in (interpreter, venv_check, timezone_check):
        reasons.extend(str(reason) for reason in section.get("reasons", ()))  # type: ignore[arg-type]
    for observation in observations:
        reasons.extend(observation.reasons)
    reasons.extend(REASON_SOURCE_UNREADABLE for _ in unreadable_sources)
    ordered = tuple(dict.fromkeys(reasons))
    refused = bool(ordered)
    dependency_rows = [
        {
            "distribution": item.distribution,
            "module": item.module,
            "expected": item.expected,
            "observed": item.observed,
            "reasons": list(item.reasons),
        }
        for item in observations
    ]
    checks = {
        "interpreter": dict(interpreter),
        "venv_isolation": dict(venv_check),
        "timezone": dict(timezone_check),
        "dependencies": {
            "expected": {"source_of_truth": str(DEFAULT_LOCK_PATH), "count": len(dependency_rows)},
            "observed": {"refused_count": sum(1 for row in dependency_rows if row["reasons"])},
            "entries": dependency_rows,
        },
        "unreadable_sources": [redact_secrets(item) for item in unreadable_sources],
    }
    return EnvironmentVerdict(
        allowed=not refused,
        status="ok" if not refused else "refused",
        exit_code=0 if not refused else _REFUSAL_EXIT_CODE,
        reasons=ordered,
        checks=checks,
    )


def _redact_tree(value: Any, secrets: Sequence[str]) -> Any:
    """Apply ``redact_secrets`` to every string leaf, preserving the JSON document shape."""
    if isinstance(value, str):
        return redact_secrets(value, secrets=secrets)
    if isinstance(value, Mapping):
        return {key: _redact_tree(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_tree(item, secrets) for item in value]
    return value


def render_payload(
    verdict: EnvironmentVerdict, environ: Mapping[str, str], *, indent: int | None = 2
) -> str:
    """Serialize the verdict with every credential-shaped string leaf and token redacted."""
    payload = _redact_tree(verdict.as_payload(), _environment_secret_tokens(environ))
    return json.dumps(payload, indent=indent, sort_keys=False, default=str)


def _read_text(path: Path, unreadable: list[str]) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        unreadable.append(str(path))
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_runtime_environment_identity.py",
        description=(
            "Report the interpreter, virtual-environment isolation, package identity and "
            "timezone this process actually has, against the lock/pyproject/CI declarations. "
            "Prints one sanitized JSON payload; exits 2 on any named refusal."
        ),
    )
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH, help="dev lock to parse")
    parser.add_argument(
        "--pyproject", type=Path, default=DEFAULT_PYPROJECT_PATH, help="backend pyproject.toml"
    )
    parser.add_argument(
        "--ci-workflow",
        type=Path,
        default=DEFAULT_CI_WORKFLOW_PATH,
        help="workflow declaring the matrix",
    )
    parser.add_argument(
        "--app-config",
        type=Path,
        default=DEFAULT_APP_CONFIG_PATH,
        help="module declaring the scheduler timezone",
    )
    parser.add_argument(
        "--compact", action="store_true", help="emit a single-line JSON payload instead of indented"
    )
    parser.add_argument(
        "--skip-imports",
        action="store_true",
        help="report only interpreter/venv/timezone checks (for pre-import preflight use)",
    )
    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    """Collect every identity check for this process and print one sanitized JSON payload."""
    args = build_parser().parse_args(argv)
    env = dict(os.environ if environ is None else environ)
    unreadable: list[str] = []

    lock_text = _read_text(args.lock, unreadable)
    pyproject_text = _read_text(args.pyproject, unreadable)
    ci_text = _read_text(args.ci_workflow, unreadable)
    config_text = _read_text(args.app_config, unreadable)

    lock = parse_lock(lock_text or "")
    if lock_text is not None and not lock:
        unreadable.append(f"{args.lock}: no pins parsed")
    requirements: dict[str, list[DeclaredRequirement]] = {}
    if tomllib is None:
        unreadable.append(f"{args.pyproject}: tomllib requires Python 3.11+")
    elif pyproject_text is not None:
        try:
            requirements = parse_pyproject_requirements(tomllib.loads(pyproject_text))
        except Exception as error:  # noqa: BLE001 - unparsable truth source refuses
            unreadable.append(f"{args.pyproject}: {type(error).__name__}")

    venv = inspect_venv(
        prefix=sys.prefix,
        base_prefix=sys.base_prefix,
        site_packages_dir=sysconfig.get_paths()["purelib"],
    )
    observations: list[DependencyObservation] = []
    if not args.skip_imports:
        for distribution in collection_distributions(lock, requirements):
            observations.append(
                probe_dependency(
                    distribution,
                    lock=lock,
                    requirements=requirements,
                    venv=venv,
                    python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
                )
            )
    verdict = build_verdict(
        interpreter=check_interpreter(
            python_version=sys.version.split()[0], matrix=parse_ci_python_matrix(ci_text or "")
        ),
        venv_check=check_venv(venv),
        timezone_check=check_timezone(
            expected_tz=parse_declared_timezone(config_text or ""),
            observed=observed_timezone(echoed_environment(env)),
        ),
        observations=observations,
        unreadable_sources=unreadable,
    )
    print(render_payload(verdict, env, indent=None if args.compact else 2))
    return verdict.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
