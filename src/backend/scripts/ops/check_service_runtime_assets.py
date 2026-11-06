"""Audit whether the paths that user systemd units execute exist and are tracked in git.

WHY THIS EXISTS
    Several units installed on this host run scripts that exist in no branch.  The failure mode
    that hides it: ``systemctl --user list-timers`` shows a ``PASSED`` column meaning *the timer
    fired*, not *the work ran*, so a unit whose ``ExecStart`` target is missing keeps failing
    every minute (``can't open file ... No such file or directory``) while still looking
    scheduled.  This auditor makes that class of defect visible from the unit files alone.

WHAT IT READS
    ``ExecStart`` / ``ExecStartPre`` / ``ExecStartPost`` values, ``WorkingDirectory`` (a path)
    and the unit file names.  ``Environment=`` and ``EnvironmentFile=`` values are never read,
    never resolved and never printed: units here point at ``.env`` files holding credentials,
    and this tool has no reason to look inside them.

WHAT IT REPORTS
    For every referenced path that lies inside a git checkout of this repository: whether the
    path exists and whether ``git ls-files`` lists it in that checkout (never assumed), plus the
    unit's ``ActiveState`` / ``Result`` / ``ExecMainStatus`` from ``systemctl --user show`` when
    that command is available.  ``@``-template units are audited once per instance discovered
    from instantiated names and ``*.wants`` symlinks (or from ``--instance``).

EXIT CODES
    ``0`` always, or ``1`` with ``--fail-on-findings`` when a ``missing_file`` or
    ``untracked_but_present`` finding exists.  ``2`` when ``--unit-dir`` does not exist.

NOT WIRED INTO CI -- DELIBERATELY
    Several units legitimately reference assets that are not in the repo yet, so a hard gate
    would turn a known, owner-tracked backlog into a red build.  Wiring this into CI,
    ``Makefile`` or pre-commit is an owner decision to be taken *after* those missing assets
    land; until then run it by hand as read-only inventory evidence.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_UNIT_DIR = Path("~/.config/systemd/user")
UNIT_SUFFIXES = (".service", ".socket", ".timer", ".target")
EXEC_KEYS = ("ExecStartPre", "ExecStart", "ExecStartPost")

CLASSIFICATION_MISSING_FILE = "missing_file"
CLASSIFICATION_UNTRACKED_BUT_PRESENT = "untracked_but_present"
CLASSIFICATION_OK = "ok"
CLASSIFICATIONS = (
    CLASSIFICATION_MISSING_FILE,
    CLASSIFICATION_UNTRACKED_BUT_PRESENT,
    CLASSIFICATION_OK,
)

# Non-finding buckets: referenced paths deliberately kept out of the findings.
REASON_OUTSIDE_REPO = "outside_repo"
REASON_GITIGNORED = "gitignored"
REASON_GIT_UNREADABLE = "git_unreadable"
REASON_UNRESOLVED_INSTANCE = "unresolved_instance"

STATUS_PROPERTIES = ("ActiveState", "Result", "ExecMainStatus")
STATUS_UNKNOWN = "unknown"

# Specifiers this parser understands; anything else is left verbatim so an unsupported escape
# shows up as an unresolved path instead of a wrong one.
_HOME_SPECIFIERS = frozenset({"h"})
_NAME_SPECIFIERS = frozenset({"n", "N", "p", "g"})
_INSTANCE_SPECIFIERS = frozenset({"i", "I", "j"})
_SPECIFIER_RE = re.compile(r"%([%a-zA-Z])")
_INSTANTIATED_UNIT_RE = re.compile(r"^(?P<prefix>[^@/]+)@(?P<instance>[^/]+)\.(?P<suffix>[a-z]+)$")
_EXEC_PREFIX_CHARS = "+-@:"
_PATHISH_SUFFIXES = (".py", ".sh", ".bash", ".js", ".ts", ".mjs", ".cjs", ".rb", ".pl")
BACKEND_SUBDIR = Path("src/backend")


@dataclass(frozen=True)
class UnitIdentity:
    """Parsed unit file name, split into the parts the specifiers need."""

    name: str
    prefix: str
    instance: str | None
    suffix: str | None

    @property
    def is_template(self) -> bool:
        """True for ``foo@.service``: its instance is only known at instantiation time."""
        return self.instance is None and "@" in self.name

    def instantiated(self, instance: str | None) -> str:
        if not self.is_template or not instance:
            return self.name
        return self.name.replace("@.", f"@{instance}.", 1)


@dataclass(frozen=True)
class ExpansionContext:
    """Values the specifier table may legitimately use -- never credential material."""

    home: Path
    user: str = ""


@dataclass
class ExecLine:
    key: str
    raw: str
    resolved: str
    tokens: list[str] = field(default_factory=list)
    unresolved_instance: bool = False


@dataclass
class PathFinding:
    path: str
    classification: str
    exists: bool
    tracked: bool | None
    ignored: bool | None
    note: str = ""


@dataclass
class UnitReport:
    unit_file: str
    unit_name: str
    exec_lines: list[ExecLine] = field(default_factory=list)
    findings: list[PathFinding] = field(default_factory=list)
    skipped: dict[str, list[str]] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)

    @property
    def has_finding(self) -> bool:
        return any(finding.classification != CLASSIFICATION_OK for finding in self.findings)

    @property
    def is_green(self) -> bool:
        """Green means every in-repo path is present *and* tracked, with nothing unresolved."""
        return not self.has_finding and not self.skipped.get(REASON_UNRESOLVED_INSTANCE)


@dataclass
class AuditSummary:
    reports: list[UnitReport]
    counts: dict[str, int]
    unit_dir: Path
    scope_label: str
    systemctl_available: bool

    @property
    def flagged_units(self) -> list[UnitReport]:
        return [report for report in self.reports if not report.is_green]

    @property
    def non_green_units(self) -> list[str]:
        return sorted(report.unit_name for report in self.flagged_units)


def parse_unit_name(filename: str) -> UnitIdentity:
    """Split ``foo@.service`` / ``foo@bar.service`` / ``foo.service`` into specifier inputs."""

    stem, _, suffix = filename.partition(".")
    if "@" in stem:
        prefix, _, instance = stem.partition("@")
        return UnitIdentity(
            name=filename, prefix=prefix, instance=instance or None, suffix=suffix or None
        )
    return UnitIdentity(name=filename, prefix=stem, instance=None, suffix=suffix or None)


def _expand_specifier(
    identity: UnitIdentity,
    context: ExpansionContext,
    instance: str | None,
    specifier: str,
) -> str | None:
    """Replacement for one specifier, or ``None`` to leave it verbatim (unresolvable here)."""

    if specifier == "%":
        return "%"
    if specifier in _HOME_SPECIFIERS:
        return str(context.home)
    if specifier == "u":
        return context.user
    if specifier == "U":
        return str(os.getuid())
    if specifier == "n":
        return identity.name
    if specifier == "N":
        return identity.name.split("@", 1)[0]
    if specifier in _NAME_SPECIFIERS:
        return identity.prefix
    if specifier in _INSTANCE_SPECIFIERS:
        if identity.is_template and instance is None:
            return None
        return instance or ""
    return None


def expand_specifiers(
    value: str,
    identity: UnitIdentity,
    context: ExpansionContext,
    instance: str | None = None,
) -> tuple[str, bool]:
    """Expand specifiers; report whether an instance escape had to stay open."""

    unresolved = False

    def replace(match: re.Match[str]) -> str:
        nonlocal unresolved
        replacement = _expand_specifier(identity, context, instance, match.group(1))
        if replacement is None:
            unresolved = True
            return match.group(0)
        return replacement

    return _SPECIFIER_RE.sub(replace, value), unresolved


def strip_exec_prefix(value: str) -> str:
    """Drop systemd's ``-``, ``@``, ``+``, ``:`` execution-modifier prefixes."""

    while value and value[0] in _EXEC_PREFIX_CHARS:
        value = value[1:]
    return value


