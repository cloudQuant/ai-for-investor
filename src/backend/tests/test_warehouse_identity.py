"""Tests for the warehouse/database identity guard.

Hermetic by construction: every case injects a fake DB-API connection (or a fake
connection factory), so no test opens a socket or touches a real database. Each refusal
path is paired with a counterfactual that would pass if the guard trusted the DSN string,
the connection outcome, or the mode label instead of the server's answer.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_GUARD_PATH = _BACKEND_ROOT / "scripts" / "ops" / "warehouse_identity.py"
_SPEC = importlib.util.spec_from_file_location("warehouse_identity", _GUARD_PATH)
assert _SPEC is not None and _SPEC.loader is not None
guard = importlib.util.module_from_spec(_SPEC)
sys.modules["warehouse_identity"] = guard
_SPEC.loader.exec_module(guard)

WAREHOUSE_DSN = "mysql+pymysql://ak_ro_user:SENTINEL-PW-9f3a@10.0.0.9:3306/akshare_data"
SECRET_SENTINELS = ("SENTINEL-PW-9f3a", "ak_ro_user", WAREHOUSE_DSN)


class FakeCursor:
    """DB-API cursor serving canned answers for the guard's read-only probes."""

    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, sql: str) -> None:
        self._connection.executed.append(sql)
        if self._connection.execute_error and self._connection.execute_error(sql):
            raise self._connection.execute_error(sql)
        lowered = sql.casefold()
        if "database()" in lowered or "current_database()" in lowered:
            self._rows = [(self._connection.database,)]
        elif "version()" in lowered:
            self._rows = [(self._connection.version,)]
        elif "information_schema" in lowered:
            if self._connection.schemas is None:
                raise AssertionError("information_schema probe is not supported by this fake")
            self._rows = [(name,) for name in self._connection.schemas]
        else:
            raise AssertionError(f"unexpected probe SQL: {sql}")

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def close(self) -> None:
        self._connection.closed_cursors += 1


class FakeConnection:
    """Fake DB-API connection; records every statement it was asked to run."""

    def __init__(
        self,
        *,
        database: str | None = "akshare_data",
        version: str | None = "8.0.36-log",
        schemas: tuple[str, ...] | None = ("ai_for_investor", "akshare_data"),
        execute_error: Any = None,
        cursor_error: bool = False,
    ) -> None:
        self.database = database
        self.version = version
        self.schemas = schemas
        self.execute_error = execute_error
        self.cursor_error = cursor_error
        self.executed: list[str] = []
        self.closed_cursors = 0
        self.closed = False
        self.commit_calls = 0

    def cursor(self) -> FakeCursor:
        if self.cursor_error:
            raise RuntimeError("cursor refused by a read-only role")
        return FakeCursor(self)

    def commit(self) -> None:  # pragma: no cover - proves the guard never commits
        self.commit_calls += 1

    def close(self) -> None:
        self.closed = True


def _identity(**kwargs: Any) -> guard.DatabaseIdentity:
    return guard.resolve_database_identity(WAREHOUSE_DSN, connection=FakeConnection(**kwargs))


def _assert_required_refusal_keys(payload: dict[str, Any]) -> None:
    """The worker's JSON vocabulary for a refusal, independent of the reason."""
    assert payload["status"] == "attention_required"
    assert payload["write_possible"] is False
    assert payload["source_failure_recorded"] is False
    assert payload["exit_code"] != 0
    assert payload["batch_started"] is False


def _assert_no_secret_leak(text: str) -> None:
    for sentinel in SECRET_SENTINELS:
        assert sentinel not in text, f"credential material leaked: {sentinel!r}"


# --------------------------------------------------------------------------- happy path


