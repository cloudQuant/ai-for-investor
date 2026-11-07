"""Verify the target database identity before the recovery plane dispatches a write.

Iteration 204 AC12 requires preflighting package/environment/**database** identity and
exiting immediately on the wrong target. The recovery/collection plane may only write to
the metadata database (``ai_for_investor``) or the market-data warehouse
(``akshare_data``); the application-dedicated ``backtrader_web`` database must never
receive a managed write.

Public API (dependency-light; stdlib only at import time)
---------------------------------------------------------
* :func:`expected_database_names` - documented default set, overridable by the
  ``AFI_EXPECTED_DATABASE_NAMES`` environment variable; never hardcoded per machine.
* :func:`resolve_database_identity` - ask the *server* who it is and return a
  :class:`DatabaseIdentity`.
* :func:`assert_write_target_allowed` - turn an identity plus a run mode into a
  :class:`Verdict` in the worker's JSON vocabulary.
* :func:`guard_write_target` - the attachable call site: resolve, judge, and never raise
  for an expected failure. It is the single function a caller needs before dispatching.
* :func:`main` - CLI for manual preflight; prints only sanitized JSON.

Wiring note: ``scripts/ops/run_full_history_recovery_worker.py`` lands on ``dev`` only
after PR #273 merges. This module deliberately does not import or edit that worker; after
it merges, the apply path calls ``guard_write_target(dsn, "apply")`` before dispatch and
returns ``Verdict.as_payload()`` verbatim when the verdict is not allowed.

Identity protocol
-----------------
The DSN's path segment is never trusted: a proxy or alias DSN can resolve to a different
database. Identity is the name the server reports for the live connection
(``SELECT DATABASE()`` for MySQL, ``SELECT current_database()`` for PostgreSQL). The
``information_schema`` schema listing is recorded as corroborating evidence, not used as a
second veto: a server may legitimately host only one of the two expected databases. A
connection that cannot be opened, or a name that cannot be read, is a refusal (fail
closed), never a pass.

Credential hygiene
------------------
Recorded evidence is limited to the database name, the host/port (never the userinfo
part), and the server version. Every driver exception is caught and run through
:func:`redact_secrets` before it can reach a message, a verdict, or stdout, so a traceback
or ``argv`` repr cannot leak a password or the full DSN.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

__all__ = [
    "DEFAULT_EXPECTED_DATABASE_NAMES",
    "DEFAULT_EXPECTED_METADATA_DATABASE",
    "DEFAULT_EXPECTED_WAREHOUSE_DATABASE",
    "EXPECTED_DATABASE_NAMES_ENV",
    "READ_ONLY_MODES",
    "WRITE_MODES",
    "DatabaseIdentity",
    "Verdict",
    "WarehouseIdentityError",
    "assert_write_target_allowed",
    "expected_database_names",
    "guard_write_target",
    "main",
    "normalize_database_name",
    "redact_secrets",
    "resolve_database_identity",
]

EXPECTED_DATABASE_NAMES_ENV = "AFI_EXPECTED_DATABASE_NAMES"
DEFAULT_EXPECTED_METADATA_DATABASE = "ai_for_investor"
DEFAULT_EXPECTED_WAREHOUSE_DATABASE = "akshare_data"
DEFAULT_EXPECTED_DATABASE_NAMES: tuple[str, ...] = (
    DEFAULT_EXPECTED_METADATA_DATABASE,
    DEFAULT_EXPECTED_WAREHOUSE_DATABASE,
)

WRITE_MODES: frozenset[str] = frozenset({"apply", "write"})
READ_ONLY_MODES: frozenset[str] = frozenset({"plan", "dry_run", "read_only"})
MODE_ALIASES: frozenset[str] = WRITE_MODES | READ_ONLY_MODES
_REFUSAL_EXIT_CODE = 2
_MAX_MESSAGE_CHARS = 300

# Quoted/blank-padded server answers are the same identifier to the server.
_QUOTED_IDENTIFIER_PAIRS = (("`", "`"), ('"', '"'), ("'", "'"), ("[", "]"))

# Any ``scheme://[user:pass@]host/path`` URL appearing inside free-form text: the userinfo
# portion is stripped so a driver error naming the target cannot leak credentials.
_URL_USERINFO_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)[^/?#\s@]*@")
_REDACTION = "<redacted>"


@dataclass(frozen=True)
class DatabaseIdentity:
    """What the *server* reported about the live connection, with secrets stripped.

    Attributes:
        database_name: Server-reported current database; ``None`` when undeterminable.
        server_version: Server-reported version string, or ``None`` when unavailable.
        host_label: ``host[:port]`` from the DSN userinfo-free portion, never credentials.
        dsn_path_database: Normalized name from the DSN path; evidence only, never trusted.
        hosted_schemas: Schemas the server lists in ``information_schema`` (best effort).
        expected_database_names: Names accepted as valid write targets.
        probe_errors: Sanitized probe failure descriptions (no credentials).
    """

    database_name: str | None
    server_version: str | None = None
    host_label: str | None = None
    dsn_path_database: str | None = None
    hosted_schemas: tuple[str, ...] = ()
    expected_database_names: tuple[str, ...] = DEFAULT_EXPECTED_DATABASE_NAMES
    probe_errors: tuple[str, ...] = ()

    def as_evidence(self) -> dict[str, Any]:
        """Return the recorded evidence; contains no DSN and no credential material."""
        return {
            "server_reported_database": self.database_name,
            "dsn_path_database": self.dsn_path_database,
            "host": self.host_label,
            "server_version": self.server_version,
            "hosted_schemas": list(self.hosted_schemas),
            "expected_database_names": list(self.expected_database_names),
            "probe_errors": list(self.probe_errors),
        }


@dataclass(frozen=True)
class Verdict:
    """Guard decision expressed in the recovery worker's JSON vocabulary.

    Attributes:
        allowed: Whether the requested run may proceed.
        mode: Normalized requested mode.
        status: ``ok`` when allowed, else the worker's ``attention_required``.
        exit_code: Process exit code the caller should use.
        write_possible: Whether the guard authorizes a managed write to proceed. It
            describes authorization only; it never claims a write already happened.
        source_failure_recorded: Always ``False``: a wrong target is an operator fault,
            so the guard must not fabricate a source failure or controller cooldown.
        attention_required: Mirrors the worker's attention flag.
        reasons: Sanitized human-readable refusal/allowance reasons.
        evidence: :meth:`DatabaseIdentity.as_evidence` output, or the refusal evidence.
    """

    allowed: bool
    mode: str
    status: str
    exit_code: int
    write_possible: bool
    source_failure_recorded: bool
    attention_required: bool
    reasons: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        """Return the JSON payload the worker envelope expects."""
        return {
            "mode": self.mode,
            "status": self.status,
            "exit_code": self.exit_code,
            "allowed": self.allowed,
            "attention_required": self.attention_required,
            "batch_started": False,
            "write_possible": self.write_possible,
            "source_failure_recorded": self.source_failure_recorded,
            "reasons": list(self.reasons),
            "evidence": self.evidence,
        }


class WarehouseIdentityError(RuntimeError):
    """Raised when the target identity cannot be established safely.

    The message is always credential-redacted, so re-raising or logging it is safe.
    """


def normalize_database_name(raw: object) -> str | None:
    """Normalize a server/DSN identifier: trim whitespace, drop quotes, casefold.

    Args:
        raw: Candidate name from the server, the DSN path, or configuration.

    Returns:
        The normalized name, or ``None`` when nothing usable remains.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    changed = True
    while changed and text:
        changed = False
        for opener, closer in _QUOTED_IDENTIFIER_PAIRS:
            if len(text) >= 2 and text.startswith(opener) and text.endswith(closer):
                text = text[1:-1].strip()
                changed = True
    if not text:
        return None
    # A server answer may already carry a fully qualified ``db.table`` form.
    return text.split(".", 1)[0].casefold()