def split_exec_value(value: str) -> list[str]:
    """Shell-style split of one command line (an approximation of systemd's own quoting)."""

    stripped = strip_exec_prefix(value.strip())
    if not stripped:
        return []
    try:
        return shlex.split(stripped, posix=True)
    except ValueError:
        return stripped.split()


def iter_unit_files(unit_dir: Path) -> list[Path]:
    """Regular unit files directly in ``unit_dir``; ``*.wants`` drop-in directories are skipped."""

    if not unit_dir.is_dir():
        return []
    found: list[Path] = []
    for entry in sorted(unit_dir.iterdir()):
        if entry.suffix not in UNIT_SUFFIXES:
            continue
        if entry.is_symlink() or not entry.is_file():
            continue
        found.append(entry)
    return found


def _safe_iterdir(directory: Path) -> list[Path]:
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def discover_template_instances(unit_dir: Path) -> dict[str, list[str]]:
    """Instances already wired on the host, read from instantiated names and ``*.wants`` links.

    Without this a template unit (``foo@.service``) cannot be audited at all: ``%i`` has no value
    until systemd instantiates it, and the instantiated names are where the broken instances are.
    """

    try:
        entries = list(unit_dir.iterdir())
    except OSError:
        return {}
    candidates = entries + [
        child for sub in entries if sub.is_dir() for child in _safe_iterdir(sub)
    ]
    found: dict[str, set[str]] = {}
    for entry in candidates:
        if entry.suffix not in UNIT_SUFFIXES:
            continue
        match = _INSTANTIATED_UNIT_RE.match(entry.name)
        if not match or not match.group("instance"):
            continue
        found.setdefault(match.group("prefix"), set()).add(match.group("instance"))
    return {prefix: sorted(instances) for prefix, instances in found.items()}