def test_expected_warehouse_target_is_allowed_for_apply() -> None:
    """Counterfactual: a DSN whose path names the forbidden app database must not veto."""
    identity = _identity(database="akshare_data")
    assert identity.database_name == "akshare_data"
    assert identity.server_version == "8.0.36-log"
    assert identity.host_label == "10.0.0.9:3306"

    verdict = guard.assert_write_target_allowed(identity, "apply")
    assert (verdict.allowed, verdict.status, verdict.exit_code) == (True, "ok", 0)
    assert verdict.write_possible is True
    assert verdict.source_failure_recorded is False
    assert verdict.attention_required is False


def test_metadata_database_target_is_allowed_for_apply() -> None:
    verdict = guard.assert_write_target_allowed(_identity(database="ai_for_investor"), "apply")
    assert (verdict.allowed, verdict.exit_code) == (True, 0)


def test_server_answer_overrides_a_forbidden_dsn_path_segment() -> None:
    """Trust the server, not the DSN: path says backtrader_web, server says akshare_data."""
    dsn = "mysql+pymysql://ak_ro_user:SENTINEL-PW-9f3a@10.0.0.9:3306/backtrader_web"
    identity = guard.resolve_database_identity(
        dsn, connection=FakeConnection(database="akshare_data")
    )
    assert identity.dsn_path_database == "backtrader_web"
    assert identity.database_name == "akshare_data"

    verdict = guard.assert_write_target_allowed(identity, "apply")
    assert verdict.allowed is True
    assert verdict.reasons[0] == "server_reported_target_allowed: akshare_data"


# --------------------------------------------------------------------------- refusals


def test_backtrader_web_target_is_refused_for_apply() -> None:
    """The forbidden app database fails closed before any batch is started."""
    identity = _identity(database="backtrader_web")
    verdict = guard.assert_write_target_allowed(identity, "apply")
    payload = verdict.as_payload()

    assert verdict.allowed is False
    _assert_required_refusal_keys(payload)
    assert any("backtrader_web" in reason for reason in verdict.reasons)
    assert verdict.evidence["server_reported_database"] == "backtrader_web"


def test_refusal_follows_the_server_when_the_dsn_path_promises_the_warehouse() -> None:
    """Counterfactual: the DSN path alone would have certified this run as safe."""
    identity = _identity(database="backtrader_web")
    verdict = guard.assert_write_target_allowed(
        guard.DatabaseIdentity(
            database_name=identity.database_name,
            dsn_path_database="akshare_data",
            expected_database_names=identity.expected_database_names,
        ),
        "apply",
    )
    assert verdict.allowed is False
    assert any("dsn_path_disagrees_with_server" in r for r in verdict.reasons)
    assert verdict.write_possible is False


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(
            lambda dsn: (_ for _ in ()).throw(
                RuntimeError(f"lost server while establishing connection to {dsn}")
            ),
            id="factory_raises",
        ),
        pytest.param(lambda dsn: None, id="factory_returns_none"),
    ],
)
def test_unreachable_connection_is_a_refusal_not_a_pass(factory: Any) -> None:
    """Fail closed: an unopenable connection never yields an allowed verdict."""
    verdict = guard.guard_write_target(WAREHOUSE_DSN, "apply", connect=factory)
    assert verdict.allowed is False
    _assert_required_refusal_keys(verdict.as_payload())
    assert verdict.reasons[0].startswith("identity_resolution_refused:")


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"database": None}, id="server_answers_null_database"),
        pytest.param({"cursor_error": True}, id="cursor_unavailable"),
        pytest.param(
            {
                "execute_error": lambda sql: (
                    RuntimeError("deny") if "database()" in sql.casefold() else None
                )
            },
            id="name_probe_denied",
        ),
    ],
)
def test_undeterminable_server_identity_is_a_refusal(kwargs: dict[str, Any]) -> None:
    """No name, no write: the guard cannot certify a target it cannot read."""
    verdict = guard.guard_write_target(WAREHOUSE_DSN, "apply", connection=FakeConnection(**kwargs))
    assert verdict.allowed is False
    _assert_required_refusal_keys(verdict.as_payload())
    assert verdict.evidence["server_reported_database"] is None


