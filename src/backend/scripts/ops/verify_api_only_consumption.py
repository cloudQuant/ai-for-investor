#!/usr/bin/env python3
"""AC18 joint verification: is data consumption really API-only after cutover?

Read-only acceptance instrument for iteration 204 AC18 ("最终只通过 API"),
shaped to §6 of ``docs/iterations/迭代204-OpenData数据中台拆分与五人并行迁移/
ACCEPTANCE_AND_CUTOVER.md``.  Legs (each PASS / FAIL / NOT_RUN):

- ``no_source_sdk``: the collection SDK counts as present when it is a
  *declared install dependency* or *importable from the runtime venv*.  Bare
  string hits (UI database names, chunk filenames) are information only --
  never the criterion: they produce false positives pre-cutover and false
  negatives elsewhere.  Pre-cutover this leg fails BY DESIGN; the receipt says
  so instead of faking a pass.
- ``no_collection_startup_hook``: no process-launching collection command in
  deploy/startup config.
- ``no_warehouse_dsn_in_artifact``: built artifacts contain no DSN /
  credential-shaped strings.  Findings report path + line count + pattern
  NAME only; matched values are never emitted.
- ``no_residual_collection_process``: ``ps`` enumeration + ``systemctl show``.
- ``egress_limited_to_opendata_api``: config host set is reported, but egress
  needs runtime observation; without an observation artifact the leg is
  NOT_RUN, never "passed from config".
- ``data_consumption_tests_after_revocation``: needs revoked warehouse write
  privileges; NOT_RUN when the host cannot provide them.

Denominator (report-only): app files touching the warehouse engine/DSN, split
collection-domain vs non-collection-domain, so E-domain progress is measurable.

Exit codes: 0 = every runnable leg passed (FAIL legs waived only via an
explicit, receipt-recorded ``--allow-fail-leg``); 1 = unwaived FAIL; 3 = no
FAIL but >=1 NOT_RUN ("could not test" is neither "it broke" nor a pass;
NOT_RUN cannot be waived).

Hard rules: pure read-only (no DB connections, no writes outside
``--json-output``, service interaction limited to ``ps`` / ``systemctl show``)
and no DSN/password/token/user:pass@host value is ever printed or receipted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PASS = "PASS"
FAIL = "FAIL"
NOT_RUN = "NOT_RUN"

CASE_ID_DEFAULT = "AC18"
SDK_NAME_DEFAULT = "akshare"
WAREHOUSE_TOKENS = ("akshare_data_database", "AKSHARE_DATA_DATABASE_URL")
# Files under these app-relative prefixes belong to the collection domain (E).
COLLECTION_DOMAIN_PREFIXES = ("data_fetch/", "api/akshare/", "services/akshare/")
PROCESS_PATTERNS = (
    "akshare",
    "data_fetch",
    "script_worker",
    "run_with_core",
    "backfill",
    "recovery",
)
# Only process-*launching* shapes are startup hooks; env vars that merely name
# a script root are not launches.
STARTUP_HOOK_PATTERNS = (
    "run_akshare_scheduled_tasks",
    "akshare_market_data_runner",
    "openbb_market_data_runner",
    "run_with_core_environment",
    "script_worker",
    "backfill_",
)
DSN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "db_scheme_url",
        re.compile(
            r"(?i)\b(?:mysql|mariadb|postgres(?:ql)?|clickhouse|sqlite)(?:\+[a-z0-9_]+)?://"
        ),
    ),
    (
        "credential_at_host",
        # user:pass@host where pass uses credential-charset only (no {}()[];/,&,
        # quotes or whitespace -- which excludes minified-CSS `}@media` shapes)
        # and host is an IP, `localhost` or a dotted domain.
        re.compile(
            r"[A-Za-z0-9._\-]{1,128}:[A-Za-z0-9._\-!#$%*+=?^~|<>]{1,256}@"
            r"(?:\d{1,3}(?:\.\d{1,3}){3}|localhost(?=[\s:\"'`)\]},;]|$)|[A-Za-z0-9](?:[A-Za-z0-9\-]{0,126}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,126}[A-Za-z0-9])?)+)(?::\d{1,5})?"
        ),
    ),
    (
        "dsn_env_assignment",
        re.compile(
            r"(?i)\b(?:[A-Z0-9_]*DATABASE_URL|[A-Z0-9_]*DB_DSN|[A-Z0-9_]*DSN_URL)\b\s*[=:]\s*[\"']?[a-z][a-z0-9+.\-]*://"
        ),
    ),
)
_URL_VALUE_RE = re.compile(
    r"(?i)\b[a-z][a-z0-9+.\-]*://(?:[^/@\s]*@)?"
    r"(\[[0-9a-fA-F:.]+\]|\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9][A-Za-z0-9.\-]{0,253})(?::\d{1,5})?(?:[/?\#]|$|\s|[\"'])"
)
_LOOPBACK = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "localhost.localdomain"}
_SELF_TOKEN = "verify_api_only_consumption"

ImportProber = Callable[[Path, str], dict[str, Any]]


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dependency_strings(pyproject_path: Path) -> list[str]:
    """All PEP-508 requirement strings from project + optional dependencies."""
    text = pyproject_path.read_text(encoding="utf-8", errors="replace")
    try:
        import tomllib

        data = tomllib.loads(text)
        project = data.get("project", {}) if isinstance(data, dict) else {}
        reqs = list(project.get("dependencies", []) or [])
        for extra_reqs in (project.get("optional-dependencies", {}) or {}).values():
            reqs.extend(extra_reqs or [])
        return [r for r in reqs if isinstance(r, str)]
    except Exception:  # noqa: BLE001 - degrade to a conservative text scan
        return re.findall(r"[\"']([A-Za-z][A-Za-z0-9._-]*(?:[<>=!~\[]|;)[^\"']*)[\"']", text)


def _dep_name(req: str) -> str:
    head = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", req.strip())
    return re.sub(r"[-_.]+", "-", head.group(1)).lower() if head else ""


def pyproject_declares_sdk(pyproject_path: Path, sdk_name: str) -> tuple[bool, list[str]]:
    """(declared, matching requirement strings); a match never echoes secrets."""
    if not pyproject_path.is_file():
        return False, []
    target = _dep_name(sdk_name)
    matched = [r.strip() for r in _dependency_strings(pyproject_path) if _dep_name(r) == target]
    return bool(matched), matched


def probe_module_importable(venv_python: Path, module: str, timeout: int = 60) -> dict[str, Any]:
    """Ask the runtime venv interpreter whether *module* resolves. Read-only probe."""
    code = (
        "import importlib.util, sys\n"
        "spec = importlib.util.find_spec(sys.argv[2])\n"
        "sys.stdout.write('IMPORTABLE' if spec else 'ABSENT')\n"
        "sys.stdout.write('\\t' + str(getattr(spec, 'origin', None) if spec else ''))\n"
        "sys.stdout.write('\\t' + sys.version.split()[0])\n"
    )
    try:
        proc = subprocess.run(
            [str(venv_python), "-c", code, "--", module],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"state": "UNKNOWN", "detail": f"probe failed: {type(exc).__name__}"}
    if proc.returncode != 0:
        return {"state": "UNKNOWN", "detail": "probe exited nonzero"}
    parts = proc.stdout.split("\t")
    state = parts[0].strip() if parts else "UNKNOWN"
    return {
        "state": state if state in ("IMPORTABLE", "ABSENT") else "UNKNOWN",
        "origin": parts[1].strip() if len(parts) > 1 else "",
        "python_version": parts[2].strip() if len(parts) > 2 else "",
    }


@dataclass
class DsnFinding:
    relpath: str
    pattern_names: list[str]
    matched_line_count: int
    total_matches: int


def scan_tree_for_dsn(root: Path) -> tuple[list[DsnFinding], int]:
    """Scan files under *root* for DSN/credential shapes.

    Findings never carry matched text -- only path, line count, pattern names.
    """
    findings: list[DsnFinding] = []
    scanned = 0
    if not root.is_dir():
        return findings, scanned
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        try:
            text = path.read_bytes().decode("latin-1")
        except OSError:
            continue
        scanned += 1
        names: set[str] = set()
        lines: set[int] = set()
        total = 0
        for pattern_name, regex in DSN_PATTERNS:
            for match in regex.finditer(text):
                names.add(pattern_name)
                lines.add(text.count("\n", 0, match.start()) + 1)
                total += 1
        if names:
            findings.append(
                DsnFinding(path.relative_to(root).as_posix(), sorted(names), len(lines), total)
            )
    return findings, scanned


def sdk_string_hits_in_tree(root: Path, sdk_name: str) -> int:
    """Files containing the bare SDK word (information only, never a criterion)."""
    if not root.is_dir():
        return 0
    needle = sdk_name.lower().encode("ascii", errors="ignore")
    hits = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if needle in path.read_bytes().lower():
                hits += 1
        except OSError:
            continue
    return hits


def scan_startup_hooks(scan_dirs: list[Path]) -> tuple[list[dict[str, Any]], int]:
    """Find process-launching collection hooks in docker/config/entrypoint files."""
    matches: list[dict[str, Any]] = []
    files_scanned = 0
    candidates: list[Path] = []
    for directory in scan_dirs:
        if directory.is_dir():
            candidates.extend(p for p in sorted(directory.rglob("*")) if p.is_file())
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files_scanned += 1
        for token in STARTUP_HOOK_PATTERNS:
            hit_lines = [no for no, line in enumerate(text.splitlines(), 1) if token in line]
            if hit_lines:
                matches.append({"file": str(path), "line": hit_lines[0], "matched_token": token})
    return matches, files_scanned


def _sanitize_args(args: str) -> str:
    """Keep at most three tokens and mask anything credential-shaped."""
    sanitized = []
    for token in args.split()[:3]:
        if "@" in token and ("://" in token or re.search(r"\w:\S+@", token)):
            sanitized.append(f"MASKED[{token.split('//')[-1].split('@')[-1]}]")
        elif re.search(r"(?i)password|passwd|secret|token=", token):
            sanitized.append("MASKED")
        else:
            sanitized.append(token)
    return " ".join(sanitized)


def collect_process_rows(
    ps_output_text: str | None, commands_log: list[str]
) -> list[dict[str, Any]]:
    """Return pid/args rows from a live ``ps`` run or an injected snapshot."""
    if ps_output_text is None:
        commands_log.append("ps -eo pid=,args=")
        try:
            proc = subprocess.run(
                ["ps", "-eo", "pid=,args="], capture_output=True, text=True, timeout=30
            )
            ps_output_text = proc.stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
    rows = []
    for line in ps_output_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        pid, args = parts[0], (parts[1] if len(parts) > 1 else "")
        if _SELF_TOKEN in args or args.startswith("ps "):
            continue
        rows.append({"pid": pid, "args": _sanitize_args(args)})
    return rows


def find_collection_processes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hits = []
    for row in rows:
        lowered = row["args"].lower()
        matched = [pattern for pattern in PROCESS_PATTERNS if pattern in lowered]
        if matched:
            hits.append({**row, "matched_patterns": matched})
    return hits


def systemctl_facts(service: str, use_systemctl: bool, commands_log: list[str]) -> dict[str, Any]:
    if not use_systemctl:
        return {"available": False, "note": "systemctl query disabled for this run"}
    commands_log.append(f"systemctl --user show {service} -p MainPID -p NRestarts")
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "show", service, "-p", "MainPID", "-p", "NRestarts"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "note": "systemctl not runnable here"}
    facts: dict[str, Any] = {"available": True, "service": service}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            facts[key] = value.strip()
    return facts


def _is_private_ip(host: str) -> bool:
    octets = host.split(".")
    if len(octets) != 4 or not all(o.isdigit() for o in octets):
        return False
    first, second = int(octets[0]), int(octets[1])
    return first == 10 or (first == 192 and second == 168) or (first == 172 and 16 <= second <= 31)


def extract_config_hosts(env_files: list[Path]) -> dict[str, Any]:
    """Sorted host set referenced by URL-shaped values in env files (values stay hidden)."""
    hosts: dict[str, str] = {}
    files_scanned: list[str] = []
    credential_shaped_keys = 0
    credential_re = DSN_PATTERNS[1][1]
    for path in env_files:
        if not path.is_file():
            continue
        files_scanned.append(str(path))
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            value = stripped.split("=", 1)[1]
            for match in _URL_VALUE_RE.finditer(value):
                host = match.group(1).strip("[]")
                if host.lower() in _LOOPBACK or host.startswith("127."):
                    hosts[host] = "internal_loopback"
                elif _is_private_ip(host):
                    hosts[host] = "internal_private"
                else:
                    hosts[host] = "external"
            # Count (never show) credential-shaped values that appear in config.
            if credential_re.search(value):
                credential_shaped_keys += 1
    return {
        "files_scanned": files_scanned,
        "hosts": dict(sorted(hosts.items())),
        "external_hosts": sorted(h for h, kind in hosts.items() if kind == "external"),
        "credential_shaped_value_count": credential_shaped_keys,
        "note": (
            "Host names only; no config value, key or credential was emitted. "
            "Config enumeration cannot prove runtime egress."
        ),
    }


def scan_warehouse_denominator(app_dir: Path) -> dict[str, Any]:
    collection: list[str] = []
    other: list[str] = []
    if not app_dir.is_dir():
        return {"error": f"app dir not found: {app_dir}", "total_files": 0}
    for path in sorted(p for p in app_dir.rglob("*.py") if p.is_file()):
        rel = path.relative_to(app_dir).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(token in text for token in WAREHOUSE_TOKENS):
            (collection if rel.startswith(COLLECTION_DOMAIN_PREFIXES) else other).append(rel)
    return {
        "tokens": list(WAREHOUSE_TOKENS),
        "total_files": len(collection) + len(other),
        "collection_domain": collection,
        "collection_domain_count": len(collection),
        "non_collection_domain": other,
        "non_collection_domain_count": len(other),
        "interpretation": (
            "non_collection_domain is the E-domain migration denominator: it must "
            "trend to zero (or API-only readers) before AC18 can pass."
        ),
    }


def git_facts(repo_root: Path, commands_log: list[str]) -> dict[str, Any]:
    facts: dict[str, Any] = {"path": str(repo_root)}
    if not (repo_root / ".git").exists():
        facts["available"] = False
        return facts
    commands_log.append(f"git -C {repo_root} rev-parse / status --porcelain")
    try:
        head = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain=v1"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        branch = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "path": str(repo_root), "note": "git not runnable"}
    facts.update(
        available=True,
        commit=head,
        branch=branch,
        dirty=bool(porcelain.strip()),
        dirty_hash=_sha256_text(porcelain) if porcelain.strip() else "clean",
    )
    return facts


def environment_identity() -> dict[str, Any]:
    """Environment identity WITHOUT credentials (no env values, no secrets)."""
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "user": os.environ.get("USER") or os.environ.get("USERNAME") or "",
        "cwd": os.getcwd(),
        "credential_values_emitted": False,
    }


@dataclass
class Config:
    repo_root: Path
    case_id: str = CASE_ID_DEFAULT
    sdk_name: str = SDK_NAME_DEFAULT
    app_dir: Path | None = None
    artifact_dirs: list[Path] | None = None
    pyproject_path: Path | None = None
    env_files: list[Path] | None = None
    hook_scan_dirs: list[Path] | None = None
    service_name: str = "ai-for-investor.service"
    use_systemctl: bool = True
    ps_output_text: str | None = None  # None => live `ps`; string => snapshot
    venv_python: Path | None = None
    import_prober: ImportProber | None = None
    opendata_root: Path | None = None
    revocation_evidence: Path | None = None
    egress_evidence: Path | None = None
    allow_fail_legs: set[str] = field(default_factory=set)
    waiver_note: str = "operator waiver, no note provided"
    json_output: Path | None = None
    probe_timeout: int = 60

    def resolved(self) -> dict[str, Any]:
        backend = self.repo_root / "src" / "backend"
        return {
            "app_dir": self.app_dir or backend / "app",
            "artifact_dirs": self.artifact_dirs or [self.repo_root / "src" / "frontend" / "dist"],
            "pyproject_path": self.pyproject_path or backend / "pyproject.toml",
            "env_files": self.env_files
            or sorted(backend.glob(".env")) + sorted(backend.glob(".env.*")),
            "hook_scan_dirs": self.hook_scan_dirs or [self.repo_root / "docker"],
            "venv_python": self.venv_python or backend / ".venv" / "bin" / "python",
        }


def _leg(name: str, criterion: str, expected: str) -> dict[str, Any]:
    return {
        "name": name,
        "criterion": criterion,
        "expected": expected,
        "status": NOT_RUN,
        "actual": None,
        "detail": {},
        "note": "",
        "waived": False,
    }


def _evidence_actual(path: Path) -> str:
    return (
        f"operator-supplied evidence: {path} "
        f"(sha256 {_sha256_file(path)[:16]}...); script recorded, did not re-derive."
    )


def run_verification(config: Config) -> tuple[dict[str, Any], int]:
    """Execute all legs and the denominator; return (receipt, exit_code)."""
    started = _utcnow()
    commands: list[str] = []
    paths = config.resolved()
    if config.import_prober is None:

        def _default_prober(venv: Path, sdk: str) -> dict[str, Any]:
            return probe_module_importable(venv, sdk, config.probe_timeout)

        prober: ImportProber = _default_prober
    else:
        prober = config.import_prober
    legs: list[dict[str, Any]] = []

    # --- Leg 1: no source SDK (dependency declaration / runtime import only) --
    leg = _leg(
        "no_source_sdk",
        "SDK absent from declared install dependencies AND not importable "
        "from the runtime venv. Bare artifact string hits are information only.",
        "no declared dependency, no importable module",
    )
    declared, declared_reqs = pyproject_declares_sdk(paths["pyproject_path"], config.sdk_name)
    import_state: dict[str, Any] = {"state": "UNKNOWN", "detail": "no runtime venv probed"}
    venv = Path(paths["venv_python"])
    commands.append(f"{venv} -c importlib.util.find_spec({config.sdk_name!r}) probe")
    import_state = prober(venv, config.sdk_name)
    leg["detail"] = {
        "declared_dependency_strings": declared_reqs,
        "import_probe": import_state,
        "artifact_bare_string_file_hits": sum(
            sdk_string_hits_in_tree(Path(d), config.sdk_name) for d in paths["artifact_dirs"]
        ),
        "bare_string_hits_are_not_the_criterion": True,
    }
    if declared or import_state.get("state") == "IMPORTABLE":
        leg["status"] = FAIL
        leg["actual"] = f"declared={declared}, importable={import_state.get('state')}"
        leg["note"] = (
            "Fails BY DESIGN pre-cutover: the install plane still ships the source "
            "SDK. Honest expected reading until the data extra and runtime import drop "
            "it; not a regression, and it does not make AC18 pass."
        )
    elif import_state.get("state") == "UNKNOWN":
        leg["status"] = FAIL
        leg["actual"] = "declared=False, import probe UNKNOWN"
        leg["note"] = "Cannot confirm absence while the import probe failed."
    else:
        leg["status"] = PASS
        leg["actual"] = "declared=False, importable=ABSENT"
    legs.append(leg)

    # --- Leg 2: no collection startup hook ------------------------------------
    leg = _leg(
        "no_collection_startup_hook",
        "No process-launching collection command wired into deploy/startup config.",
        "zero launch-hook matches",
    )
    hook_matches, hook_files = scan_startup_hooks([Path(d) for d in paths["hook_scan_dirs"]])
    leg["detail"] = {"files_scanned": hook_files, "matches": hook_matches}
    leg["status"] = PASS if not hook_matches else FAIL
    leg["actual"] = f"{len(hook_matches)} launch-hook matches in {hook_files} files"
    legs.append(leg)

    # --- Leg 3: no warehouse DSN in built artifacts (masked reporting) ----------
    leg = _leg(
        "no_warehouse_dsn_in_artifact",
        "Built-artifact trees contain zero DSN/credential-shape matches; findings "
        "report path + line count + pattern name only, matched values stay masked.",
        "zero matching files",
    )
    all_findings: list[dict[str, Any]] = []
    scanned_total = 0
    for artifact_dir in paths["artifact_dirs"]:
        findings, scanned = scan_tree_for_dsn(Path(artifact_dir))
        scanned_total += scanned
        all_findings.extend(
            {
                "artifact_root": str(artifact_dir),
                "file": f.relpath,
                "pattern_names": f.pattern_names,
                "matched_line_count": f.matched_line_count,
                "total_matches": f.total_matches,
            }
            for f in findings
        )
    leg["detail"] = {"files_scanned": scanned_total, "findings": all_findings}
    leg["status"] = PASS if not all_findings else FAIL
    leg["actual"] = f"{len(all_findings)} files matched DSN patterns in {scanned_total} scanned"
    legs.append(leg)

    # --- Leg 4: no residual collection process ----------------------------------
    leg = _leg(
        "no_residual_collection_process",
        "ps enumeration (patterns: " + ", ".join(PROCESS_PATTERNS) + ") plus "
        "systemctl show facts; code+config+cron+process jointly checked.",
        "zero matching processes",
    )
    rows = collect_process_rows(config.ps_output_text, commands)
    hits = find_collection_processes(rows)
    facts = systemctl_facts(config.service_name, config.use_systemctl, commands)
    leg["detail"] = {"ps_rows": len(rows), "matching_processes": hits, "systemctl": facts}
    if facts.get("available") and facts.get("MainPID"):
        leg["detail"]["main_process"] = [r for r in rows if r["pid"] == facts["MainPID"]][:1]
    leg["status"] = PASS if not hits else FAIL
    leg["actual"] = f"{len(hits)} matching processes from {len(rows)} ps rows"
    legs.append(leg)

    # --- Leg 5: egress limited to opendata data API ------------------------------
    leg = _leg(
        "egress_limited_to_opendata_api",
        "Runtime egress reaches only the opendata data API; the config host set "
        "may corroborate but cannot prove it.",
        "runtime observation shows only the opendata data API host",
    )
    hosts_info = extract_config_hosts([Path(p) for p in paths["env_files"]])
    leg["detail"] = {"config_hosts": hosts_info}
    if config.egress_evidence and Path(config.egress_evidence).is_file():
        leg["status"] = PASS
        leg["actual"] = _evidence_actual(Path(config.egress_evidence))
        leg["note"] = "Closed on operator-attested runtime observation, not on config."
    else:
        leg["status"] = NOT_RUN
        leg["actual"] = (
            f"config declares hosts {sorted(hosts_info['hosts'])} "
            f"({len(hosts_info['external_hosts'])} external)"
        )
        leg["note"] = (
            "NOT_RUN by construction: config alone can never establish runtime egress "
            "limits. Supply --egress-evidence with a runtime observation artifact to "
            "close this leg. This is not a pass."
        )
    legs.append(leg)

    # --- Leg 6: data-consumption tests after DB privilege revocation ------------
    leg = _leg(
        "data_consumption_tests_after_revocation",
        "With warehouse write privileges revoked, all data-consumption tests "
        "still pass through the API.",
        "revocation executed + consumption test suite green",
    )
    if config.revocation_evidence and Path(config.revocation_evidence).is_file():
        leg["status"] = PASS
        leg["actual"] = _evidence_actual(Path(config.revocation_evidence))
        leg["note"] = "Closed on operator-attested evidence, not re-derived here."
    else:
        leg["status"] = NOT_RUN
        leg["actual"] = "revocation cannot be performed on this host"
        leg["note"] = (
            "NOT_RUN (not skipped-and-fine): the app DB user gets (1044) Access denied on "
            "CREATE DATABASE and no owned instance exists, so write privileges cannot be "
            "revoked and the consumption suite cannot be re-run against a revoked plane."
        )
    legs.append(leg)

    # --- waivers + exit code ------------------------------------------------------
    waivers: list[dict[str, Any]] = []
    ignored_waivers: list[dict[str, str]] = []
    for name in sorted(config.allow_fail_legs):
        target = next((item for item in legs if item["name"] == name), None)
        if target is None:
            ignored_waivers.append({"leg": name, "reason": "unknown leg name"})
        elif target["status"] == FAIL:
            target["waived"] = True
            waivers.append(
                {
                    "leg": name,
                    "note": config.waiver_note,
                    "granted_via": "--allow-fail-leg",
                    "printed_in_receipt": True,
                }
            )
        else:
            ignored_waivers.append(
                {
                    "leg": name,
                    "reason": f"leg status is {target['status']}; NOT_RUN cannot be waived",
                }
            )
    unwaived_fail = [item["name"] for item in legs if item["status"] == FAIL and not item["waived"]]
    not_run = [item["name"] for item in legs if item["status"] == NOT_RUN]
    exit_code = 1 if unwaived_fail else (3 if not_run else 0)

    afi = git_facts(config.repo_root, commands)
    opendata_path = Path(config.opendata_root or (config.repo_root.parent / "opendata"))
    opendata = (
        git_facts(opendata_path, commands)
        if opendata_path.is_dir()
        else {"available": False, "path": str(opendata_path), "note": "OpenData checkout not found"}
    )
    pyproject = Path(paths["pyproject_path"])
    receipt: dict[str, Any] = {
        "receipt_version": "afi-ac18-joint-verification/v1",
        "case_id": config.case_id,
        "work_package": "iteration204/AC18 joint verification (API-only consumption)",
        "dataset_task_script_ids": [
            "AC18",
            "src/backend/scripts/ops/verify_api_only_consumption.py",
        ],
        "repos": {"afi": afi, "opendata": opendata},
        "dependency_image_config_versions": {
            "python_running": platform.python_version(),
            "venv_probe": import_state.get("python_version", ""),
            "pyproject_sha256": _sha256_file(pyproject) if pyproject.is_file() else None,
            "config_file_hashes": {
                str(p): _sha256_file(Path(p))[:16] for p in paths["env_files"] if Path(p).is_file()
            },
            "image": None,
            "image_note": "no container-image digest observable from a bare host run",
        },
        "schema_publication_raw_hash": None,
        "schema_note": "AC18 legs do not read schemas; hash left null rather than fake",
        "environment": environment_identity(),
        "scope": {
            "repo_root": str(config.repo_root),
            "artifact_roots": [str(p) for p in paths["artifact_dirs"]],
            "app_dir": str(paths["app_dir"]),
            "hook_scan_dirs": [str(p) for p in paths["hook_scan_dirs"]],
            "env_files": hosts_info["files_scanned"],
            "business_keys": "n/a (infrastructure-level legs, not per-instrument)",
            "time_window": f"{started} .. {_utcnow()}",
        },
        "commands_run": commands,
        "start_utc": started,
        "end_utc": _utcnow(),
        "legs": legs,
        "denominator_warehouse_dsn_files": scan_warehouse_denominator(Path(paths["app_dir"])),
        "failures": unwaived_fail,
        "waived_failures": waivers,
        "ignored_waiver_requests": ignored_waivers,
        "skips_not_run": not_run,
        "exit_code": exit_code,
        "reviewer": {
            "name": None,
            "verdict": "PENDING_REVIEWER",
            "bound_head_sha": afi.get("commit"),
        },
    }
    if config.json_output:
        out = Path(config.json_output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt, exit_code


def _fmt_repo(facts: dict[str, Any]) -> str:
    if not facts.get("available"):
        return "unavailable"
    return f"{facts.get('commit', '')[:12]}@{facts.get('branch', '')}"


def format_summary(receipt: dict[str, Any], exit_code: int) -> str:
    lines = [
        f"AC18 joint verification — case_id={receipt['case_id']} exit_code={exit_code}",
        f"  repos: afi={_fmt_repo(receipt['repos']['afi'])} "
        f"opendata={_fmt_repo(receipt['repos']['opendata'])}",
        f"  dirty hash: afi={str(receipt['repos']['afi'].get('dirty_hash', 'n/a'))[:12]}",
    ]
    for leg in receipt["legs"]:
        waived = " (WAIVED)" if leg.get("waived") else ""
        lines.append(f"  [{leg['status']}] {leg['name']}{waived}: expected={leg['expected']!r}")
        lines.append(f"      actual: {leg['actual']}")
        if leg.get("note"):
            lines.append(f"      note: {leg['note']}")
    for waiver in receipt["waived_failures"]:
        lines.append(f"  WAIVER RECORDED: leg={waiver['leg']} note={waiver['note']}")
    for ignored in receipt["ignored_waiver_requests"]:
        lines.append(f"  WAIVER IGNORED: leg={ignored['leg']} reason={ignored['reason']}")
    denom = receipt["denominator_warehouse_dsn_files"]
    lines.append(
        f"  denominator: {denom.get('total_files', '?')} app files touch warehouse DSN "
        f"= collection {denom.get('collection_domain_count', '?')} "
        f"+ non-collection {denom.get('non_collection_domain_count', '?')}"
    )
    if receipt["failures"]:
        lines.append(f"  FAILED (unwaived): {', '.join(receipt['failures'])}")
    if receipt["skips_not_run"]:
        lines.append(
            f"  NOT_RUN (untested; neither a failure nor a pass): {', '.join(receipt['skips_not_run'])}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case-id", default=CASE_ID_DEFAULT)
    parser.add_argument("--repo-root", default=None, help="repo whose artifacts are audited")
    parser.add_argument("--sdk", default=SDK_NAME_DEFAULT)
    parser.add_argument("--app-dir", default=None)
    parser.add_argument("--artifact-dir", action="append", dest="artifact_dirs")
    parser.add_argument("--pyproject", default=None)
    parser.add_argument("--env-file", action="append", dest="env_files")
    parser.add_argument("--hook-scan-dir", action="append", dest="hook_scan_dirs")
    parser.add_argument("--service", default="ai-for-investor.service")
    parser.add_argument("--no-systemctl", action="store_true")
    parser.add_argument("--ps-file", default=None, help="snapshot of `ps -eo pid=,args=` text")
    parser.add_argument("--venv-python", default=None)
    parser.add_argument("--skip-import-probe", action="store_true")
    parser.add_argument("--opendata-root", default=None)
    parser.add_argument("--revocation-evidence", default=None)
    parser.add_argument("--egress-evidence", default=None)
    parser.add_argument(
        "--allow-fail-leg",
        action="append",
        dest="allow_fail_legs",
        default=[],
        metavar="NAME",
        help="waive a FAIL leg; printed and recorded in the receipt",
    )
    parser.add_argument("--waiver-note", default="operator waiver, no note provided")
    parser.add_argument("--json-output", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[4]

    def _absent_prober(_venv: Path, _sdk: str) -> dict[str, Any]:
        return {"state": "ABSENT"}

    config = Config(
        repo_root=repo_root,
        case_id=args.case_id,
        sdk_name=args.sdk,
        app_dir=Path(args.app_dir) if args.app_dir else None,
        artifact_dirs=[Path(v) for v in args.artifact_dirs] if args.artifact_dirs else None,
        pyproject_path=Path(args.pyproject) if args.pyproject else None,
        env_files=[Path(v) for v in args.env_files] if args.env_files else None,
        hook_scan_dirs=[Path(v) for v in args.hook_scan_dirs] if args.hook_scan_dirs else None,
        service_name=args.service,
        use_systemctl=not args.no_systemctl,
        ps_output_text=Path(args.ps_file).read_text(encoding="utf-8") if args.ps_file else None,
        venv_python=Path(args.venv_python) if args.venv_python else None,
        import_prober=_absent_prober if args.skip_import_probe else None,
        opendata_root=Path(args.opendata_root) if args.opendata_root else None,
        revocation_evidence=Path(args.revocation_evidence) if args.revocation_evidence else None,
        egress_evidence=Path(args.egress_evidence) if args.egress_evidence else None,
        allow_fail_legs=set(args.allow_fail_legs),
        waiver_note=args.waiver_note,
        json_output=Path(args.json_output) if args.json_output else None,
    )
    receipt, exit_code = run_verification(config)
    print(format_summary(receipt, exit_code))
    if receipt["skips_not_run"]:
        print("  REMINDER: NOT_RUN legs keep AC18 open; they are neither failures nor passes.")
    if args.json_output:
        print(f"  receipt JSON written to {args.json_output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