def parse_exec_lines(
    text: str,
    identity: UnitIdentity,
    context: ExpansionContext,
    instance: str | None,
) -> tuple[list[ExecLine], str | None]:
    """Collect the Exec* command lines plus the working directory.

    ``Environment`` / ``EnvironmentFile`` lines are skipped on purpose: their values may carry
    credentials and this auditor never needs them.
    """

    lines: list[ExecLine] = []
    working_directory: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("[", ";", "#")) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "WorkingDirectory":
            if working_directory is None:
                working_directory, _ = expand_specifiers(value, identity, context, instance)
            continue
        if key not in EXEC_KEYS:
            continue
        expanded, unresolved = expand_specifiers(value, identity, context, instance)
        lines.append(
            ExecLine(
                key=key,
                raw=value,
                resolved=expanded,
                tokens=split_exec_value(expanded),
                unresolved_instance=unresolved,
            )
        )
    return lines, working_directory


def _looks_like_path(token: str) -> bool:
    """Reject flags, URLs, ``module:attribute`` specs, bare words and free-form argument text.

    A token counts as a path when it is absolute or carries a known script suffix.  Relative
    suffix-free arguments (``hello world/folder``) are deliberately not treated as paths -- they
    would otherwise be reported as missing repository files.
    """

    if not token or token.startswith("-"):
        return False
    if token.startswith("/"):
        return True
    return Path(token).suffix in _PATHISH_SUFFIXES


def candidate_paths(tokens: Sequence[str], working_directory: str | None, home: Path) -> list[Path]:
    """Every token naming a filesystem path, absolute or resolved against the unit's cwd."""

    paths: list[Path] = []
    for token in tokens:
        if "%" in token or not _looks_like_path(token):
            continue
        if token.startswith("/"):
            paths.append(Path(os.path.normpath(token)))
            continue
        base = working_directory or str(home)
        if base.startswith("~"):
            base = str(home) + base[1:]
        elif not base.startswith("/"):
            base = str(home / base)
        paths.append(Path(os.path.normpath(os.path.join(base, token))))
    return paths


def nearest_checkout(path: Path, cache: dict[str, Path | None]) -> Path | None:
    """Checkout owning ``path``: the nearest ancestor directory holding ``.git``."""

    walked: list[Path] = []
    for parent in (path, *path.parents):
        key = str(parent)
        if key in cache:
            cached = cache[key]
            for done in walked:
                cache[str(done)] = cached
            return cached
        walked.append(parent)
        if (parent / ".git").exists():
            for done in walked:
                cache[str(done)] = parent
            return parent
    for done in walked:
        cache[str(done)] = None
    return None