def test_resolve_database_identity_raises_on_undeterminable_name() -> None:
    with pytest.raises(guard.WarehouseIdentityError, match="identity_undeterminable"):
        _identity(database=None)


def test_unknown_mode_is_refused() -> None:
    """A mode label the guard cannot classify is treated as a write request to block."""
    verdict = guard.assert_write_target_allowed(_identity(), "apply-ish")
    assert verdict.allowed is False
    assert verdict.mode == "apply-ish"
    _assert_required_refusal_keys(verdict.as_payload())


def test_unsupported_dialect_refuses_instead_of_guessing() -> None:
    """SQLite has no server to ask, so identity cannot be established."""
    with pytest.raises(guard.WarehouseIdentityError, match="unsupported_driver"):
        guard.resolve_database_identity("sqlite+aiosqlite:///./app.db", environment={})


def test_missing_or_empty_environment_variable_is_a_refusal() -> None:
    missing = guard.guard_write_target("AKSHARE_DATA_DATABASE_URL", "apply", environment={})
    assert missing.allowed is False
    assert "environment_variable_empty_or_missing" in missing.reasons[0]

    not_a_dsn = guard.guard_write_target(
        "AKSHARE_DATA_DATABASE_URL", "apply", environment={"AKSHARE_DATA_DATABASE_URL": "nope"}
    )
    assert not_a_dsn.allowed is False
    assert "environment_value_is_not_a_dsn" in not_a_dsn.reasons[0]

    empty_target = guard.guard_write_target("", "apply", environment={})
    assert empty_target.allowed is False
    assert "no_target_dsn_supplied" in empty_target.reasons[0]


# --------------------------------------------------------------------------- plan mode


def test_plan_mode_reports_mismatch_without_claiming_safety() -> None:
    """Counterfactual: a dry run must not be dressed up as harmless on the wrong target."""
    identity = _identity(database="backtrader_web")
    verdict = guard.assert_write_target_allowed(identity, "plan")
    payload = verdict.as_payload()

    assert verdict.allowed is False
    assert "read_only_run_mismatch_is_not_safe" in verdict.reasons[-1]
    assert verdict.write_possible is False
    _assert_required_refusal_keys(payload)


def test_plan_mode_on_expected_target_reports_ok_without_authorizing_a_write() -> None:
    verdict = guard.assert_write_target_allowed(_identity(), "dry_run")
    assert (verdict.allowed, verdict.status, verdict.exit_code) == (True, "ok", 0)
    assert verdict.write_possible is False, "a read-only verdict must never look like write consent"