def expected_database_names(environment: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Return the accepted write-target database names.

    The documented default is the metadata database plus the market-data warehouse.
    ``AFI_EXPECTED_DATABASE_NAMES`` (comma separated) overrides it so the expectation is
    configuration, never a per-machine hardcode.

    Args:
        environment: Optional mapping used instead of ``os.environ``.

    Returns:
        Normalized, de-duplicated, order-preserving expected names.
    """
    source = os.environ if environment is None else environment
    override = (source.get(EXPECTED_DATABASE_NAMES_ENV) or "").strip()
    candidates: Iterable[str] = override.split(",") if override else DEFAULT_EXPECTED_DATABASE_NAMES
    names: list[str] = []
    for candidate in candidates:
        normalized = normalize_database_name(candidate)
        if normalized and normalized not in names:
            names.append(normalized)
    return tuple(names) or DEFAULT_EXPECTED_DATABASE_NAMES


def _secret_tokens(dsn: str | None) -> tuple[str, ...]:
    """Collect credential substrings that must never leave the guard."""
    if not dsn:
        return ()
    tokens: list[str] = [dsn]
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return tuple(tokens)
    for token in (parts.password, parts.username):
        if token:
            tokens.append(str(token))
    if parts.netloc:
        tokens.append(parts.netloc)
    return tuple(dict.fromkeys(tokens))


def redact_secrets(text: object, secrets: Iterable[str] = ()) -> str:
    """Strip credential material from arbitrary text (driver errors, argv reprs, URLs).

    Any ``scheme://...`` URL substring is rewritten without its userinfo, every known
    secret token is replaced, and the result is length bounded.

    Args:
        text: Raw message, typically from a caught exception.
        secrets: Exact tokens to remove, e.g. the DSN and its password.

    Returns:
        A sanitized, bounded single-line message.
    """
    message = " ".join(str(text).split())
    for token in secrets:
        if token and len(str(token)) >= 3:
            message = message.replace(str(token), _REDACTION)
    message = _URL_USERINFO_RE.sub(rf"\1{_REDACTION}@", message)
    if len(message) > _MAX_MESSAGE_CHARS:
        message = message[:_MAX_MESSAGE_CHARS] + "..."
    return message or _REDACTION


def _host_label(dsn: str) -> str | None:
    """Return ``host[:port]`` from a DSN, never the userinfo portion."""
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return None
    if not parts.hostname:
        return None
    if parts.port:
        return f"{parts.hostname}:{parts.port}"
    return str(parts.hostname)


def _dsn_path_database(dsn: str) -> str | None:
    """Normalized database name from the DSN path (evidence only, never trusted)."""
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return None
    path = (parts.path or "").lstrip("/")
    if not path:
        return None
    return normalize_database_name(path.split("?", 1)[0])


def _resolve_dsn(dsn_or_env: str, environment: Mapping[str, str]) -> tuple[str | None, str | None]:
    """Accept a literal DSN or the name of an environment variable holding one.

    Returns:
        A ``(dsn, refusal_reason)`` pair; exactly one entry is set.
    """
    value = (dsn_or_env or "").strip()
    if not value:
        return None, "no_target_dsn_supplied"
    if "://" in value:
        return value, None
    from_env = (environment.get(value) or "").strip()
    if not from_env:
        return None, f"environment_variable_empty_or_missing: {redact_secrets(value)}"
    if "://" not in from_env:
        return None, f"environment_value_is_not_a_dsn: {redact_secrets(value)}"
    return from_env, None


def _drivername_parts(dsn: str) -> tuple[str, str]:
    """Return ``(dialect, driver)`` of a SQLAlchemy-style URL, e.g. ``mysql, pymysql``."""
    scheme = urlsplit(dsn).scheme.strip().lower()
    dialect, _, driver = scheme.partition("+")
    return dialect, driver


def _open_default_connection(dsn: str) -> Any:
    """Open a synchronous DB-API connection using the installed driver.

    Args:
        dsn: SQLAlchemy-style URL with a MySQL or PostgreSQL dialect.

    Returns:
        A DB-API connection object.

    Raises:
        WarehouseIdentityError: No synchronous driver is importable for the dialect, or
            the connection could not be made. Messages are credential-redacted.
    """
    dialect, driver = _drivername_parts(dsn)
    parts = urlsplit(dsn)
    module_name = {
        "mysql": driver if driver.startswith("mysql") else "pymysql",
        "postgresql": driver if driver in {"psycopg2", "psycopg"} else "psycopg2",
    }.get(dialect)
    if module_name is None:
        raise WarehouseIdentityError(
            f"unsupported_driver_for_server_identity: dialect={redact_secrets(dialect or 'unknown')}"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise WarehouseIdentityError(
            f"driver_unavailable: {redact_secrets(module_name)} ({redact_secrets(exc)})"
        ) from exc
    database = (parts.path or "").lstrip("/")
    kwargs: dict[str, Any] = {
        "host": parts.hostname,
        "port": parts.port or (5432 if dialect == "postgresql" else 3306),
        "user": parts.username,
        "password": parts.password or "",
        "autocommit": True,
    }
    if database:
        kwargs["database"] = database
    if dialect == "mysql":
        kwargs["read_timeout"] = 15
    try:
        return module.connect(**kwargs)
    except Exception as exc:  # driver-specific; never let its repr escape unredacted
        raise WarehouseIdentityError(
            f"connection_failed: {redact_secrets(exc, _secret_tokens(dsn))}"
        ) from exc


def _run_probe(connection: Any, sql: str, secrets: Iterable[str] = ()) -> list[Any]:
    """Execute a read-only probe and return its rows; raises ``WarehouseIdentityError``."""
    try:
        cursor = connection.cursor()
    except Exception as exc:
        raise WarehouseIdentityError(f"cursor_unavailable: {redact_secrets(exc, secrets)}") from exc
    try:
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
        except Exception as exc:
            raise WarehouseIdentityError(f"probe_rejected: {redact_secrets(exc, secrets)}") from exc
    finally:
        try:
            cursor.close()
        except Exception:  # pragma: no cover - close must never mask the decision
            pass
    return list(rows or [])


def _row_scalar(row: Any) -> Any:
    """Reduce one DB-API row to its first column; drivers hand back tuples, not strings."""
    if isinstance(row, (tuple, list)):
        return row[0] if row else None
    return row


def _first_scalar(rows: Sequence[Any]) -> Any:
    for row in rows:
        return _row_scalar(row)
    return None


_NAME_PROBES: tuple[str, ...] = ("SELECT DATABASE()", "SELECT current_database()")
_VERSION_PROBES: tuple[str, ...] = ("SELECT VERSION()", "SELECT version()")
_SCHEMA_LIST_PROBES: tuple[str, ...] = (
    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA",
    "SELECT schema_name FROM information_schema.schemata",
)


def resolve_database_identity(
    dsn_or_env: str,
    *,
    environment: Mapping[str, str] | None = None,
    connect: Callable[[str], Any] | None = None,
    connection: Any = None,
) -> DatabaseIdentity:
    """Establish who the target *server* says it is.

    Args:
        dsn_or_env: Literal DSN, or the name of an environment variable holding one.
        environment: Mapping consulted for the DSN and the expected-name override.
        connect: Optional DSN-to-connection factory (injected in tests); defaults to the
            installed synchronous driver.
        connection: Optional already-open DB-API connection; takes precedence.

    Returns:
        A :class:`DatabaseIdentity` whose ``database_name`` is the server answer.

    Raises:
        WarehouseIdentityError: The DSN is unusable, the connection cannot be made, or the
            server's current database cannot be determined. Fail closed. Every message is
            credential-redacted.
    """
    env: Mapping[str, str] = os.environ if environment is None else environment
    dsn, dsn_refusal = _resolve_dsn(dsn_or_env, env)
    if dsn is None:
        raise WarehouseIdentityError(redact_secrets(dsn_refusal or "no_target_dsn_supplied"))

    secrets = _secret_tokens(dsn)
    expected = expected_database_names(env)
    host_label = _host_label(dsn)
    dsn_path_database = _dsn_path_database(dsn)

    own_connection = None
    target = connection
    try:
        if target is None:
            factory = connect if connect is not None else _open_default_connection
            try:
                own_connection = factory(dsn)
            except WarehouseIdentityError:
                raise
            except Exception as exc:  # factory may raise anything
                raise WarehouseIdentityError(
                    f"connection_failed: {redact_secrets(exc, secrets)}"
                ) from exc
            target = own_connection
        if target is None:
            raise WarehouseIdentityError("connection_failed: no connection object")

        probe_errors: list[str] = []
        database_name: str | None = None
        for sql in _NAME_PROBES:
            try:
                answer = _first_scalar(_run_probe(target, sql, secrets))
            except WarehouseIdentityError as exc:
                probe_errors.append(str(exc))
                continue
            database_name = normalize_database_name(answer)
            if database_name is None:
                probe_errors.append("server_answered_null_database")
            break
        if database_name is None:
            detail = probe_errors[-1] if probe_errors else "no_supported_identity_probe"
            raise WarehouseIdentityError(f"identity_undeterminable: {detail}")

        server_version: str | None = None
        for sql in _VERSION_PROBES:
            try:
                answer = _first_scalar(_run_probe(target, sql, secrets))
            except WarehouseIdentityError:
                continue
            if answer is not None:
                server_version = redact_secrets(answer, secrets)
                break

        hosted_schemas: tuple[str, ...] = ()
        for sql in _SCHEMA_LIST_PROBES:
            try:
                rows = _run_probe(target, sql, secrets)
            except WarehouseIdentityError:
                continue
            names = [normalize_database_name(_row_scalar(row)) for row in rows]
            hosted_schemas = tuple(dict.fromkeys(n for n in names if n))
            break

        return DatabaseIdentity(
            database_name=database_name,
            server_version=server_version,
            host_label=host_label,
            dsn_path_database=dsn_path_database,
            hosted_schemas=hosted_schemas,
            expected_database_names=expected,
            probe_errors=tuple(dict.fromkeys(probe_errors)),
        )
    finally:
        if own_connection is not None:
            try:
                own_connection.close()
            except Exception:  # pragma: no cover - teardown is best effort
                pass


def _normalized_mode(mode: object) -> str:
    return str(mode or "").strip().casefold()


def _identity_notes(identity: DatabaseIdentity) -> tuple[str, ...]:
    """Evidence notes that accompany an allowed verdict without vetoing the run.

    The ``information_schema`` listing is corroborating evidence, not a second veto: a
    deployment may legitimately host only one of the two databases on a given server, so a
    missing peer schema is reported, never invented into a refusal or a pass claim. A name
    outside the expected set is still refused by :func:`assert_write_target_allowed`.
    """
    if not identity.hosted_schemas:
        return ("information_schema_listing_unavailable: identity rests on the server answer",)
    missing = [
        name for name in identity.expected_database_names if name not in identity.hosted_schemas
    ]
    if missing:
        return (f"expected_schema_not_hosted_by_target_server: {', '.join(missing)}",)
    return ()


def assert_write_target_allowed(identity: DatabaseIdentity | None, mode: str = "apply") -> Verdict:
    """Decide whether a dispatch may proceed against this identity.

    Args:
        identity: Resolved server identity, or ``None``/unresolved when resolution failed.
        mode: ``apply``/``write`` for managed writes; ``plan``/``dry_run``/``read_only``
            for a read-only run. Anything else is refused.

    Returns:
        A :class:`Verdict`. A write outside the expected set fails closed: nonzero exit,
        ``status=attention_required``, ``write_possible=False``,
        ``source_failure_recorded=False``. A read-only mismatch is reported prominently
        with the same vocabulary instead of being dressed up as safe.
    """
    normalized = _normalized_mode(mode)
    expected = (
        tuple(identity.expected_database_names) if identity else DEFAULT_EXPECTED_DATABASE_NAMES
    )
    evidence = identity.as_evidence() if identity else {"server_reported_database": None}

    if normalized not in MODE_ALIASES:
        return Verdict(
            allowed=False,
            mode=normalized or "unknown",
            status="attention_required",
            exit_code=_REFUSAL_EXIT_CODE,
            write_possible=False,
            source_failure_recorded=False,
            attention_required=True,
            reasons=("unknown_mode_refused: expected apply/write or plan/dry_run/read_only",),
            evidence=evidence,
        )

    if identity is None or identity.database_name is None:
        return Verdict(
            allowed=False,
            mode=normalized,
            status="attention_required",
            exit_code=_REFUSAL_EXIT_CODE,
            write_possible=False,
            source_failure_recorded=False,
            attention_required=True,
            reasons=("identity_undeterminable_refused: server database name could not be read",),
            evidence=evidence,
        )

    if identity.database_name in expected:
        is_write = normalized in WRITE_MODES
        return Verdict(
            allowed=True,
            mode=normalized,
            status="ok",
            exit_code=0,
            write_possible=is_write,
            source_failure_recorded=False,
            attention_required=False,
            reasons=(
                f"server_reported_target_allowed: {identity.database_name}",
                *_identity_notes(identity),
            ),
            evidence=evidence,
        )

    mismatch = (
        f"unexpected_target_database: server reported {identity.database_name} "
        f"but only {', '.join(expected)} are valid write targets"
    )
    reasons = [mismatch]
    if identity.dsn_path_database and identity.dsn_path_database != identity.database_name:
        reasons.append(
            "dsn_path_disagrees_with_server: "
            f"dsn_path={identity.dsn_path_database} server={identity.database_name}; "
            "the server answer decides"
        )
    reasons.append(
        "read_only_run_mismatch_is_not_safe"
        if normalized in READ_ONLY_MODES
        else "write_dispatch_blocked_before_any_batch"
    )
    return Verdict(
        allowed=False,
        mode=normalized,
        status="attention_required",
        exit_code=_REFUSAL_EXIT_CODE,
        write_possible=False,
        source_failure_recorded=False,
        attention_required=True,
        reasons=tuple(reasons),
        evidence=evidence,
    )


def guard_write_target(
    dsn_or_env: str,
    mode: str = "apply",
    *,
    environment: Mapping[str, str] | None = None,
    connect: Callable[[str], Any] | None = None,
    connection: Any = None,
) -> Verdict:
    """Attachable preflight: resolve identity, then judge it; never raises on refusal.

    Args:
        dsn_or_env: Literal DSN or the environment variable name holding one.
        mode: ``apply``/``write`` or ``plan``/``dry_run``/``read_only``.
        environment: Mapping consulted for the DSN and expected names.
        connect: Optional DSN-to-connection factory.
        connection: Optional already-open connection.

    Returns:
        A :class:`Verdict`. When identity resolution fails, the verdict is a refusal with
        the sanitized cause, so a caller can emit ``as_payload()`` and exit nonzero.
    """
    normalized = _normalized_mode(mode)
    try:
        identity = resolve_database_identity(
            dsn_or_env,
            environment=environment,
            connect=connect,
            connection=connection,
        )
    except Exception as exc:  # fail closed; str(exc) is already redacted
        cause = redact_secrets(exc, _secret_tokens(dsn_or_env))
        expected = expected_database_names(environment)
        return Verdict(
            allowed=False,
            mode=normalized or "unknown",
            status="attention_required",
            exit_code=_REFUSAL_EXIT_CODE,
            write_possible=False,
            source_failure_recorded=False,
            attention_required=True,
            reasons=(f"identity_resolution_refused: {cause}",),
            evidence={
                "server_reported_database": None,
                "dsn_path_database": None,
                "host": None,
                "server_version": None,
                "hosted_schemas": [],
                "expected_database_names": list(expected),
                "probe_errors": [cause],
            },
        )
    return assert_write_target_allowed(identity, normalized)


def _argv_tokens() -> tuple[str, ...]:
    """DSN-shaped argv tokens are secrets for output purposes."""
    return tuple(token for token in sys.argv[1:] if "://" in token)


def main(argv: Sequence[str] | None = None) -> int:
    """Print the sanitized guard payload as JSON and return the exit code.

    Args:
        argv: Optional argument list; defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` only when the target is allowed; ``2`` on any refusal.
    """
    parser = argparse.ArgumentParser(description="Preflight the warehouse write target identity.")
    parser.add_argument("--dsn", help="Literal DSN, mutually exclusive with --dsn-env")
    parser.add_argument("--dsn-env", help="Name of the environment variable holding the DSN")
    parser.add_argument("--mode", default="apply", help="apply|write|plan|dry_run|read_only")
    parser.add_argument("--pretty", action="store_true", help="Indent the JSON payload")
    args = parser.parse_args(list(argv) if argv is not None else None)

    target = args.dsn or args.dsn_env or ""
    # An exception here can repr argv or the parsed URL, so every DSN-shaped token on the
    # command line is treated as secret material before anything is printed.
    secrets = (*_secret_tokens(target), *_argv_tokens())
    try:
        verdict = guard_write_target(target, args.mode)
    except Exception as exc:  # pragma: no cover - guard already absorbs expected failures
        payload = {
            "mode": _normalized_mode(args.mode),
            "status": "attention_required",
            "exit_code": _REFUSAL_EXIT_CODE,
            "allowed": False,
            "write_possible": False,
            "source_failure_recorded": False,
            "reasons": [redact_secrets(exc, secrets)],
            "evidence": {},
        }
        print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=False))
        return _REFUSAL_EXIT_CODE

    print(json.dumps(verdict.as_payload(), indent=2 if args.pretty else None, sort_keys=False))
    return verdict.exit_code


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