def _run_git(
    checkout: Path, args: Sequence[str], timeout: float
) -> subprocess.CompletedProcess[str] | None:
    if shutil.which("git") is None:
        return None
    try:
        return subprocess.run(
            ["git", "-C", str(checkout), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def is_tracked(checkout: Path, path: Path, timeout: float) -> bool | None:
    """``git ls-files`` truth for one path; ``None`` when git cannot answer."""

    try:
        relative = path.relative_to(checkout).as_posix()
    except ValueError:
        return None
    result = _run_git(checkout, ["ls-files", "-z", "--", relative], timeout)
    if result is None or result.returncode != 0:
        return None
    return bool(result.stdout.strip("\x00 "))


def is_ignored(checkout: Path, path: Path, timeout: float) -> bool | None:
    """Separate an intentionally ignored path (venv, cache, logs) from an untracked asset."""

    try:
        relative = path.relative_to(checkout).as_posix()
    except ValueError:
        return None
    result = _run_git(checkout, ["check-ignore", "--", relative], timeout)
    if result is None or result.returncode not in (0, 1):
        return None
    return bool(result.stdout.strip())


def repository_identity(checkout: Path, cache: dict[str, str | None], timeout: float) -> str | None:
    """Repository identity of a checkout: worktrees share their main repository's git dir."""

    key = str(checkout)
    if key in cache:
        return cache[key]
    result = _run_git(checkout, ["rev-parse", "--git-common-dir"], timeout)
    identity: str | None = None
    if result is not None and result.returncode == 0 and result.stdout.strip():
        candidate = Path(result.stdout.strip())
        if not candidate.is_absolute():
            candidate = checkout / candidate
        identity = str(candidate.resolve(strict=False))
    cache[key] = identity
    return identity


def resolve_scope(repo_scope: Path | None, timeout: float) -> tuple[str | None, str]:
    """Identity to restrict findings to, plus a label for the report header."""

    if repo_scope is None:
        return None, "any git checkout"
    identity = repository_identity(repo_scope, {}, timeout)
    if identity is None:
        return str(repo_scope), f"{repo_scope} (git identity unreadable)"
    return identity, identity


def classify_path(
    path: Path,
    *,
    scope_identity: str | None,
    checkout_cache: dict[str, Path | None],
    identity_cache: dict[str, str | None],
    timeout: float,
) -> tuple[PathFinding | None, str | None]:
    """Return either a finding or a skip reason for one referenced path."""

    checkout = nearest_checkout(path, checkout_cache)
    if checkout is None:
        return None, REASON_OUTSIDE_REPO
    if scope_identity is not None:
        identity = repository_identity(checkout, identity_cache, timeout)
        if identity != scope_identity:
            return None, REASON_OUTSIDE_REPO
    exists = path.exists()
    tracked = is_tracked(checkout, path, timeout)
    if tracked is None:
        return None, REASON_GIT_UNREADABLE
    if not exists:
        note = "absent from disk but in the index" if tracked else "absent and in no branch index"
        return (
            PathFinding(
                path=str(path),
                classification=CLASSIFICATION_MISSING_FILE,
                exists=False,
                tracked=tracked,
                ignored=None,
                note=note,
            ),
            None,
        )
    if tracked:
        return (
            PathFinding(
                path=str(path),
                classification=CLASSIFICATION_OK,
                exists=True,
                tracked=True,
                ignored=None,
            ),
            None,
        )
    ignored = is_ignored(checkout, path, timeout)
    if ignored:
        return None, REASON_GITIGNORED
    note = "exists on disk but git ls-files does not list it"
    if ignored is None:
        note += " (gitignore state unreadable)"
    return (
        PathFinding(
            path=str(path),
            classification=CLASSIFICATION_UNTRACKED_BUT_PRESENT,
            exists=True,
            tracked=False,
            ignored=ignored,
            note=note,
        ),
        None,
    )


def query_unit_status(unit: str, *, user: bool = True, timeout: float = 5.0) -> dict[str, str]:
    """Read ActiveState/Result/ExecMainStatus for one unit; empty when systemctl cannot answer.

    Queried per unit: ``systemctl show`` with several units prints bare ``Key=Value`` blocks that
    do not name the unit, which cannot be attributed reliably.
    """

    if shutil.which("systemctl") is None:
        return {}
    command = ["systemctl"]
    if user:
        command.append("--user")
    command.append("show")
    for prop in STATUS_PROPERTIES:
        command.extend(["-p", prop])
    command.append(unit)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    status: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in STATUS_PROPERTIES:
            status[key] = value or STATUS_UNKNOWN
    return status


def own_checkout(timeout: float) -> Path | None:
    """Checkout holding this script, so the default scope is *this* repository."""

    return nearest_checkout(Path(__file__).resolve(), {})


def audit_units(
    unit_dir: Path,
    *,
    home: Path,
    repo_scope: Path | None = None,
    instance: str | None = None,
    timeout: float = 5.0,
    use_systemctl: bool = True,
    statuses: dict[str, dict[str, str]] | None = None,
) -> AuditSummary:
    """Audit every unit file in ``unit_dir``; read-only and credential-free.

    ``repo_scope=None`` accepts any git checkout; ``instance`` pins one template instance,
    otherwise the instances already wired on the host are discovered.
    """

    context = ExpansionContext(home=home, user=os.environ.get("USER", ""))
    scope_identity, scope_label = resolve_scope(repo_scope, timeout)
    instances_by_prefix = discover_template_instances(unit_dir)
    checkout_cache: dict[str, Path | None] = {}
    identity_cache: dict[str, str | None] = {}
    counts: dict[str, int] = {}
    reports: list[UnitReport] = []

    unit_files = iter_unit_files(unit_dir)
    for unit_file in unit_files:
        template_identity = parse_unit_name(unit_file.name)
        try:
            text = unit_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            _bump(counts, "unreadable_unit_files")
            continue
        if template_identity.is_template and instance:
            instances: list[str | None] = [instance]
        elif template_identity.is_template:
            # Nothing wired on the host: keep one unresolved report so the template stays visible.
            instances = list(instances_by_prefix.get(template_identity.prefix, [])) or [None]
        else:
            instances = [None]
        for resolved_instance in instances:
            name = template_identity.instantiated(resolved_instance)
            identity = parse_unit_name(name) if resolved_instance else template_identity
            report = _audit_one_unit(
                unit_file.name,
                identity,
                text,
                context,
                resolved_instance,
                scope_identity=scope_identity,
                checkout_cache=checkout_cache,
                identity_cache=identity_cache,
                timeout=timeout,
                counts=counts,
            )
            if report is None:
                continue
            if statuses is None and use_systemctl:
                report.status = query_unit_status(report.unit_name, user=True, timeout=timeout)
            else:
                report.status = dict((statuses or {}).get(report.unit_name, {}))
            if not report.status:
                _bump(counts, "status_unavailable")
            reports.append(report)

    counts["unit_files_scanned"] = counts.get("unit_files_scanned", 0) + len(unit_files)
    counts["units_audited"] = counts.get("units_audited", 0) + len(reports)
    counts["green_units"] = sum(1 for report in reports if report.is_green)
    counts["units_with_findings"] = sum(1 for report in reports if not report.is_green)

    return AuditSummary(
        reports=reports,
        counts=counts,
        unit_dir=unit_dir,
        scope_label=scope_label,
        systemctl_available=shutil.which("systemctl") is not None,
    )


def _audit_one_unit(
    unit_file: str,
    identity: UnitIdentity,
    text: str,
    context: ExpansionContext,
    instance: str | None,
    *,
    scope_identity: str | None,
    checkout_cache: dict[str, Path | None],
    identity_cache: dict[str, str | None],
    timeout: float,
    counts: dict[str, int],
) -> UnitReport | None:
    lines, working_directory = parse_exec_lines(text, identity, context, instance)
    if not lines:
        _bump(counts, "units_without_exec")
        return None
    report = UnitReport(unit_file=unit_file, unit_name=identity.name)
    report.exec_lines = lines
    seen: set[str] = set()
    for line in lines:
        if line.unresolved_instance:
            _bump(counts, REASON_UNRESOLVED_INSTANCE)
            report.skipped.setdefault(REASON_UNRESOLVED_INSTANCE, []).append(line.raw)
            continue
        for path in candidate_paths(line.tokens, working_directory, context.home):
            if str(path) in seen:
                continue
            seen.add(str(path))
            finding, reason = classify_path(
                path,
                scope_identity=scope_identity,
                checkout_cache=checkout_cache,
                identity_cache=identity_cache,
                timeout=timeout,
            )
            if finding is not None:
                report.findings.append(finding)
                _bump(counts, finding.classification)
            elif reason is not None:
                report.skipped.setdefault(reason, []).append(str(path))
                _bump(counts, reason)
    return report


def _bump(counts: dict[str, int], key: str, amount: int = 1) -> None:
    counts[key] = counts.get(key, 0) + amount


_COUNT_ORDER = (
    "unit_files_scanned",
    "units_audited",
    "units_without_exec",
    "green_units",
    "units_with_findings",
    CLASSIFICATION_MISSING_FILE,
    CLASSIFICATION_UNTRACKED_BUT_PRESENT,
    CLASSIFICATION_OK,
    REASON_OUTSIDE_REPO,
    REASON_GITIGNORED,
    REASON_GIT_UNREADABLE,
    REASON_UNRESOLVED_INSTANCE,
    "status_unavailable",
    "unreadable_unit_files",
)


def _yesno(value: bool | None) -> str:
    if value is None:
        return "?"
    return "yes" if value else "no"


def render_summary(summary: AuditSummary) -> list[str]:
    """Aggregate counts first, then per-unit lines.  Never contains credential values."""

    lines: list[str] = [
        "systemd runtime asset audit (read-only; environment values are not read or printed)",
        f"unit_dir={summary.unit_dir} scope={summary.scope_label} "
        f"systemctl={'available' if summary.systemctl_available else 'unavailable'}",
        "counts: "
        + " ".join(f"{key}={summary.counts[key]}" for key in _COUNT_ORDER if key in summary.counts),
        "",
    ]
    for report in summary.reports:
        mark = "ok  " if report.is_green else "FLAG"
        lines.append(f"[{mark}] {report.unit_name} ({report.unit_file})")
        for line in report.exec_lines:
            lines.append(f"     {line.key}: {line.raw}")
        for finding in report.findings:
            note = f"  {finding.note}" if finding.note else ""
            lines.append(
                f"       {finding.classification:<22} exists={_yesno(finding.exists)} "
                f"tracked={_yesno(finding.tracked)} {finding.path}{note}"
            )
        for reason in sorted(report.skipped):
            for path in report.skipped[reason]:
                lines.append(f"       {reason:<22} {path}")
        status = report.status or dict.fromkeys(STATUS_PROPERTIES, STATUS_UNKNOWN)
        lines.append(
            "       status: " + " ".join(f"{key}={status[key]}" for key in STATUS_PROPERTIES)
        )
    lines.append("")
    lines.append("non-green units: " + (", ".join(summary.non_green_units) or "none"))
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_service_runtime_assets.py",
        description=(
            "Read-only audit of the paths user systemd units execute against the git checkout that "
            "should contain them. Never prints Environment or EnvironmentFile values."
        ),
    )
    parser.add_argument(
        "--unit-dir",
        type=Path,
        default=DEFAULT_UNIT_DIR,
        help=f"directory holding unit files (default: {DEFAULT_UNIT_DIR})",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="checkout root to restrict findings to (default: the repository holding this script)",
    )
    parser.add_argument(
        "--all-repos",
        action="store_true",
        help="audit paths referenced inside any git checkout, not just this repository",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=None,
        help="value for the %%h specifier (default: the current user's home directory)",
    )
    parser.add_argument(
        "--instance",
        default=None,
        help="pin one template instance for %%i/%%I instead of the instances found on the host",
    )
    parser.add_argument(
        "--no-systemctl",
        action="store_true",
        help="skip reading ActiveState/Result/ExecMainStatus from systemctl --user show",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="per-command timeout in seconds for the git/systemctl probes (default: 5)",
    )
    parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="exit 1 when a missing_file or untracked_but_present finding exists (default: exit 0)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    unit_dir = Path(os.path.expanduser(str(args.unit_dir)))
    if not unit_dir.is_dir():
        print(f"error: unit directory does not exist: {unit_dir}", file=sys.stderr)
        return 2
    home = Path(os.path.expanduser(str(args.home))) if args.home else Path.home()
    repo_scope: Path | None
    if args.repo is not None:
        repo_scope = Path(os.path.expanduser(str(args.repo)))
    elif args.all_repos:
        repo_scope = None
    else:
        repo_scope = own_checkout(args.timeout)

    summary = audit_units(
        unit_dir,
        home=home,
        repo_scope=repo_scope,
        instance=args.instance,
        timeout=args.timeout,
        use_systemctl=not args.no_systemctl,
    )
    for line in render_summary(summary):
        print(line)

    if args.fail_on_findings and any(report.has_finding for report in summary.reports):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