# --------------------------------------------------------------------------- normalization


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AKSHARE_DATA", "akshare_data"),
        ("  akshare_data  ", "akshare_data"),
        ("`AkShare_Data`", "akshare_data"),
        ('"akshare_data"', "akshare_data"),
        ("'akshare_data'", "akshare_data"),
        ("[akshare_data]", "akshare_data"),
        ("akshare_data.some_table", "akshare_data"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_normalize_database_name_handles_case_whitespace_and_quotes(
    raw: object, expected: str | None
) -> None:
    assert guard.normalize_database_name(raw) == expected


@pytest.mark.parametrize("server_answer", [" AKSHARE_DATA ", "`akshare_data`"])
def test_quoted_or_uppercase_server_answer_still_matches_expected_target(
    server_answer: str,
) -> None:
    verdict = guard.assert_write_target_allowed(_identity(database=server_answer), "apply")
    assert verdict.allowed is True


# --------------------------------------------------------------------------- env override


def test_expected_names_default_and_env_override() -> None:
    assert guard.expected_database_names({}) == ("ai_for_investor", "akshare_data")
    assert guard.expected_database_names({"AFI_EXPECTED_DATABASE_NAMES": ""}) == (
        "ai_for_investor",
        "akshare_data",
    )
    overridden = guard.expected_database_names(
        {"AFI_EXPECTED_DATABASE_NAMES": " Akshare_Data_V2 , warehouse_alt , , "}
    )
    assert overridden == ("akshare_data_v2", "warehouse_alt")


def test_env_override_changes_which_target_is_accepted() -> None:
    """The expectation is configuration, not a per-machine hardcode."""
    environment = {"AFI_EXPECTED_DATABASE_NAMES": "warehouse_alt"}
    allowed = guard.guard_write_target(
        WAREHOUSE_DSN,
        "apply",
        environment=environment,
        connection=FakeConnection(database="warehouse_alt"),
    )
    refused = guard.guard_write_target(
        WAREHOUSE_DSN,
        "apply",
        environment=environment,
        connection=FakeConnection(database="akshare_data"),
    )
    assert allowed.allowed is True
    assert refused.allowed is False
    assert refused.evidence["expected_database_names"] == ["warehouse_alt"]


def test_dsn_can_be_supplied_by_environment_variable_name() -> None:
    identity = guard.resolve_database_identity(
        "AKSHARE_DATA_DATABASE_URL",
        environment={"AKSHARE_DATA_DATABASE_URL": WAREHOUSE_DSN},
        connection=FakeConnection(database="akshare_data"),
    )
    assert identity.database_name == "akshare_data"
    assert identity.host_label == "10.0.0.9:3306"


# --------------------------------------------------------------------------- leak hygiene


def test_credentials_never_reach_the_verdict_or_its_payload() -> None:
    verdict = guard.guard_write_target(
        WAREHOUSE_DSN,
        "apply",
        connect=lambda dsn: (_ for _ in ()).throw(
            RuntimeError(f"pymysql.err.OperationalError: access denied for {dsn}")
        ),
    )
    rendered = json.dumps(verdict.as_payload(), sort_keys=True) + repr(verdict)
    _assert_no_secret_leak(rendered)


def test_credentials_never_reach_an_exception_message() -> None:
    """A driver error that reprs the URL is caught, sanitized, and re-raised clean."""
    with pytest.raises(guard.WarehouseIdentityError) as excinfo:
        guard.resolve_database_identity(
            WAREHOUSE_DSN,
            connect=lambda dsn: (_ for _ in ()).throw(RuntimeError(f"connect {dsn} failed")),
        )
    _assert_no_secret_leak(str(excinfo.value))
    assert "<redacted>" in str(excinfo.value)


def test_credentials_never_reach_printed_cli_output(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """argv carries the DSN; stdout must still contain no credential material."""

    def refuse(dsn: str) -> FakeConnection:
        raise RuntimeError(f"OperationalError while connecting to {dsn}")

    monkeypatch.setattr(guard, "_open_default_connection", refuse)

    exit_code = guard.main(["--dsn", WAREHOUSE_DSN, "--mode", "apply"])
    captured = capsys.readouterr()

    assert exit_code == 2
    _assert_no_secret_leak(captured.out + captured.err)
    assert json.loads(captured.out)["status"] == "attention_required"


def test_cli_prints_allowed_identity_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AKSHARE_DATA_DATABASE_URL", WAREHOUSE_DSN)
    monkeypatch.setattr(
        guard, "_open_default_connection", lambda dsn: FakeConnection(database="akshare_data")
    )

    exit_code = guard.main(["--dsn-env", "AKSHARE_DATA_DATABASE_URL", "--mode", "plan"])

    captured = capsys.readouterr()
    assert exit_code == 0, captured.out
    payload = json.loads(captured.out)
    assert payload["status"] == "ok"
    assert payload["evidence"]["server_reported_database"] == "akshare_data"
    assert payload["evidence"]["host"] == "10.0.0.9:3306"


def test_cli_without_a_target_fails_closed(capsys: pytest.CaptureFixture[str]) -> None:
    assert guard.main(["--mode", "apply"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert "no_target_dsn_supplied" in payload["reasons"][0]


def test_cli_scrubs_an_argv_repr_from_an_unexpected_crash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Counterfactual: repr(argv) would print the DSN; the CLI must not."""

    def crash(target: str, mode: str) -> Any:
        raise RuntimeError(f"unexpected failure with {sys.argv!r}")

    monkeypatch.setattr(sys, "argv", ["warehouse_identity.py", "--dsn", WAREHOUSE_DSN])
    monkeypatch.setattr(guard, "guard_write_target", crash)

    exit_code = guard.main(["--dsn", WAREHOUSE_DSN, "--mode", "apply"])
    captured = capsys.readouterr()

    assert exit_code == 2
    _assert_no_secret_leak(captured.out + captured.err)
    assert json.loads(captured.out)["write_possible"] is False


@pytest.mark.parametrize(
    ("message", "sentinels"),
    [
        pytest.param(
            "error at mysql+pymysql://user:hunter2@db.internal:3306/akshare_data",
            ("hunter2", "user"),
            id="url_userinfo_in_message",
        ),
        pytest.param("literal hunter2 password reuse", ("hunter2",), id="bare_token"),
    ],
)
def test_redact_secrets_strips_credentials_from_free_text(
    message: str, sentinels: tuple[str, ...]
) -> None:
    redacted = guard.redact_secrets(message, sentinels)
    for sentinel in sentinels:
        assert sentinel not in redacted
    assert "<redacted>" in redacted


# --------------------------------------------------------------------------- read-only proof


def test_guard_only_issues_read_only_probes_and_never_commits() -> None:
    """The guard must be incapable of producing a persistent change itself."""
    connection = FakeConnection(database="akshare_data")
    verdict = guard.guard_write_target(WAREHOUSE_DSN, "apply", connect=lambda dsn: connection)

    assert verdict.allowed is True
    assert connection.commit_calls == 0
    assert connection.closed is True, "the guard closes the connection it opened for identity"
    assert connection.executed, "identity must come from a server question"
    for sql in connection.executed:
        assert sql.lstrip().upper().startswith("SELECT"), sql
        assert not any(
            verb in sql.upper() for verb in (" INSERT ", " UPDATE ", " DELETE ", " CREATE ")
        )


def test_version_and_schema_probes_are_best_effort_evidence() -> None:
    """Counterfactual: a restricted read-only role that cannot list schemas still passes."""
    identity = _identity(database="akshare_data", schemas=None, version=None)
    verdict = guard.assert_write_target_allowed(identity, "apply")

    assert verdict.allowed is True
    assert identity.hosted_schemas == ()
    assert verdict.evidence["server_version"] is None
    assert any("information_schema_listing_unavailable" in r for r in verdict.reasons)


def test_missing_peer_schema_is_reported_as_evidence_not_a_refusal() -> None:
    identity = _identity(database="akshare_data", schemas=("akshare_data",))
    verdict = guard.assert_write_target_allowed(identity, "plan")

    assert verdict.allowed is True
    assert any(
        "expected_schema_not_hosted_by_target_server: ai_for_investor" in r for r in verdict.reasons
    )
    assert not any(
        r.endswith("akshare_data") and "expected_schema_not_hosted" in r for r in verdict.reasons
    ), "the hosted schema must not be reported as missing"


def test_schema_rows_are_reduced_to_their_first_column() -> None:
    """Counterfactual: DB-API drivers hand back one-column tuples, so a name that keeps the
    row wrapper never matches and every schema looks missing on a healthy server."""
    identity = _identity(database="akshare_data", schemas=("akshare_data", "ai_for_investor"))
    verdict = guard.assert_write_target_allowed(identity, "apply")

    assert identity.hosted_schemas == ("akshare_data", "ai_for_investor")
    assert not any("expected_schema_not_hosted_by_target_server" in r for r in verdict.reasons)
    assert verdict.allowed is True
